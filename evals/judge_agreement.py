"""Does previz_review carry any signal about what a human actually keeps?

The reviewer has been measured ranking four arms in exact reverse of blind
human judgement while rejecting ~88% of everything, and its stated job is
plan fidelity with a binary verdict and no notion of severity -- on one run
it rejected four beats over a missing tote bag while saying nothing about
the scene's antagonist being absent entirely. Its concerns are folded into
the next attempt's prompt as "Fix this: ...", so a bad concern actively
corrupts a retry rather than merely wasting a call.

This settles whether it separates images a human kept from images a human
threw away. Both groups already exist on disk with the exact prompt that
produced them (docs/decisions/0053), so nothing is generated here -- the
only spend is review calls.

Human-rejected candidates never got a verdict in production: rejecting
every candidate short-circuits before the review call runs. That is why
they have to be scored here rather than read out of the run logs.

Outcome -> consequence, decided before running so the result cannot be
rationalised after the fact:
  separates the groups  -> real signal; fix is severity (grade on a scale)
  does not separate     -> no signal about what the owner wants; delete or
                           rescope to whatever binary compliance suits

Usage:
    uv run python evals/judge_agreement.py --dry-run
    uv run python evals/judge_agreement.py --limit 20
    uv run python evals/judge_agreement.py --out evals/results/judge.json
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterator
from pathlib import Path

from historical_video_ai.config import get_stage_model, load_environment
from historical_video_ai.stages.fact_check import FactCheckResult
from historical_video_ai.stages.previz import PrevizError, run_previz_review_stage
from historical_video_ai.stages.research import FactSheet
from historical_video_ai.stages.scene_planning import (
    Beat,
    Character,
    ScenePlanningError,
    load_scene_plan,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _beat_and_characters(log: dict, index: int) -> tuple[Beat | None, list[Character]]:
    """Rebuild the scene-plan context the reviewer is given in production.

    Goes through the real parser so this shares the pipeline's code path
    (docs/playbook/repo-audit-brief.md, finding 4). A plan that no longer
    parses yields no context rather than failing the sweep -- the review
    still runs, just without the settled-details block.
    """
    try:
        plan = load_scene_plan(log.get("scene_plan") or {})
    except ScenePlanningError:
        return None, []
    beat = plan.beats[index - 1] if 0 < index <= len(plan.beats) else None
    if beat is None:
        return None, plan.characters
    staged = {s.character_id for s in beat.staging}
    return beat, [c for c in plan.characters if c.id in staged] or plan.characters


def _cases(runs_dir: Path) -> Iterator[dict]:
    """One case per image a human ruled on, labelled with that ruling."""
    for log_path in sorted(runs_dir.glob("*/run_log.json")):
        try:
            log = json.loads(log_path.read_text())
        except json.JSONDecodeError:
            continue
        if log.get("mock"):
            continue
        scene = {k: log.get(k, "") for k in ("time", "place", "description")}
        for result in log.get("previz_beats") or []:
            index = result.get("index") or 0
            beat, characters = _beat_and_characters(log, index)
            shared = {
                "run": log_path.parent.name,
                "beat": index,
                "scene": scene,
                "beat_obj": beat,
                "characters": characters,
                "requires_grounding": bool(log.get("requires_grounding", True)),
            }
            # Positive: the image the human chose to keep for this beat.
            kept = result.get("image_path")
            if kept and Path(kept).exists():
                yield {**shared, "path": kept, "human_kept": True}
            # Negatives: candidates the human threw away. Only runs from
            # docs/decisions/0053 onward record these per candidate.
            for attempt in result.get("attempts") or []:
                for candidate in attempt.get("candidates") or []:
                    if not isinstance(candidate, dict) or candidate.get("kept"):
                        continue
                    if Path(candidate["path"]).exists():
                        yield {**shared, "path": candidate["path"], "human_kept": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, default=REPO_ROOT / "outputs")
    parser.add_argument("--dry-run", action="store_true", help="count cases, spend nothing")
    parser.add_argument("--limit", type=int, help="cap cases per group (for a cheap first look)")
    parser.add_argument("--out", type=Path, help="write per-image verdicts here as JSON")
    args = parser.parse_args()

    cases = list(_cases(args.runs)) if args.runs.exists() else []
    kept = [c for c in cases if c["human_kept"]]
    tossed = [c for c in cases if not c["human_kept"]]
    if args.limit:
        kept, tossed = kept[: args.limit], tossed[: args.limit]

    print(f"{len(kept)} image(s) the human kept, {len(tossed)} the human rejected")
    print(f"{len(kept) + len(tossed)} review call(s), no image generation")
    if not kept or not tossed:
        raise SystemExit(
            "Need both groups to say anything. Human-rejected candidates only "
            "exist in runs from docs/decisions/0053 onward."
        )
    if args.dry_run:
        print("\n--dry-run: nothing called, nothing spent.")
        return

    load_environment()
    model = get_stage_model("previz_review")
    rows = []
    for case in kept + tossed:
        scene = case["scene"]
        try:
            review = run_previz_review_stage(
                Path(case["path"]),
                FactCheckResult(fact_sheet=FactSheet(**scene, claims=[])),
                characters=case["characters"],
                beat=case["beat_obj"],
                requires_grounding=case["requires_grounding"],
                model=model,
            )
            accepted, concern = review.accepted, review.concern
        except PrevizError as exc:  # a malformed verdict is a finding, not a crash
            accepted, concern = None, f"review failed: {exc}"
        rows.append(
            {
                "run": case["run"],
                "beat": case["beat"],
                "path": case["path"],
                "human_kept": case["human_kept"],
                "judge_accepted": accepted,
                "concern": concern,
            }
        )
        mark = {True: "accept", False: "reject", None: "error"}[accepted]
        print(f"  {'kept ' if case['human_kept'] else 'tossed'} -> judge {mark}")

    scored = [r for r in rows if r["judge_accepted"] is not None]
    k = [r for r in scored if r["human_kept"]]
    t = [r for r in scored if not r["human_kept"]]
    k_rate = sum(r["judge_accepted"] for r in k) / len(k) if k else 0.0
    t_rate = sum(r["judge_accepted"] for r in t) / len(t) if t else 0.0
    agree = sum(r["judge_accepted"] == r["human_kept"] for r in scored)

    print(f"\njudge accepts {k_rate:.0%} of images the human KEPT ({len(k)})")
    print(f"judge accepts {t_rate:.0%} of images the human REJECTED ({len(t)})")
    print(f"agreement: {agree}/{len(scored)} ({agree / len(scored):.0%})" if scored else "")
    # The whole question: does it accept keepers more often than rejects?
    gap = k_rate - t_rate
    print(f"separation: {gap:+.0%} (positive = has signal, <=0 = none or inverted)")
    if len(rows) - len(scored):
        print(f"{len(rows) - len(scored)} review(s) failed to return a usable verdict")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(rows, indent=2))
        print(f"\nper-image verdicts written to {args.out}")


if __name__ == "__main__":
    main()
