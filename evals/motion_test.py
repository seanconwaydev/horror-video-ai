"""Animate existing still images and measure how much motion actually
came out.

The question: a dense, heavily-inked comic panel looks like a finished
tableau -- is it harder to animate than a sparser frame? The competing
hypothesis is that detail is irrelevant and what governs motion is
whether the prompt asks for any, which is what this project's own logged
Sora result suggested (a beat describing a held, frozen pose produced a
clip with ~2-3/255 mean frame-to-frame difference -- noise, not movement).

So this generates a clip per image and reports the same metric, rather
than settling the question by argument.

It calls the real video-generation stage, which means it is also the
first real exercise of the Replicate path added in docs/decisions/0038.
Roughly $0.05 per clip.

Usage:
    uv run python evals/motion_test.py --dry-run
    uv run python evals/motion_test.py evals/results/<run>/*.png
"""

from __future__ import annotations

import argparse
import itertools
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

from historical_video_ai.config import load_environment
from historical_video_ai.stages.video_generation import run_video_generation_stage

EVALS_DIR = Path(__file__).parent

# Restrained on purpose: the motion-comic format wants a breath, not a
# stunt (docs/decisions/0037). This is also the "explicit motion cue"
# the playbook recommends adding on top of an otherwise static beat
# description, which is exactly the variable under test.
DEFAULT_MOTION_PROMPT = (
    "Subtle, restrained motion only: the subject breathes and shifts weight very "
    "slightly, fabric and hair drift a little, shadows creep almost imperceptibly. "
    "The camera pushes in very slowly. Nothing else moves; no cuts, no new elements."
)


def _mean_frame_delta(video_path: Path) -> float:
    """Mean absolute frame-to-frame pixel difference, 0-255.

    The same metric this project already used to catch a near-static Sora
    clip, so results stay comparable to that logged finding. ~2-3 is
    noise; ~8-12 was real movement on the earlier Wan clips.
    """
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-i", str(video_path), "-vf", "fps=8,scale=160:-1",
             f"{tmp}/f_%04d.png"],
            check=True,
        )
        frames = sorted(Path(tmp).glob("f_*.png"))
        if len(frames) < 2:
            return 0.0
        deltas = []
        for a, b in itertools.pairwise(frames):
            with Image.open(a) as ia, Image.open(b) as ib:
                diff = ImageChops.difference(ia.convert("RGB"), ib.convert("RGB"))
                deltas.append(sum(ImageStat.Stat(diff).mean) / 3)
        return sum(deltas) / len(deltas)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="*", type=Path, help="still images to animate")
    parser.add_argument("--dry-run", action="store_true", help="print the plan, spend nothing")
    parser.add_argument("--prompt", default=DEFAULT_MOTION_PROMPT, help="motion prompt")
    parser.add_argument(
        "--static-prompt",
        action="store_true",
        help="use the image's own static description instead of a motion cue -- the control "
        "condition, reproducing the beat text that produced a motionless clip before",
    )
    args = parser.parse_args()

    images = args.images or sorted((EVALS_DIR / "results").glob("*/*.png"))[:2]
    if not images:
        parser.error("no images found -- run run_eval.py first, or pass paths")

    prompt = "A still, quiet moment. The subject holds their pose." if args.static_prompt else args.prompt
    print(f"{len(images)} clip(s) at roughly $0.05 each")
    print(f"prompt: {prompt[:90]}...")
    for image in images:
        print(f"  {image}")

    if args.dry_run:
        print("\n--dry-run: nothing called, nothing spent.")
        return

    load_environment()
    out_dir = EVALS_DIR / "results" / f"motion-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
    out_dir.mkdir(parents=True)

    results = []
    for image in images:
        print(f"\n--- {image.name}")
        result = run_video_generation_stage(
            image, prompt, output_dir=out_dir, output_filename=f"{image.stem}.mp4"
        )
        delta = _mean_frame_delta(result.video_path)
        results.append((image.stem, result.video_path, delta))
        print(f"    {result.video_path.name}  mean frame delta {delta:.1f}/255")

    print(f"\nClips in {out_dir}\n")
    print(f"{'image':<45} {'delta':>7}  reading")
    for stem, _, delta in results:
        reading = "near-static (noise)" if delta < 4 else "real motion" if delta >= 8 else "some motion"
        print(f"{stem:<45} {delta:>7.1f}  {reading}")
    print("\nThe number only says how much changed, not whether it looked good.")
    print("Watch them: line shimmer and texture crawl are the specific failure")
    print("modes to look for in a heavily-inked panel, and no metric catches those.")


if __name__ == "__main__":
    main()
