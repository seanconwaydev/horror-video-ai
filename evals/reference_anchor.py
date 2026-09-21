"""Does the character reference image flatten every beat that conditions on it?

Beat images are generated as an *edit* of the character sheet, and that
sheet is specified as "Standing... calm neutral expression... eye-level,
centered... soft, even, shadowless studio-quality light". The hypothesis
is that this anchors pose, camera and lighting, so a beat asking for
someone lying down, seen from behind, lit by one hard source has to fight
its own reference.

The scene here is frozen from a real run whose beats were rejected three
times in a row for exactly that shape -- "already sitting up on the edge
of the bed" against a beat that said "has not yet sat up", and "facing the
camera front-on" against a beat that said "seen from behind". Known
failing cases.

Four arms, same three beats:

    current   character sheet + location reference   (what ships today)
    location  location reference only                (is the character ref the cause?)
    dramatic  in-world, hard-lit character sheet + location reference
    none      no references at all                   (ceiling for adherence)

Two things are measured, and both matter, because this is a trade-off
rather than a bug. Adherence -- does the image do what the beat's action
and camera fields say -- is scored by previz_review, the same reviewer
that surfaced the pattern, and its concern text is recorded verbatim.
Identity consistency -- is it recognisably the same person across three
beats -- is the whole reason the reference exists, and only a human can
judge it, so each arm's beats are written side by side for that.

Measuring only adherence would produce a misleading "delete the reference"
answer.

HISTORICAL. The question this answers -- is the character reference
flattening every beat? -- was closed by docs/decisions/0050: references are off by
default now, behind `--references`. It reads `anchor_scene.json`, a
deliberately frozen pre-0049 fixture with no `staging` (ADR 0064), so the
prompts it builds are not the shape the pipeline produces today. Re-run it
for the record it already holds, not as a measurement of current output.

Usage:
    uv run python evals/reference_anchor.py --dry-run
    uv run python evals/reference_anchor.py
    uv run python evals/reference_anchor.py --arms current,dramatic
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from selection import select

from horror_video_ai.config import get_stage_model, load_environment
from horror_video_ai.stages.previz import (
    _style_instruction,
    build_character_sheet_prompt,
    build_location_reference_prompt,
    run_beat_image_stage,
    run_previz_review_stage,
    run_reference_image_stage,
)
from horror_video_ai.stages.scene_planning import (
    Beat,
    Character,
    Location,
    Scene,
    load_scene_plan,
)

EVALS_DIR = Path(__file__).parent
STYLE = "horror-comic"

# 1x1 PNG, for --mock only.
_TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)

# The arm under test. Deliberately NOT added to previz.py -- it earns a
# place in the pipeline by winning here, not before.
_DRAMATIC_SHEET = """\
CHARACTER: {face_build}, {hair}.
WARDROBE (signature): {wardrobe_signature}.
WARDROBE (flexible): {wardrobe_flexible}.
DISTINGUISHING DETAIL: {distinguishing_detail}.

SUBJECT: The character described above, alone.
ACTION: Caught mid-movement in an unguarded moment, weight off-centre, \
expression alert and uneasy rather than composed -- this is an identity \
reference, so the face and wardrobe must read clearly, but the pose must \
not read as a posed portrait.
SETTING: A dark, unremarkable domestic interior, deliberately vague.
CAMERA: Three-quarter view from slightly below eye level, subject \
off-centre in frame.
LIGHTING: One hard, directional source from low and to one side, throwing \
a defined shadow across the far side of the face and the wall behind.
STYLE: {style} No on-screen text, no logos, no watermark."""


def _sheet_prompt(kind: str, character: Character, style_text: str) -> str:
    return _SHEETS[kind].format(
        face_build=character.face_build,
        hair=character.hair,
        wardrobe_signature=character.wardrobe_signature,
        wardrobe_flexible=character.wardrobe_flexible,
        distinguishing_detail=character.distinguishing_detail,
        style=style_text,
    )


# Identity with no body pose and no camera framing to copy. The neutral
# full-body sheet held identity better than anything else tried, and
# suppressed pose, camera and mood in every beat -- so this keeps the face
# and drops the rest of the frame.
_PORTRAIT_SHEET = """\
CHARACTER: {face_build}, {hair}.
DISTINGUISHING DETAIL: {distinguishing_detail}.
WARDROBE (collar and shoulders only, visible at the very bottom of frame): \
{wardrobe_signature}.

SUBJECT: The face of the character described above.
ACTION: Neutral, unposed, looking slightly off camera. This is an identity \
reference for the face ONLY.
SETTING: A plain dark backdrop, no location, nothing narrative.
CAMERA: Tight head-and-shoulders portrait. Nothing below the collarbone is \
in frame -- no arms, no hands, no body pose, no standing posture.
LIGHTING: Soft and slightly directional, enough to show the bone structure.
STYLE: {style} No on-screen text, no logos, no watermark."""

# The dramatic arm won on adherence and lost identity, its wardrobe
# drifting to black long sleeves against a grey t-shirt and sleep shorts,
# because the prompt left clothing underconstrained. Same pose, wardrobe
# pinned.
_DRAMATIC_LOCKED_SHEET = """\
CHARACTER: {face_build}, {hair}.
DISTINGUISHING DETAIL: {distinguishing_detail}.

WARDROBE -- EXACT, NON-NEGOTIABLE. The character wears precisely this and \
nothing else: {wardrobe_signature}. Do not substitute, restyle, recolour, \
add layers, lengthen sleeves, or change the fabric. If the pose or setting \
would suggest different clothing, keep this clothing anyway.

SUBJECT: The character described above, alone.
ACTION: Caught mid-movement in an unguarded moment, weight off-centre, \
expression alert and uneasy rather than composed.
SETTING: A dark, unremarkable domestic interior, deliberately vague.
CAMERA: Three-quarter view from slightly below eye level, subject \
off-centre in frame.
LIGHTING: One hard, directional source from low and to one side, throwing \
a defined shadow across the far side of the face and the wall behind.
STYLE: {style} No on-screen text, no logos, no watermark."""

_SHEETS = {"dramatic": _DRAMATIC_SHEET, "portrait": _PORTRAIT_SHEET, "dramatic_locked": _DRAMATIC_LOCKED_SHEET}

ARMS: dict[str, dict[str, Any]] = {
    "current": {"character_ref": "neutral", "location_ref": True},
    "portrait": {"character_ref": "portrait", "location_ref": True},
    "dramatic_locked": {"character_ref": "dramatic_locked", "location_ref": True},
    "location": {"character_ref": None, "location_ref": True},
    "dramatic": {"character_ref": "dramatic", "location_ref": True},
    "none": {"character_ref": None, "location_ref": False},
}


def _load_scene() -> tuple[dict, Character, list[Location], list[Beat]]:
    """Goes through the real parser so this fixture stays on the same code
    path as a live plan -- it drifted out of the Beat schema once already
    (docs/playbook/repo-audit-brief.md, finding 4)."""
    raw = json.loads((EVALS_DIR / "anchor_scene.json").read_text())
    plan = load_scene_plan(raw["plan"])
    return raw["scene"], plan.characters[0], plan.locations, plan.beats


def _scene_input(scene: dict) -> Scene:
    """previz_review takes one: just when, where and what happens."""
    return Scene(
        time=scene["time"], place=scene["place"], description=scene["description"]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print the plan, spend nothing")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="run the whole script end to end with fake image and review calls. Exists "
        "because the stage functions bind their defaults at definition time, so "
        "monkeypatching the module's `litellm` attribute from outside does NOT "
        "intercept them -- an attempt to do that made real paid calls instead.",
    )
    parser.add_argument("--arms", default=",".join(ARMS), help="comma-separated arm names")
    parser.add_argument(
        "--reuse-locations",
        type=Path,
        help="reuse the shared location references from a previous run directory, instead "
        "of regenerating them. Cheaper, and it holds them constant across experiments.",
    )
    args = parser.parse_args()

    scene, character, locations, beats = _load_scene()
    arms = select(parser, ARMS, args.arms, flag="arms")

    character_sheets = len({a["character_ref"] for a in arms.values() if a["character_ref"]})
    shared_locations = (
        0
        if args.reuse_locations
        else len(locations)
        if any(a["location_ref"] for a in arms.values())
        else 0
    )
    total = character_sheets + shared_locations + len(arms) * len(beats)
    print(
        f"{len(arms)} arm(s) x {len(beats)} beats + {character_sheets} character sheet(s) "
        f"+ {shared_locations} shared location reference(s) = {total} images"
        + (f" (reusing locations from {args.reuse_locations})" if args.reuse_locations else "")
    )
    for name, arm in arms.items():
        print(f"  {name:9} character_ref={arm['character_ref']!s:8} location_ref={arm['location_ref']}")
    print(f"  plus {len(arms) * len(beats)} previz_review calls")

    if args.dry_run:
        print("\n--dry-run: nothing called, nothing spent.")
        return

    # Split the same way cli.py splits them: a reference is plain
    # text-to-image and takes no edit_fn, while a beat conditions on
    # references and takes both.
    ref_image_kwargs: dict = {}
    beat_image_kwargs: dict = {}
    review_kwargs: dict = {}
    if args.mock:
        tiny = SimpleNamespace(data=[SimpleNamespace(b64_json=_TINY_PNG_B64)])
        ref_image_kwargs = {"image_fn": lambda **k: tiny}
        beat_image_kwargs = {"image_fn": lambda **k: tiny, "edit_fn": lambda **k: tiny}
        review_kwargs = {
            "completion_fn": lambda **k: SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content='{"accepted": true, "concern": null}')
                    )
                ]
            )
        }
    else:
        load_environment()
    previz_model = get_stage_model("previz")
    review_model = get_stage_model("previz_review")
    run_dir = EVALS_DIR / "results" / f"anchor-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
    run_dir.mkdir(parents=True)
    locations_by_id = {location.id: location for location in locations}
    fact_check = _scene_input(scene)
    manifest: list[dict] = []

    # Location references are identical across arms -- only the character
    # reference is under test -- so generate them once and share. Cheaper,
    # and it holds a variable constant that would otherwise vary per arm
    # for no reason.
    shared_location_refs: dict[str, Path] = {}
    if args.reuse_locations:
        for location in locations:
            existing = args.reuse_locations / "_shared_locations" / location.id / "reference.png"
            if not existing.exists():
                raise SystemExit(f"--reuse-locations: no reference at {existing}")
            shared_location_refs[location.id] = existing
        print(f"Reusing {len(shared_location_refs)} location reference(s) from {args.reuse_locations}")
    elif any(arm["location_ref"] for arm in arms.values()):
        shared_dir = run_dir / "_shared_locations"
        for location in locations:
            result = run_reference_image_stage(
                build_location_reference_prompt(location, style=STYLE),
                model=previz_model,
                output_dir=shared_dir / location.id,
                **ref_image_kwargs,
            )
            shared_location_refs[location.id] = result.image_path
        print(f"{len(shared_location_refs)} shared location reference(s) generated once")

    for arm_name, arm in arms.items():
        arm_dir = run_dir / f"arm_{arm_name}"
        arm_dir.mkdir()
        print(f"\n########## arm: {arm_name} ##########")

        character_ref = None
        if arm["character_ref"]:
            prompt = (
                build_character_sheet_prompt(character, style=STYLE)
                if arm["character_ref"] == "neutral"
                else _sheet_prompt(arm["character_ref"], character, _style_instruction(STYLE))
            )
            result = run_reference_image_stage(
                prompt,
                model=previz_model,
                output_dir=arm_dir / "character",
                **ref_image_kwargs,
            )
            character_ref = result.image_path
            print(f"  character reference ({arm['character_ref']}) -> {character_ref.name}")

        location_refs = shared_location_refs if arm["location_ref"] else {}

        for index, beat in enumerate(beats, start=1):
            beat_result = run_beat_image_stage(
                beat,
                characters=[character],
                location=locations_by_id.get(beat.location_id),
                character_references=[character_ref] if character_ref else (),
                location_reference=location_refs.get(beat.location_id),
                style=STYLE,
                model=previz_model,
                output_dir=arm_dir,
                **beat_image_kwargs,
            )
            beat_result.image_path.rename(arm_dir / f"beat_{index}.png")
            final = arm_dir / f"beat_{index}.png"

            review = run_previz_review_stage(
                final,
                fact_check,
                characters=[character],
                beat=beat,
                model=review_model,
                **review_kwargs,
            )
            verdict = "accepted" if review.accepted else "REJECTED"
            print(f"  beat {index}: {verdict}" + (f" -- {review.concern}" if review.concern else ""))
            manifest.append(
                {
                    "arm": arm_name,
                    "beat": index,
                    "file": f"arm_{arm_name}/beat_{index}.png",
                    "accepted": review.accepted,
                    "concern": review.concern,
                }
            )

    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    print("\n================ adherence (previz_review) ================")
    print(f"{'arm':<10} {'accepted':>9}   rejections")
    for arm_name in arms:
        rows = [m for m in manifest if m["arm"] == arm_name]
        ok = sum(1 for m in rows if m["accepted"])
        print(f"{arm_name:<10} {ok:>4}/{len(rows):<4}")
        for row in rows:
            if not row["accepted"]:
                print(f"           beat {row['beat']}: {row['concern']}")

    print(f"\nImages in {run_dir}")
    print("\nAdherence is scored above. Identity consistency is not, and is the")
    print("whole reason the reference exists -- open each arm's folder and judge")
    print("whether its three beats show the same person.")


if __name__ == "__main__":
    main()
