"""Interactive CLI entry point for the v1 pipeline: collects a scene
(time, place, description), runs it through research -> fact-check ->
previz, showing each stage's output and pausing for confirmation before
continuing (except previz, which just runs and ends).

See docs/decisions/0006-narrow-v1-scope-single-image.md for why the
pipeline is scoped this way. Run with `uv run historical-video-ai` (or
`uv run python -m historical_video_ai.cli`).

Two ways to avoid paying for research/fact-check on every iteration:
- `--mock`: no network calls, no API keys at all -- synthetic placeholder
  data for every stage. Good for exercising pipeline mechanics only.
- `--fixture <path>`: replays a previously captured *real* research +
  fact-check result (same shape this file already writes to run_log.json),
  skipping those two API calls entirely while still running previz for
  real. Use this once you've found a research output worth reusing --
  see tests/fixtures/. Combine with --mock for fully offline iteration on
  real historical claims with a zero-cost previz too.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from historical_video_ai.config import get_stage_model, load_environment
from historical_video_ai.stages.fact_check import ClaimFlag, FactCheckResult, run_fact_check_stage
from historical_video_ai.stages.previz import run_previz_stage
from historical_video_ai.stages.research import Claim, FactSheet, run_research_stage

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
    """time/place/description are all required (docs/decisions/0006) --
    loop until a non-empty value is given, printing an explicit error on
    every empty attempt (whether it came in empty via a CLI flag or was
    left blank at the prompt) rather than silently re-prompting."""
    while not value:
        print(f"Error: {label} is required and cannot be empty.")
        value = input(f"{label}: ").strip()
    return value


def _resolve_flags(fact_sheet: FactSheet, flags: list[ClaimFlag]) -> FactSheet:
    """Give the human the final say on each fact-check flag -- accept the
    claim as-is, cut it, or soften its wording -- per docs/pipeline.md's
    stage 3 review gate. Previously nothing did this: previz silently
    auto-excluded "contradicted" claims (unreliably -- see fact_check.py's
    claim_text validation) and left "uncertain" ones untouched either way,
    with no way to override either outcome. Returns fact_sheet unchanged if
    there are no flags to resolve."""
    if not flags:
        return fact_sheet

    claims_by_text = {c.text: c for c in fact_sheet.claims}
    resolved_claims = list(fact_sheet.claims)

    print("\nResolve flagged claims:")
    for flag in flags:
        claim = claims_by_text[flag.claim_text]
        print(f"\nClaim: {claim.text}")
        print(f"Flag [{flag.severity}]: {flag.concern}")
        action = ""
        while action not in ("a", "c", "s"):
            action = input("(a)ccept / (c)ut / (s)often this claim? [a/c/s]: ").strip().lower()
        if action == "c":
            resolved_claims = [c for c in resolved_claims if c.text != claim.text]
        elif action == "s":
            new_text = ""
            while not new_text:
                new_text = input("New text for this claim: ").strip()
            resolved_claims = [
                dataclasses.replace(c, text=new_text) if c.text == claim.text else c
                for c in resolved_claims
            ]
        # "a" (accept): keep the claim exactly as research produced it.

    return dataclasses.replace(fact_sheet, claims=resolved_claims)


def _project_root() -> Path:
    """Walk up from this file looking for pyproject.toml, so outputs/
    always lands in the same place regardless of the directory the command
    was invoked from. (Previously outputs/ was created relative to the
    current working directory, which silently nested outputs/outputs/ if
    you happened to be inside a prior run's outputs/ folder when you ran
    the command again.)"""
    here = Path(__file__).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "pyproject.toml").exists():
            return candidate
    return here.parents[2]  # fallback: src/historical_video_ai/cli.py -> repo root


def _run_dir() -> Path:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    d = _project_root() / "outputs" / f"run_{run_id}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_log(out_dir: Path, log: dict) -> None:
    (out_dir / "run_log.json").write_text(json.dumps(log, indent=2, default=str))


def _load_fixture(path: Path) -> FactCheckResult:
    """Reconstruct a real FactSheet + FactCheckResult from a previously
    saved run_log.json (or anything matching its shape), so research and
    fact-check don't need to run -- and cost nothing -- again.

    Raises FileNotFoundError / KeyError as-is if the fixture is missing or
    malformed, rather than silently degrading into an empty scene. Also
    raises ValueError if time/place/description are missing or empty --
    they're required (docs/decisions/0006) whether the scene came from a
    live prompt or a fixture file."""
    data = json.loads(path.read_text())
    for required_field in ("time", "place", "description"):
        if not data.get(required_field):
            raise ValueError(f"Fixture {path} is missing a non-empty '{required_field}'")
    claims = [Claim(**c) for c in data["research_claims"]]
    fact_sheet = FactSheet(
        time=data["time"],
        place=data["place"],
        description=data["description"],
        claims=claims,
    )
    flags = [ClaimFlag(**f) for f in data["fact_check_flags"]]

    # Same invariant fact_check.py's _parse_flags enforces on a live model
    # response -- a fixture captured before that validation existed (or
    # hand-edited) could still have a flag whose claim_text doesn't match
    # any claim verbatim, which would otherwise crash _resolve_flags with a
    # raw KeyError instead of a clear, actionable error.
    known_claim_texts = {c.text for c in claims}
    for flag in flags:
        if flag.claim_text not in known_claim_texts:
            raise ValueError(
                f"Fixture {path} has a flag whose claim_text doesn't exactly "
                f"match any research claim: {flag.claim_text!r}"
            )

    return FactCheckResult(fact_sheet=fact_sheet, flags=flags)


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
    parser.add_argument(
        "--fixture",
        type=Path,
        help=(
            "Path to a previously captured real run_log.json -- replays its "
            "research + fact-check output instead of calling those APIs "
            "again (previz still runs for real unless --mock is also set)."
        ),
    )
    parser.add_argument(
        "--experiment-model",
        help=(
            "Override the pinned research + fact_check models for this run "
            "only (config/models.yaml is untouched) -- e.g. "
            "'deepseek/deepseek-v4-flash' to try DeepSeek in place of "
            "Perplexity/Gemini. Note this drops fact_check's live search grounding "
            "(docs/decisions/0007), since DeepSeek doesn't have it -- this "
            "is meant for a quick quality/cost comparison, not a real "
            "replacement for the pinned choices. previz is unaffected "
            "(DeepSeek isn't an image model). No effect with --fixture, "
            "since research/fact-check don't run at all in that mode."
        ),
    )
    args = parser.parse_args()

    if args.fixture and args.experiment_model:
        print(
            "Warning: --experiment-model has no effect with --fixture -- "
            "research/fact-check are loaded from the fixture, not run."
        )

    if not args.mock:
        load_environment()

    completion_kwargs = {"completion_fn": _mock_completion} if args.mock else {}
    image_kwargs = {"image_fn": _mock_image} if args.mock else {}

    research_model = args.experiment_model or get_stage_model("research")
    fact_check_model = args.experiment_model or get_stage_model("fact_check")

    out_dir = _run_dir()

    if args.fixture:
        fact_check_result = _load_fixture(args.fixture)
        fact_sheet = fact_check_result.fact_sheet
        time, place, description = fact_sheet.time, fact_sheet.place, fact_sheet.description
        log = {"time": time, "place": place, "description": description, "mock": args.mock}
        log["fixture"] = str(args.fixture)

        print(f"\n--- research (loaded from fixture: {args.fixture}) ---")
        for c in fact_sheet.claims:
            print(f"- {c.text} [source: {c.source}]")
        log["research_claims"] = [dataclasses.asdict(c) for c in fact_sheet.claims]

        print("\n--- fact-check (loaded from fixture) ---")
        if fact_check_result.flags:
            for f in fact_check_result.flags:
                print(f"- [{f.severity}] {f.claim_text} -- {f.concern}")
        else:
            print("No issues flagged.")
        log["fact_check_flags"] = [dataclasses.asdict(f) for f in fact_check_result.flags]

        resolved_fact_sheet = _resolve_flags(fact_sheet, fact_check_result.flags)
        fact_check_result = dataclasses.replace(fact_check_result, fact_sheet=resolved_fact_sheet)
        log["research_claims"] = [dataclasses.asdict(c) for c in resolved_fact_sheet.claims]
        _write_log(out_dir, log)

        if not _confirm("\nProceed to previz with this fixture's fact-check result?"):
            print(f"Stopped by user. Run artifacts saved in {out_dir}")
            return
    else:
        time = _prompt_if_missing(args.time, "Time")
        place = _prompt_if_missing(args.place, "Place")
        description = _prompt_if_missing(args.description, "What the main character does")
        log = {"time": time, "place": place, "description": description, "mock": args.mock}

        print(f"\n--- research (model: {research_model}) ---")
        fact_sheet = run_research_stage(
            time, place, description, model=research_model, **completion_kwargs
        )
        for c in fact_sheet.claims:
            print(f"- {c.text} [source: {c.source}]")
        log["research_model"] = research_model
        log["research_claims"] = [dataclasses.asdict(c) for c in fact_sheet.claims]
        _write_log(out_dir, log)
        if not _confirm("\nProceed to fact-check with this research?"):
            print(f"Stopped by user. Run artifacts saved in {out_dir}")
            return

        print(f"\n--- fact-check (model: {fact_check_model}) ---")
        fact_check_result = run_fact_check_stage(
            fact_sheet, model=fact_check_model, **completion_kwargs
        )
        log["fact_check_model"] = fact_check_model
        if fact_check_result.flags:
            for f in fact_check_result.flags:
                print(f"- [{f.severity}] {f.claim_text} -- {f.concern}")
        else:
            print("No issues flagged.")
        log["fact_check_flags"] = [dataclasses.asdict(f) for f in fact_check_result.flags]

        resolved_fact_sheet = _resolve_flags(fact_sheet, fact_check_result.flags)
        fact_check_result = dataclasses.replace(fact_check_result, fact_sheet=resolved_fact_sheet)
        log["research_claims"] = [dataclasses.asdict(c) for c in resolved_fact_sheet.claims]
        _write_log(out_dir, log)
        if not _confirm("\nProceed to previz with this fact-check result?"):
            print(f"Stopped by user. Run artifacts saved in {out_dir}")
            return

    previz_model = get_stage_model("previz")
    print(f"\n--- previz (model: {previz_model}) ---")
    previz_result = run_previz_stage(
        fact_check_result, model=previz_model, output_dir=out_dir, **image_kwargs
    )
    log["previz_model"] = previz_model
    log["previz_image_path"] = str(previz_result.image_path)
    log["previz_prompt_used"] = previz_result.prompt_used
    _write_log(out_dir, log)
    print(f"Image saved to {previz_result.image_path}")

    print(f"\nDone. Run artifacts saved in {out_dir}")


if __name__ == "__main__":
    main()
