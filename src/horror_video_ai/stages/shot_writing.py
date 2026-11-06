"""Turns a `ScenePlan` into shots a video model will actually animate.

Scene planning describes frozen instants, which is correct for a
still-image model and is exactly what made earlier image-to-video clips
motionless -- a prompt naming a held pose renders as a held pose. This
stage rewrites each beat as something happening, keeping the plan's
characters, location and staging.

Its output is the artifact a human reads and edits before any paid
generation: one JSON file of shots, the look restated in each, and the
negative prompt. Nothing downstream generates from shots nobody has seen.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

import litellm

from horror_video_ai.config import get_stage_model
from horror_video_ai.stages.scene_planning import ScenePlan

DEFAULT_TOTAL_SECONDS = 15
DEFAULT_MAX_SHOTS = 6

# The tightest per-shot ceiling across the supported backends (Kling's,
# which is undocumented -- see video_backends/kling.py). Writing to the
# tightest one keeps a shot list portable across every backend, which is
# the whole point of a bake-off.
DEFAULT_MAX_SHOT_CHARS = 512


class ShotWritingError(Exception):
    """Raised when the shot writer returns malformed or unusable output --
    same fail-loud convention as ConfigError and every other stage."""


@dataclass(frozen=True)
class Shot:
    """One continuous take: what is on screen, and for how long."""

    prompt: str
    duration_seconds: int


@dataclass(frozen=True)
class ShotList:
    """A whole short, ready to review. Self-contained on purpose: the look
    and the negative prompt travel with the shots so the JSON a human
    edits is the complete description of what will be generated."""

    shots: list[Shot]
    look: str
    negative_prompt: str

    @property
    def total_seconds(self) -> int:
        return sum(shot.duration_seconds for shot in self.shots)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=1)

    @classmethod
    def from_json(cls, text: str) -> ShotList:
        """Read back a (probably hand-edited) shot list. Fails loud on a
        missing field rather than generating from a half-valid file."""
        try:
            raw = json.loads(text)
            return cls(
                shots=[
                    Shot(prompt=s["prompt"], duration_seconds=int(s["duration_seconds"]))
                    for s in raw["shots"]
                ],
                look=raw["look"],
                negative_prompt=raw["negative_prompt"],
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise ShotWritingError(f"Unusable shot list: {exc}") from exc


# PLATFORM-SAFETY(ambiguous anatomy between the legs -- generate a standing
#   figure in a loose hem with bare legs, in high-contrast low light, and
#   look at the crotch region): a real 15s generation put what read as a
#   phallic form between a figure's legs. The figure was gaunt, in an
#   oversized t-shirt, with "long bare shins", lit by infrared blowout --
#   loose fabric plus bare legs plus crushed tonal range is the geometry
#   that goes ambiguous. A video with that in it cannot be published, so
#   this is prevented at prompt time rather than caught afterwards.
#
#   NOT a MODEL-BAN: it does not expire when a model pin moves. Every
#   generator has this failure mode and every platform acts on it.
_ANATOMY_RISK_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bbare (legs?|shins?|thighs?|knees?|lower body)\b", "bare lower body"),
    (r"\b(naked|nude|undressed|unclothed|topless)\b", "nudity"),
    (r"\b(underwear|boxers|briefs|panties|thong|loincloth|trunks)\b", "underwear"),
    (r"\b(crotch|groin|genitals?|bulge)\b", "anatomy named directly"),
    (r"\bbetween (its|his|her|their) legs\b", "attention drawn between the legs"),
    (r"\b(wet|soaked|clinging) (clothing|fabric|shirt|gown|cloth)\b", "clinging fabric"),
)

_SAFETY_RULES = """\
- EVERY FIGURE IS CLOTHED FROM NECK TO ANKLE, and you must name the garment. A
  long coat, a work overall, a hospital gown to the floor, trousers and boots.
  Never bare legs, and never a loose hem with nothing named beneath it. This is
  not prudishness: loose fabric over bare legs in crushed low-contrast light
  renders as ambiguous anatomy, and a video with that in it cannot be published.
  Replace rather than blandify -- "a caretaker's long grey coat" is as
  characterful as bare shins and is not ambiguous.
- NEVER LIGHT OR CENTRE THE PELVIS. If a standing figure's lower body is in
  frame, keep it in shadow and keep the light and the eye somewhere else. When
  a figure is backlit or lit from below, frame it waist-up or as a full flat
  silhouette, never as a mid-shot in heavy contrast.
"""

_CRAFT_RULES = """\
- SOMETHING MOVES IN EVERY SHOT. Name the movement with a verb in progress --
  it rises, the head rotates, the door creeps open. The plan describes frozen
  instants because it was written for a still-image model. Unfreeze it. A shot
  that only describes a pose renders as a still.
- ONE THING CHANGES PER SHOT. The camera does not move and the frame is the
  same every time. That is the strength of the format: the model only has to
  animate the one thing you name, so name one.
- THE THREAT MOVES BETWEEN SHOTS, NOT DURING THEM. It is somewhere new at each
  cut and is never seen travelling. Inside a shot it may breathe, tilt its
  head, flex a hand -- small, and never a step toward the camera. Being nearer
  with nothing to explain it is the whole effect. A figure that lunges is a
  monster; a figure that simply IS closer is frightening.
- THE FIRST SHOT OPENS ON THE WRONG THING. No establishing, no build. Whatever
  is frightening is already in frame at the first frame.
- EVERYONE IS IN THE FIRST SHOT. The camera never moves, so the room is a
  fixed stage: a person who was not there a moment ago reads as a mistake,
  not a scare. The threat may be somewhere new at each cut; the people it is
  happening to may not appear, leave and come back. If a character is in the
  short at all, they are in frame at the first frame.
- HOLD THE FACE BACK. Do not spend the face, the mouth or the eyes early.
  Distance, posture and silhouette carry the opening.
- ESCALATE IN THE BODY, NOT JUST IN SIZE. A threat that only grows larger reads
  as one figure at four zoom levels. Change its posture, its angle, its head.
- THE LAST SHOT TURNS. End on a change that completes on screen, not on a held
  pose: an expression arriving, a movement finishing, a sound cutting out. A
  face that is merely present is where the clip stopped, not an ending. The
  strongest close is a small human gesture on an inhuman face -- a smile lands
  harder than a scream.
- WRITE THE SOUND. The model generates audio. End every shot with "Audio:" and
  describe it -- room tone, one specific noise, silence. Deliberate silence is
  stronger than a sting.
- NEVER IMPLY A BODY PART THE FRAME HAS NO ROOM FOR. If the shot is full of a
  face, do not describe a hand touching something, in the picture or the audio.
  The model will invent the hand, and hands are what it renders worst.
- NO ON-SCREEN TEXT of any kind. It renders as garbage.
"""

_INSTRUCTIONS = """\
You are writing the shot prompts for a {total}-second vertical horror short.
They go straight to a video model, so every word has to earn its place.

THE LOOK -- restate this, near enough verbatim, at the start of every shot:
{look}

THE PLAN -- the characters, the location and the beats to work from:
{plan}

Write at most {max_shots} shots. Durations are whole seconds of at least 1 and
must add up to exactly {total}. Fewer, longer shots beat more, shorter ones;
four is usually right.

Rules that decide whether this is publishable:
{safety_rules}
Rules that decide whether this is any good:
{craft_rules}
HARD LIMIT: each shot's prompt must be under {max_chars} characters, and the
look above eats a chunk of that. Write tight. This is not advisory -- a backend
rejects the whole generation over it.

Return ONLY a JSON array, no prose and no code fence:
[{{"prompt": "...", "duration_seconds": 4}}, ...]
"""

NEGATIVE_PROMPT = (
    "nude, naked, exposed genitals, bare legs, underwear, anatomical bulge, "
    "on-screen text, timestamp, captions, subtitles, watermark, logo, user "
    "interface, camera movement, camera shake, zoom, pan, dolly, colour, "
    "daylight, cartoon, anime, illustration, glossy cinematic film look, "
    "shallow depth of field, a child, two figures, duplicate figure, extra "
    "limbs, distorted hands, blur, low quality"
)


def check_platform_safety(text: str) -> list[str]:
    """Risky constructions in shot text, as human-readable reasons.

    Blocking rather than advisory by default -- see the PLATFORM-SAFETY
    marker above. A false positive costs a reword; a false negative costs
    a whole generation and produces something unpublishable.
    """
    lowered = text.lower()
    return [
        reason
        for pattern, reason in _ANATOMY_RISK_PATTERNS
        if re.search(pattern, lowered)
    ]


def format_plan(plan: ScenePlan) -> str:
    """The plan flattened to text, as the shot writer sees it."""
    lines: list[str] = []
    for character in plan.characters:
        lines.append(
            f"CHARACTER {character.id}: {character.face_build}. Hair: {character.hair}. "
            f"Wardrobe: {character.wardrobe_signature} ({character.wardrobe_flexible}). "
            f"Distinguishing: {character.distinguishing_detail}"
        )
    for location in plan.locations:
        lines.append(
            f"LOCATION {location.id}: {location.architecture}. "
            f"Fixed props: {location.fixed_props}. "
            f"Ambient light: {location.ambient_light}"
        )
    for i, beat in enumerate(plan.beats, start=1):
        head = (
            f"BEAT {i} (location {beat.location_id}, {beat.duration_seconds}s): "
            f"subject: {beat.subject}; action: {beat.action}; camera: {beat.camera}; "
            f"lighting: {beat.lighting}; audio: {beat.audio}"
        )
        for label, value in (
            ("facing", beat.facing),
            ("contact", beat.contact),
            ("intensity", beat.intensity),
        ):
            if value:
                head += f"; {label}: {value}"
        lines.append(head)
        for staging in beat.staging:
            detail = (
                f"    staging [{staging.character_id}]: {staging.action}; "
                f"blocking: {staging.blocking}"
            )
            for label, value in (
                ("size", staging.size_in_frame),
                ("occlusion", staging.occlusion),
            ):
                if value:
                    detail += f"; {label}: {value}"
            lines.append(detail)
    return "\n".join(lines)


def _parse_shots(text: str) -> list[Shot]:
    cleaned = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        raw = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ShotWritingError(f"The shot writer did not return JSON:\n{cleaned}") from exc
    if not isinstance(raw, list) or not raw:
        raise ShotWritingError(f"The shot writer returned no shots:\n{cleaned}")
    shots = []
    for entry in raw:
        try:
            shots.append(
                Shot(
                    prompt=str(entry["prompt"]).strip(),
                    duration_seconds=max(1, int(entry["duration_seconds"])),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ShotWritingError(f"Malformed shot {entry!r}: {exc}") from exc
    return shots


def fit_durations(shots: list[Shot], total_seconds: int) -> list[Shot]:
    """Force the durations to sum to exactly `total_seconds`.

    Backends reject a shot list whose parts do not add up, and a paid call
    refused for being one second out is not worth a retry, so the last
    shot absorbs the difference and whole shots are dropped if that is not
    enough.
    """
    fitted = list(shots)
    while len(fitted) > 1 and sum(s.duration_seconds for s in fitted[:-1]) >= total_seconds:
        fitted.pop()
    head = sum(s.duration_seconds for s in fitted[:-1])
    last = fitted[-1]
    return [*fitted[:-1], Shot(prompt=last.prompt, duration_seconds=total_seconds - head)]


def run_shot_writing_stage(
    plan: ScenePlan,
    *,
    look: str,
    total_seconds: int = DEFAULT_TOTAL_SECONDS,
    max_shots: int = DEFAULT_MAX_SHOTS,
    max_shot_chars: int = DEFAULT_MAX_SHOT_CHARS,
    model: str | None = None,
    completion_fn: Callable[..., Any] = litellm.completion,
) -> ShotList:
    """Rewrite `plan`'s beats as shots that move, under `look`.

    `model` defaults to the pinned "shot_writer" model. `completion_fn` is
    the injection point for tests, same as every other stage.

    Raises ShotWritingError on unparseable output, on more than
    `max_shots` shots, or on any shot that trips the platform-safety
    check -- that last one is deliberately fatal here rather than a
    warning, because the resulting video would be unpublishable.
    """
    prompt = _INSTRUCTIONS.format(
        total=total_seconds,
        look=look,
        plan=format_plan(plan),
        max_shots=max_shots,
        max_chars=max_shot_chars,
        safety_rules=_SAFETY_RULES,
        craft_rules=_CRAFT_RULES,
    )
    response = completion_fn(
        model=model or get_stage_model("shot_writer"),
        messages=[{"role": "user", "content": prompt}],
    )
    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError, TypeError) as exc:
        raise ShotWritingError(f"Malformed shot-writer response: {exc}") from exc
    if not content:
        raise ShotWritingError("The shot writer returned an empty response.")

    shots = fit_durations(_parse_shots(content), total_seconds)
    if len(shots) > max_shots:
        raise ShotWritingError(
            f"{len(shots)} shots -- the tightest backend accepts {max_shots}."
        )
    for i, shot in enumerate(shots, start=1):
        problems = check_platform_safety(shot.prompt)
        if problems:
            raise ShotWritingError(
                f"Shot {i} trips the platform-safety check ({', '.join(problems)}). "
                "See the PLATFORM-SAFETY marker in stages/shot_writing.py -- this "
                "produces unpublishable video, so it is refused before any paid call."
            )
    return ShotList(shots=shots, look=look, negative_prompt=NEGATIVE_PROMPT)
