"""Scene-planning stage -- inserted between fact-check and previz. See
docs/decisions/0023-scene-planning-stage.md.

Turns a verified fact sheet into a full plan (characters, locations, and
beats) before any image generation happens -- formalizes what was, until
now, done by hand in a chat session for every real multi-beat scene this
project has produced (Agent Voss, the Pompeii influencer scene). Locations
are a distinct concept from beats, not just a flat shot list: see
docs/playbook/video-generation-prompting.md's location-consistency
findings for why. previz doesn't consume this plan's `Location`/`Character`
references yet -- that's docs/decisions/0024.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import litellm

from historical_video_ai.config import get_stage_model
from historical_video_ai.json_utils import parse_json_response
from historical_video_ai.stages.fact_check import FactCheckResult


class ScenePlanningError(Exception):
    """Raised when the scene-planning stage's response is missing or malformed."""


@dataclass(frozen=True)
class Character:
    """The playbook's CHARACTER block fields -- a reusable identity
    anchor, later turned into an actual reference image by
    docs/decisions/0024's `run_reference_image_stage`."""

    id: str
    face_build: str
    hair: str
    wardrobe_signature: str
    wardrobe_flexible: str
    distinguishing_detail: str


@dataclass(frozen=True)
class Location:
    """The playbook's LOCATION block fields -- a reusable setting anchor,
    distinct from any one beat's shot-specific camera/lighting choices.
    Later turned into an actual reference image by 0024, reused across
    every beat with a matching `location_id`."""

    id: str
    architecture: str
    fixed_props: str
    ambient_light: str


@dataclass(frozen=True)
class Beat:
    """One shot: the 7-part fields (minus setting, which comes from the
    Location this beat points at) plus duration. `location_id` must match
    one of the plan's `Location.id` values."""

    location_id: str
    subject: str
    action: str
    camera: str
    lighting: str
    style: str
    audio: str
    duration_seconds: str


@dataclass(frozen=True)
class ScenePlan:
    """The reviewable artifact this stage produces -- see cli.py's
    per-item review loop (characters, then locations, then beats, in that
    order, docs/decisions/0023)."""

    characters: list[Character] = field(default_factory=list)
    locations: list[Location] = field(default_factory=list)
    beats: list[Beat] = field(default_factory=list)


_PROMPT_TEMPLATE = """\
You are a shot-list planner for a short historical video scene. Break the \
scene below into a full plan BEFORE any image gets generated: the \
character(s) involved, the distinct locations the action moves through, \
and the individual beats (shots) that tell the story.

Scene -- Time: {time} | Place: {place} | What happens: {description}

Verified claims about this place (use these to ground locations and \
beats in real detail; some may describe other eras and must not be \
depicted unless they hold at {time} specifically):
{claims_block}

Planning rules:
- A LOCATION is one physical space the action happens in -- if the scene \
visits multiple distinct spaces (e.g. a street, then a building's \
interior), each is its own Location. Describe architecture in physical, \
concrete terms (materials, fixed structures), not aesthetic ones.
- A BEAT is exactly one moment/shot, never more -- do not describe \
multiple sequential actions in one beat's `action` field. Every beat must \
reference a `location_id` matching one of the Locations you define.
- Vary camera framing deliberately per beat rather than defaulting every \
shot to facing the camera -- a character can face away from camera, be \
seen in profile, or be shot from behind, whenever that's the more natural \
choice for what's happening in that beat.
- `style` should include "photorealistic, no on-screen text/UI/logos" \
unless the scene specifically calls for something else.

Respond with ONLY a JSON object (no prose, no markdown fences) matching \
this exact shape:

{{
  "characters": [
    {{"id": "<short id>", "face_build": "...", "hair": "...",
      "wardrobe_signature": "...", "wardrobe_flexible": "...",
      "distinguishing_detail": "..."}}
  ],
  "locations": [
    {{"id": "<short id>", "architecture": "...", "fixed_props": "...",
      "ambient_light": "..."}}
  ],
  "beats": [
    {{"location_id": "<must match a location id above>", "subject": "...",
      "action": "...", "camera": "...", "lighting": "...", "style": "...",
      "audio": "...", "duration_seconds": "..."}}
  ]
}}
"""


def _require_str_fields(item: dict, fields_: list[str], *, item_desc: str) -> None:
    for f in fields_:
        if not isinstance(item.get(f), str) or not item[f]:
            raise ScenePlanningError(f"{item_desc} is missing or has an empty '{f}'")


def check_unique_ids(items: list, *, label: str) -> None:
    """Raise ScenePlanningError if any two `items` (Character or Location
    objects, or anything with an `.id`) share an id -- reused by
    `_parse_scene_plan` (the LLM's raw output) and by cli.py's
    `_review_scene_plan` (after a human edit could just as easily
    introduce a collision the LLM didn't). A silent collision would make
    `character_refs`/`location_refs` -- plain dicts keyed by id -- drop
    one item's reference image in favor of another's without any warning.
    """
    ids = [item.id for item in items]
    if len(ids) != len(set(ids)):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        raise ScenePlanningError(f"Duplicate {label} id(s): {dupes}")


def check_beat_location_references(beats: list, locations: list) -> None:
    """Raise ScenePlanningError if any beat's location_id doesn't match a
    defined location -- reused by `_parse_scene_plan` (the LLM's raw
    output) and by cli.py's `_review_scene_plan` (after a human edit to
    either a beat's location_id or a location's id could just as easily
    break the reference the LLM originally got right)."""
    location_ids = {loc.id for loc in locations}
    for beat in beats:
        if beat.location_id not in location_ids:
            raise ScenePlanningError(
                f"A beat references location_id {beat.location_id!r}, which doesn't match "
                f"any defined location ({sorted(location_ids)})"
            )


def _parse_scene_plan(raw_content: str) -> ScenePlan:
    data = parse_json_response(raw_content, ScenePlanningError, "Scene-planning response")

    if not isinstance(data, dict):
        raise ScenePlanningError("Scene-planning response is not a JSON object")

    characters = []
    for item in data.get("characters", []):
        _require_str_fields(
            item,
            ["id", "face_build", "hair", "wardrobe_signature", "wardrobe_flexible", "distinguishing_detail"],
            item_desc="A character",
        )
        characters.append(Character(**{f: item[f] for f in Character.__dataclass_fields__}))
    check_unique_ids(characters, label="character")

    locations = []
    for item in data.get("locations", []):
        _require_str_fields(
            item, ["id", "architecture", "fixed_props", "ambient_light"], item_desc="A location"
        )
        locations.append(Location(**{f: item[f] for f in Location.__dataclass_fields__}))
    check_unique_ids(locations, label="location")

    beats = []
    for item in data.get("beats", []):
        _require_str_fields(
            item,
            ["location_id", "subject", "action", "camera", "lighting", "style", "audio", "duration_seconds"],
            item_desc="A beat",
        )
        beats.append(Beat(**{f: item[f] for f in Beat.__dataclass_fields__}))
    check_beat_location_references(beats, locations)

    if not beats:
        raise ScenePlanningError("Scene-planning response has no beats")

    return ScenePlan(characters=characters, locations=locations, beats=beats)


def run_scene_planning_stage(
    fact_check_result: FactCheckResult,
    *,
    model: str | None = None,
    completion_fn: Callable = litellm.completion,
) -> ScenePlan:
    """Build a full `ScenePlan` (characters, locations, beats) from a
    verified fact sheet, before any image generation happens.

    `model` defaults to the pinned "scene_planning" model. `completion_fn`
    is an injection point for tests.

    Raises ScenePlanningError if the response isn't valid JSON, is missing
    required fields, or a beat references an undefined location.
    """
    resolved_model = model or get_stage_model("scene_planning")
    fact_sheet = fact_check_result.fact_sheet
    claims_block = "\n".join(f"- {c.text}" for c in fact_sheet.claims) or "(no claims)"
    prompt = _PROMPT_TEMPLATE.format(
        time=fact_sheet.time,
        place=fact_sheet.place,
        description=fact_sheet.description,
        claims_block=claims_block,
    )

    response = completion_fn(model=resolved_model, messages=[{"role": "user", "content": prompt}])
    raw_content = response.choices[0].message.content
    return _parse_scene_plan(raw_content)
