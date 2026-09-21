"""Export every human judgement made at the previz gate as one flat dataset.

Every candidate image a run showed is a labelled datapoint: an exact prompt,
the beat it came from, and whether the project owner kept it. A four-beat run
with four candidates produces sixteen of them. Before the judgements were
recorded (docs/decisions/0053) they existed only in terminal scrollback; this
turns the recorded form into something a study can actually consume.

One row per candidate image, not per beat, because the unit of judgement is an
image: rejecting three of four candidates is three negatives and one positive,
and collapsing that to "the beat was accepted" throws away most of the signal.

Rows carry `chosen_over`, the sibling candidates shown at the same time, since a
rejection is only meaningful relative to what it was rejected in favour of. A
candidate rejected alongside three others that were also rejected is a weaker
negative than one passed over for a specific sibling.

`gave_up` marks a beat the owner abandoned entirely -- the strongest negative
available, and the case where every candidate lost and no sibling won.

`--update-dataset` merges the rows into `evals/judgements.jsonl`, which is
committed. `outputs/` is gitignored and gets pruned, so a label whose images
are gone survives only if it was written somewhere tracked; the merge is a
union that never drops a row, because an overwrite from a pruned `outputs/`
would delete exactly the history this file exists to keep (docs/decisions/0074).

Usage:
    uv run python evals/export_judgements.py                     # summary only
    uv run python evals/export_judgements.py --update-dataset    # after a run
    uv run python evals/export_judgements.py --out judgements.jsonl
    uv run python evals/export_judgements.py --runs outputs --out -
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# The committed dataset. Deliberately not under evals/results/, which is
# gitignored -- a label is only durable if it is tracked.
DATASET_PATH = REPO_ROOT / "evals" / "judgements.jsonl"

# What makes one labelled image itself. The image path alone is not enough:
# a beat's candidate filenames restart per run, so the run has to be in the
# key, and an attempt's kept candidate is rewritten to its archived path.
_IDENTITY_FIELDS = ("run", "beat_index", "cycle", "attempt", "image_path")

# Run-level context every row is stamped with. A judgement is only
# comparable to another made under the same conditions -- a rejection under
# one image model or style preset says nothing about a different one.
_RUN_FIELDS = (
    "genre",
    "tone",
    "style",
    "previz_model",
    "previz_review_model",
    "scene_planning_model",
    "requires_grounding",
)


def _repo_relative(path: str) -> str:
    """A run log stores absolute image paths, which cannot be committed.

    They are machine-specific and they are part of a row's identity, so the
    same image exported from a clone would merge as a second row. Anything
    genuinely outside the repo (a --runs pointed elsewhere) is left alone
    rather than mangled into a wrong relative path.
    """
    try:
        return str(Path(path).resolve().relative_to(REPO_ROOT))
    except ValueError:
        return path


def _run_logs(runs_dir: Path) -> Iterator[tuple[Path, dict]]:
    """Every readable run_log.json under `runs_dir`, oldest first.

    A run interrupted mid-write leaves invalid JSON behind -- skipped with a
    warning rather than aborting the export, since one truncated run must not
    make every other run's labels unreachable.
    """
    for path in sorted(runs_dir.glob("*/run_log.json")):
        try:
            yield path, json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            print(f"warning: skipping unreadable {path} ({exc})", file=sys.stderr)


def _beat_rows(run_path: Path, log: dict) -> Iterator[dict]:
    # A --mock run's prompts are literally "[MOCK]" and its images are
    # placeholders, so its rows would look like data and be worthless.
    # Excluded here rather than left to every consumer to remember.
    if log.get("mock"):
        return
    run_context = {field: log.get(field) for field in _RUN_FIELDS}
    for beat_result in log.get("previz_beats", []):
        beat = beat_result.get("beat", {})
        # A beat with no image and no attempt that the human accepted was
        # given up on. `image_path` is None for both that and a run cut off
        # mid-beat, so it alone can't distinguish them.
        # An interrupted beat also has no image_path, but the human never
        # ruled on it -- treating that as a give-up would invent a label
        # (docs/decisions/0056).
        gave_up = beat_result.get("image_path") is None and not beat_result.get("in_progress")
        for attempt in beat_result.get("attempts", []):
            # `accepted: None` means the attempt was recorded before the
            # human answered. Its candidates carry no judgement at all, so
            # they are not negatives.
            if attempt.get("accepted") is None:
                continue
            candidates = attempt.get("candidates") or []
            # Before docs/decisions/0053 this was a list of bare path
            # strings with no prompt attached. Those images exist on disk
            # but are not usable labels, and the shape difference is the
            # only way to tell -- checking for an empty list is not enough.
            if not all(isinstance(c, dict) for c in candidates):
                continue
            if not candidates:
                continue
            # Under --yes the first candidate is taken with no human in
            # the loop. Those rows record what happened but are not
            # preference data, so they are labelled rather than silently
            # mixed in (docs/decisions/0053). Recorded by the run, not
            # inferred: an auto-pick and a human choosing candidate 1 look
            # identical from the outside.
            unattended = bool(attempt.get("unattended"))
            kept_paths = [c["path"] for c in candidates if c.get("kept")]
            for candidate in candidates:
                siblings = [
                    _repo_relative(c["path"])
                    for c in candidates
                    if c["path"] != candidate["path"]
                ]
                yield {
                    "run": run_path.parent.name,
                    "beat_index": beat_result.get("index"),
                    "cycle": attempt.get("cycle"),
                    "attempt": attempt.get("attempt"),
                    "image_path": _repo_relative(candidate["path"]),
                    # The exact text sent to the image model. The whole
                    # point: a beat's fields can't reconstruct it, because
                    # _build_beat_prompt changes over time.
                    "prompt_used": candidate["prompt_used"],
                    "kept": bool(candidate.get("kept")),
                    "chosen_over": siblings,
                    "had_a_winner": bool(kept_paths),
                    "gave_up": gave_up,
                    "unattended": unattended,
                    "human_action": attempt.get("human_action"),
                    "human_choice": attempt.get("human_choice"),
                    "feedback": attempt.get("feedback"),
                    # The judge's opinion, and ONLY on the image it
                    # actually scored. previz_review runs once per attempt,
                    # on the candidate the human kept -- copying its verdict
                    # onto the siblings it never saw would manufacture
                    # agreement and disagreement out of nothing, in the one
                    # study this dataset exists to support
                    # (docs/playbook/eval-loop-plan.md, step 2).
                    "review_accepted": (
                        attempt.get("review_accepted") if candidate.get("kept") else None
                    ),
                    "review_concern": (
                        attempt.get("concern") if candidate.get("kept") else None
                    ),
                    "beat_camera": beat.get("camera"),
                    "beat_action": beat.get("action"),
                    "n_characters": len(beat.get("staging", [])),
                    **run_context,
                }


def _row_identity(row: dict) -> tuple:
    """What makes one labelled image itself, for merging."""
    return tuple(row.get(field) for field in _IDENTITY_FIELDS)


def _sort_key(row: dict) -> tuple:
    """A total order over rows, so the committed file diffs as an append.

    Ints are kept as ints rather than stringified so beat 10 sorts after
    beat 2; a missing or wrong-typed field sorts first instead of raising,
    since a write that aborts on one odd row loses every other row with it.
    """

    def _n(value: object) -> int:
        return value if isinstance(value, int) else -1

    return (
        str(row.get("run") or ""),
        _n(row.get("beat_index")),
        _n(row.get("cycle")),
        _n(row.get("attempt")),
        str(row.get("image_path") or ""),
    )


def _read_dataset(path: Path) -> list[dict]:
    """Rows already committed, or none if the dataset does not exist yet.

    A malformed line fails loud rather than being skipped. Everywhere else
    in this script a bad input is skipped with a warning, because the run
    logs are disposable and one truncated run must not block the rest --
    but this file is the only copy of its labels, and silently dropping a
    line here would delete data on the next write.
    """
    if not path.exists():
        return []
    rows = []
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{path}:{number}: corrupt dataset line ({exc})") from exc
    return rows


def _merge(existing: list[dict], fresh: list[dict]) -> list[dict]:
    """Union of both, fresh winning on a collision -- never fewer rows.

    A run log is the better source while it still exists: a beat the human
    had not ruled on yet exports no row at all, and gets one once they do.
    But `outputs/` is pruned, so rows whose run is gone have no fresh
    counterpart and must survive untouched (docs/decisions/0074).
    """
    merged = {_row_identity(row): row for row in existing}
    merged.update({_row_identity(row): row for row in fresh})
    return sorted(merged.values(), key=_sort_key)


def _write_dataset(path: Path, rows: list[dict]) -> None:
    # sort_keys so a field's position in the line never moves, and the diff
    # shows what actually changed rather than a reshuffle.
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))


def _summarise(rows: list[dict]) -> str:
    if not rows:
        return (
            "No labelled judgements found.\n"
            "Runs from before docs/decisions/0053 don't record candidate prompts, "
            "so they can't be exported. Do one interactive run to produce some."
        )
    unattended = sum(r["unattended"] for r in rows)
    rows = [r for r in rows if not r["unattended"]]
    if not rows:
        return (
            f"{unattended} row(s) found, all from unattended (--yes) attempts.\n"
            "Those record what happened but are not preference data. "
            "One interactive run produces real labels."
        )
    kept = sum(r["kept"] for r in rows)
    with_feedback = sum(r["feedback"] is not None for r in rows)
    given_up = len({(r["run"], r["beat_index"]) for r in rows if r["gave_up"]})
    runs = len({r["run"] for r in rows})
    # Where the judge ran on the image the human also judged. Agreement is
    # the number that decides previz_review's fate, so it is surfaced here
    # rather than left for a separate script to rediscover.
    both = [r for r in rows if r["review_accepted"] is not None]
    agreed = sum(r["review_accepted"] == r["kept"] for r in both)
    lines = [
        f"{len(rows)} labelled image(s) across {runs} run(s)"
        + (f" ({unattended} unattended row(s) excluded)" if unattended else ""),
        f"  kept:        {kept}",
        f"  rejected:    {len(rows) - kept}",
        f"  beats given up on: {given_up}",
        f"  with written feedback: {with_feedback}",
    ]
    if both:
        lines.append(
            f"  previz_review agreed with the human on {agreed}/{len(both)} "
            f"image(s) it also scored ({agreed / len(both):.0%})"
        )
    else:
        lines.append("  previz_review scored none of these images")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runs",
        type=Path,
        default=None,
        help="directory of run_* output folders (default: outputs/)",
    )
    parser.add_argument(
        "--out",
        help="write JSONL here; '-' for stdout. Omit to print only the summary.",
    )
    parser.add_argument(
        "--update-dataset",
        nargs="?",
        const=str(DATASET_PATH),
        default=None,
        metavar="PATH",
        help=(
            "merge these rows into the committed dataset "
            f"(default: {DATASET_PATH.relative_to(REPO_ROOT)}) and rewrite it"
        ),
    )
    args = parser.parse_args()

    # A missing outputs/ is the normal state of a fresh checkout -- it is
    # gitignored, so nobody has run the pipeline there yet. That is zero
    # judgements, not an error. A --runs path given explicitly and missing
    # is a typo and still fails, since silently reporting zero rows for it
    # would look like a real answer.
    runs_dir = args.runs or (REPO_ROOT / "outputs")
    if args.runs is not None and not args.runs.exists():
        raise SystemExit(f"No such directory: {args.runs}")

    rows = (
        [row for path, log in _run_logs(runs_dir) for row in _beat_rows(path, log)]
        if runs_dir.exists()
        else []
    )

    if args.out:
        lines = "".join(json.dumps(row) + "\n" for row in rows)
        if args.out == "-":
            sys.stdout.write(lines)
        else:
            Path(args.out).write_text(lines)
            print(f"Wrote {len(rows)} row(s) to {args.out}")

    # The merged dataset, not this export, is what later studies read, so
    # it is what gets summarised once there is one.
    summarised = rows
    if args.update_dataset:
        dataset = Path(args.update_dataset)
        existing = _read_dataset(dataset)
        summarised = _merge(existing, rows)
        _write_dataset(dataset, summarised)
        print(
            f"{dataset}: {len(summarised)} row(s), "
            f"{len(summarised) - len(existing)} new from {runs_dir}"
        )

    print(_summarise(summarised), file=sys.stderr if args.out == "-" else sys.stdout)


if __name__ == "__main__":
    main()
