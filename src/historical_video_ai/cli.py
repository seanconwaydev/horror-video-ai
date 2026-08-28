"""Interactive CLI entry point for the v1 pipeline: collects a scene
(time, place, description), runs it through research -> fact-check ->
previz (docs/decisions/0006). Run with `uv run historical-video-ai`.

Refuses rather than fabricates in two cases: fact-check flagging the
scene's premise as historically impossible (docs/decisions/0008,
_resolve_premise_conflict -- offers a suggested alternative or your own
corrected description, re-verified before continuing), and previz's own
generated image failing independent review (docs/decisions/0009,
_generate_previz_with_review -- regenerates blind up to
_MAX_PREVIZ_ATTEMPTS times, then gives up).

Flags:
- `--mock`: no network calls, no API keys -- synthetic data for every stage.
- `--fixture <path>`: replays a captured real research+fact-check result,
  skipping those API calls while still running previz for real -- see
  tests/fixtures/. Combine with --mock for a fully offline previz too.
- `--video-gen-from <run_dir> [...]`: runs stage 9 standalone against one
  or more completed previz outputs (docs/decisions/0010), writing each
  video into its source run_dir and appending to that run's existing log.
- `--video-seconds`: requests a clip duration, validated against Sora's
  documented values before any API call (docs/decisions/0012, 0020).
- `--video-prompt`: overrides the saved previz prompt for --video-gen-from,
  to test a hand-written prompt against an already-approved image.
- `--yes`: non-interactive -- auto-confirms every prompt and auto-accepts
  an "uncertain" fact-check flag, but stops the run on a "contradicted"
  one rather than auto-accepting it (docs/decisions/0017, 0019), and skips
  (rather than auto-proceeding past) any scene a moderation pre-flight
  flags before video generation (docs/decisions/0022).

Every --video-gen-from scene also runs a two-layer moderation pre-flight
(docs/decisions/0022, stages/moderation.py) before the paid video-
generation call: a free policy-category check plus a paid pose/risk
review, both against the actual image and prompt about to be submitted.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from historical_video_ai.config import get_stage_model, load_environment
from historical_video_ai.stages.fact_check import (
    ClaimFlag,
    FactCheckResult,
    PremiseConflict,
    run_fact_check_stage,
)
from historical_video_ai.stages.moderation import (
    run_moderation_policy_check,
    run_moderation_risk_review,
)
from historical_video_ai.stages.previz import (
    PrevizResult,
    run_previz_review_stage,
    run_previz_stage,
)
from historical_video_ai.stages.research import Claim, FactSheet, run_research_stage
from historical_video_ai.stages.video_generation import run_video_generation_stage

# 90x160 (Sora's exact 9:16 target ratio, tiny for speed) rather than a
# bare 1x1 pixel -- video_generation's aspect-ratio guard (docs/decisions
# /0011) genuinely opens and checks this image even in --mock mode (only
# the litellm-facing calls are mocked, not local image processing), so a
# 1x1 image used to fail --mock --video-gen-from with a real
# VideoGenerationError instead of exercising the mock path.
_MOCK_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAFoAAACgCAIAAAADw+wqAAABOUlEQVR4nO3SsQ3AMBAD"
    "sY/339mpYvgyA1mpPuiZ2cNnnYUcf94RcoQcIUfIEXKEHCFHyBFyhBwhR8gRcoQcIUfI"
    "EXKEHCFHyBFyhBwhR8gRcoQcIUfIEXKEHCFHyBFyhBwhR8gRcoQcIUfIEXKEHCFHyBFy"
    "hBwhR8gRcoQcIUfIEXKEHCFHyBFyhBwhR8gRcoQcIUfIEXKEHCFHyBFyhBwhR8gRcoQc"
    "IUfIEXKEHCFHyBFyhBwhR8gRcoQcIUfIEXKEHCFHyBFyhBwhR8gRcoQcIUfIEXKEHCFH"
    "yBFyhBwhR8gRcoQcIUfIEXKEHCFHyBFyhBwhR8gRcoQcIUfIEXKEHCFHyBFyhBwhR8gR"
    "coQcIUfIEXKEHCFHyBFyhBwhR8gRcoQcIUfIEXKEHCFHyBFyhBwhR8gxtxdJIAI/Sl4X"
    "NwAAAABJRU5ErkJggg=="
)


def _mock_completion(**kwargs: object) -> SimpleNamespace:
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


def _mock_image(**kwargs: object) -> SimpleNamespace:
    return SimpleNamespace(data=[SimpleNamespace(b64_json=_MOCK_PNG_B64)])


def _mock_review_completion(**kwargs: object) -> SimpleNamespace:
    """No network call, no API key -- always accepts, so --mock exercises
    the previz-review loop's mechanics without cost or credentials."""
    content = json.dumps({"accepted": True, "concern": None})
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def _mock_video_generation(**kwargs: object) -> SimpleNamespace:
    """No network call, no API key -- returns a job already 'completed', so
    --video-gen-from --mock exercises the polling loop's mechanics (it just
    skips the loop entirely, since the job is terminal on creation) without
    cost or credentials."""
    return SimpleNamespace(id="mock-video-id", status="completed", error=None)


def _mock_video_status(**kwargs: object) -> SimpleNamespace:
    return SimpleNamespace(id="mock-video-id", status="completed", error=None)


def _mock_video_content(**kwargs: object) -> bytes:
    return b"[MOCK] not a real video file"


def _mock_moderation_policy_check(**kwargs: object) -> SimpleNamespace:
    """No network call, no API key -- always comes back clean, so --mock
    exercises the moderation pre-flight's mechanics (docs/decisions/0022)
    without cost or credentials."""
    return SimpleNamespace(results=[SimpleNamespace(flagged=False, categories={})])


def _mock_moderation_risk_review(**kwargs: object) -> SimpleNamespace:
    content = json.dumps({"flagged": False, "concern": None})
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


# See docs/decisions/0009-previz-image-review.md -- your call: bounded, not
# tunable via a flag, to keep behavior predictable rather than open-ended.
_MAX_PREVIZ_ATTEMPTS = 3


def _confirm(prompt: str, *, auto_yes: bool = False) -> bool:
    """`auto_yes` (--yes) answers every confirm prompt as yes without
    calling input() at all -- see docs/decisions/0017-non-interactive-mode.md.
    Prints the prompt either way, so a run's transcript still shows every
    decision point even when nothing was actually typed."""
    if auto_yes:
        print(f"{prompt} [y/n]: y (--yes)")
        return True
    while True:
        answer = input(f"{prompt} [y/n]: ").strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("Please answer y or n.")


def _prompt_if_missing(value: str | None, label: str, *, auto_yes: bool = False) -> str:
    """time/place/description are all required (docs/decisions/0006) --
    loop until a non-empty value is given, printing an explicit error on
    every empty attempt (whether it came in empty via a CLI flag or was
    left blank at the prompt) rather than silently re-prompting.

    `auto_yes` (--yes) can't answer a free-text field -- there's nothing
    sensible to guess -- so a missing value under --yes raises instead of
    blocking on input(), which would just hang (or crash with EOFError)
    in a genuinely non-interactive context anyway.
    """
    if not value and auto_yes:
        raise ValueError(
            f"{label} is required and cannot be empty -- --yes can't answer this "
            "for you, pass it explicitly as a flag."
        )
    while not value:
        print(f"Error: {label} is required and cannot be empty.")
        value = input(f"{label}: ").strip()
    return value


def _resolve_flags(
    fact_sheet: FactSheet, flags: list[ClaimFlag], *, auto_yes: bool = False
) -> FactSheet | None:
    """Give the human the final say on each fact-check flag -- accept the
    claim as-is, cut it, or soften its wording (docs/pipeline.md stage 3
    review gate). Returns fact_sheet unchanged if there are no flags.

    `auto_yes` (--yes) auto-accepts an "uncertain" flag (a soft doubt, no
    competing claim) but refuses to auto-accept a "contradicted" one (fact-
    check asserting a specific competing fact) -- returns None to stop the
    run instead, same as --yes already does for an unresolved premise
    conflict (docs/decisions/0019). Auto-cut/auto-soften remain unsafe
    defaults for the reason they always were -- rewriting or dropping claim
    text isn't a call --yes can make without a human reading the concern --
    and blind-accepting a claim fact-check specifically flagged as wrong is
    the same kind of unsafe call in the other direction.
    """
    if not flags:
        return fact_sheet

    if auto_yes:
        contradicted = [f for f in flags if f.severity == "contradicted"]
        if contradicted:
            print("\n--yes won't auto-accept a contradicted fact-check flag:")
            for flag in contradicted:
                print(f"\nClaim: {flag.claim_text}")
                print(f"Flag [contradicted]: {flag.concern}")
            print("\nStopping -- rerun without --yes to review this claim.")
            return None

    claims_by_text = {c.text: c for c in fact_sheet.claims}
    resolved_claims = list(fact_sheet.claims)

    print("\nResolve flagged claims:")
    for flag in flags:
        claim = claims_by_text[flag.claim_text]
        print(f"\nClaim: {claim.text}")
        print(f"Flag [{flag.severity}]: {flag.concern}")
        if auto_yes:
            print("(a)ccept / (c)ut / (s)often this claim? [a/c/s]: a (--yes)")
            continue
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


def _record_research_claims(
    fact_sheet: FactSheet, *, research_model: str, out_dir: Path, log: dict
) -> None:
    """Persist research's output to `log` immediately -- used as
    `_run_research_and_fact_check`'s `on_research_completed` callback, from
    both of its call sites in `main()` (the initial pass and a premise-
    conflict re-verification pass), so a fact-check-stage crash right
    after either one doesn't lose the research it would otherwise have
    recorded. See docs/decisions/0015-persist-research-before-fact-check.md.
    """
    log["research_model"] = research_model
    log["research_claims"] = [dataclasses.asdict(c) for c in fact_sheet.claims]
    _write_log(out_dir, log)


def _run_research_and_fact_check(
    time: str,
    place: str,
    description: str,
    *,
    research_model: str,
    fact_check_model: str,
    completion_kwargs: dict,
    on_research_completed: Callable[[FactSheet], None] | None = None,
    auto_yes: bool = False,
    fact_sheet: FactSheet | None = None,
) -> tuple[FactSheet, FactCheckResult] | None:
    """Run research then fact-check for real, pausing for the research
    review gate. Returns None if the human declines to proceed past
    research. Shared so a premise-conflict correction
    (_resolve_premise_conflict) can re-run this on a corrected description.

    `on_research_completed`, if given, is called with the research output
    right after it succeeds -- *before* fact-check runs, which can itself
    fail. Without this, a fact-check crash lost a real, already-paid-for
    research result with no way to recover it via --fixture (docs/decisions/0015).

    `fact_sheet`, if given, skips the research call entirely and jumps
    straight to fact-check against it -- used to resume a fixture whose
    fact-check crashed before it ever completed (a research-only fixture,
    per docs/decisions/0015).
    """
    if fact_sheet is None:
        print(f"\n--- research (model: {research_model}) ---")
        fact_sheet = run_research_stage(
            time, place, description, model=research_model, **completion_kwargs
        )
        for c in fact_sheet.claims:
            print(f"- {c.text} [source: {c.source}]")
        if on_research_completed is not None:
            on_research_completed(fact_sheet)
    else:
        print("\n--- research (loaded from fixture) ---")
        for c in fact_sheet.claims:
            print(f"- {c.text} [source: {c.source}]")
    if not _confirm("\nProceed to fact-check with this research?", auto_yes=auto_yes):
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
    on_research_completed: Callable[[FactSheet], None] | None = None,
    auto_yes: bool = False,
) -> tuple[FactSheet, FactCheckResult] | None:
    """If fact-check flagged the scene's own premise as historically
    impossible (docs/decisions/0008), push back instead of silently
    proceeding -- previz would refuse anyway, but that's a last-resort
    safety net, not a substitute for asking. Offers the suggested
    alternative, or lets the human supply their own, then re-verifies with
    one fresh research + fact-check pass (correcting the premise re-runs
    research rather than reusing claims shaped by the old, impossible one).

    Returns the resolved (fact_sheet, fact_check_result) pair, or None if
    the human stopped. Only re-verifies once -- a still-conflicted
    corrected description is treated as a stop, not a retry loop.
    """
    conflict = fact_check_result.premise_conflict
    if conflict is None:
        return fact_sheet, fact_check_result

    print(f"\nThis scene's premise appears to be historically impossible: {conflict.explanation}")

    new_description: str | None = None
    if conflict.suggested_alternative:
        print(f"Closest historically plausible version: {conflict.suggested_alternative}")
        if _confirm("Use this instead?", auto_yes=auto_yes):
            new_description = conflict.suggested_alternative
    else:
        print("No reasonably close, historically plausible version of this scene was found.")

    if new_description is None:
        if auto_yes:
            # Nothing sensible to auto-supply for a free-text corrected
            # description -- stop cleanly rather than guess one.
            print(
                "Stopping -- --yes can't supply a corrected description for an "
                "unresolved premise conflict with no suggested alternative."
            )
            return None
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
        on_research_completed=on_research_completed,
        auto_yes=auto_yes,
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
    actual image against the scene (docs/decisions/0009). On rejection,
    regenerates blind (no prompt rewriting), capped at _MAX_PREVIZ_ATTEMPTS.

    Returns (accepted PrevizResult, attempt log), or (None, attempt log)
    if every attempt was rejected. A rejected attempt's image is archived
    as previz_attempt_<n>_rejected.png rather than overwritten.

    `on_image_generated`, if given, is called with each attempt's
    PrevizResult right after the image is written -- *before* review runs,
    which can itself fail. Without this, a review-stage crash left a real,
    already-paid-for image on disk with no record of it in the log.
    """
    attempts: list[dict] = []
    for attempt in range(1, _MAX_PREVIZ_ATTEMPTS + 1):
        print(f"\n--- previz (model: {previz_model}, attempt {attempt}/{_MAX_PREVIZ_ATTEMPTS}) ---")
        previz_result = run_previz_stage(
            fact_check_result,
            model=previz_model,
            output_dir=out_dir,
            on_transient_retry=lambda n, exc: print(
                f"Transient error ({exc}) -- retrying (attempt {n + 1})..."
            ),
            **image_kwargs,
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


def _slugify(text: str, max_length: int = 40) -> str:
    """Turn free text into a short, filesystem-safe fragment for a run
    directory name -- lowercase, every run of non-alphanumeric characters
    collapsed to a single hyphen, trimmed to `max_length` without cutting
    a word in half where a hyphen boundary is nearby, and hyphens stripped
    from both ends.

    Returns "" if nothing usable remains (empty input, or input that's
    entirely punctuation) -- callers should treat an empty slug as "no
    context available" rather than tack on a trailing separator with
    nothing after it.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if len(slug) <= max_length:
        return slug
    truncated = slug[:max_length]
    if "-" in truncated:
        truncated = truncated.rsplit("-", 1)[0]
    return truncated


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


def _run_dir(slug: str | None = None) -> Path:
    """Create (and return) this run's output directory, named
    `run_<timestamp>` or `run_<timestamp>_<slug>` if `slug` is given and
    non-empty. The timestamp alone told you *when* a run happened but
    nothing about *what* it was -- telling scenes apart meant opening
    run_log.json in each candidate folder. `slug` should already be a
    filesystem-safe fragment (see `_slugify`) -- this function doesn't
    sanitize it itself, so callers building one from free text must slugify
    it first."""
    run_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    dir_name = f"run_{run_id}_{slug}" if slug else f"run_{run_id}"
    d = _project_root() / "outputs" / dir_name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_log(out_dir: Path, log: dict) -> None:
    (out_dir / "run_log.json").write_text(json.dumps(log, indent=2, default=str))


def _load_fact_sheet_from_fixture(path: Path) -> FactSheet:
    """Reconstruct just the FactSheet (time/place/description/claims) from
    a saved run_log.json -- the part every fixture has, whether or not
    fact-check ever ran against it (docs/decisions/0015 persists research
    before fact-check, so a run that crashed at fact-check still has a
    usable fixture here, just not a full one -- see `_load_fixture`).

    Raises ValueError if time/place/description are missing or empty
    (docs/decisions/0006), and KeyError as-is if research_claims is absent.
    """
    data = json.loads(path.read_text())
    for required_field in ("time", "place", "description"):
        if not data.get(required_field):
            raise ValueError(f"Fixture {path} is missing a non-empty '{required_field}'")
    claims = [Claim(**c) for c in data["research_claims"]]
    return FactSheet(
        time=data["time"],
        place=data["place"],
        description=data["description"],
        claims=claims,
    )


def _load_fixture(path: Path) -> FactCheckResult:
    """Reconstruct a real FactSheet + FactCheckResult from a previously
    saved run_log.json (or anything matching its shape), so research and
    fact-check don't need to run -- and cost nothing -- again. Requires the
    fixture to have a completed fact-check result already (a
    `fact_check_flags` key) -- for a fixture that only has research so
    far, use `_load_fact_sheet_from_fixture` and run fact-check for real.

    Raises FileNotFoundError / KeyError as-is if the fixture is missing or
    malformed, rather than silently degrading into an empty scene.
    """
    data = json.loads(path.read_text())
    fact_sheet = _load_fact_sheet_from_fixture(path)
    claims = fact_sheet.claims
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


def _load_previz_output(run_dir: Path, *, prompt_override: str | None = None) -> tuple[Path, str]:
    """Load a previously generated previz image and its prompt from an
    existing run's run_log.json, so --video-gen-from can run stage 9
    standalone instead of requiring a fresh research/fact-check/previz
    pass every time (docs/decisions/0010).

    `prompt_override` (--video-prompt), if given, is returned instead of
    the saved previz prompt -- lets a hand-written, video-specific prompt
    be tested against an already-approved image without a fresh (and
    separately costly) previz pass. Still requires the run to have a
    valid image on disk; only the *text* is substituted.

    Raises FileNotFoundError if run_dir has no run_log.json or the image
    it references no longer exists, and ValueError if the log doesn't show
    a completed previz result.
    """
    log_path = run_dir / "run_log.json"
    if not log_path.exists():
        raise FileNotFoundError(f"No run_log.json found in {run_dir}")

    data = json.loads(log_path.read_text())
    image_path_str = data.get("previz_image_path")
    prompt_used = prompt_override or data.get("previz_prompt_used")
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


# Wording that has actually tripped real Sora moderation in this project
# (docs/playbook/video-generation-prompting.md) -- not a claimed-complete
# list, just the concrete evidence gathered so far.
_VIDEO_PROMPT_RISK_WORDS = frozenset(
    {"fight", "attack", "kill", "blood", "injury", "weapon", "battle", "war", "die", "tactical"}
)
# Research found 2-3 sequential beats is the practical ceiling for one
# generation call before quality degrades (docs/playbook/video-generation-
# prompting.md) -- flagged, not enforced, since a human may have a good
# reason to try more anyway.
_MAX_RECOMMENDED_BEATS = 3


def _check_video_prompt_practices(prompt: str) -> list[str]:
    """Cheap, mechanical checks against docs/playbook/video-generation-
    prompting.md's findings -- advisory only, never blocks a run. Exists
    because a hand-written --video-prompt is free-form text with no
    structure enforced anywhere, and it's easy to leave out something the
    playbook already learned the hard way (a real run did exactly this).
    Deliberately narrow: flags concrete, objectively-checkable omissions
    (no character block, no audio direction, too many beats crammed into
    one call, wording that's tripped real moderation before) rather than
    judging actual prompt quality, which isn't something this can do
    reliably and isn't its job -- a human still decides whether to proceed.
    """
    found = []
    if "CHARACTER:" not in prompt:
        found.append(
            "no 'CHARACTER:' block -- character consistency across beats relies on "
            "reusing one verbatim"
        )
    if "Audio:" not in prompt:
        found.append(
            "no 'Audio:' direction -- Sora generates audio natively and expects to be "
            "told what to hear"
        )
    beat_count = len(re.findall(r"\(\d+-\d+s\)", prompt))
    if beat_count > _MAX_RECOMMENDED_BEATS:
        found.append(
            f"{beat_count} timecoded beats in one prompt -- {_MAX_RECOMMENDED_BEATS} is "
            "the practical ceiling before quality degrades; consider a separate image + "
            "generation per beat instead"
        )
    risk_words = sorted(
        w for w in _VIDEO_PROMPT_RISK_WORDS if re.search(rf"\b{w}\b", prompt, re.IGNORECASE)
    )
    if risk_words:
        found.append(
            f"wording that has tripped real moderation before: {', '.join(risk_words)} -- "
            "consider neutral, film-direction language instead"
        )
    return found


def _run_video_generation_only(
    run_dirs: list[Path],
    *,
    mock: bool,
    auto_yes: bool = False,
    video_model: str | None = None,
    video_seconds: str | None = None,
    video_prompt: str | None = None,
) -> None:
    """Run stage 9 (video generation) standalone against one or more
    already-completed previz outputs, skipping research/fact-check/previz
    for this invocation (docs/decisions/0010). Each run_dir is one scene's
    anchor image + prompt; blocks and polls each to completion before
    starting the next (0010's v1 choice, not the SQS fan-out named for
    this stage in 0004). Lets VideoGenerationError propagate uncaught,
    same fail-loud convention as every other stage.

    Before each scene's paid video-generation call, runs the two-layer
    moderation pre-flight (docs/decisions/0022) -- a free policy-category
    check plus a paid pose/risk review, both against the actual image and
    prompt about to be submitted. A flag from either layer prints the
    concern and requires confirmation (`_confirm`) to proceed with that
    scene; under `auto_yes` (--yes), a flag skips that scene rather than
    auto-proceeding, same precedent as 0019's contradicted-flag refusal.
    This skips only the flagged scene, not the whole run -- each run_dir is
    an independent scene, and one flagged scene shouldn't block generating
    the others.

    `video_seconds`, if given, requests that duration (see 0012 for why
    it's not validated client-side).

    `video_prompt` (--video-prompt), if given, replaces the saved previz
    prompt for every run_dir -- a deliberately simple one-override-for-all
    shape, since this exists for testing one hand-written prompt against
    one (or a few identically-treated) already-approved image(s), not for
    driving several different scenes' worth of independent prompts at
    once. When `video_prompt` is given, it's checked against
    `_check_video_prompt_practices` first -- printed as warnings, never
    blocking (docs/decisions/0021) -- since this is free-form hand-written
    text with nothing else enforcing the playbook's own findings on it.

    Each video is written directly into its source run_dir as
    `video_<timestamp>.mp4` -- the timestamp avoids collisions when
    re-running against the same previz output (e.g. a different
    duration), and the scene's existing run_log.json gets a `"videos"`
    list appended to rather than a separate log file, so one folder holds
    a scene's whole history.
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
    policy_check_kwargs = (
        {"moderation_fn": _mock_moderation_policy_check} if mock else {}
    )
    risk_review_kwargs = (
        {"completion_fn": _mock_moderation_risk_review} if mock else {}
    )

    video_model = video_model or get_stage_model("video_generation")

    if video_prompt is not None:
        practice_warnings = _check_video_prompt_practices(video_prompt)
        if practice_warnings:
            print("\n--video-prompt doesn't follow known best practice:")
            for warning in practice_warnings:
                print(f"- {warning}")
            print("Proceeding anyway -- this is advisory, not a block.")

    for i, run_dir in enumerate(run_dirs, start=1):
        print(f"\n--- video generation (model: {video_model}, scene {i}/{len(run_dirs)}) ---")
        image_path, prompt = _load_previz_output(run_dir, prompt_override=video_prompt)
        print(f"Source: {run_dir} (image: {image_path})")

        print("Running moderation pre-flight (docs/decisions/0022)...")
        policy_result = run_moderation_policy_check(prompt, image_path, **policy_check_kwargs)
        risk_review = run_moderation_risk_review(image_path, **risk_review_kwargs)

        concerns = []
        if policy_result.flagged:
            concerns.append(
                "omni-moderation-latest flagged categories: "
                + ", ".join(policy_result.flagged_categories)
            )
        if risk_review.flagged:
            concerns.append(f"pose/risk review: {risk_review.concern}")

        if concerns:
            print("\nModeration pre-flight raised a concern before spending on video generation:")
            for concern in concerns:
                print(f"- {concern}")
            log_path = run_dir / "run_log.json"
            log = json.loads(log_path.read_text())
            log.setdefault("moderation_preflight_flags", []).append(
                {"concerns": concerns, "prompt_used": prompt}
            )
            log_path.write_text(json.dumps(log, indent=2, default=str))

            if auto_yes:
                print(
                    "\n--yes won't auto-proceed past a moderation pre-flight flag -- "
                    f"skipping {run_dir}. Rerun without --yes to review and confirm."
                )
                continue
            if not _confirm("Proceed with video generation for this scene anyway?"):
                print(f"Skipped {run_dir} by user choice.")
                continue

        # Microsecond precision, not just seconds -- two attempts against
        # the same previz output (e.g. comparing --video-seconds values)
        # can easily land in the same second, and a filename collision
        # would silently overwrite the earlier video instead of
        # accumulating both.
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
        result = run_video_generation_stage(
            image_path,
            prompt,
            model=video_model,
            output_dir=run_dir,
            output_filename=f"video_{timestamp}.mp4",
            **({"seconds": video_seconds} if video_seconds is not None else {}),
            **video_kwargs,
        )
        print(
            f"Video saved to {result.video_path} "
            f"(requested {result.seconds_requested}s, provider reports {result.seconds_actual}s)"
        )

        log_path = run_dir / "run_log.json"
        log = json.loads(log_path.read_text())
        log.setdefault("videos", []).append(
            {
                "video_generation_model": video_model,
                "video_path": str(result.video_path),
                "seconds_requested": result.seconds_requested,
                "seconds_actual": result.seconds_actual,
                "mock": mock,
                # Recorded per attempt, not just once for the run, so
                # comparing several --video-prompt overrides against the
                # same image stays traceable -- which prompt produced
                # which file -- instead of only the latest being visible.
                "prompt_used": prompt,
            }
        )
        log_path.write_text(json.dumps(log, indent=2, default=str))

    print("\nDone.")


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
        "--yes",
        action="store_true",
        help=(
            "Non-interactive: auto-confirm every 'Proceed?' prompt and "
            "auto-accept every fact-check flag as-is (never auto-cut or "
            "auto-soften). --time/--place/--description must be given as "
            "flags in this mode -- there's nothing sensible to prompt for "
            "interactively. See docs/decisions/0017-non-interactive-mode.md."
        ),
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
            "Requested clip duration in seconds (only used with "
            "--video-gen-from) -- one of \"4\", \"8\", \"12\", \"16\", "
            "\"20\"; any other value is rejected before any API call "
            "(docs/decisions/0012, 0020). Defaults to the stage's own "
            "default if not given."
        ),
    )
    parser.add_argument(
        "--video-prompt",
        help=(
            "Override the saved previz prompt with this text for "
            "--video-gen-from (applied to every RUN_DIR given). Lets a "
            "hand-written, video-specific prompt be tested against an "
            "already-approved previz image without paying for a fresh "
            "research/fact-check/previz pass just to change the wording."
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
            auto_yes=args.yes,
            video_seconds=args.video_seconds,
            video_prompt=args.video_prompt,
        )
        return

    completion_kwargs = {"completion_fn": _mock_completion} if args.mock else {}
    image_kwargs = {"image_fn": _mock_image} if args.mock else {}
    review_kwargs = {"completion_fn": _mock_review_completion} if args.mock else {}

    research_model = args.experiment_model or get_stage_model("research")
    fact_check_model = args.experiment_model or get_stage_model("fact_check")

    if args.fixture:
        # A fixture saved after a fact-check-stage crash has research but
        # no fact_check_flags key yet (docs/decisions/0015 persists
        # research before fact-check runs) -- that's a real, valid,
        # cheaper-to-resume case, not a malformed fixture: run fact-check
        # for real against the loaded research instead of requiring a full
        # fixture. `_load_fixture` needs a completed fact-check result;
        # peek at the raw fixture first to tell which case this is.
        has_fact_check = "fact_check_flags" in json.loads(args.fixture.read_text())

        fact_sheet = _load_fact_sheet_from_fixture(args.fixture)
        time, place, description = fact_sheet.time, fact_sheet.place, fact_sheet.description
        # Computed here, not before the scene is known -- see _run_dir's
        # docstring on why the directory name now carries a content hint,
        # not just a timestamp.
        out_dir = _run_dir(_slugify(description))
        log = {"time": time, "place": place, "description": description, "mock": args.mock}
        log["fixture"] = str(args.fixture)

        if has_fact_check:
            fact_check_result = _load_fixture(args.fixture)
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
            print(f"\nFixture {args.fixture} has research but no completed fact-check -- running fact-check for real against it.")
            result = _run_research_and_fact_check(
                time,
                place,
                description,
                research_model=research_model,
                fact_check_model=fact_check_model,
                completion_kwargs=completion_kwargs,
                auto_yes=args.yes,
                fact_sheet=fact_sheet,
            )
            if result is None:
                _write_log(out_dir, log)
                print(f"Stopped by user. Run artifacts saved in {out_dir}")
                return
            fact_sheet, fact_check_result = result
    else:
        time = _prompt_if_missing(args.time, "Time", auto_yes=args.yes)
        place = _prompt_if_missing(args.place, "Place", auto_yes=args.yes)
        description = _prompt_if_missing(
            args.description, "What the main character does", auto_yes=args.yes
        )
        out_dir = _run_dir(_slugify(description))
        log = {"time": time, "place": place, "description": description, "mock": args.mock}

        result = _run_research_and_fact_check(
            time,
            place,
            description,
            research_model=research_model,
            fact_check_model=fact_check_model,
            completion_kwargs=completion_kwargs,
            auto_yes=args.yes,
            on_research_completed=lambda fs: _record_research_claims(
                fs, research_model=research_model, out_dir=out_dir, log=log
            ),
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
        auto_yes=args.yes,
        on_research_completed=lambda fs: _record_research_claims(
            fs, research_model=research_model, out_dir=out_dir, log=log
        ),
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

    resolved_fact_sheet = _resolve_flags(fact_sheet, fact_check_result.flags, auto_yes=args.yes)
    if resolved_fact_sheet is None:
        log["stopped_reason"] = "contradicted_flag_unresolved"
        _write_log(out_dir, log)
        print(f"Stopped. Run artifacts saved in {out_dir}")
        return
    fact_check_result = dataclasses.replace(fact_check_result, fact_sheet=resolved_fact_sheet)
    log["research_claims"] = [dataclasses.asdict(c) for c in resolved_fact_sheet.claims]
    _write_log(out_dir, log)

    if not _confirm("\nProceed to previz with this fact-check result?", auto_yes=args.yes):
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
