"""Build a blind view of a multi-arm result directory, for human scoring.

Arms are relabelled W/X/Y/Z with a single shuffle applied across the whole
run, not per beat. That matters: labels have to stay stable across beats
so identity consistency -- is this the same person in all three? -- is
still judgeable, while which arm is which stays hidden.

Reads `anchor_scene.json` for the planned text it shows beside each
image. That fixture is deliberately frozen at a pre-0049 shape (ADR 0064),
so a blind view built over a *current* run's results would show it plan
text that run never used -- point this at the anchor-* results it was
written for.

Usage:
    uv run python evals/blind_view.py evals/results/anchor-<timestamp>
    uv run python evals/blind_view.py --reveal evals/results/anchor-<timestamp>
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
from pathlib import Path

LABELS = ["W", "X", "Y", "Z"]

CRITERIA = [
    ("action", "Does the figure's pose and action match the planned action text?"),
    ("camera", "Does the shot match the planned camera position and angle?"),
    ("mood", "Does it read as dread?"),
]


def build(run_dir: Path, seed: int | None) -> None:
    arms = sorted(p.name.removeprefix("arm_") for p in run_dir.glob("arm_*"))
    beats = sorted({int(p.stem.removeprefix("beat_")) for p in run_dir.glob("arm_*/beat_*.png")})

    rng = random.Random(seed)
    labels = LABELS[: len(arms)]
    rng.shuffle(labels)
    mapping = dict(zip(labels, arms, strict=True))

    blind_dir = run_dir / "blind"
    if blind_dir.exists():
        shutil.rmtree(blind_dir)
    for label, arm in mapping.items():
        (blind_dir / label).mkdir(parents=True)
        for beat in beats:
            shutil.copy2(run_dir / f"arm_{arm}" / f"beat_{beat}.png", blind_dir / label / f"beat_{beat}.png")

    (run_dir / "blind_key.json").write_text(json.dumps(mapping, indent=2))

    lines = [
        "# Blind scoring — reference anchor",
        "",
        "Four versions of the same three beats. Only the character reference differs.",
        "**Do not open blind_key.json until you're done.**",
        "",
        "## Part 1 — per beat: which version best matches the plan?",
        "",
        "Open all four for one beat side by side, then put a single letter per row.",
        "If none is good, still pick the least bad — this is a comparison, not a grade.",
        "",
    ]
    plan_path = Path(__file__).parent / "anchor_scene.json"
    planned = json.loads(plan_path.read_text())["plan"]["beats"] if plan_path.exists() else []

    for beat in beats:
        lines += [f"### beat {beat}", ""]
        if beat <= len(planned):
            spec = planned[beat - 1]
            lines += [
                "> **Planned action** — " + spec["action"],
                ">",
                "> **Planned camera** — " + spec["camera"],
                "",
            ]
        lines += ["| criterion | best (W/X/Y/Z) | why |", "|---|---|---|"]
        lines += [f"| {name} — {question} | | |" for name, question in CRITERIA]
        lines.append("")
    lines += [
        "## Part 2 — per version: is it the same person in all three beats?",
        "",
        "This is the whole reason the character reference exists, so it has to be",
        "weighed against Part 1 rather than read on its own.",
        "",
        "| version | same person across its 3 beats? | notes |",
        "|---|---|---|",
    ]
    lines += [f"| {label} | | |" for label in sorted(mapping)]
    lines += ["", "Reveal with:", "", f"    uv run python evals/blind_view.py --reveal {run_dir}", ""]
    (run_dir / "SCORING.md").write_text("\n".join(lines))

    print(f"Blind view: {blind_dir}")
    for label in sorted(mapping):
        print(f"  {label}/  ({len(beats)} beats)")
    print(f"\nScore in {run_dir / 'SCORING.md'} — do not open blind_key.json first.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--reveal", action="store_true", help="print the label-to-arm mapping")
    parser.add_argument("--seed", type=int, help="fix the shuffle")
    args = parser.parse_args()

    if args.reveal:
        mapping = json.loads((args.run_dir / "blind_key.json").read_text())
        print("Label -> arm:")
        for label, arm in sorted(mapping.items()):
            print(f"  {label} = {arm}")
        return
    build(args.run_dir, args.seed)


if __name__ == "__main__":
    main()
