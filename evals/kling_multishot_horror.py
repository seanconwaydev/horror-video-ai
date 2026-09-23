"""One 15-second horror short, text-to-video, in a single multi-shot call.

A deliberate counter-test to this project's image-then-animate pipeline:
no scene planning, no previz, no anchor image. Kling 3.0's multi-shot mode
takes an array of shots -- each with its own prompt and duration -- and
generates them as one continuous video with character consistency held
across the cuts, plus native audio. The question is whether that beats
four separately-animated stills at roughly the same total spend.

Nothing here reads config/models.yaml or the stage modules. The pinned
video model (wan-2.2-i2v-fast) is image-to-video and cannot do this at
all, and the scene-planning prompt's MODEL-BAN rules are written to
suppress motion language, which is exactly what a video model needs. The
only pieces reused are replicate_client's polling and retry behaviour,
which are model-agnostic.

Two findings from the real API that the payload below depends on:

- `multi_prompt` is a JSON-encoded STRING, not an array, and the shot
  durations must sum to exactly `duration`. Max 6 shots, min 1s each.
- `generate_audio` defaults to FALSE. Kling's native audio is half of why
  it is worth testing, so this script always sends it True.

Generation is slow: Replicate's own reference example for a 15s `pro`
clip logged predict_time 532s. replicate_client's default poll ceiling is
120 attempts x 5s = 600s, close enough to that to lose a paid clip to a
cold start, so this raises it to 30 minutes.

Cost is roughly $2.50-$5 for one 15s `pro` clip with audio -- vendor list
price for Kling v3 pro is $0.168/s, and Replicate's own markup on it was
not published anywhere findable. Check the prediction's billing after the
first run rather than trusting that range.

Usage:
    uv run python evals/kling_multishot_horror.py --dry-run
    uv run python evals/kling_multishot_horror.py
    uv run python evals/kling_multishot_horror.py --mode standard
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from horror_video_ai.config import load_environment
from horror_video_ai.replicate_client import (
    ReplicateError,
    download_output,
    run_prediction,
)

MODEL = "kwaivgi/kling-v3-video"

# Hard limits from the model's own input schema on Replicate, not from
# documentation -- read off /v1/models/kwaivgi/kling-v3-video.
MAX_SHOTS = 6
MAX_TOTAL_SECONDS = 15
MIN_SHOT_SECONDS = 1
MAX_PROMPT_CHARS = 2500

# 532s observed on the model's own reference example for a 15s pro clip.
# 360 x 5s = 30 minutes, which leaves room for a cold start and a queue.
POLL_ATTEMPTS = 360

# Restated verbatim at the head of every shot. Each shot in a multi-shot
# call is its own prompt, so the look has to be re-established in each one
# or the cuts drift apart -- the same "reuse the block verbatim" rule
# docs/playbook/video-generation-prompting.md already documents for
# character blocks.
LOOK = (
    "Infrared night-vision security-camera footage. Locked-off camera mounted high "
    "in the corner of a small adult bedroom at night, angled down across the room. "
    "Hard monochrome infrared grey-green, heavy sensor grain, soft lens vignette, "
    "blown-out highlights, slightly soft focus. The camera never moves, never zooms, "
    "never pans."
)

# The premise is deliberately an adult's bedroom. The same beats framed
# around a child's room are the most heavily moderated setup on every
# hosted platform and would most likely just be refused.
SHOTS: list[dict[str, Any]] = [
    {
        # HOOK. Something is already wrong at frame one -- no establishing,
        # no build. The first 2-3 seconds decide whether a Short is watched.
        "duration": 3,
        "prompt": (
            f"{LOOK} A single bed in the middle of the room, duvet thrown violently "
            "back, sheets twisted, the bed empty. In the open doorway at the far wall "
            "stands a tall, thin adult figure, head almost touching the top of the "
            "door frame, absolutely motionless, its face lost to infrared glare. "
            "Nothing in the room moves at all. "
            "Audio: flat electronic hiss, faint room tone, no music."
        ),
    },
    {
        # The empty beat. One thing changed and nothing else -- the whole
        # reason a locked-off frame works for a model that fumbles motion.
        "duration": 3,
        "prompt": (
            f"{LOOK} The identical framing of the same bedroom, the same empty bed "
            "with its duvet thrown back. The doorway at the far wall is now empty -- "
            "the tall figure is no longer there. Nothing else in the room has moved "
            "or changed. The room is completely still. "
            "Audio: the same flat hiss, a little louder, no footsteps, no music."
        ),
    },
    {
        # Escalation by proximity, not by action. The only movement asked
        # for is a few degrees of head turn.
        "duration": 4,
        "prompt": (
            f"{LOOK} The identical framing. The tall thin figure is now standing "
            "directly beside the bed, much closer to the camera, its head turned up "
            "toward the lens. Its eyes catch the infrared light and burn as two flat "
            "white discs. Its body stays perfectly still; only its head rotates a few "
            "degrees further toward the camera. "
            "Audio: hiss, one soft mechanical click, a single low sustained sub-bass note."
        ),
    },
    {
        # Payoff. Ends on signal failure rather than on the threat doing
        # something -- the model has to animate a glitch, not a body.
        "duration": 5,
        "prompt": (
            f"{LOOK} The tall figure has crossed the room and is now directly beneath "
            "the camera, its head and shoulders filling the lower half of the frame, "
            "face tilted straight up into the lens, eyes two blown-out white discs, "
            "skin washed featureless and flat by the infrared. It rises slowly toward "
            "the lens until its face fills the whole frame. The image tears into "
            "horizontal glitch bands and drops to black. "
            "Audio: hiss climbing into harsh digital distortion, one wet breath, "
            "then abrupt total silence."
        ),
    },
]

# On-screen text is in here because this project already measured models
# rendering it as garbled nonsense (docs/playbook/video-generation-
# prompting.md). A found-footage look does not need a burned-in timestamp
# to read as found footage, and a garbled one wrecks the illusion.
NEGATIVE_PROMPT = (
    "on-screen text, timestamp, date stamp, captions, subtitles, watermark, logo, "
    "user interface, camera movement, camera shake, zoom, pan, dolly, colour, daylight, "
    "warm light, cartoon, anime, illustration, glossy cinematic film look, shallow depth "
    "of field, a child, a person lying in the bed, two figures, duplicate figure, "
    "extra limbs, distorted hands, blur, low quality"
)


def build_payload(mode: str) -> dict[str, Any]:
    """The exact Replicate input for one multi-shot generation.

    `multi_prompt` is JSON-encoded because the schema types it as a
    string, not an array -- passing a real list is rejected.
    """
    total = sum(int(shot["duration"]) for shot in SHOTS)
    return {
        "mode": mode,
        "prompt": SHOTS[0]["prompt"],
        "multi_prompt": json.dumps(
            [{"prompt": shot["prompt"], "duration": shot["duration"]} for shot in SHOTS]
        ),
        "duration": total,
        "aspect_ratio": "9:16",
        "generate_audio": True,
        "negative_prompt": NEGATIVE_PROMPT,
    }


def validate() -> list[str]:
    """Check the shot list against the model's schema limits before any
    paid call. Every one of these is a documented constraint that would
    otherwise surface as a 422 after the run has already started."""
    problems = []
    total = sum(int(shot["duration"]) for shot in SHOTS)
    if len(SHOTS) > MAX_SHOTS:
        problems.append(f"{len(SHOTS)} shots -- the model accepts at most {MAX_SHOTS}")
    if total > MAX_TOTAL_SECONDS:
        problems.append(f"shots total {total}s -- the model's ceiling is {MAX_TOTAL_SECONDS}s")
    for i, shot in enumerate(SHOTS, start=1):
        if int(shot["duration"]) < MIN_SHOT_SECONDS:
            problems.append(f"shot {i} is under the {MIN_SHOT_SECONDS}s minimum")
        if len(shot["prompt"]) > MAX_PROMPT_CHARS:
            problems.append(
                f"shot {i}'s prompt is {len(shot['prompt'])} chars -- "
                f"the ceiling is {MAX_PROMPT_CHARS}"
            )
    return problems


def print_plan(payload: dict[str, Any]) -> None:
    total = payload["duration"]
    print(f"{MODEL} -- {len(SHOTS)} shots, {total}s total, {payload['mode']} mode, "
          f"{payload['aspect_ratio']}, audio {'on' if payload['generate_audio'] else 'off'}")
    for i, shot in enumerate(SHOTS, start=1):
        print(f"\n  shot {i} ({shot['duration']}s, {len(shot['prompt'])} chars)")
        print(f"    {shot['prompt']}")
    print(f"\n  negative: {NEGATIVE_PROMPT}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="print the payload, call nothing, spend nothing"
    )
    parser.add_argument(
        "--mode",
        default="pro",
        choices=("standard", "pro", "4k"),
        help="standard=720p, pro=1080p, 4k. Defaults to pro.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="output directory (default: evals/results/kling-multishot-<timestamp>)",
    )
    args = parser.parse_args()

    problems = validate()
    if problems:
        for problem in problems:
            print(f"invalid shot list: {problem}", file=sys.stderr)
        return 1

    payload = build_payload(args.mode)
    print_plan(payload)

    if args.dry_run:
        print("\n--dry-run: nothing called, nothing spent.")
        return 0

    load_environment()

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    out_dir = args.out or Path("evals/results") / f"kling-multishot-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Written BEFORE the call, not after: a 9-minute generation that dies
    # on a timeout or a refusal should still leave behind exactly what was
    # asked for, so the attempt is re-checkable either way.
    (out_dir / "payload.json").write_text(json.dumps(payload, indent=1))

    print(f"\nGenerating -- this takes roughly 9 minutes for a 15s {args.mode} clip.")
    try:
        prediction = run_prediction(MODEL, payload, max_poll_attempts=POLL_ATTEMPTS)
    except ReplicateError as exc:
        print(f"\nGeneration failed: {exc}", file=sys.stderr)
        print(f"The payload that was sent is in {out_dir / 'payload.json'}", file=sys.stderr)
        return 1

    output = prediction.get("output")
    if isinstance(output, list):
        output = output[0] if output else None
    if not output:
        print(f"\nPrediction {prediction.get('id')} returned no video.", file=sys.stderr)
        return 1

    video_path = out_dir / "short.mp4"
    video_path.write_bytes(download_output(output))

    (out_dir / "prediction.json").write_text(
        json.dumps(
            {
                "id": prediction.get("id"),
                "model": MODEL,
                "metrics": prediction.get("metrics"),
                "output_url": output,
            },
            indent=1,
        )
    )

    metrics = prediction.get("metrics") or {}
    print(f"\nWrote {video_path} ({video_path.stat().st_size / 1_000_000:.1f} MB)")
    if metrics.get("predict_time"):
        print(f"Generation took {metrics['predict_time']:.0f}s")
    print(f"Payload and prediction metadata alongside it in {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
