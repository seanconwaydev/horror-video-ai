"""Should a beat author where a character is in the FRAME, or in the SPACE?

The pipeline authors both and reconciles neither. `frame_position` states
where someone sits in the 2D frame; the same beat's `action` prose and the
location text state where they are in the world; and `camera` was stripped
of any world position by ADR 0044. Frame position is a *projection* --
world position through a camera -- so the planner is being asked to do
that projection in its head, and run_20260918-221017 shows it getting it
wrong: "far background, upper-left of frame" under a `wide, low, from
behind` camera put a standing man at ceiling height, and the model
invented a concrete slab to hide him behind.

Two arms, one variable:

    frame       what the pipeline emits today -- POSITION IN FRAME / HIDDEN
                BY, taken close to verbatim from that run's beats.
    world       the same scene with NO frame coordinates at all. Where each
                character stands relative to the location's own features and
                to each other, which way each faces, and how far from camera.
    world_size  world placement plus one frame-space quantity: how much of
                the image each character occupies.

The third arm exists because the first run (`results/blocking-20260918-224824`)
exposed an asymmetry the first two arms did not control. `frame` carries an
explicit apparent size ("roughly a twentieth of the image") because that is
how `frame_position` is written, and `world` carried none -- and apparent
size is the strongest depth cue a rendered image has. So that run compared
"frame coordinates plus size" against "world position, no size", and its
only two depth successes were in the arm holding the size. `world_size`
separates the two: if it matches `frame`, the lever is apparent size and
not frame coordinates, which is a much smaller change to the schema.

Everything else is held constant, the camera line included -- in both arms
it stays in ADR 0044's three renderable terms, because that ADR's finding
(an image model does not place a virtual camera in a floor plan) is not
what is under test here.

**The validity risk is in the world arm's wording**, and it is worth
naming rather than hoping about. If it says anything the frame arm does
not, it can win for being more specific rather than for being world-space.
The two arms below were written from the same source beats and deliberately
carry the same facts -- same actions, same occluders, same relationship --
differing only in whether placement is expressed as frame coordinates or as
positions in the room. Read them side by side before trusting a result.

Conditioning is deliberately absent: run_20260918-221017 used
`--references none` (ADR 0050) and produced the conflict anyway, so
references are not the variable here. See evals/camera_obedience.py for
that one, which has still never been run.

Scored by a human, blind. There is no automated scorer -- ADR 0055 deleted
the only one this project had after measuring it at 56% agreement.

Usage:
    uv run python evals/blocking_space.py --dry-run
    uv run python evals/blocking_space.py --mock
    uv run python evals/blocking_space.py
"""

from __future__ import annotations

import argparse
import base64
import json
import random
from datetime import UTC, datetime
from pathlib import Path

import litellm
from selection import select

from horror_video_ai.config import load_environment

EVALS_DIR = Path(__file__).parent

_TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)

MODEL = "gemini/gemini-3.1-flash-lite-image"

# Identity only, and identical in every cell. Wardrobe and face are not
# what is being tested, and a long identity block is one more thing for the
# model to spend attention on.
CHARACTERS = """\
CHARACTER mara: a woman in her late twenties, short red hair.
WARDROBE: a dark green zip jacket, jeans.
CHARACTER watcher: a tall man, gaunt, face in shadow.
WARDROBE: a long black coat."""

SETTING = (
    "SETTING: an underground concrete car park at night. Fixed props: two long rows "
    "of square concrete pillars down both sides of a straight aisle, painted yellow "
    "bay lines, parked cars in the bays, a low concrete ceiling with fluorescent tubes."
)

# Held constant so that a difference between arms cannot come from here.
BOTH_PRESENT = (
    "ALL OF THESE CHARACTERS ARE IN THIS SHOT: mara, watcher. Every one of them must "
    "be visible in the frame, even if only partially -- a silhouette, a figure in the "
    "background, a hand at the frame edge."
)
REACT = (
    "These characters are in the same moment and must react to each other -- their "
    "gazes, distances and body angles have to agree, not read as separate figures "
    "posed independently and placed in one frame."
)
STYLE = (
    "STYLE: Stylized horror comic panel -- heavy inked black shadows, bold confident "
    "linework, flat colour fills, high contrast between lit and unlit areas. "
    "Explicitly NOT photorealistic, NOT 3D-rendered, NOT cute."
)

# The three beats of run_20260918-221017, which is where the failure was
# observed. Actions and occluders are carried across both arms unchanged;
# only placement is re-expressed.
SCENARIOS: dict[str, dict[str, object]] = {
    "distant_figure": {
        "camera": "CAMERA: wide, low, from behind",
        "lighting": (
            "LIGHTING: the ceiling tubes run away in a receding line, the nearest "
            "throwing one hard pool of white light onto the concrete around her while "
            "the far end of the aisle drops into unlit black"
        ),
        "frame": """\
mara DOING: her right hand closed around a car key fob with the thumb pressed down on \
the lock button, her weight on the front foot mid-step along the yellow bay line.
mara POSITION IN FRAME: small and low in the frame, lower-left of centre, occupying \
roughly a tenth of the image width.
mara HIDDEN BY: nothing -- she is fully in the open, seen from behind.
watcher DOING: his shoulder pressed flat to the far face of a pillar, one flat palm \
held against the concrete, keeping the pillar between himself and her sightline.
watcher POSITION IN FRAME: a sliver in the far background, upper-left of frame, \
roughly a twentieth of the image.
watcher HIDDEN BY: the rows of intervening pillars -- only the outer edge of one \
shoulder and a slice of the dark coat survive the nearest pillar's corner.""",
        "world": """\
mara DOING: her right hand closed around a car key fob with the thumb pressed down on \
the lock button, her weight on the front foot mid-step along the yellow bay line.
mara STANDS: on the aisle floor a few metres ahead of the camera, walking away from \
it down the middle of the aisle. Nothing is in front of her.
watcher DOING: his shoulder pressed flat to the far face of a pillar, one flat palm \
held against the concrete, keeping the pillar between himself and her sightline.
watcher STANDS: on the same aisle floor, far down at the unlit end, several pillars \
beyond her, behind one of the pillars in the left-hand row. He is looking along the \
aisle toward her. The pillars between him and the camera cover him except for the \
outer edge of one shoulder and a slice of his coat.""",
        "world_size": """\
mara DOING: her right hand closed around a car key fob with the thumb pressed down on \
the lock button, her weight on the front foot mid-step along the yellow bay line.
mara STANDS: on the aisle floor a few metres ahead of the camera, walking away from \
it down the middle of the aisle. Nothing is in front of her. She occupies roughly a \
tenth of the image width.
watcher DOING: his shoulder pressed flat to the far face of a pillar, one flat palm \
held against the concrete, keeping the pillar between himself and her sightline.
watcher STANDS: on the same aisle floor, far down at the unlit end, several pillars \
beyond her, behind one of the pillars in the left-hand row. He is looking along the \
aisle toward her. The pillars between him and the camera cover him except for the \
outer edge of one shoulder and a slice of his coat. He occupies roughly a twentieth \
of the image.""",
        "questions": [
            "Is the far figure STANDING ON THE FLOOR (not floating, not up near the ceiling)?",
            (
                "Does he read as FAR DOWN THE AISLE from her, in the same room, "
                "at a believable distance?"
            ),
            "Is he partly hidden by a PILLAR (rather than by something invented)?",
        ],
    },
    "near_lurker": {
        "camera": "CAMERA: medium, eye level, three-quarter",
        "lighting": (
            "LIGHTING: the stuttering tube at the far end blinks, so the lit band of "
            "aisle behind her pulses while the gap between the two pillars stays in "
            "flat shadow"
        ),
        "frame": """\
mara DOING: her weight settled onto her back foot with the front toe barely touching \
down, her right hand stopped halfway to her jacket pocket with the fingers spread and \
frozen, chin lifted toward the pillars.
mara POSITION IN FRAME: head and shoulders filling the lower-right third of the frame, \
off-centre, with the left half of the frame left open to the aisle.
mara HIDDEN BY: the roof and wing mirror of a parked car clip across the bottom edge \
of her torso.
watcher DOING: his right hand gripping the vertical corner of a pillar with the \
fingers hooked around the edge, torso twisted about forty degrees from the hips, \
holding the pillar corner between his face and her.
watcher POSITION IN FRAME: mid-ground at frame left, about a quarter of the image height.
watcher HIDDEN BY: the pillar he is holding covers everything below his chest and half \
his face -- one deep-set eye, one shoulder and the hooked hand survive.""",
        "world": """\
mara DOING: her weight settled onto her back foot with the front toe barely touching \
down, her right hand stopped halfway to her jacket pocket with the fingers spread and \
frozen, chin lifted toward the pillars.
mara STANDS: close to the camera, in the aisle beside a parked car whose roof and wing \
mirror pass between her waist and the camera. She is turned toward the pillars.
watcher DOING: his right hand gripping the vertical corner of a pillar with the \
fingers hooked around the edge, torso twisted about forty degrees from the hips, \
holding the pillar corner between his face and her.
watcher STANDS: behind a pillar part-way down the aisle, closer than the far end but \
well behind her, on the same floor. He is looking at her past the pillar's edge. The \
pillar covers everything below his chest and half his face -- one eye, one shoulder \
and the hooked hand clear it.""",
        "world_size": """\
mara DOING: her weight settled onto her back foot with the front toe barely touching \
down, her right hand stopped halfway to her jacket pocket with the fingers spread and \
frozen, chin lifted toward the pillars.
mara STANDS: close to the camera, in the aisle beside a parked car whose roof and wing \
mirror pass between her waist and the camera. She is turned toward the pillars. Her \
head and shoulders fill roughly a third of the image.
watcher DOING: his right hand gripping the vertical corner of a pillar with the \
fingers hooked around the edge, torso twisted about forty degrees from the hips, \
holding the pillar corner between his face and her.
watcher STANDS: behind a pillar part-way down the aisle, closer than the far end but \
well behind her, on the same floor. He is looking at her past the pillar's edge. The \
pillar covers everything below his chest and half his face -- one eye, one shoulder \
and the hooked hand clear it. He is about a quarter of the image height.""",
        "questions": [
            "Is the man BEHIND A PILLAR with the pillar covering half his face?",
            "Do the two read as being in ONE SPACE at a believable distance apart?",
            "Is he LOOKING AT HER (not at the camera, not away)?",
        ],
    },
    "confrontation": {
        "camera": "CAMERA: close-up, low, profile",
        "lighting": (
            "LIGHTING: the nearest tube overhead is the only one still working, "
            "dropping a hard white pool onto the aisle that flattens his coat into a "
            "black slab and catches the shine on her forehead and eyes"
        ),
        "frame": """\
mara DOING: her upper body recoiling backwards from the waist away from the extended \
arm, her raised left forearm across her cheekbone, chin tucked in, eyes stretched wide.
mara POSITION IN FRAME: the right half of the frame, head and shoulder in close-up, \
seen in profile.
mara HIDDEN BY: nothing in front of her -- she is fully in the open.
watcher DOING: his weight on his front foot with the torso stooped forward and \
twisted, his right arm extended at her chest height with the knuckles turned toward \
her face.
watcher POSITION IN FRAME: large and soft-focused in the left third of the frame, \
roughly a third of the image.
watcher HIDDEN BY: nothing covering him -- he is fully in the open, closer to the \
camera than she is.""",
        "world": """\
mara DOING: her upper body recoiling backwards from the waist away from the extended \
arm, her raised left forearm across her cheekbone, chin tucked in, eyes stretched wide.
mara STANDS: on the aisle floor an arm's length from the man, side-on to the camera, \
facing him.
watcher DOING: his weight on his front foot with the torso stooped forward and \
twisted, his right arm extended at her chest height with the knuckles turned toward \
her face.
watcher STANDS: on the same floor directly between her and the camera, near enough to \
touch her, side-on, facing her. He is looking at her face. Nothing is in front of \
either of them.""",
        "world_size": """\
mara DOING: her upper body recoiling backwards from the waist away from the extended \
arm, her raised left forearm across her cheekbone, chin tucked in, eyes stretched wide.
mara STANDS: on the aisle floor an arm's length from the man, side-on to the camera, \
facing him. Her head and shoulder fill the image in close-up.
watcher DOING: his weight on his front foot with the torso stooped forward and \
twisted, his right arm extended at her chest height with the knuckles turned toward \
her face.
watcher STANDS: on the same floor directly between her and the camera, near enough to \
touch her, side-on, facing her. He is looking at her face. Nothing is in front of \
either of them. He is large and soft-focused, roughly a third of the image.""",
        "questions": [
            "Are they close enough to TOUCH, reacting to each other?",
            "Is the man BETWEEN the camera and her (nearer to camera than she is)?",
            "Is he LOOKING AT HER (not at the camera)?",
        ],
    },
}

ARMS = ("frame", "world", "world_size")


def _build_prompt(scenario: dict[str, object], arm: str) -> str:
    return "\n".join(
        [
            CHARACTERS,
            str(scenario[arm]),
            BOTH_PRESENT,
            REACT,
            SETTING,
            str(scenario["camera"]),
            str(scenario["lighting"]),
            STYLE,
            "No on-screen text, no UI, no logos, no watermark.",
        ]
    )


def _generate(prompt: str) -> bytes:
    response = litellm.image_generation(model=MODEL, prompt=prompt, size="720x1280")
    data = getattr(response, "data", None) or []
    if not data:
        raise RuntimeError("empty data list (silent refusal)")
    return base64.b64decode(data[0].b64_json)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print the plan, spend nothing")
    parser.add_argument("--mock", action="store_true", help="run end to end with fake images")
    parser.add_argument(
        "--candidates",
        type=int,
        default=2,
        help="images per cell. More than one so a single fluke is visible as one.",
    )
    parser.add_argument(
        "--scenarios",
        help="comma-separated subset to run, e.g. distant_figure,confrontation. "
        "Dropping a scenario that cannot produce a good image regardless buys "
        "candidates for the ones that can.",
    )
    parser.add_argument(
        "--arms",
        help="comma-separated subset of arms, e.g. world,world_size. Narrowing to "
        "the one comparison still in question is how a cell gets enough candidates "
        "to rise above the between-candidate variance.",
    )
    parser.add_argument("--seed", type=int, help="fix the blind shuffle")
    args = parser.parse_args()

    scenarios = (
        select(parser, SCENARIOS, args.scenarios, flag="scenarios")
        if args.scenarios
        else SCENARIOS
    )
    arms = tuple(select(parser, dict.fromkeys(ARMS), args.arms, flag="arms")) if args.arms else ARMS

    total = len(scenarios) * len(arms) * args.candidates
    print(
        f"{len(scenarios)} scenario(s) x {len(arms)} arm(s) x "
        f"{args.candidates} candidate(s) = {total} images"
    )
    print(f"  model: {MODEL}, text-to-image, no reference conditioning")
    print(f"  arms: {', '.join(arms)}")
    for name in scenarios:
        print(f"  scenario: {name}")
    if args.dry_run:
        print("\n--dry-run: nothing called, nothing spent.")
        return

    if not args.mock:
        load_environment()
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    run_dir = EVALS_DIR / "results" / f"blocking-{stamp}"
    run_dir.mkdir(parents=True)
    # Out of the directory the scorer is looking at: the prompts name their
    # own arm, so a glance at the file list should not give the key away.
    prompts_dir = run_dir / "prompts"

    # Which arm is which must not be readable off the filename.
    rng = random.Random(args.seed)
    labels = [f"a{n}" for n in range(1, len(arms) + 1)]
    rng.shuffle(labels)
    key = dict(zip(labels, arms, strict=True))

    manifest = []
    for scenario_name, scenario in scenarios.items():
        for label, arm in key.items():
            prompt = _build_prompt(scenario, arm)
            prompts_dir.mkdir(exist_ok=True)
            (prompts_dir / f"{scenario_name}__{label}.txt").write_text(prompt)
            for n in range(1, args.candidates + 1):
                try:
                    data = base64.b64decode(_TINY_PNG_B64) if args.mock else _generate(prompt)
                except Exception as exc:  # noqa: BLE001 -- one bad cell shouldn't end the sweep
                    print(f"  FAILED {scenario_name}/{label}/{n}: {exc}")
                    manifest.append(
                        {
                            "scenario": scenario_name,
                            "label": label,
                            "candidate": n,
                            "outcome": "failed",
                        }
                    )
                    continue
                out = run_dir / f"{scenario_name}__{label}_{n}.png"
                out.write_bytes(data)
                print(f"  ok {scenario_name}/{label}/{n} -> {out.name}")
                manifest.append(
                    {
                        "scenario": scenario_name,
                        "label": label,
                        "candidate": n,
                        "file": out.name,
                        "outcome": "ok",
                    }
                )

    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (run_dir / "blocking_key.json").write_text(json.dumps(key, indent=2))

    lines = [
        "# Frame coordinates vs world blocking — yes or no",
        "",
        "One variable: whether each character's placement was authored as a position",
        "in the FRAME or as a position in the ROOM. Actions, occluders, camera,",
        "lighting, setting and style are identical between the two arms.",
        "",
        "Answer each question yes / no / partial. Not which image is nicer.",
        "",
        "**Do not open blocking_key.json or prompts/ until you're done.** Both name",
        "which arm is which; they are saved for reading afterwards.",
        "",
    ]
    for scenario_name, scenario in scenarios.items():
        questions = list(scenario["questions"])  # type: ignore[call-overload]
        lines += [f"## {scenario_name}", ""]
        for qi, question in enumerate(questions, 1):
            lines += [f"**Q{qi}.** {question}", ""]
        header = " | ".join(f"Q{qi}" for qi in range(1, len(questions) + 1))
        divider = "|".join(["---"] * (len(questions) + 2))
        lines += [f"| image | {header} | notes |", f"|{divider}|"]
        blanks = " | ".join([""] * len(questions))
        for label in sorted(key):
            for n in range(1, args.candidates + 1):
                lines.append(f"| {scenario_name}__{label}_{n}.png | {blanks} | |")
        lines.append("")
    lines += [
        "## Overall",
        "",
        "Did either arm produce an image you would actually keep? Which one, and why?",
        "",
    ]
    (run_dir / "SCORING.md").write_text("\n".join(lines))

    print(f"\nImages in {run_dir}")
    print(f"Score in {run_dir / 'SCORING.md'} -- blind; the key is blocking_key.json.")
    print("\nThe question the third arm settles: if world_size matches frame, the")
    print("lever is apparent size rather than frame coordinates, and world")
    print("placement can replace frame_position as long as size comes with it.")


if __name__ == "__main__":
    main()
