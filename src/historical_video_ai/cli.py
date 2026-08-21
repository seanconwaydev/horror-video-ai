"""Interactive CLI entry point for the v1 pipeline: collects a scene
(time, place, description), runs it through research -> fact-check ->
previz, showing each stage's output and pausing for confirmation before
continuing (except previz, which just runs and ends).

See docs/decisions/0006-narrow-v1-scope-single-image.md for why the
pipeline is scoped this way. Run with `uv run historical-video-ai` (or
`uv run python -m historical_video_ai.cli`), add --mock to exercise the
pipeline's mechanics with no network calls and no API keys.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from historical_video_ai.config import load_environment
from historical_video_ai.stages.fact_check import run_fact_check_stage
from historical_video_ai.stages.previz import run_previz_stage
from historical_video_ai.stages.research import run_research_stage

_MOCK_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _mock_completion(**kwargs):
    """No network call, no API key -- returns a plausible-shaped fake so
    the pipeline's mechanics (ordering, confirm-loop, run logging) can be
    exercised without cost or credentials. Used only with --mock."""
    prompt = kwargs["messages"][0]["content"]
    if "Claims to check" in prompt:
        content = json.dumps({"flags": []})
    else:
        content = json.dumps(
            {
                "claims": [
                    {
                        "text": "[MOCK] A placeholder claim standing in for real research.",
                        "source": "[MOCK] no real source -- this is a dry run",
                        "date": None,
                        "names": [],
                    }
                ]
            }
        )
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def _mock_image(**kwargs):
    return SimpleNamespace(data=[SimpleNamespace(b64_json=_MOCK_PNG_B64)])


def _confirm(prompt: str) -> bool:
    while True:
        answer = input(f"{prompt} [y/n]: ").strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("Please answer y or n.")


def _prompt_if_missing(value: str | None, label: str) -> str:
    while not value:
        value = input(f"{label}: ").strip()
    return value


def _run_dir() -> Path:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    d = Path("outputs") / f"run_{run_id}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_log(out_dir: Path, log: dict) -> None:
    (out_dir / "run_log.json").write_text(json.dumps(log, indent=2, default=str))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the research -> fact-check -> previz pipeline for one scene."
    )
    parser.add_argument("--time", help="When the scene takes place, e.g. 'July 1969'.")
    parser.add_argument("--place", help="Where the scene takes place.")
    parser.add_argument("--description", help="What the main character does, third person.")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="No network calls, no API keys -- exercise the pipeline's mechanics only.",
    )
    args = parser.parse_args()

    time = _prompt_if_missing(args.time, "Time")
    place = _prompt_if_missing(args.place, "Place")
    description = _prompt_if_missing(args.description, "What the main character does")

    if not args.mock:
        load_environment()

    completion_kwargs = {"completion_fn": _mock_completion} if args.mock else {}
    image_kwargs = {"image_fn": _mock_image} if args.mock else {}

    out_dir = _run_dir()
    log = {"time": time, "place": place, "description": description, "mock": args.mock}

    print("\n--- research ---")
    fact_sheet = run_research_stage(time, place, description, **completion_kwargs)
    for c in fact_sheet.claims:
        print(f"- {c.text} [source: {c.source}]")
    log["research_claims"] = [dataclasses.asdict(c) for c in fact_sheet.claims]
    _write_log(out_dir, log)
    if not _confirm("\nProceed to fact-check with this research?"):
        print(f"Stopped by user. Run artifacts saved in {out_dir}")
        return

    print("\n--- fact-check ---")
    fact_check_result = run_fact_check_stage(fact_sheet, **completion_kwargs)
    if fact_check_result.flags:
        for f in fact_check_result.flags:
            print(f"- [{f.severity}] {f.claim_text} -- {f.concern}")
    else:
        print("No issues flagged.")
    log["fact_check_flags"] = [dataclasses.asdict(f) for f in fact_check_result.flags]
    _write_log(out_dir, log)
    if not _confirm("\nProceed to previz with this fact-check result?"):
        print(f"Stopped by user. Run artifacts saved in {out_dir}")
        return

    print("\n--- previz ---")
    previz_result = run_previz_stage(fact_check_result, output_dir=out_dir, **image_kwargs)
    log["previz_image_path"] = str(previz_result.image_path)
    log["previz_prompt_used"] = previz_result.prompt_used
    _write_log(out_dir, log)
    print(f"Image saved to {previz_result.image_path}")

    print(f"\nDone. Run artifacts saved in {out_dir}")


if __name__ == "__main__":
    main()
