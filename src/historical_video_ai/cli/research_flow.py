"""Research and fact-check, and what happens when fact-check says no.

The two cheap stages that run before anything costs real money
(docs/architecture.md, "Design principles"). Research is written to the
run log before fact-check starts, so a fact-check crash does not lose it
(docs/decisions/0015).

`resolve_premise_conflict` is the refusal path: when fact-check reports
the scene itself could not have happened, the pipeline does not fabricate
it (docs/decisions/0008). It offers fact-check's own suggested
alternative or a correction of your own, re-verifies whichever you pick,
and can also record the scene as deliberate fiction (docs/decisions/0027).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path

from historical_video_ai.cli.review import confirm, prompt_if_missing
from historical_video_ai.cli.runlog import write_log
from historical_video_ai.stages.fact_check import (
    ClaimFlag,
    FactCheckResult,
    run_fact_check_stage,
)
from historical_video_ai.stages.research import Claim, FactSheet, run_research_stage


def resolve_flags(
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

    # Indexed, not keyed by text: nothing upstream prevents two distinct
    # claims from sharing identical text, and resolving one must not
    # silently affect an unrelated claim that merely happens to match.
    # `claimed_indices` tracks which original positions a flag has already
    # consumed, so each flag resolves exactly one claim -- the first
    # not-yet-consumed match -- rather than every claim with that text.
    resolved_claims: list[Claim | None] = list(fact_sheet.claims)
    claimed_indices: set[int] = set()

    print("\nResolve flagged claims:")
    for flag in flags:
        idx = next(
            i
            for i, c in enumerate(fact_sheet.claims)
            if i not in claimed_indices and c.text == flag.claim_text
        )
        claimed_indices.add(idx)
        claim = fact_sheet.claims[idx]
        print(f"\nClaim: {claim.text}")
        print(f"Flag [{flag.severity}]: {flag.concern}")
        if auto_yes:
            print("(a)ccept / (c)ut / (s)often this claim? [a/c/s]: a (--yes)")
            continue
        action = ""
        while action not in ("a", "c", "s"):
            action = input("(a)ccept / (c)ut / (s)often this claim? [a/c/s]: ").strip().lower()
        if action == "c":
            resolved_claims[idx] = None
        elif action == "s":
            new_text = ""
            while not new_text:
                new_text = input("New text for this claim: ").strip()
            resolved_claims[idx] = dataclasses.replace(claim, text=new_text)
        # "a" (accept): keep the claim exactly as research produced it.

    return dataclasses.replace(fact_sheet, claims=[c for c in resolved_claims if c is not None])


def record_research_claims(
    fact_sheet: FactSheet, *, research_model: str, out_dir: Path, log: dict
) -> None:
    """Persist research's output to `log` immediately -- used as
    `run_research_and_fact_check`'s `on_research_completed` callback, from
    both of its call sites in `main()` (the initial pass and a premise-
    conflict re-verification pass), so a fact-check-stage crash right
    after either one doesn't lose the research it would otherwise have
    recorded. See docs/decisions/0015-persist-research-before-fact-check.md.
    """
    log["research_model"] = research_model
    log["research_claims"] = [dataclasses.asdict(c) for c in fact_sheet.claims]
    write_log(out_dir, log)


def run_research_and_fact_check(
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
    (resolve_premise_conflict) can re-run this on a corrected description.

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
    if not confirm("\nProceed to fact-check with this research?", auto_yes=auto_yes):
        return None

    print(f"\n--- fact-check (model: {fact_check_model}) ---")
    fact_check_result = run_fact_check_stage(fact_sheet, model=fact_check_model, **completion_kwargs)
    if fact_check_result.flags:
        for f in fact_check_result.flags:
            print(f"- [{f.severity}] {f.claim_text} -- {f.concern}")
    else:
        print("No issues flagged.")

    return fact_sheet, fact_check_result


def resolve_premise_conflict(
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
) -> tuple[FactSheet, FactCheckResult, str | None] | None:
    """If fact-check flagged the scene's own premise as historically
    impossible (docs/decisions/0008), push back instead of silently
    proceeding -- previz would refuse anyway, but that's a last-resort
    safety net, not a substitute for asking. Offers three resolutions:
    use the suggested alternative, supply a corrected description
    (re-verified with one fresh research + fact-check pass), or keep the
    premise as intentional fiction (docs/decisions/0025) -- acknowledges
    the conflict without altering the description, clearing
    `premise_conflict` since previz's own check exists to require
    knowing acknowledgment, not to forbid fiction outright.

    Returns (fact_sheet, fact_check_result, resolution_type), or None if
    the human stopped. `resolution_type` is None when there was no
    conflict to resolve in the first place, `"kept_as_intentional_fiction"`
    or `"corrected"` otherwise -- see docs/decisions/0025. Only
    re-verifies once for a corrected description -- a still-conflicted
    correction is treated as a stop, not a retry loop.
    """
    conflict = fact_check_result.premise_conflict
    if conflict is None:
        return fact_sheet, fact_check_result, None

    print(f"\nThis scene's premise appears to be historically impossible: {conflict.explanation}")
    if conflict.suggested_alternative:
        print(f"Closest historically plausible version: {conflict.suggested_alternative}")
    else:
        print("No reasonably close, historically plausible version of this scene was found.")

    if auto_yes:
        # --yes has no sound basis to guess between "keep as intentional
        # fiction" and "use the corrected version" -- they produce
        # meaningfully different videos, unlike an "uncertain" fact-check
        # flag. Stop cleanly, same precedent as every other case --yes
        # refuses to guess at (0017, 0019).
        print("\n--yes won't auto-resolve a premise conflict -- rerun without --yes to choose.")
        return None

    valid_actions = {"k", "o", "s"} | ({"u"} if conflict.suggested_alternative else set())
    prompt = "(k)eep as intentional fiction"
    if conflict.suggested_alternative:
        prompt = f"(u)se the suggested alternative / {prompt}"
    prompt += " / (o)wn corrected description / (s)top"

    action = ""
    while action not in valid_actions:
        action = input(f"{prompt}: ").strip().lower()

    if action == "k":
        print("Keeping this premise as intentional fiction -- proceeding as written.")
        return (
            fact_sheet,
            dataclasses.replace(
                fact_check_result,
                premise_conflict=None,
                # docs/decisions/0026: carried forward, not discarded, so
                # previz_review knows this specific thing is already
                # acknowledged rather than re-flagging it on every beat.
                # docs/decisions/0030: broadened beyond the literal
                # explanation text -- a real run showed fact-check's
                # premise_conflict narrows in on one specific anachronism
                # (a time-travel smartphone) while leaving its obvious
                # knock-on consequences (a modern visitor's modern
                # clothing) unacknowledged, so previz_review flagged the
                # outfit as a *separate*, uncovered anachronism the
                # instant a beat's framing actually showed it. Per 0026's
                # own principle -- an explicit allowlist beats asking the
                # reviewer to infer more -- the fix broadens what's
                # explicitly acknowledged, not the reviewer's inference.
                acknowledged_fiction=(
                    f"{conflict.explanation}\n\nThis acknowledgment also covers any other "
                    "detail that is a natural, expected consequence of this same "
                    "acknowledged fictional premise -- not just the specific anachronism "
                    "named above -- so don't flag those knock-on details as a separate, "
                    "new anachronism."
                ),
            ),
            "kept_as_intentional_fiction",
        )
    if action == "s":
        print("Stopping -- the scene's premise was never resolved.")
        return None
    if action == "u":
        # "u" is only in valid_actions when this is non-empty, above.
        assert conflict.suggested_alternative is not None
        new_description = conflict.suggested_alternative
    else:
        new_description = prompt_if_missing(None, "Corrected description")

    print(f"\nRe-verifying with the corrected description: {new_description!r}")
    result = run_research_and_fact_check(
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

    return new_fact_sheet, new_fact_check_result, "corrected"
