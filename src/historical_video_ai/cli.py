"""Interactive CLI entry point for the v1 pipeline: collects a scene
(time, place, description), runs it through research -> fact-check ->
previz, showing each stage's output and pausing for confirmation before
continuing (except previz, which just runs and ends).

See docs/decisions/0006-narrow-v1-scope-single-image.md for why the
pipeline is scoped this way. Run with `uv run historical-video-ai` (or
`uv run python -m historical_video_ai.cli`).

If fact-check flags the scene's own premise as historically impossible --
not a single claim being wrong, but the requested scene depicting something
that couldn't have existed or happened yet -- this pipeline refuses to
generate an image of it as asked. See docs/decisions/0008-refuse-impossible-
premises.md and _resolve_premise_conflict: you're offered a suggested
historically-plausible alternative (if one exists), or can supply your own
corrected description, which gets freshly re-verified before continuing;
declining both stops the run.

previz's *image* also gets independently reviewed before you see it -- a
hedged, accurate text prompt can still produce an image that unambiguously
depicts something impossible (see docs/decisions/0009-previz-image-review.md
and PrevizReview's docstring). A rejected image is regenerated blind, no
prompt rewriting between attempts, up to _MAX_PREVIZ_ATTEMPTS times; giving
up after that stops the run with no image produced, same "refuse rather
than fabricate" principle as the premise-conflict check.

Two ways to avoid paying for research/fact-check on every iteration:
- `--mock`: no network calls, no API keys at all -- synthetic placeholder
  data for every stage. Good for exercising pipeline mechanics only.
- `--fixture <path>`: replays a previously captured *real* research +
  fact-check result (same shape this file already writes to run_log.json),
  skipping those two API calls entirely while still running previz for
  real. Use this once you've found a research output worth reusing --
  see tests/fixtures/. Combine with --mock for fully offline iteration on
  real historical claims with a zero-cost previz too.

`--video-gen-from <run_dir> [<run_dir> ...]` runs stage 9 (video generation)
standalone, skipping research, fact-check, and previz entirely: each given
run directory must already contain a completed previz result, and becomes
one scene's anchor image + prompt (see docs/decisions/0010-video-generation-
model-and-standalone-stage.md). Passing multiple directories generates one
clip per directory. Combine with --mock to exercise the polling loop without
a real API call. --video-seconds requests a specific clip duration; see
docs/decisions/0012-video-generation-duration.md for what's actually been
confirmed to work against the real API.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from historical_video_ai.config import get_stage_model, load_environment
from historical_video_ai.stages.fact_check import (
    ClaimFlag,
    FactCheckResult,
    PremiseConflict,
    run_fact_check_stage,
)
from historical_video_ai.stages.previz import (
    PrevizResult,
    run_previz_review_stage,
    run_previz_stage,
)
from historical_video_ai.stages.research import Claim, FactSheet, run_research_stage
from historical_video_ai.stages.video_generation import run_video_generation_stage

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


def _mock_review_completion(**kwargs):
    """No network call, no API key -- always accepts, so --mock exercises
    the previz-review loop's mechanics without cost or credentials."""
    content = json.dumps({"accepted": True, "concern": None})
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def _mock_video_generation(**kwargs):
    """No network call, no API key -- returns a job already 'completed', so
    --video-gen-from --mock exercises the polling loop's mechanics (it just
    skips the loop entirely, since the job is terminal on creation) without
    cost or credentials."""
    return SimpleNamespace(id="mock-video-id", status="completed", error=None)


def _mock_video_status(**kwargs):
    return SimpleNamespace(id="mock-video-id", status="completed", error=None)


def _mock_video_content(**kwargs):
    return b"[MOCK] not a real video file"


# See docs/decisions/0009-previz-image-review.md -- your call: bounded, not
# tunable via a flag, to keep behavior predictable rather than open-ended.
_MAX_PREVIZ_ATTEMPTS = 3


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


def _run_research_and_fact_check(
    time: str,
    place: str,
    description: str,
    *,
    research_model: str,
    fact_check_model: str,
    completion_kwargs: dict,
) -> tuple[FactSheet, FactCheckResult] | None:
    """Run research then fact-check for real, printing progress and pausing
    for the research review gate. Returns None if the human declines to
    proceed past research. Shared so a premise-conflict correction (see
    _resolve_premise_conflict) can re-run this exact sequence on a
    corrected description, rather than duplicating it."""
    print(f"\n--- research (model: {research_model}) ---")
    fact_sheet = run_research_stage(
        time, place, description, model=research_model, **completion_kwargs
    )
    for c in fact_sheet.claims:
        print(f"- {c.text} [source: {c.source}]")
    if not _confirm("\nProceed to fact-check with this research?"):
        return None

    print(f"\n--- fact-check (model: {fact_check_model}) ---")
    fact_check_result = run_fact_check_stage(fact_sheet, model=fact_check_model, **completion_kwargs)
    if fact_check_result.flags:
        for f in fact_check_result.flags:
            print(f"- [{f.severity}] {f.claim_text} -- {f.concern}")
    else:
        print("No issues flagged.")

    return fact_sheet, fact_check_result


def _resolve_premise_conflict(
    fact_sheet: FactSheet,
    fact_check_result: FactCheckResult,
    *,
    time: str,
    place: str,
    research_model: str,
    fact_check_model: str,
    completion_kwargs: dict,
) -> tuple[FactSheet, FactCheckResult] | None:
    """Per docs/decisions/0008-refuse-impossible-premises.md: if fact-check
    flagged the scene's own premise as historically impossible, push back
    instead of silently proceeding (previz would refuse anyway -- see its
    PrevizError check -- but that's a last-resort safety net, not a
    substitute for actually asking). Offers the suggested alternative if
    there is one, or lets the human supply their own corrected description,
    then re-verifies it for real with one fresh research + fact-check pass
    (per your call: correcting the premise re-runs research rather than
    reusing the old claims, since they were shaped by the original,
    impossible premise).

    Returns the resolved (fact_sheet, fact_check_result) pair, or None if
    the human chose to stop. Only re-verifies once -- if the corrected
    description still has an unresolved premise conflict, that's reported
    and treated as a stop rather than looping indefinitely; try a fresh run
    instead.
    """
    conflict = fact_check_result.premise_conflict
    if conflict is None:
        return fact_sheet, fact_check_result

    print(f"\nThis scene's premise appears to be historically impossible: {conflict.explanation}")

    new_description: str | None = None
    if conflict.suggested_alternative:
        print(f"Closest historically plausible version: {conflict.suggested_alternative}")
        if _confirm("Use this instead?"):
            new_description = conflict.suggested_alternative
    else:
        print("No reasonably close, historically plausible version of this scene was found.")

    if new_description is None:
        if _confirm("Provide your own corrected description instead?"):
            new_description = _prompt_if_missing(None, "Corrected description")
        else:
            print("Stopping -- the scene's premise was never resolved.")
            return None

    print(f"\nRe-verifying with the corrected description: {new_description!r}")
    result = _run_research_and_fact_check(
        time,
        place,
        new_description,
        research_model=research_model,
        fact_check_model=fact_check_model,
        completion_kwargs=completion_kwargs,
    )
    if result is None:
        print("Stopping -- declined to proceed past research on the corrected description.")
        return None
    new_fact_sheet, new_fact_check_result = result

    if new_fact_check_result.premise_conflict is not None:
        print(
            "\nThe corrected description still has an unresolved premise "
            f"conflict: {new_fact_check_result.premise_conflict.explanation}\n"
            "Stopping rather than looping indefinitely -- try a fresh run "
            "with a different description."
        )
        return None

    return new_fact_sheet, new_fact_check_result


def _generate_previz_with_review(
    fact_check_result: FactCheckResult,
    *,
    previz_model: str,
    review_model: str,
    image_kwargs: dict,
    review_kwargs: dict,
    out_dir: Path,
    on_image_generated: Callable[[PrevizResult], None] | None = None,
) -> tuple[PrevizResult | None, list[dict]]:
    """Generate previz's image, then have an independent pass review the
    actual image -- not just the text prompt -- against the scene (see
    docs/decisions/0009-previz-image-review.md). On rejection, regenerates
    blind: no prompt rewriting between attempts, per your call to avoid
    that rabbit hole in favor of a hard cap (_MAX_PREVIZ_ATTEMPTS).

    Returns (accepted PrevizResult, attempt log) once accepted, or
    (None, attempt log) if every attempt was rejected -- giving up rather
    than looping indefinitely, same principle as _resolve_premise_conflict.
    A rejected attempt's image is archived as previz_attempt_<n>_rejected
    .png (rather than silently overwritten by the next attempt) so the
    reason it was rejected has something to point at.

    `on_image_generated`, if given, is called with each attempt's
    PrevizResult right after the image is written -- *before* the review
    call, which can itself fail (a real, observed case: previz_review's
    model raising an auth error on a missing API key). Without this,
    main()'s run_log.json only recorded previz_image_path/prompt_used after
    this whole function returned, which meant a review-stage crash left a
    real, already-generated (and already paid for) image on disk with no
    record of it in the log -- exactly the gap --video-gen-from's
    _load_previz_output depends on not having. Hooking in here instead of
    writing the log directly keeps this function's only concern generation
    + review, not log-file format.
    """
    attempts: list[dict] = []
    for attempt in range(1, _MAX_PREVIZ_ATTEMPTS + 1):
        print(f"\n--- previz (model: {previz_model}, attempt {attempt}/{_MAX_PREVIZ_ATTEMPTS}) ---")
        previz_result = run_previz_stage(
            fact_check_result, model=previz_model, output_dir=out_dir, **image_kwargs
        )
        print(f"Image saved to {previz_result.image_path}")
        if on_image_generated is not None:
            on_image_generated(previz_result)

        print(f"--- previz review (model: {review_model}) ---")
        review = run_previz_review_stage(
            previz_result.image_path, fact_check_result, model=review_model, **review_kwargs
        )

        if review.accepted:
            print("Accepted.")
            attempts.append({"attempt": attempt, "accepted": True, "concern": None})
            return previz_result, attempts

        print(f"Rejected: {review.concern}")
        archived_path = out_dir / f"previz_attempt_{attempt}_rejected.png"
        previz_result.image_path.rename(archived_path)
        attempts.append(
            {
                "attempt": attempt,
                "accepted": False,
                "concern": review.concern,
                "image_path": str(archived_path),
            }
        )
        if attempt < _MAX_PREVIZ_ATTEMPTS:
            print("Regenerating...")

    print(f"\nGiving up after {_MAX_PREVIZ_ATTEMPTS} rejected attempts.")
    return None, attempts


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

    raw_premise_conflict = data.get("premise_conflict")
    premise_conflict = (
        PremiseConflict(**raw_premise_conflict) if raw_premise_conflict is not None else None
    )

    return FactCheckResult(fact_sheet=fact_sheet, flags=flags, premise_conflict=premise_conflict)


def _load_previz_output(run_dir: Path) -> tuple[Path, str]:
    """Load a previously generated previz image and the prompt used to
    produce it from an existing run's run_log.json, so --video-gen-from can
    run stage 9 standalone against real previz output instead of requiring
    a fresh research -> fact-check -> previz pass every time. Reuses the
    run_log.json this file already writes rather than inventing a separate
    manifest format for (image, prompt) pairs -- see
    docs/decisions/0010-video-generation-model-and-standalone-stage.md.

    Raises FileNotFoundError if run_dir has no run_log.json, or if the
    image path it references no longer exists on disk, and ValueError if
    the log doesn't show a completed previz result -- fails loud rather
    than silently treating an incomplete or stale run as usable input.
    """
    log_path = run_dir / "run_log.json"
    if not log_path.exists():
        raise FileNotFoundError(f"No run_log.json found in {run_dir}")

    data = json.loads(log_path.read_text())
    image_path_str = data.get("previz_image_path")
    prompt_used = data.get("previz_prompt_used")
    if not image_path_str or not prompt_used:
        raise ValueError(
            f"{log_path} has no completed previz result (missing "
            "'previz_image_path' or 'previz_prompt_used') -- point "
            "--video-gen-from at a run that finished previz successfully."
        )

    image_path = Path(image_path_str)
    if not image_path.exists():
        raise FileNotFoundError(
            f"Previz image referenced by {log_path} no longer exists: {image_path}"
        )

    return image_path, prompt_used


def _run_video_generation_only(
    run_dirs: list[Path],
    *,
    mock: bool,
    out_dir: Path,
    video_model: str | None = None,
    video_seconds: str | None = None,
) -> None:
    """Run stage 9 (video generation) standalone against one or more
    already-completed previz outputs, skipping research, fact-check, and
    previz entirely for this invocation. Each run_dir becomes one scene's
    anchor image + prompt -- multiple directories today stands in for the
    future multi-scene case, where each approved shot becomes its own
    image-to-video job. See docs/decisions/0010-video-generation-model-and-
    standalone-stage.md.

    Blocks and polls each job to completion before starting the next --
    0010's v1 choice, not the SQS fan-out already named for this stage in
    docs/decisions/0004 for when there's real multi-scene volume to justify
    a queue.

    Lets VideoGenerationError propagate uncaught on failure, same
    fail-loud convention as every other stage -- this doesn't try to
    continue past a failed scene and finish the rest.

    `out_dir` is a required parameter rather than computed here (same
    reason as `_generate_previz_with_review`'s `out_dir`) -- keeps this
    testable against a tmp_path instead of writing into the real project's
    outputs/ directory.

    `video_seconds`, if given, requests that clip duration from the
    provider (see run_video_generation_stage's own docstring and
    docs/decisions/0012 for why this isn't validated client-side --
    OpenAI's own docs disagree with each other about what's accepted).
    Left as None, the stage's own default applies.
    """
    video_kwargs = (
        {
            "video_fn": _mock_video_generation,
            "status_fn": _mock_video_status,
            "content_fn": _mock_video_content,
            "sleep_fn": lambda _seconds: None,
        }
        if mock
        else {}
    )

    video_model = video_model or get_stage_model("video_generation")
    log = {
        "mode": "video_generation_only",
        "mock": mock,
        "video_generation_model": video_model,
        "video_seconds_requested": video_seconds,
        "source_previz_runs": [str(d) for d in run_dirs],
        "scenes": [],
    }
    _write_log(out_dir, log)

    for i, run_dir in enumerate(run_dirs, start=1):
        print(f"\n--- video generation (model: {video_model}, scene {i}/{len(run_dirs)}) ---")
        image_path, prompt = _load_previz_output(run_dir)
        print(f"Source: {run_dir} (image: {image_path})")

        result = run_video_generation_stage(
            image_path,
            prompt,
            model=video_model,
            output_dir=out_dir,
            output_filename=f"video_scene_{i}.mp4",
            **({"seconds": video_seconds} if video_seconds is not None else {}),
            **video_kwargs,
        )
        print(
            f"Video saved to {result.video_path} "
            f"(requested {result.seconds_requested}s, provider reports {result.seconds_actual}s)"
        )
        log["scenes"].append(
            {
                "source_previz_run": str(run_dir),
                "source_image_path": str(result.source_image_path),
                "prompt_used": result.prompt_used,
                "video_path": str(result.video_path),
                "seconds_requested": result.seconds_requested,
                "seconds_actual": result.seconds_actual,
            }
        )
        _write_log(out_dir, log)

    print(f"\nDone. Run artifacts saved in {out_dir}")


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
        "--video-gen-from",
        type=Path,
        nargs="+",
        metavar="RUN_DIR",
        help=(
            "Run stage 9 (video generation) standalone against one or more "
            "existing run output directories that already completed previz "
            "-- each becomes one scene's anchor image + prompt. Skips "
            "research, fact-check, and previz entirely for this "
            "invocation. Combine with --mock to exercise the polling loop "
            "without a real API call."
        ),
    )
    parser.add_argument(
        "--video-seconds",
        help=(
            "Requested clip duration in seconds, passed through to the "
            "video_generation stage as-is (only used with --video-gen-from). "
            "Not validated client-side -- OpenAI's own docs disagree with "
            "each other about what's accepted above \"4\"/\"8\"/\"12\" (see "
            "docs/decisions/0012). Defaults to the stage's own default if "
            "not given."
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
            "(DeepSeek isn't an image model). Has no effect on the initial "
            "research/fact-check in --fixture mode (loaded from the "
            "fixture, not run) -- but still applies if a premise-conflict "
            "correction (see docs/decisions/0008) triggers a real "
            "re-verification pass."
        ),
    )
    args = parser.parse_args()

    if not args.mock:
        load_environment()

    if args.video_gen_from:
        _run_video_generation_only(
            args.video_gen_from,
            mock=args.mock,
            out_dir=_run_dir(),
            video_seconds=args.video_seconds,
        )
        return

    completion_kwargs = {"completion_fn": _mock_completion} if args.mock else {}
    image_kwargs = {"image_fn": _mock_image} if args.mock else {}
    review_kwargs = {"completion_fn": _mock_review_completion} if args.mock else {}

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

        print("\n--- fact-check (loaded from fixture) ---")
        if fact_check_result.flags:
            for f in fact_check_result.flags:
                print(f"- [{f.severity}] {f.claim_text} -- {f.concern}")
        else:
            print("No issues flagged.")
    else:
        time = _prompt_if_missing(args.time, "Time")
        place = _prompt_if_missing(args.place, "Place")
        description = _prompt_if_missing(args.description, "What the main character does")
        log = {"time": time, "place": place, "description": description, "mock": args.mock}

        result = _run_research_and_fact_check(
            time,
            place,
            description,
            research_model=research_model,
            fact_check_model=fact_check_model,
            completion_kwargs=completion_kwargs,
        )
        if result is None:
            _write_log(out_dir, log)
            print(f"Stopped by user. Run artifacts saved in {out_dir}")
            return
        fact_sheet, fact_check_result = result

    log["research_model"] = research_model
    log["fact_check_model"] = fact_check_model
    log["research_claims"] = [dataclasses.asdict(c) for c in fact_sheet.claims]
    log["fact_check_flags"] = [dataclasses.asdict(f) for f in fact_check_result.flags]
    original_premise_conflict = fact_check_result.premise_conflict
    log["premise_conflict"] = (
        dataclasses.asdict(original_premise_conflict) if original_premise_conflict else None
    )
    _write_log(out_dir, log)

    resolved = _resolve_premise_conflict(
        fact_sheet,
        fact_check_result,
        time=time,
        place=place,
        research_model=research_model,
        fact_check_model=fact_check_model,
        completion_kwargs=completion_kwargs,
    )
    if resolved is None:
        log["stopped_reason"] = "premise_conflict_unresolved"
        _write_log(out_dir, log)
        print(f"Stopped. Run artifacts saved in {out_dir}")
        return
    fact_sheet, fact_check_result = resolved

    if original_premise_conflict is not None:
        log["premise_conflict_resolved_with_description"] = fact_sheet.description
    log["description"] = fact_sheet.description
    log["research_claims"] = [dataclasses.asdict(c) for c in fact_sheet.claims]
    log["fact_check_flags"] = [dataclasses.asdict(f) for f in fact_check_result.flags]
    _write_log(out_dir, log)

    resolved_fact_sheet = _resolve_flags(fact_sheet, fact_check_result.flags)
    fact_check_result = dataclasses.replace(fact_check_result, fact_sheet=resolved_fact_sheet)
    log["research_claims"] = [dataclasses.asdict(c) for c in resolved_fact_sheet.claims]
    _write_log(out_dir, log)

    if not _confirm("\nProceed to previz with this fact-check result?"):
        print(f"Stopped by user. Run artifacts saved in {out_dir}")
        return

    previz_model = get_stage_model("previz")
    review_model = get_stage_model("previz_review")
    log["previz_model"] = previz_model
    log["previz_review_model"] = review_model

    def _record_previz_image(result: PrevizResult) -> None:
        # Persisted as soon as the image exists -- not after the whole
        # generate+review loop returns -- so a crash inside review (e.g. a
        # missing API key) still leaves run_log.json pointing at a real,
        # already-generated image instead of silently losing it. See
        # _generate_previz_with_review's on_image_generated docstring.
        log["previz_image_path"] = str(result.image_path)
        log["previz_prompt_used"] = result.prompt_used
        _write_log(out_dir, log)

    previz_result, previz_attempts = _generate_previz_with_review(
        fact_check_result,
        previz_model=previz_model,
        review_model=review_model,
        image_kwargs=image_kwargs,
        review_kwargs=review_kwargs,
        out_dir=out_dir,
        on_image_generated=_record_previz_image,
    )
    log["previz_attempts"] = previz_attempts
    if previz_result is None:
        # Every attempt was explicitly rejected and its image renamed to
        # previz_attempt_<n>_rejected.png (see _generate_previz_with_review)
        # -- clear the path _record_previz_image left from the last
        # attempt, since it no longer points at a real file, and this
        # branch's whole meaning is "no accepted image exists."
        log.pop("previz_image_path", None)
        log.pop("previz_prompt_used", None)
        log["stopped_reason"] = "previz_review_rejected_max_attempts"
        _write_log(out_dir, log)
        print(f"\nNo image produced. Run artifacts saved in {out_dir}")
        return
    # previz_image_path/previz_prompt_used are already in log and on disk,
    # written by _record_previz_image the moment the accepted image was
    # generated -- this just flushes previz_attempts alongside them.
    _write_log(out_dir, log)

    print(f"\nDone. Run artifacts saved in {out_dir}")


if __name__ == "__main__":
    main()
