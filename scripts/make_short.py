"""Make one finished 15-second vertical horror short.

Kling 3.0 renders the four shots in SHOTS as one continuous 15-second
vertical video with native audio, in a single call.

Those shots came out of this pipeline -- scene planning wrote the
character, the location and the beats, and the shot writer below turned
those beats into something that moves -- and were then read and edited by
hand. --replan rolls a new set the same way.

No previz, no anchor images, no per-beat review loop -- the thing this
produces is a video, not a set of stills to animate later.

Usage:
    uv run python scripts/make_short.py
    uv run python scripts/make_short.py --plan-only
    uv run python scripts/make_short.py --replan --plan-only
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import litellm

from horror_video_ai.config import get_stage_model, load_environment
from horror_video_ai.replicate_client import (
    ReplicateError,
    download_output,
    run_prediction,
)
from horror_video_ai.stages.scene_planning import (
    Scene,
    ScenePlan,
    run_scene_planning_stage,
)

VIDEO_MODEL = "kwaivgi/kling-v3-video"

# From the model's own input schema, not its documentation.
MAX_SHOTS = 6
TOTAL_SECONDS = 15
MAX_PROMPT_CHARS = 2500

# Undocumented, and learned from a rejected prediction: the 2500-character
# limit the schema advertises applies to the top-level `prompt` only. Each
# shot inside `multi_prompt` is capped at 512, and going over is not
# caught until the prediction has already been created --
#   "Shot prompt exceeds 512 characters at shot index 0. (E006)"
# Roughly 140 of those 512 go on restating the look, so a shot has about
# 360 characters of its own to work with.
MAX_SHOT_PROMPT_CHARS = 512

# A 15s pro clip took 532s on the model's own reference example, and the
# shared client's default ceiling is 600s. 30 minutes leaves room for a
# cold start without losing a paid generation to a timeout.
POLL_ATTEMPTS = 360

# The scene. Three strings in, a whole plan out -- this is the only
# creative input the pipeline needs.
SCENE = Scene(
    time="the middle of the night, present day",
    place="a small bedroom watched by a corner-mounted infrared security camera",
    description=(
        "The bed is empty, its duvet thrown back. Someone very tall is standing "
        "in the doorway, and over the next few seconds it gets closer to the camera "
        "without ever being seen to walk."
    ),
)

# The look, restated at the head of every shot. Found footage is doing real
# work here: infrared grain, a fixed mount and a blown-out highlight range
# are the format's own texture, so the artifacts a video model produces read
# as camera artifacts instead of mistakes.
# Kept deliberately terse: it is repeated inside every shot's 512-character
# budget, so every word here is a word the shot itself does not get.
LOOK = (
    "IR night-vision security cam, locked off high in a corner, angled down. "
    "Monochrome grey-green, heavy grain, blown highlights. Camera static."
)

NEGATIVE_PROMPT = (
    "on-screen text, timestamp, date stamp, captions, subtitles, watermark, logo, "
    "user interface, camera movement, camera shake, zoom, pan, dolly, colour, daylight, "
    "warm light, cartoon, anime, illustration, glossy cinematic film look, shallow depth "
    "of field, a child, two figures, duplicate figure, extra limbs, distorted hands, "
    "blur, low quality"
)

# The shots, as written. These came out of scene planning plus the shot
# writer below, then were read and edited by hand -- shot 4's audio
# originally named a hand touching the camera, which a frame full of face
# has no room for. --replan rolls a new set.
SHOTS: list[dict[str, Any]] = [
    {
        "duration": 4,
        "prompt": (
            "IR night-vision security cam, locked off high in a corner, angled down. Monochrome "
            "grey-green, heavy grain, blown highlights. Camera static. Wide, down the room. Empty "
            "bed, duvet thrown back, a pillow on the floor. In the far doorway a very tall gaunt "
            "silhouette stands in a hand's-width gap: one long bare shin, one hand flat on the "
            "frame, the rest lost to black. The door leaf creeps open another inch under an "
            "unseen weight. The figure does not step. Audio: mic hiss, faint hum, one slow hinge "
            "creak."
        ),
    },
    {
        "duration": 4,
        "prompt": (
            "IR night-vision security cam, locked off high in a corner, angled down. Monochrome "
            "grey-green, heavy grain, blown highlights. Camera static. The tall gaunt figure is "
            "mid-floor now, halfway between bed and camera, having crossed with no step seen; the "
            "doorway behind it hangs open on black. Stooped forward, weight on the front foot, "
            "trailing heel lifted. Its bowed head tilts slowly back and its eyes rise to the "
            "lens, lips parting off the teeth. Audio: hiss, one floorboard creak that is not "
            "footsteps."
        ),
    },
    {
        "duration": 4,
        "prompt": (
            "IR night-vision security cam, locked off high in a corner, angled down. Monochrome "
            "grey-green, heavy grain, blown highlights. Camera static. Its head and shoulders "
            "fill the frame directly beneath the lens, the bed a blurred pale shape at the bottom "
            "edge, the rest gone to black. The face is tipped back and up, eyes wide on the "
            "glass. The jaw slowly drops further open, the throat cording as it widens, teeth "
            "catching the infrared flare. Audio: hiss thickening into a slow, wet rasp of "
            "breathing on the lens."
        ),
    },
    {
        "duration": 3,
        "prompt": (
            "IR night-vision security cam, locked off high in a corner, angled down. Monochrome "
            "grey-green, heavy grain, blown highlights. Camera static. The face is pressed flat "
            "against the lens: one eye filling the centre of the frame, the open jaw shoved into "
            "the lower half, a shoulder blocking the rest, the frame's edge solid black. The "
            "pupil slowly contracts and the eye gives one long, deliberate blink. Nothing else "
            "moves. Audio: hiss gone, one low tone cutting abruptly to silence."
        ),
    },
]


SHOT_WRITER_INSTRUCTIONS = """\
You are writing the shot prompts for a {total}-second vertical horror short.
They go straight to a video model, so every word has to earn its place.

THE LOOK -- restate this, near enough verbatim, at the start of every shot:
{look}

THE PLAN -- the characters, the location and the beats to work from:
{plan}

Write at most {max_shots} shots. Their durations must be whole seconds of at
least 1 and must add up to exactly {total}. Fewer, longer shots beat more,
shorter ones; four is usually right.

Rules that decide whether this is any good:

- SOMETHING MOVES IN EVERY SHOT. Name the movement with a verb in progress --
  it rises, the head rotates, the image tears. The plan describes frozen
  instants because it was written for a still-image model. Unfreeze it. A shot
  that only describes a pose will render as a still, which is the exact failure
  this is built to avoid.
- ONE THING CHANGES PER SHOT. The camera is bolted to the wall and the frame is
  identical every time. That is the format's strength: the model only has to
  animate the one thing you name, so name one.
- THE THREAT MOVES BETWEEN SHOTS, NOT DURING THEM. It is somewhere new at each
  cut and is never seen travelling. Inside a shot it may breathe, tilt its
  head, flex a hand, drift a little -- small, and never a step toward the
  camera. Being nearer with no motion that explains it is the whole effect, and
  a figure that lunges is a monster while a figure that simply IS closer is
  frightening. Everything else in frame may move freely.
- HOLD THE FACE BACK. Do not spend the face, the mouth or the eyes in the first
  shot. Distance, posture and silhouette carry the opening; the face is the
  last thing the short gives up.
- THE FIRST SHOT OPENS ON THE WRONG THING. No establishing, no build. Whatever
  is frightening is already in frame at the first frame.
- ESCALATE IN THE BODY, NOT JUST IN SIZE. A threat that only gets bigger reads
  as the same figure at four zoom levels. Change its posture, its angle, what
  it is doing with its head or hands.
- WRITE THE SOUND. The model generates audio natively. End every shot with
  "Audio:" and describe it -- room tone, a single specific noise, silence.
  Silence used deliberately is stronger than a sting.
- NO ON-SCREEN TEXT of any kind. It renders as garbage.
- HARD LIMIT: each shot's prompt must be under {max_chars} characters, and the
  look above eats about 140 of them. That leaves roughly 360 characters for the
  shot itself, so write tight. This is not advisory -- the model rejects the
  whole generation over it. Each shot still has to be self-contained: the look,
  what is in frame, the one thing that changes, and the audio.

Return ONLY a JSON array, no prose and no code fence:
[{{"prompt": "...", "duration": 4}}, ...]
"""


def format_plan(plan: ScenePlan) -> str:
    """The plan as the shot writer sees it -- every field scene planning
    filled in, flattened to text."""
    lines = []
    for character in plan.characters:
        lines.append(
            f"CHARACTER {character.id}: {character.face_build}. Hair: {character.hair}. "
            f"Wardrobe: {character.wardrobe_signature} ({character.wardrobe_flexible}). "
            f"Distinguishing: {character.distinguishing_detail}"
        )
    for location in plan.locations:
        lines.append(
            f"LOCATION {location.id}: {location.architecture}. "
            f"Fixed props: {location.fixed_props}. Ambient light: {location.ambient_light}"
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


def write_shots(plan: ScenePlan, *, model: str) -> list[dict[str, Any]]:
    """Turn the plan's beats into shot prompts that move."""
    prompt = SHOT_WRITER_INSTRUCTIONS.format(
        total=TOTAL_SECONDS,
        look=LOOK,
        plan=format_plan(plan),
        max_shots=MAX_SHOTS,
        max_chars=MAX_SHOT_PROMPT_CHARS,
    )
    response = litellm.completion(model=model, messages=[{"role": "user", "content": prompt}])
    text = response.choices[0].message.content.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        shots = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"The shot writer did not return JSON:\n{text}") from exc
    if not isinstance(shots, list) or not shots:
        raise SystemExit(f"The shot writer returned no shots:\n{text}")
    return shots


def fix_durations(shots: list[dict[str, Any]]) -> None:
    """Force the durations to sum to exactly TOTAL_SECONDS, in place.

    The model gets this right most of the time, and a paid call rejected
    for being one second out is not worth a retry -- so the last shot
    absorbs the difference.
    """
    for shot in shots:
        shot["duration"] = max(1, int(shot.get("duration", 1)))
    drift = TOTAL_SECONDS - sum(shot["duration"] for shot in shots)
    if drift:
        shots[-1]["duration"] = max(1, shots[-1]["duration"] + drift)
    # Trimming the last shot may not have been enough to absorb an
    # oversized plan; drop whole shots from the end until it fits.
    while sum(shot["duration"] for shot in shots) > TOTAL_SECONDS and len(shots) > 1:
        shots.pop()
        shots[-1]["duration"] = TOTAL_SECONDS - sum(s["duration"] for s in shots[:-1])


def validate(shots: list[dict[str, Any]]) -> list[str]:
    problems = []
    if len(shots) > MAX_SHOTS:
        problems.append(f"{len(shots)} shots -- the model accepts at most {MAX_SHOTS}")
    total = sum(shot["duration"] for shot in shots)
    if total != TOTAL_SECONDS:
        problems.append(f"durations total {total}s, must be exactly {TOTAL_SECONDS}s")
    for i, shot in enumerate(shots, start=1):
        length = len(shot.get("prompt", ""))
        if length > MAX_SHOT_PROMPT_CHARS:
            problems.append(
                f"shot {i} is {length} characters -- each shot is capped at "
                f"{MAX_SHOT_PROMPT_CHARS}, and the model only says so after the "
                "prediction is created"
            )
        if not shot.get("prompt"):
            problems.append(f"shot {i} has no prompt")
    return problems


def show(shots: list[dict[str, Any]]) -> None:
    print(f"\n{len(shots)} shots, {sum(s['duration'] for s in shots)}s total\n")
    for i, shot in enumerate(shots, start=1):
        print(f"  shot {i} ({shot['duration']}s)")
        print(f"    {shot['prompt']}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plan-only", action="store_true", help="write the shots and stop before generating"
    )
    parser.add_argument("--yes", action="store_true", help="skip the confirmation before spending")
    parser.add_argument(
        "--replan", action="store_true", help="write a new set of shots instead of using SHOTS"
    )
    parser.add_argument(
        "--mode",
        default="pro",
        choices=("standard", "pro", "4k"),
        help="standard=720p, pro=1080p, 4k. Defaults to pro.",
    )
    args = parser.parse_args()

    load_environment()

    if args.replan:
        print(f"Scene: {SCENE.time} -- {SCENE.place}")
        print(f"        {SCENE.description}")
        print("\nPlanning the scene...")
        plan = run_scene_planning_stage(SCENE, genre="horror", tone="dread", max_beats=4)
        print(
            f"  {len(plan.characters)} character(s), {len(plan.locations)} location(s), "
            f"{len(plan.beats)} beat(s)"
        )
        print("Writing the shots...")
        shots = write_shots(plan, model=get_stage_model("shot_writer"))
        fix_durations(shots)
    else:
        shots = [dict(shot) for shot in SHOTS]

    problems = validate(shots)
    if problems:
        for problem in problems:
            print(f"unusable shot list: {problem}", file=sys.stderr)
        return 1
    show(shots)

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    out_dir = Path("outputs") / f"short_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "plan.json").write_text(
        json.dumps({"scene": SCENE.__dict__, "shots": shots}, indent=1, default=str)
    )

    if args.plan_only:
        print(f"--plan-only: nothing generated. Shots saved to {out_dir / 'plan.json'}")
        return 0

    payload = {
        "mode": args.mode,
        "prompt": shots[0]["prompt"],
        "multi_prompt": json.dumps(
            [{"prompt": s["prompt"], "duration": s["duration"]} for s in shots]
        ),
        "duration": TOTAL_SECONDS,
        "aspect_ratio": "9:16",
        "generate_audio": True,
        "negative_prompt": NEGATIVE_PROMPT,
    }
    (out_dir / "payload.json").write_text(json.dumps(payload, indent=1))

    if not args.yes:
        answer = input(f"Generate {TOTAL_SECONDS}s in {args.mode} mode (~$2.50-$5)? [y/N] ")
        if answer.strip().lower() not in {"y", "yes"}:
            print(f"Stopped. The shots are still in {out_dir / 'plan.json'}")
            return 0

    print(f"\nGenerating -- roughly 9 minutes for {TOTAL_SECONDS}s in {args.mode} mode.")
    try:
        prediction = run_prediction(VIDEO_MODEL, payload, max_poll_attempts=POLL_ATTEMPTS)
    except ReplicateError as exc:
        print(f"\nGeneration failed: {exc}", file=sys.stderr)
        print(f"What was sent is in {out_dir / 'payload.json'}", file=sys.stderr)
        return 1

    output = prediction.get("output")
    if isinstance(output, list):
        output = output[0] if output else None
    if not output:
        print(f"\nPrediction {prediction.get('id')} returned no video.", file=sys.stderr)
        return 1

    video = out_dir / "short.mp4"
    video.write_bytes(download_output(output))
    print(f"\n{video} ({video.stat().st_size / 1_000_000:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
