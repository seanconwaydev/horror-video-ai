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


# docs/decisions/0034: two preambles, not one -- historical grounding
# framing ("verified claims", "must hold at this time") is actively wrong
# for a scene that was never claiming to be real in the first place. The
# shared planning rules below apply to both; only the framing and whether
# claims get woven in differs.
_GROUNDED_PREAMBLE = """\
You are a shot-list planner for a short historical video scene. Break the \
scene below into a full plan BEFORE any image gets generated: the \
character(s) involved, the distinct locations the action moves through, \
and the individual beats (shots) that tell the story.

Scene -- Time: {time} | Place: {place} | What happens: {description}

Verified claims about this place (use these to ground locations and \
beats in real detail; some may describe other eras and must not be \
depicted unless they hold at {time} specifically):
{claims_block}
{max_beats_line}
"""

_CREATIVE_PREAMBLE = """\
You are a shot-list planner for a short creative video scene. This scene \
is not meant to be historically or factually accurate -- do not treat \
anything in it as needing real-world grounding, and do not flag anything \
as implausible on those terms. Break the scene below into a full plan \
BEFORE any image gets generated: the character(s) involved, the distinct \
locations the action moves through, and the individual beats (shots) \
that tell the story.

Scene -- Setting: {time}, {place} | What happens: {description}
{max_beats_line}
"""

_PLANNING_RULES_AND_SHAPE = """\
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
- When multiple beats share a `location_id`, give them real "coverage" \
(the standard film-production term): shots from genuinely different \
camera *positions* in that space, not just a different angle adjective on \
roughly the same spot -- move the camera to a different part of the room \
or street, and vary how close it is to the subject (a wider shot, then a \
closer one, not two medium shots back to back). The same static shot \
repeated can be a legitimate deliberate choice for a specific effect, but \
must never be the unplanned default outcome of two beats sharing a \
location.
- Also vary the character's body position and what they're physically \
doing across beats -- avoid repeating the same standing position, \
orientation, and pose in consecutive beats at the same location. Give \
each beat a distinct, concrete physical action (reaching, turning, \
stepping, sitting, gesturing) unless stillness is specifically the point \
of that beat. A slightly different look for the character between beats \
(hair catching light differently, a minor pose-driven wardrobe shift) is \
fine and expected -- prioritize dynamic, believable movement over rigid \
visual sameness.
- For a character who doesn't belong to the historical setting (a \
modern-day visitor, time traveler, narrator), describe \
`wardrobe_signature`/`wardrobe_flexible` with specific, concrete, \
contemporary clothing items -- not vague terms like "casual clothes" -- \
so the result actually reads as modern, not historical.
- Any lit screen (a phone, a device) should be described as a subtle, \
realistic light source, clearly weaker than the beat's main light source \
(sun, lamp, sky) -- e.g. "a faint, dim glow on her hands, much weaker \
than the daylight around her," not open-ended "glowing"/"electric glow" \
language, which image models tend to render as an unrealistically bright, \
star-like point light.
- When a beat has a character looking at a handheld or propped screen \
from a camera angle that would naturally hide the screen from camera (an \
over-the-shoulder shot from behind her, a side view, a back view), \
explicitly state in `action` or `camera` that the screen face is NOT \
visible to camera -- we see its back or edge instead. Image models \
default to rendering a screen's face toward the viewer regardless of the \
described geometry unless told the opposite outright.
- `style` is for per-beat cinematography notes only (lens choice, depth of \
field, film grain, color grade) -- always include "no on-screen text/UI/\
logos". The overall realism level (photorealistic, semi-realistic, or \
stylized) is set once for the whole run elsewhere and always overrides \
whatever `style` says here, so do not make realism claims in this field.
- Keep the camera on one consistent side of the "line of action" across \
consecutive beats at the same location (the 180-degree rule) -- if a \
character is moving left-to-right or two characters face each other \
across a space, don't flip which side of that line the camera is on \
between beats without a deliberate reason, or the sense of spatial \
geography breaks for the viewer.
- Give each beat a clear anticipation beat when it helps: a brief, \
readable lead-in to the main action (a breath, a shift of weight, a \
glance) rather than starting the beat already mid-action with no setup -- \
this gives a viewer, and the eventual video-generation step, a clearer \
sense of what's about to happen.
- Add a concrete secondary action when it reinforces what's happening -- \
a small supporting detail beyond the main pose (hair or fabric caught by \
wind, a hand tightening on a strap, steam rising) rather than a flat, \
static figure with nothing else happening in frame. Keep it subtle for a \
photorealistic scene and can be more pronounced for a stylized one.
- Every beat should communicate ONE clear, legible focal action or \
emotion a viewer can read at a glance (the animation principle of \
"staging" -- clarity beats complexity) -- avoid a generic, ambiguous pose \
that could mean anything. If a beat's `action` doesn't make clear what \
the character wants or feels in that moment, it needs more specific \
detail, not more general description.
- When a beat places a character near furniture or props (sitting at a \
table, leaning on a counter), describe the specific point of contact \
explicitly (e.g. "her feet rest flat on the floor in front of the low \
stool," "her forearm rests on the counter's edge") rather than leaving \
the spatial relationship implicit -- image models have a documented \
tendency to merge a limb into nearby furniture with no clear boundary \
between them when contact isn't specified precisely. When two characters \
interact, give each a specific reaction to the other (a returned glance, \
a mirrored gesture) so they read as one connected moment, not two \
independently-posed figures that happen to share a frame.

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


def _truncate_references_safely(plan: ScenePlan, max_references: int) -> ScenePlan:
    """Drop characters/locations to fit `max_references` total, but only
    ones it's provably safe to drop -- never orphans a beat. Best-effort,
    not a hard guarantee like `max_beats`'s truncation: if every remaining
    reference is actually in use, this stops short of the target rather
    than silently breaking a beat's location_id (the same class of bug
    docs/decisions/0027/0028 fixed elsewhere).

    Safe to drop, in order: every character past the first (cli.py's
    `_generate_beats_with_choices` only ever conditions on
    `characters[0]` -- a documented v1 simplification, Beat has no
    character_id -- so the rest are already unused by construction), then
    any location no beat's `location_id` actually references.
    """
    characters = list(plan.characters)
    locations = list(plan.locations)

    while len(characters) + len(locations) > max_references and len(characters) > 1:
        characters.pop()

    used_location_ids = {b.location_id for b in plan.beats}
    i = len(locations) - 1
    while len(characters) + len(locations) > max_references and i >= 0:
        if locations[i].id not in used_location_ids:
            locations.pop(i)
        i -= 1

    if len(characters) + len(locations) == len(plan.characters) + len(plan.locations):
        return plan  # nothing was safe to drop
    return ScenePlan(characters=characters, locations=locations, beats=plan.beats)


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
    max_beats: int | None = None,
    max_references: int | None = None,
    requires_grounding: bool = True,
    completion_fn: Callable = litellm.completion,
) -> ScenePlan:
    """Build a full `ScenePlan` (characters, locations, beats) from a
    verified fact sheet, before any image generation happens.

    `model` defaults to the pinned "scene_planning" model. `completion_fn`
    is an injection point for tests.

    `max_beats`, if given, is passed to the model as a soft target *and*
    enforced afterward by truncating the parsed beat list -- a cost-control
    flag (useful while iterating on image/video quality) needs a real
    guarantee, not just hope that the model honored the instruction.

    `max_references` (characters + locations combined -- these, not
    beats, are what a scene can't generate a single image without) gets
    the same soft-target prompt treatment, but its enforcement is
    best-effort, not guaranteed -- see `_truncate_references_safely`.

    `requires_grounding` (docs/decisions/0034) selects which preamble is
    used -- historical-accuracy framing is actively wrong for a scene that
    was never claiming to be real (a meme/creative premise), not just
    unnecessary overhead. When False, `fact_sheet.claims` is ignored (a
    stub FactCheckResult for an ungrounded run has none anyway).

    Raises ScenePlanningError if the response isn't valid JSON, is missing
    required fields, or a beat references an undefined location.
    """
    resolved_model = model or get_stage_model("scene_planning")
    fact_sheet = fact_check_result.fact_sheet
    max_beats_line = (
        f"\nKeep this scene tight: produce at most {max_beats} beat(s) total, not more.\n"
        if max_beats is not None
        else ""
    )
    if max_references is not None:
        max_beats_line += (
            f"\nAlso keep the cast and setting minimal: at most {max_references} "
            "character(s) and location(s) combined -- prefer one character and "
            "one location unless the scene genuinely needs more.\n"
        )
    if requires_grounding:
        claims_block = "\n".join(f"- {c.text}" for c in fact_sheet.claims) or "(no claims)"
        preamble = _GROUNDED_PREAMBLE.format(
            time=fact_sheet.time,
            place=fact_sheet.place,
            description=fact_sheet.description,
            claims_block=claims_block,
            max_beats_line=max_beats_line,
        )
    else:
        preamble = _CREATIVE_PREAMBLE.format(
            time=fact_sheet.time,
            place=fact_sheet.place,
            description=fact_sheet.description,
            max_beats_line=max_beats_line,
        )
    prompt = preamble + _PLANNING_RULES_AND_SHAPE

    response = completion_fn(model=resolved_model, messages=[{"role": "user", "content": prompt}])
    raw_content = response.choices[0].message.content
    plan = _parse_scene_plan(raw_content)
    if max_beats is not None and len(plan.beats) > max_beats:
        plan = ScenePlan(
            characters=plan.characters, locations=plan.locations, beats=plan.beats[:max_beats]
        )
    if max_references is not None and len(plan.characters) + len(plan.locations) > max_references:
        plan = _truncate_references_safely(plan, max_references)
    return plan
