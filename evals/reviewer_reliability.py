"""Is previz_review a reliable grader at all?

It ranked four arms of the reference-anchor experiment against blind human
judgment and disagreed sharply, while holding the full planned beat
including the camera and lighting text it was scoring against. (The
stronger "exact reverse" reading this was first written under measured a
different task -- ranking by quality -- and docs/decisions/0055 retracts
it.) Disagreement that size still rules out an incomplete prompt, and
leaves three candidate causes: the review prompt's framing, the model, or
the verdict simply being non-deterministic.

Non-determinism is the cheapest to rule in or out and the most damaging if
true, so it is what this measures. The same image and the same beat are
submitted several times. A grader that flips its own verdict on identical
input cannot be trusted for anything -- not for the retry loop it gates in
production, and not as a metric in evals/ -- regardless of how well its
prompt is written.

Reads the images a previous multi-arm run already produced, so it spends
nothing on generation.

HISTORICAL. `previz_review` was deleted from the pipeline by docs/decisions/0055
after measuring 56% agreement with the owner against 79% for accepting
everything; `run_previz_review_stage` survives only for evals like this
one. Its fixture, `anchor_scene.json`, is a deliberately frozen pre-0049
plan (ADR 0064) and does not match today's prompt shape.

Usage:
    uv run python evals/reviewer_reliability.py --dry-run evals/results/anchor-<ts>
    uv run python evals/reviewer_reliability.py evals/results/anchor-<ts>
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from historical_video_ai.config import get_stage_model, load_environment
from historical_video_ai.stages.previz import run_previz_review_stage
from historical_video_ai.stages.scene_planning import Scene, load_scene_plan

EVALS_DIR = Path(__file__).parent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path, help="a finished multi-arm anchor run")
    parser.add_argument("--repeats", type=int, default=3, help="verdicts per image (default 3)")
    parser.add_argument("--dry-run", action="store_true", help="print the plan, spend nothing")
    args = parser.parse_args()

    raw = json.loads((EVALS_DIR / "anchor_scene.json").read_text())
    scene = raw["scene"]
    plan = load_scene_plan(raw["plan"])
    character, beats = plan.characters[0], plan.beats

    images = sorted(args.run_dir.glob("arm_*/beat_*.png"))
    print(f"{len(images)} image(s) x {args.repeats} repeat(s) = {len(images) * args.repeats} review calls")
    print("No image generation -- this reuses an existing run's output.")
    if args.dry_run:
        print("\n--dry-run: nothing called, nothing spent.")
        return

    load_environment()
    review_model = get_stage_model("previz_review")
    scene_input = Scene(
        time=scene["time"], place=scene["place"], description=scene["description"]
    )

    rows = []
    for image in images:
        arm = image.parent.name.removeprefix("arm_")
        index = int(image.stem.removeprefix("beat_"))
        verdicts = []
        for _ in range(args.repeats):
            review = run_previz_review_stage(
                image,
                scene_input,
                characters=[character],
                beat=beats[index - 1],
                model=review_model,
            )
            verdicts.append(bool(review.accepted))
        flipped = len(set(verdicts)) > 1
        rows.append({"arm": arm, "beat": index, "verdicts": verdicts, "flipped": flipped})
        marks = "".join("A" if v else "r" for v in verdicts)
        print(f"  {arm:<10} beat {index}  {marks}" + ("   <-- FLIPPED" if flipped else ""))

    (args.run_dir / "reviewer_reliability.json").write_text(json.dumps(rows, indent=2))

    flips = sum(1 for r in rows if r["flipped"])
    print(f"\n{flips}/{len(rows)} image(s) got an inconsistent verdict on identical input.")
    if flips:
        print(
            "A grader that contradicts itself on the same input cannot gate a paid retry\n"
            "loop or serve as an eval metric, whatever its prompt says."
        )
    else:
        print(
            "Verdicts are self-consistent, so the reverse-ranking is not noise --\n"
            "it is a systematic disagreement, and the prompt or the model is the cause."
        )
    per_arm = Counter(r["arm"] for r in rows if r["flipped"])
    if per_arm:
        print("Flips by arm: " + ", ".join(f"{a}={n}" for a, n in sorted(per_arm.items())))


if __name__ == "__main__":
    main()
