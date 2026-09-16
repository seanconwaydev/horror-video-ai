"""Interactive CLI entry point for the v1 pipeline: collects a scene
(time, place, description), runs it through research -> fact-check ->
scene planning -> previz (docs/decisions/0006, 0023). Run with
`uv run historical-video-ai`.

Scene planning (docs/decisions/0023) produces a reviewed plan --
characters, locations, and beats -- but isn't yet wired into previz's
actual generation calls (that's docs/decisions/0024); previz still
generates its one image from fact_check_result alone, same as before this
stage existed.

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
- `--video-seconds`: requests a clip duration, validated against the
  video model's real supported range before any API call
  (docs/decisions/0020, 0038).
- `--video-prompt`: overrides the saved previz prompt for --video-gen-from,
  to test a hand-written prompt against an already-approved image.
- `--yes`: non-interactive -- auto-confirms every prompt and auto-accepts
  an "uncertain" fact-check flag, but stops the run on a "contradicted"
  one rather than auto-accepting it (docs/decisions/0017, 0019). Note
  that --yes is a deliberately secondary mode: the interactive path is
  where design effort goes (docs/decisions/0043).

Every --video-gen-from scene runs a free, advisory moderation check
(docs/decisions/0038, stages/moderation.py) before the paid video-
generation call. It reports flagged categories and never blocks -- horror
routinely trips the violence category, and this project's video model has
no vendor moderation for it to predict.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
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
from historical_video_ai.stages.moderation import run_moderation_policy_check
from historical_video_ai.stages.previz import (
    DEFAULT_STYLE,
    PHOTOREAL_STYLES,
    STYLE_PRESETS,
    PrevizResult,
    build_character_sheet_prompt,
    build_location_reference_prompt,
    run_beat_image_stage,
    run_previz_review_stage,
    run_previz_stage,
    run_reference_image_stage,
)
from historical_video_ai.stages.research import Claim, FactSheet, run_research_stage
from historical_video_ai.stages.scene_planning import (
    Beat,
    Location,
    ScenePlan,
    ScenePlanningError,
    check_beat_location_references,
    check_unique_ids,
    identity_field_pose_warnings,
    run_scene_planning_stage,
)
from historical_video_ai.stages.video_generation import (
    MAX_VIDEO_SECONDS,
    MIN_VIDEO_SECONDS,
    run_video_generation_stage,
)

# 90x160 (9:16, tiny for speed). The aspect-ratio guard that originally
# forced a real image here is gone with Sora (docs/decisions/0038) -- the
# video stage now only base64-encodes whatever file it's given -- but a
# real PNG is still the honest stand-in for a previz output, and previz's
# own code paths do open it.
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


def _mock_image_edit(**kwargs: object) -> SimpleNamespace:
    return SimpleNamespace(data=[SimpleNamespace(b64_json=_MOCK_PNG_B64)])


def _mock_review_completion(**kwargs: object) -> SimpleNamespace:
    """No network call, no API key -- always accepts, so --mock exercises
    the previz-review loop's mechanics without cost or credentials."""
    content = json.dumps({"accepted": True, "concern": None})
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def _mock_scene_planning_completion(**kwargs: object) -> SimpleNamespace:
    """No network call, no API key -- returns a minimal valid ScenePlan, so
    --mock exercises the scene-planning stage's mechanics (docs/decisions
    /0023) without cost or credentials."""
    content = json.dumps(
        {
            "characters": [
                {
                    "id": "mock-character",
                    "face_build": "[MOCK]",
                    "hair": "[MOCK]",
                    "wardrobe_signature": "[MOCK]",
                    "wardrobe_flexible": "[MOCK]",
                    "distinguishing_detail": "[MOCK]",
                }
            ],
            "locations": [
                {
                    "id": "mock-location",
                    "architecture": "[MOCK]",
                    "fixed_props": "[MOCK]",
                    "ambient_light": "[MOCK]",
                }
            ],
            "beats": [
                {
                    "location_id": "mock-location",
                    "subject": "[MOCK]",
                    "action": "[MOCK]",
                    "camera": "[MOCK]",
                    "lighting": "[MOCK]",
                    "cinematography": "[MOCK]",
                    "audio": "[MOCK]",
                    "duration_seconds": "4",
                }
            ],
        }
    )
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def _mock_prediction(*args: object, **kwargs: object) -> dict:
    """No network call, no API token -- returns a prediction already
    'succeeded', so --video-gen-from --mock exercises the stage's own
    payload-building and output-handling without cost or credentials."""
    return {
        "id": "mock-prediction-id",
        "status": "succeeded",
        "output": "https://example.invalid/mock-video.mp4",
        "error": None,
    }


def _mock_download(*args: object, **kwargs: object) -> bytes:
    return b"[MOCK] not a real video file"


def _mock_moderation_policy_check(**kwargs: object) -> SimpleNamespace:
    """No network call, no API key -- always comes back clean, so --mock
    exercises the moderation pre-flight's mechanics (docs/decisions/0038)
    without cost or credentials."""
    return SimpleNamespace(results=[SimpleNamespace(flagged=False, categories={})])


# See docs/decisions/0009-previz-image-review.md -- your call: bounded, not
# tunable via a flag, to keep behavior predictable rather than open-ended.
_MAX_PREVIZ_ATTEMPTS = 3

# Real, checked per-image costs (docs/decisions/0024) -- never a guessed
# number. Keyed by the exact pinned model string, so a config change that
# swaps the previz model automatically falls back to "cost unknown" rather
# than silently reporting a stale price for a different model.
_KNOWN_IMAGE_MODEL_COSTS_USD = {
    "gemini/gemini-2.5-flash-image": 0.039,
}


def _estimate_image_cost(model: str, count: int) -> str:
    """A short cost-visibility string for `count` images from `model` --
    "$X.XX total" if the model's per-image cost is known, otherwise an
    honest "cost unknown" rather than a fabricated number."""
    cost = _KNOWN_IMAGE_MODEL_COSTS_USD.get(model)
    if cost is None:
        return f"{count} image(s) at an unknown per-image cost for {model}"
    return f"{count} image(s) at ~${cost:.3f} each (~${cost * count:.2f} total)"


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


def _print_item_fields(item: object) -> None:
    for f in dataclasses.fields(item):
        print(f"  {f.name}: {getattr(item, f.name)}")


# A Beat has 8 fields, but a human editing one is almost always reacting
# to a specific rendered mismatch (the wrong action, the wrong framing, a
# missing shadow) -- walking through all 8 one by one (including
# location_id, which shouldn't change here without the revalidation
# decisions/0028 requires for a real structural edit) was real, reported
# friction. These three are what actually drives what gets rendered.
_BEAT_QUICK_EDIT_FIELDS = ("action", "camera", "lighting")


def _beat_with_review_corrections(beat: Beat, previous_concerns: list[str]) -> Beat:
    """Return `beat` with every prior rejection reason appended to its
    `action` text as a direct correction, or `beat` unchanged if there are
    none yet (first attempt). Reframes previz_review's own third-person
    critique ("the image shows anger, not fear") as an imperative
    instruction ("Fix this: ...") rather than passing the raw complaint
    through verbatim -- the same shape as the project owner's own real
    (f)eedback note that fixed a near-identical case by hand. Does not
    mutate the caller's stored `beat` -- only this specific generation
    attempt's prompt sees the correction; `beat_results`' recorded `beat`
    field stays the original, human/scene-plan-approved text."""
    if not previous_concerns:
        return beat
    corrections = " ".join(f"Fix this: {concern}" for concern in previous_concerns)
    return dataclasses.replace(beat, action=f"{beat.action} {corrections}")


def _edit_item_fields(item: object, *, fields: tuple[str, ...] | None = None) -> object:
    """Prompt for a new value per field (blank keeps the current one) and
    return the updated item -- the shared editing mechanism behind both
    _review_item's (a)ccept/(e)dit loop and the beat-generation loop's
    (e)dit choice (docs/decisions/0023, 0024). Generic over any frozen
    dataclass with string fields.

    `fields`, if given, restricts prompting to just those field names --
    every other field keeps its current value untouched. See
    _BEAT_QUICK_EDIT_FIELDS."""
    updates = {}
    field_names = fields if fields is not None else [f.name for f in dataclasses.fields(item)]
    for name in field_names:
        current = getattr(item, name)
        new_value = input(f"  {name} [{current}]: ").strip()
        if new_value:
            updates[name] = new_value
    return dataclasses.replace(item, **updates)


def _review_item(item: object, *, item_desc: str, auto_yes: bool = False) -> object:
    """Print one scene-plan item (Character/Location/Beat) and let a human
    accept it as-is or edit it field-by-field -- docs/decisions/0023's
    per-item review loop. Editing replaces the item directly; unlike
    _resolve_premise_conflict's corrected description, an edit here is
    never re-verified through another LLM pass, since these are creative
    fields (a character's hairstyle, a location's lighting), not factual
    claims to check.

    Generic over any frozen dataclass with string fields -- Character,
    Location, and Beat all qualify, so one function serves all three
    review passes in `_review_scene_plan`. A Beat's edit is restricted to
    _BEAT_QUICK_EDIT_FIELDS rather than every field -- see that constant.
    """
    print(f"\n{item_desc}:")
    _print_item_fields(item)

    if auto_yes:
        print("(a)ccept or (e)dit? [a/e]: a (--yes)")
        return item

    action = ""
    while action not in ("a", "e"):
        action = input("(a)ccept or (e)dit? [a/e]: ").strip().lower()
    if action == "a":
        return item
    if isinstance(item, Beat):
        return _edit_item_fields(item, fields=_BEAT_QUICK_EDIT_FIELDS)
    return _edit_item_fields(item)


def _review_list_with_unique_ids(items: list, *, item_label: str, auto_yes: bool) -> list:
    """Review each item (Character or Location) via _review_item, then
    re-check the whole reviewed list for a duplicate id -- an edit can
    introduce a collision the LLM's original output didn't have just as
    easily as the LLM itself can (docs/decisions/0028). If one turns up
    interactively, re-review the whole list rather than crash a review
    session the human otherwise just finished; under auto_yes no edit
    could have happened, so a failure here means the LLM's own output was
    already broken and _parse_scene_plan should have already caught it --
    raising here is a safety net, not the expected path.
    """
    while True:
        reviewed = [
            _review_item(item, item_desc=f"{item_label} '{item.id}'", auto_yes=auto_yes)
            for item in items
        ]
        try:
            check_unique_ids(reviewed, label=item_label.lower())
        except ScenePlanningError as exc:
            print(f"\n{exc}")
            if auto_yes:
                raise
            print("Reviewing these again -- fix the colliding id(s).")
            items = reviewed
            continue
        return reviewed


def _review_scene_plan(plan: ScenePlan, *, auto_yes: bool = False) -> ScenePlan:
    """Per-item accept-or-edit review of a full ScenePlan --
    docs/decisions/0023. Reviewed in a fixed, strictly linear order --
    characters, then locations, then beats -- with no going back to reopen
    an earlier list once later ones are under review. Deliberate v1
    simplification, not an oversight: beats are reviewed against an
    already-finalized set of characters/locations, matching the natural
    dependency order, rather than building a free-form editor.

    Re-validates after edits, not just the LLM's original output
    (docs/decisions/0028): an edited beat's location_id, or an edited
    location's own id, can silently stop matching anything, which would
    otherwise drop all location grounding for that beat with no warning
    at all.
    """
    print("\n--- scene plan review (docs/decisions/0023) ---")
    for warning in identity_field_pose_warnings(plan.characters):
        print(f"\nheads up: {warning}")
    reviewed_characters = _review_list_with_unique_ids(
        plan.characters, item_label="Character", auto_yes=auto_yes
    )
    still_posed = identity_field_pose_warnings(reviewed_characters)
    if still_posed and not auto_yes:
        print(f"\n{len(still_posed)} identity field(s) still look like a pose; continuing anyway.")
    reviewed_locations = _review_list_with_unique_ids(
        plan.locations, item_label="Location", auto_yes=auto_yes
    )

    reviewed_beats = []
    for b in plan.beats:
        while True:
            reviewed_beat = _review_item(
                b, item_desc=f"Beat at '{b.location_id}': {b.action}", auto_yes=auto_yes
            )
            try:
                check_beat_location_references([reviewed_beat], reviewed_locations)
            except ScenePlanningError as exc:
                print(f"\n{exc}")
                if auto_yes:
                    raise
                print("Reviewing this beat again.")
                b = reviewed_beat
                continue
            reviewed_beats.append(reviewed_beat)
            break

    return ScenePlan(characters=reviewed_characters, locations=reviewed_locations, beats=reviewed_beats)


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
    new_description = (
        conflict.suggested_alternative if action == "u" else _prompt_if_missing(None, "Corrected description")
    )

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

    return new_fact_sheet, new_fact_check_result, "corrected"


def _safe_path_component(value: str) -> str:
    """Make a scene-plan id safe to use as a directory name.

    Ids come from a planning model and can be changed by hand at review
    time, so they are not guaranteed to be single path components. An id
    containing a separator -- "a/../../evil" being the worst shape --
    resolved outside the run directory entirely.
    """
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    return cleaned or "unnamed"


def _choose_candidate(candidates: list[PrevizResult], *, auto_yes: bool) -> PrevizResult | None:
    """Ask which of several candidate images to keep, or None to reject all.

    Generating one image per attempt meant a single roll of a
    non-deterministic process, which is indistinguishable from luck -- the
    project owner's own read of an improved beat was "not super obvious it's
    not just getting lucky". A real run spent 1.8 images per beat anyway, one
    at a time, discarding each before the next existed. Showing them together
    costs the same money and turns a gamble into a choice
    (docs/decisions/0046).

    Unattended, the first candidate is taken: there is nobody to ask, and
    picking arbitrarily is at least honest about that.
    """
    if auto_yes:
        return candidates[0]

    folder = candidates[0].image_path.parent
    print(f"\n{len(candidates)} candidates in {folder}:")
    for n, candidate in enumerate(candidates, start=1):
        print(f"  {n}. {candidate.image_path.name}")
    # One command that opens them together, since comparing them side by
    # side is the entire point.
    print(f"  open {folder}/candidate_*.png")

    valid = {str(n) for n in range(1, len(candidates) + 1)} | {"n"}
    choice = ""
    while choice not in valid:
        choice = input(
            f"  Keep which? [1-{len(candidates)}] or (n)one of them: "
        ).strip().lower()
    return None if choice == "n" else candidates[int(choice) - 1]


def _next_archive_path(out_dir: Path, prefix: str, *, suffix: str = "rejected") -> Path:
    """First unused `<prefix>_<n>_rejected.png` in `out_dir`.

    Deliberately not derived from the retry loop's own attempt counter.
    A (r)eroll, or an (e)dit-and-retry whose attempts then fail, starts a
    *fresh* `_generate_image_with_review` call against the same directory
    -- its counter restarts at 1, so deriving the name from it reused
    `<prefix>_1_rejected.png`, and `Path.rename` replaces the destination
    silently on POSIX. That destroyed the earlier cycle's already-paid-for
    images with no warning, found in a real run.

    The index is therefore a monotonic count of rejected images kept for
    this beat, not the "attempt N/3" shown while generating -- those are
    genuinely different things once a beat has had more than one cycle.
    Each attempt's own record in the run log carries its real image path,
    so nothing depends on the two agreeing.
    """
    # Globs on the index rather than the full name: the same index must not
    # be reused under a different suffix, or a superseded image would
    # overwrite a rejected one with the same number.
    n = 1
    while any(out_dir.glob(f"{prefix}_{n}_*.png")):
        n += 1
    return out_dir / f"{prefix}_{n}_{suffix}.png"


def _generate_image_with_review(
    generate_fn: Callable[[list[str]], PrevizResult],
    fact_check_result: FactCheckResult,
    *,
    review_model: str,
    review_kwargs: dict,
    out_dir: Path,
    archive_prefix: str = "previz_attempt",
    on_image_generated: Callable[[PrevizResult], None] | None = None,
    on_reviewed: Callable[[str | None, int], str] | None = None,
    initial_concerns: list[str] | None = None,
    choose_auto: bool = False,
    max_attempts: int | None = _MAX_PREVIZ_ATTEMPTS,
) -> tuple[PrevizResult | None, list[dict]]:
    """Generate an image via `generate_fn` (a callable producing one
    PrevizResult from the concerns accumulated so far -- a closure over
    run_previz_stage for the original single-scene flow, or over
    run_beat_image_stage for a scene-plan beat, docs/decisions/0023/0024),
    then have an independent pass review the actual image against the
    scene (docs/decisions/0009). On rejection, regenerates -- now with
    every prior rejection reason handed to `generate_fn` too (see below),
    not a truly blind identical retry -- unless `on_reviewed` says to
    stop, capped at _MAX_PREVIZ_ATTEMPTS regardless. Shared by both
    generation paths -- only how the image itself gets made differs
    between them.

    `generate_fn` receives the list of rejection reasons accumulated on
    this beat so far (empty on the first attempt). Real usage (2026-09-15)
    found previz_review's own rejection text -- e.g. "the image shows
    anger, not the fear/terror the beat calls for" -- is itself a
    near-ready corrective instruction, confirmed by a human manually
    typing almost the same correction via the (f)eedback option and
    getting a fixed result. Previously a blind retry reused the exact
    same prompt with zero new information on every attempt; feeding the
    reviewer's own concerns back into generation is strictly more
    information than that, at no extra cost (no added model call -- the
    concern text already exists from the review that just ran).

    Returns (accepted PrevizResult, attempt log), or (None, attempt log)
    if the human kept nothing, or `on_reviewed` stopped early. A
    rejected attempt's image is archived as `<archive_prefix>_<n>_rejected.png`
    rather than overwritten.

    `on_image_generated`, if given, is called with each attempt's
    PrevizResult right after the image is written -- *before* review runs,
    which can itself fail. Without this, a review-stage crash left a real,
    already-paid-for image on disk with no record of it in the log.

    `on_reviewed`, if given, is called after EVERY review -- not only
    after a rejection -- with (concern or None, attempt), and its return
    value picks one of three outcomes: "accept" keeps this attempt's
    image, "stop" ends the loop with nothing kept, anything else
    regenerates with the accumulated concerns folded in.

    Asking on every review, rather than letting the reviewer's verdict
    decide whether to ask at all, is docs/decisions/0043. previz_review
    was measured ranking four arms in exact reverse of blind human
    judgement, and rejecting 88% of images; letting it choose the default
    action spent money retrying images a human would have kept, and never
    offered the choice on images a human would have rerolled.

    With no callback the reviewer's verdict is followed, which is what
    --yes does.
    """
    attempts: list[dict] = []
    # Seeded rather than always empty: an (e)dit or (f)eedback ends this
    # call and starts a fresh one, and the reviewer's concerns used to be
    # thrown away at that boundary -- so adding a note of your own silently
    # discarded everything the reviewer had said (docs/decisions/0043).
    previous_concerns: list[str] = list(initial_concerns or [])
    # `max_attempts=None` means no ceiling. The cap exists to stop an
    # UNATTENDED run regenerating forever; once every attempt is an
    # explicit human choice (docs/decisions/0043) it stops being a guard
    # and becomes a refusal to do what was just asked for. Choosing
    # (r)etry on the last allowed attempt silently behaved as a give-up.
    attempt = 0
    while max_attempts is None or attempt < max_attempts:
        attempt += 1
        candidates = generate_fn(previous_concerns)
        for candidate in candidates:
            print(f"Image saved to {candidate.image_path}")
            if on_image_generated is not None:
                on_image_generated(candidate)

        if len(candidates) > 1:
            chosen = _choose_candidate(candidates, auto_yes=choose_auto)
            if chosen is None:
                # Rejecting every candidate is a rejection of the attempt,
                # not of the beat -- the loop offers the usual choices next.
                print("None kept.")
                attempts.append(
                    {
                        "attempt": attempt,
                        "accepted": False,
                        "concern": "human rejected every candidate",
                        "candidates": [str(c.image_path) for c in candidates],
                    }
                )
                decision = (
                    on_reviewed("none of the candidates were usable", attempt)
                    if on_reviewed is not None
                    else "continue"
                )
                if decision in ("accept", "stop"):
                    break
                continue
            previz_result = chosen
        else:
            previz_result = candidates[0]

        print(f"--- previz review (model: {review_model}) ---")
        review = run_previz_review_stage(
            previz_result.image_path,
            fact_check_result,
            model=review_model,
            # Carries forward every prior rejection reason on this same
            # beat so a retry review isn't an independent judgment with no
            # memory of what it already flagged -- observed in a real run
            # to matter: the reviewer caught a missing fisheye distortion
            # once, then accepted a second attempt that still didn't have
            # it, because nothing forced it to specifically re-check that.
            previous_concerns=previous_concerns or None,
            **review_kwargs,
        )

        if review.accepted:
            print("Review: no concerns.")
        else:
            print(f"Review concern: {review.concern}")

        # Asked after EVERY review, not only after a rejection
        # (docs/decisions/0043). The reviewer's verdict is shown as
        # information and no longer decides anything on its own: it was
        # measured ranking four arms in exact reverse of blind human
        # judgement, and rejecting 88% of images, so letting it pick the
        # default action cost real money on images a human would have kept.
        decision = (
            on_reviewed(review.concern if not review.accepted else None, attempt)
            if on_reviewed is not None
            else ("accept" if review.accepted else "continue")
        )

        if decision == "accept":
            attempts.append(
                {
                    "attempt": attempt,
                    "accepted": True,
                    "concern": review.concern,
                    "review_accepted": review.accepted,
                }
            )
            return previz_result, attempts

        # Archived whichever way the review went: a human can now retry an
        # image the reviewer was happy with, and that image must not be
        # silently overwritten by the next attempt.
        suffix = "rejected" if not review.accepted else "superseded"
        archived_path = _next_archive_path(out_dir, archive_prefix, suffix=suffix)
        previz_result.image_path.rename(archived_path)
        attempts.append(
            {
                "attempt": attempt,
                "accepted": False,
                "concern": review.concern,
                "review_accepted": review.accepted,
                "image_path": str(archived_path),
            }
        )
        if review.concern:
            previous_concerns.append(review.concern)
        if decision == "stop":
            break
        if max_attempts is None or attempt < max_attempts:
            print("Regenerating...")

    print(f"\nNo image kept for this beat after {len(attempts)} attempt(s).")
    return None, attempts


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
    """The original single-scene previz+review flow (docs/decisions/0009) --
    now a thin wrapper around _generate_image_with_review. See that
    function's docstring for the shared retry/review behavior.

    Unlike the scene-plan beat path (`_generate_beats_with_choices`),
    this flow doesn't fold prior rejection reasons back into the retry --
    `run_previz_stage` builds its prompt from the whole `fact_check_result`
    with no per-attempt correction-injection point today. Left as a real,
    known gap rather than force-fit, since this flow predates scene
    planning and is less actively used now that beats exist.
    """
    attempt_n = 0

    def _generate(previous_concerns: list[str]) -> list[PrevizResult]:
        del previous_concerns  # not used by this flow -- see docstring above
        nonlocal attempt_n
        attempt_n += 1
        print(f"\n--- previz (model: {previz_model}, attempt {attempt_n}/{_MAX_PREVIZ_ATTEMPTS}) ---")
        # A list of one: this flow has no candidate fan-out, but
        # _generate_image_with_review takes a list from every caller so it
        # has one shape to handle rather than two.
        return [
            run_previz_stage(
                fact_check_result,
                model=previz_model,
                output_dir=out_dir,
                on_transient_retry=lambda n, exc: print(
                    f"Transient error ({exc}) -- retrying (attempt {n + 1})..."
                ),
                **image_kwargs,
            )
        ]

    return _generate_image_with_review(
        _generate,
        fact_check_result,
        review_model=review_model,
        review_kwargs=review_kwargs,
        out_dir=out_dir,
        on_image_generated=on_image_generated,
    )


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
    the command again.)

    Raises RuntimeError if no ancestor has a pyproject.toml -- fail loud
    rather than guess at a directory (e.g. a fixed parents[2] offset) that
    was never actually confirmed to be the project root, which would risk
    reintroducing the exact silent-nesting bug this function exists to
    prevent."""
    here = Path(__file__).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise RuntimeError(
        f"Could not find pyproject.toml in any ancestor directory of {here} -- "
        "outputs/ needs a real, confirmed project root."
    )


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
    base = f"run_{run_id}_{slug}" if slug else f"run_{run_id}"
    outputs = _project_root() / "outputs"

    # Second precision alone is not unique: re-running the same command
    # right after a failed attempt -- routine while iterating -- lands in
    # the same second with the same slug, and `exist_ok=True` then let the
    # second run write its images and log straight over the first one's.
    # A numeric suffix keeps the readable name while making a collision
    # impossible. (video_generation.py already reached for microsecond
    # precision against this same hazard; this keeps folder names legible
    # instead.)
    dir_name, n = base, 1
    while (outputs / dir_name).exists():
        n += 1
        dir_name = f"{base}-{n}"

    d = outputs / dir_name
    d.mkdir(parents=True)
    return d


def _write_log(out_dir: Path, log: dict) -> None:
    (out_dir / "run_log.json").write_text(json.dumps(log, indent=2, default=str))


def _read_log(out_dir: Path) -> dict:
    return json.loads((out_dir / "run_log.json").read_text())


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
    # docs/decisions/0027: read back alongside premise_conflict -- a
    # fixture saved before this ADR won't have this key, so .get() rather
    # than a required field, same graceful-absence handling as
    # premise_conflict itself.
    acknowledged_fiction = data.get("acknowledged_fiction")

    return FactCheckResult(
        fact_sheet=fact_sheet,
        flags=flags,
        premise_conflict=premise_conflict,
        acknowledged_fiction=acknowledged_fiction,
    )


@dataclasses.dataclass(frozen=True)
class VideoGenTarget:
    """One (image, prompt) pair ready for video generation -- either the
    whole of an old-style single-image run (docs/decisions/0010), or one
    accepted beat within a new-style multi-beat scene-plan run
    (docs/decisions/0023/0024's --video-gen-from follow-up).

    `beat_index` is None for the old-style case; for a beat, it locates
    where to record a video/moderation-flag result back in the parent
    run's run_log.json (see _record_video_gen_result) -- nested under
    that beat's own entry, not mixed into one flat list across every beat.
    """

    run_dir: Path
    image_path: Path
    prompt_used: str
    output_dir: Path
    label: str
    beat_index: int | None


def _resolve_recorded_path(recorded: str, run_dir: Path) -> Path:
    """Resolve a path recorded in a run log, tolerating a moved outputs/.

    Run logs store absolute paths, so they embed wherever the project
    happened to live when the run executed. Moving or copying a run folder
    -- or handing one to someone else -- breaks every reference in it, even
    though the files are sitting right beside the log. The gallery
    symlinks were deliberately made relative for exactly this reason
    (`_link_beat_into_gallery`); the log was not.

    The portion of a recorded path after the run directory's own name is
    still correct relative to wherever that directory is now, so fall back
    to that. Returns the original path unchanged if neither resolves, so
    the caller's error message still names what it actually looked for.
    """
    path = Path(recorded)
    if path.exists():
        return path
    parts = path.parts
    if run_dir.name in parts:
        candidate = run_dir.joinpath(*parts[parts.index(run_dir.name) + 1 :])
        if candidate.exists():
            return candidate
    return path


def _load_video_gen_targets(
    run_dir: Path, *, prompt_override: str | None = None
) -> list[VideoGenTarget]:
    """Expand one run_dir into its video-generation targets. A new-style
    run (a "previz_beats" list in its run_log.json, docs/decisions/0023)
    produces one target per beat that has an accepted image -- a beat
    with no accepted image (every previz_review attempt was rejected) is
    silently skipped, not an error, since that's a real, expected
    per-beat outcome. An old-style run (docs/decisions/0010) produces a
    single target, via _load_previz_output unchanged.

    Raises FileNotFoundError if run_dir has no run_log.json or a
    referenced image no longer exists, and ValueError if there's no
    completed previz result to work from (old-style: see
    _load_previz_output; new-style: no beat produced an accepted image,
    or an accepted beat has no recorded prompt_used -- a run from before
    docs/decisions/0024 started saving it).
    """
    log_path = run_dir / "run_log.json"
    if not log_path.exists():
        raise FileNotFoundError(f"No run_log.json found in {run_dir}")
    data = json.loads(log_path.read_text())

    if "previz_beats" not in data:
        image_path, prompt_used = _load_previz_output(run_dir, prompt_override=prompt_override)
        return [
            VideoGenTarget(
                run_dir=run_dir,
                image_path=image_path,
                prompt_used=prompt_used,
                output_dir=run_dir,
                label=run_dir.name,
                beat_index=None,
            )
        ]

    targets = []
    for beat_result in data["previz_beats"]:
        if beat_result.get("image_path") is None:
            continue
        index = beat_result["index"]
        prompt_used = prompt_override or beat_result.get("prompt_used")
        if not prompt_used:
            raise ValueError(
                f"{log_path}: beat {index} has an accepted image but no recorded "
                "'prompt_used' -- pass --video-prompt, or point --video-gen-from at a run "
                "generated after docs/decisions/0024 started recording it."
            )
        image_path = _resolve_recorded_path(beat_result["image_path"], run_dir)
        if not image_path.exists():
            raise FileNotFoundError(
                f"Beat {index}'s image referenced by {log_path} no longer exists: {image_path}"
            )
        targets.append(
            VideoGenTarget(
                run_dir=run_dir,
                image_path=image_path,
                prompt_used=prompt_used,
                output_dir=image_path.parent,
                label=f"{run_dir.name} beat {index}",
                beat_index=index,
            )
        )
    if not targets:
        raise ValueError(
            f"{log_path} has a scene plan but no beat produced an accepted image -- "
            "nothing to generate video from."
        )
    return targets


def _record_video_gen_result(target: VideoGenTarget, key: str, entry: dict) -> None:
    """Append `entry` to list `key` in this target's run_log.json -- at
    the top level for an old-style single-image run, or nested under the
    matching beat's own entry in "previz_beats" for a new-style
    multi-beat run, so a beat's video/moderation history stays co-located
    with that beat's own record instead of mixed into one flat list
    across every beat."""
    log = _read_log(target.run_dir)
    if target.beat_index is None:
        log.setdefault(key, []).append(entry)
    else:
        for beat_result in log["previz_beats"]:
            if beat_result["index"] == target.beat_index:
                beat_result.setdefault(key, []).append(entry)
                break
    _write_log(target.run_dir, log)


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

    image_path = _resolve_recorded_path(image_path_str, run_dir)
    if not image_path.exists():
        raise FileNotFoundError(
            f"Previz image referenced by {log_path} no longer exists: {image_path}"
        )

    return image_path, prompt_used


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
    (no character block, too many beats crammed into one call) rather than
    judging actual prompt quality, which isn't something this can do
    reliably and isn't its job -- a human still decides whether to proceed.

    Two checks were removed in docs/decisions/0038 when the video model
    changed: an audio-direction check (Wan generates no audio at all, so
    asking a prompt to describe sound is dead weight until a real
    sound-design step exists) and a list of words that had tripped Sora's
    moderation -- "fight", "attack", "blood", "weapon" and similar. That
    list steered prompts away from the exact vocabulary this project's own
    genre needs, and the model it was protecting against is gone.
    """
    found = []
    if "CHARACTER:" not in prompt:
        found.append(
            "no 'CHARACTER:' block -- character consistency across beats relies on "
            "reusing one verbatim"
        )
    # [-–] not just "-": the playbook's own documented timecode format
    # ("(0–3s)") uses an en-dash, not an ASCII hyphen -- an ASCII-only
    # pattern silently counted zero beats in a prompt written exactly the
    # way the playbook shows.
    beat_count = len(re.findall(r"\(\d+[-–]\d+s\)", prompt))
    if beat_count > _MAX_RECOMMENDED_BEATS:
        found.append(
            f"{beat_count} timecoded beats in one prompt -- {_MAX_RECOMMENDED_BEATS} is "
            "the practical ceiling before quality degrades; consider a separate image + "
            "generation per beat instead"
        )
    return found


def _run_video_generation_only(
    run_dirs: list[Path],
    *,
    mock: bool,
    video_model: str | None = None,
    video_seconds: float | None = None,
    video_prompt: str | None = None,
) -> None:
    """Run stage 9 (video generation) standalone against one or more
    already-completed previz outputs, skipping research/fact-check/previz
    for this invocation (docs/decisions/0010). Each run_dir expands into
    one or more `VideoGenTarget`s (`_load_video_gen_targets`) -- a single
    target for an old-style single-image run, or one target per accepted
    beat for a new-style multi-beat scene-plan run (docs/decisions/0023/
    0024). Blocks and polls each target to completion before starting the
    next (0010's v1 choice, not the SQS fan-out named for this stage in
    0004). Lets VideoGenerationError propagate uncaught, same fail-loud
    convention as every other stage.

    Before each target's paid video-generation call, runs the free
    moderation check (docs/decisions/0038) against the actual image and
    prompt about to be submitted. Flagged categories are printed and
    recorded, and the run continues either way -- this project's genre
    trips the violence category as a matter of course, and the model being
    called has no vendor moderation for the check to predict. It is a
    YouTube-policy signal for the human reading the run log, not a gate.

    `video_seconds`, if given, requests that duration -- validated against
    the model's real supported range before any call (0020, 0038).

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
        {"prediction_fn": _mock_prediction, "download_fn": _mock_download} if mock else {}
    )
    policy_check_kwargs = {"moderation_fn": _mock_moderation_policy_check} if mock else {}

    video_model = video_model or get_stage_model("video_generation")

    if video_prompt is not None:
        practice_warnings = _check_video_prompt_practices(video_prompt)
        if practice_warnings:
            print("\n--video-prompt doesn't follow known best practice:")
            for warning in practice_warnings:
                print(f"- {warning}")
            print("Proceeding anyway -- this is advisory, not a block.")

    targets = [
        target
        for run_dir in run_dirs
        for target in _load_video_gen_targets(run_dir, prompt_override=video_prompt)
    ]

    for i, target in enumerate(targets, start=1):
        print(f"\n--- video generation (model: {video_model}, scene {i}/{len(targets)}) ---")
        print(f"Source: {target.label} (image: {target.image_path})")

        print("Running moderation check (advisory -- docs/decisions/0038)...")
        policy_result = run_moderation_policy_check(
            target.prompt_used, target.image_path, **policy_check_kwargs
        )
        if policy_result.flagged:
            categories = ", ".join(policy_result.flagged_categories)
            print(
                f"Note: omni-moderation-latest flagged [{categories}]. Recorded for "
                "YouTube-policy review; not blocking generation."
            )
            _record_video_gen_result(
                target,
                "moderation_flags",
                {
                    "flagged_categories": policy_result.flagged_categories,
                    "prompt_used": target.prompt_used,
                },
            )

        # Microsecond precision, not just seconds -- two attempts against
        # the same previz output (e.g. comparing --video-seconds values)
        # can easily land in the same second, and a filename collision
        # would silently overwrite the earlier video instead of
        # accumulating both.
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
        result = run_video_generation_stage(
            target.image_path,
            target.prompt_used,
            model=video_model,
            output_dir=target.output_dir,
            output_filename=f"video_{timestamp}.mp4",
            **({"seconds": video_seconds} if video_seconds is not None else {}),
            **video_kwargs,
        )
        print(
            f"Video saved to {result.video_path} "
            f"(requested {result.seconds_requested:.2f}s, actual {result.seconds_actual:.2f}s)"
        )

        _record_video_gen_result(
            target,
            "videos",
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
                "prompt_used": target.prompt_used,
            },
        )

    print("\nDone.")


def _generate_scene_references(
    scene_plan: ScenePlan,
    *,
    previz_model: str,
    image_kwargs: dict,
    out_dir: Path,
    style: str = DEFAULT_STYLE,
    auto_yes: bool = False,
    want_character: bool = True,
    want_location: bool = True,
) -> tuple[dict[str, Path], dict[str, Path]]:
    """Generate one canonical reference image per Character and per
    Location in scene_plan (docs/decisions/0024). Each gets its own
    accept/regenerate confirm before moving on -- a bad reference is far
    cheaper to catch here than after generating several beats off it.
    `style` (docs/decisions/0033) is the run's single authoritative
    realism-level source.

    Returns (character_refs, location_refs), each a dict keyed by id.
    """
    character_refs: dict[str, Path] = {}
    for i, character in enumerate(scene_plan.characters if want_character else [], start=1):
        prompt = build_character_sheet_prompt(character, style=style)
        while True:
            print(
                f"\n--- character reference '{character.id}' "
                f"({i}/{len(scene_plan.characters)}) ---"
            )
            result = run_reference_image_stage(
                prompt,
                model=previz_model,
                output_dir=out_dir / f"character_{_safe_path_component(character.id)}",
                on_transient_retry=lambda n, exc: print(
                    f"Transient error ({exc}) -- retrying (attempt {n + 1})..."
                ),
                **image_kwargs,
            )
            print(f"Reference saved to {result.image_path}")
            if _confirm("Accept this reference?", auto_yes=auto_yes):
                character_refs[character.id] = result.image_path
                break
            # Archive rather than let the next attempt overwrite it.
            # References wrote to a fixed "reference.png", so every
            # rejected one was destroyed with no way to compare or go
            # back -- while beats had archived their rejects all along.
            archived = _next_archive_path(result.image_path.parent, "reference_attempt")
            result.image_path.rename(archived)
            print(f"Previous attempt kept at {archived.name}. Regenerating...")

    location_refs: dict[str, Path] = {}
    for i, location in enumerate(scene_plan.locations if want_location else [], start=1):
        prompt = build_location_reference_prompt(location, style=style)
        while True:
            print(f"\n--- location reference '{location.id}' ({i}/{len(scene_plan.locations)}) ---")
            result = run_reference_image_stage(
                prompt,
                model=previz_model,
                output_dir=out_dir / f"location_{_safe_path_component(location.id)}",
                on_transient_retry=lambda n, exc: print(
                    f"Transient error ({exc}) -- retrying (attempt {n + 1})..."
                ),
                **image_kwargs,
            )
            print(f"Reference saved to {result.image_path}")
            if _confirm("Accept this reference?", auto_yes=auto_yes):
                location_refs[location.id] = result.image_path
                break
            archived = _next_archive_path(result.image_path.parent, "reference_attempt")
            result.image_path.rename(archived)
            print(f"Previous attempt kept at {archived.name}. Regenerating...")

    return character_refs, location_refs


def _generate_beats_with_choices(
    scene_plan: ScenePlan,
    fact_check_result: FactCheckResult,
    *,
    character_refs: dict[str, Path],
    location_refs: dict[str, Path],
    previz_model: str,
    review_model: str,
    image_kwargs: dict,
    review_kwargs: dict,
    out_dir: Path,
    style: str = DEFAULT_STYLE,
    requires_grounding: bool = True,
    auto_yes: bool = False,
    candidates: int = 1,
    on_beat_complete: Callable[[list[dict]], None] | None = None,
) -> list[dict]:
    """Generate each beat's image (docs/decisions/0024). `style`
    (docs/decisions/0033) is the run's single authoritative realism-level
    source. Every attempt
    still goes through previz_review's own automatic reject-and-regenerate
    loop (docs/decisions/0009, via _generate_image_with_review), but now
    with an on-rejection hook (docs/decisions/0029): after *any*
    rejection, not just after all attempts are exhausted, a human can edit
    the beat's text and retry fresh, or give up on this beat now --
    otherwise Enter keeps the existing blind-retry behavior. This matters
    because some rejections are attributable to something baked into the
    prompt itself (e.g. an anachronistic detail on the shared Character),
    which fails identically on every blind attempt -- see the real run
    that motivated this. Under `auto_yes` there's no human to ask, so the
    hook instead applies a cheap heuristic: an identical rejection concern
    twice in a row gives up rather than spending the last attempt on a
    near-certain repeat (0029 -- a real judgment call on "is this doomed"
    needs a model in the loop, which is future work, not this).

    Once an attempt is accepted by review, a human gets three further
    choices, not an automatic proceed: (a)ccept, (r)eroll (same beat text,
    another blind attempt -- for "unlucky roll"), or (e)dit (update the
    beat's text first, reusing 0023's per-item edit mechanism, then retry
    -- for "this needs an actual change," not just another random draw).

    Assumes a single main character, the common case in every real scene
    built so far: with zero characters, no character reference is used;
    with more than one, the first is used for every beat. A known v1
    simplification (Beat has no character_id field to disambiguate), not
    a silent bug -- worth revisiting if a real scene needs more than one
    named character across its beats.

    Returns a list of per-beat result dicts (index, beat, image path or
    None if every review attempt was rejected, attempt log) for
    run_log.json.
    """
    characters_by_id = {c.id: c for c in scene_plan.characters}
    locations_by_id = {loc.id: loc for loc in scene_plan.locations}

    beat_results = []

    def _record(entry: dict) -> None:
        """Append a finished beat and persist immediately.

        Persisting per beat rather than once at the end: a real run was
        interrupted partway through and its log recorded zero beats,
        despite two having been accepted and paid for. The images
        survived; the metadata pairing them with their prompts -- which is
        what --video-gen-from needs later -- did not.
        """
        beat_results.append(entry)
        if on_beat_complete is not None:
            on_beat_complete(beat_results)

    for i, beat in enumerate(scene_plan.beats, start=1):
        # Every character the beat says is present, not just the scene's
        # first one (docs/decisions/0041). A beat that names nobody falls
        # back to the first character, which is what every beat got before.
        beat_character_ids = beat.character_ids or (
            [scene_plan.characters[0].id] if scene_plan.characters else []
        )
        beat_characters = [
            characters_by_id[cid] for cid in beat_character_ids if cid in characters_by_id
        ]
        beat_character_refs = [
            character_refs[c.id] for c in beat_characters if c.id in character_refs
        ]
        location = locations_by_id.get(beat.location_id)
        location_ref = location_refs.get(beat.location_id)
        beat_out_dir = out_dir / f"beat_{i}"

        # Spans attempt cycles, unlike the list inside
        # _generate_image_with_review, which is per call. An (e)dit or
        # (f)eedback starts a new call, and the reviewer's concerns must
        # survive that (docs/decisions/0043).
        carried_concerns: list[str] = []
        cycle = 0
        while True:
            cycle += 1
            if cycle == 1:
                print(f"\n=== beat {i}/{len(scene_plan.beats)}: {beat.action} ===")
            else:
                # A (r)eroll or an (e)dit-and-retry re-enters this loop for
                # the SAME beat. Reprinting the original header made that
                # read as a new beat being generated, which it isn't.
                print(
                    f"\n=== beat {i}/{len(scene_plan.beats)} -- restarting, "
                    f"attempt cycle {cycle} ==="
                )
            attempt_n = 0
            beat_was_edited = False
            last_concern: str | None = None

            def _on_reviewed(
                concern: str | None,
                attempt: int,
                i: int = i,
                # Bound as a default like the other loop captures
                # (ruff B023). It is mutated in place, not rebound,
                # so the caller sees every append.
                carried_concerns: list[str] = carried_concerns,
            ) -> str:
                """One prompt after every review, whatever the verdict.

                The reviewer's opinion is shown above this as information
                and decides nothing on its own (docs/decisions/0043): it
                was measured ranking four arms in exact reverse of blind
                human judgement and rejecting 88% of images, so letting it
                choose the default action spent money on images a human
                would have kept, and skipped the question entirely on ones
                a human would have rerolled.
                """
                nonlocal beat, beat_was_edited, last_concern
                if auto_yes:
                    # Unattended, there is no human to ask. Follow the
                    # reviewer, since something has to decide -- but stop on
                    # a repeated concern rather than spend the remaining
                    # attempts on a near-certain repeat. Deliberately the
                    # weaker path now: --yes is a secondary mode, and its
                    # gate is the component measured as anti-correlated.
                    if concern is None:
                        return "accept"
                    is_repeat = last_concern is not None and concern == last_concern
                    last_concern = concern
                    return "stop" if is_repeat else "continue"

                if concern is not None:
                    carried_concerns.append(concern)

                # The retry option says what it actually does. It folds
                # every concern so far into the next attempt's prompt, and
                # nothing said so -- which led to the reasonable assumption
                # that the reviewer's wording had to be copy-pasted in by
                # hand via (f)eedback.
                n_carried = len(carried_concerns)
                retry_label = (
                    f"(r)etry carrying {n_carried} review "
                    f"concern{'' if n_carried == 1 else 's'}"
                    if n_carried
                    else "(r)etry"
                )
                choice = None
                while choice not in ("a", "r", "e", "f", "g"):
                    # No "/3": interactively there is no ceiling, so a
                    # denominator would promise a limit that isn't there.
                    # The running count is the cost signal instead.
                    choice = input(
                        f"  Attempt {attempt} -- (a)ccept / "
                        f"{retry_label} / (e)dit the beat / "
                        "(f)eedback then retry / (g)ive up: "
                    ).strip().lower()
                if choice == "a":
                    return "accept"
                if choice == "e":
                    print(f"\nBeat {i}:")
                    beat = _edit_item_fields(beat, fields=_BEAT_QUICK_EDIT_FIELDS)
                    beat_was_edited = True
                    return "stop"
                if choice == "f":
                    # A targeted correction ("keep this, just make her
                    # smaller") appended to the existing action text --
                    # cheaper than rewriting a field that was already
                    # mostly right, for the common case where the plan was
                    # fine and only the render missed one specific thing.
                    note = ""
                    while not note:
                        note = input("  Feedback (appended to the beat's action): ").strip()
                    beat = dataclasses.replace(beat, action=f"{beat.action} {note}")
                    beat_was_edited = True
                    return "stop"
                if choice == "g":
                    return "stop"
                return "continue"

            # Default-argument bindings, not closures over the loop
            # variables directly: `_generate` is redefined fresh each
            # while-loop iteration specifically so an (e)dited `beat`
            # takes effect on the next attempt -- these defaults capture
            # each variable's *current* value at definition time, which is
            # exactly what's wanted, but spelling it as a bare closure
            # over loop variables is a real footgun ruff correctly flags
            # (B023) even though this particular control flow is safe.
            def _generate(
                previous_concerns: list[str],
                candidates: int = candidates,
                beat: Beat = beat,
                location: Location | None = location,
                location_ref: Path | None = location_ref,
                beat_out_dir: Path = beat_out_dir,
                beat_characters: list = beat_characters,
                beat_character_refs: list = beat_character_refs,
            ) -> PrevizResult:
                nonlocal attempt_n
                attempt_n += 1
                cap = f"/{_MAX_PREVIZ_ATTEMPTS}" if auto_yes else ""
                print(
                    f"--- beat image (model: {previz_model}, "
                    f"attempt {attempt_n}{cap}) ---"
                )
                corrected = _beat_with_review_corrections(beat, previous_concerns)
                # One call per candidate. Gemini's image API has no n>1
                # parameter via litellm, so the fan-out lives here rather
                # than in the provider call (docs/decisions/0046).
                return [
                    run_beat_image_stage(
                        corrected,
                        characters=beat_characters,
                        location=location,
                        character_references=beat_character_refs,
                        location_reference=location_ref,
                        style=style,
                        model=previz_model,
                        output_dir=beat_out_dir,
                        filename=(
                            "previz.png"
                            if candidates == 1
                            else f"candidate_{attempt_n}_{n}.png"
                        ),
                        on_transient_retry=lambda n, exc: print(
                            f"Transient error ({exc}) -- retrying (attempt {n + 1})..."
                        ),
                        **image_kwargs,
                    )
                    for n in range(1, candidates + 1)
                ]

            previz_result, attempts = _generate_image_with_review(
                _generate,
                fact_check_result,
                review_model=review_model,
                # docs/decisions/0032: character/beat are already
                # scene-plan-approved -- previz_review shouldn't re-derive
                # their plausibility from scratch on every attempt.
                review_kwargs={
                    **review_kwargs,
                    "characters": beat_characters,
                    "beat": beat,
                    "requires_grounding": requires_grounding,
                },
                out_dir=beat_out_dir,
                archive_prefix=f"beat{i}_attempt",
                on_reviewed=_on_reviewed,
                initial_concerns=carried_concerns,
                choose_auto=auto_yes,
                max_attempts=_MAX_PREVIZ_ATTEMPTS if auto_yes else None,
            )

            if previz_result is None:
                if beat_was_edited:
                    continue  # human edited the beat -- restart a fresh attempt cycle
                _record(
                    {
                        "index": i,
                        "beat": dataclasses.asdict(beat),
                        "image_path": None,
                        "attempts": attempts,
                    }
                )
                break  # every automatic attempt was rejected, or the human gave up on this beat

            # A returned result means the human already chose to keep it at
            # the single review prompt (docs/decisions/0043). Asking
            # accept/reroll/edit again here was the same question twice.
            print("Beat accepted.")
            _link_beat_into_gallery(out_dir, i, str(previz_result.image_path))
            _record(
                {
                    "index": i,
                    "beat": dataclasses.asdict(beat),
                    "image_path": str(previz_result.image_path),
                    # The actual prompt sent to the image model for the
                    # accepted attempt -- video generation (the
                    # --video-gen-from follow-up to docs/decisions/0024)
                    # needs this alongside the image itself, the same way
                    # the old single-image flow paired previz_image_path
                    # with previz_prompt_used.
                    "prompt_used": previz_result.prompt_used,
                    "attempts": attempts,
                }
            )
            break

    return beat_results


def _beat_gallery_dir(out_dir: Path) -> Path:
    """Create (if needed) and return this run's flat `all_beats/` folder --
    clicking through `beat_1/`, `beat_2/`, ... individually to review a
    run's images was real, reported friction. Called as early as possible
    (right when `out_dir` itself is created), not only after beat
    generation finishes, since the project owner reported restarting runs
    often -- a folder that only appears at the very end is useless to
    someone who never reaches the end.
    """
    gallery_dir = out_dir / "all_beats"
    gallery_dir.mkdir(exist_ok=True)
    return gallery_dir


def _link_beat_into_gallery(out_dir: Path, index: int, image_path: str) -> None:
    """Symlink one beat's accepted image into `_beat_gallery_dir(out_dir)`,
    named by beat index. Called immediately once a beat's image is
    finalized (both the override-accept and normal-accept paths), not
    batched until the whole run finishes -- same reasoning as
    `_beat_gallery_dir`. Symlinks rather than copies, per the project
    owner's own correction: same one-folder browsing convenience with no
    extra disk space, and macOS Finder/Preview/Quick Look all follow them
    transparently. Relative targets so the links stay valid if the whole
    run folder (or all of `outputs/`) is later moved or copied elsewhere
    as a unit.
    """
    gallery_dir = _beat_gallery_dir(out_dir)
    source = Path(image_path)
    link = gallery_dir / f"beat_{index}{source.suffix}"
    link.unlink(missing_ok=True)  # re-running against the same out_dir shouldn't fail
    link.symlink_to(os.path.relpath(source, start=gallery_dir))


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
        type=float,
        help=(
            "Requested clip duration in seconds (only used with "
            "--video-gen-from). The video model accepts a narrow range "
            f"({MIN_VIDEO_SECONDS:.2f}-{MAX_VIDEO_SECONDS:.2f}s); anything "
            "outside it is rejected before any API call "
            "(docs/decisions/0020, 0038). Defaults to the stage's own "
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
        "--genre",
        default="historical",
        help=(
            "What kind of scene this is -- e.g. 'historical', 'meme', "
            "'vlog', 'kids-content', 'abstract'. Free text, not a fixed "
            "list: fed into scene-planning's prompt to inform staging and "
            "convention choices (docs/decisions/0035). Only 'historical' "
            "(the default) requires real-world grounding -- every other "
            "value skips research and fact-check entirely and drops the "
            "historical-accuracy framing from scene-planning and "
            "previz_review's prompts, since that framing is actively "
            "wrong (not just unhelpful overhead) for a scene that was "
            "never claiming to be real. Scene planning's plan-fidelity "
            "check (does the image match what was planned) still applies "
            "regardless of genre."
        ),
    )
    parser.add_argument(
        "--tone",
        default=None,
        help=(
            "The scene's tone -- e.g. 'comedic', 'ironic', 'sincere', "
            "'dramatic', 'wholesome'. Free text, fed into scene-planning's "
            "prompt to inform staging, expression, and wardrobe choices. "
            "Unset means the model infers tone from the description alone, "
            "same as before this flag existed."
        ),
    )
    parser.add_argument(
        "--style",
        choices=sorted(STYLE_PRESETS),
        default=DEFAULT_STYLE,
        help=(
            "Art style for every reference and beat image in this run, and "
            "the ONLY thing that sets it (docs/decisions/0033, 0039). Each "
            "preset is a single committed direction -- pick one per run and "
            "vary between runs, rather than asking for several at once. "
            f"Defaults to {DEFAULT_STYLE}. Photoreal presets "
            f"({', '.join(sorted(PHOTOREAL_STYLES))}) are supported but "
            "measurably more likely to have violent scenes silently refused "
            "by the image model -- see docs/playbook/failure-taxonomy.md."
        ),
    )
    parser.add_argument(
        "--references",
        choices=["both", "location", "character", "none"],
        default="both",
        help=(
            "Which reference images to condition beats on (docs/decisions/0024, 0047). "
            "'both' is the previous behaviour. 'none' generates no references at all and "
            "relies on the character and location text already present in every beat "
            "prompt. The middle options exist because the two references may not be "
            "earning their keep equally: a location reference was introduced to stop "
            "cross-beat setting drift, and a character reference to hold identity, but "
            "both also pin composition."
        ),
    )
    parser.add_argument(
        "--candidates",
        type=int,
        default=1,
        metavar="N",
        help=(
            "Generate N images per beat attempt and choose between them, "
            "instead of one at a time (docs/decisions/0046). A real run "
            "already spent 1.8 images per beat sequentially, discarding each "
            "before seeing the next -- this costs about the same and lets you "
            "pick. Defaults to 1, which is the previous behaviour."
        ),
    )
    parser.add_argument(
        "--max-beats",
        type=int,
        help=(
            "Cap the scene-planning stage at this many beats -- passed to "
            "the model as a soft target and enforced afterward by "
            "truncation, so the cost-control guarantee doesn't depend on "
            "the model honoring the instruction. Useful while iterating "
            "on image/video quality, to keep a run's image-generation "
            "spend small (e.g. 3-5 instead of a full 10+ beat scene). "
            "Unset means no cap, the model's own judgment decides."
        ),
    )
    parser.add_argument(
        "--max-references",
        type=int,
        help=(
            "Cap characters + locations combined -- these, not beats, set "
            "a run's real minimum image cost (one reference image each, "
            "before a single beat generates). Same soft-target-plus-"
            "enforcement idea as --max-beats, but the enforcement is "
            "best-effort, not guaranteed: only references no beat actually "
            "uses get dropped, so a scene where every character/location "
            "is genuinely in use may still land over this number -- see "
            "the printed cost estimate before confirming either way."
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
            video_seconds=args.video_seconds,
            video_prompt=args.video_prompt,
        )
        return

    completion_kwargs = {"completion_fn": _mock_completion} if args.mock else {}
    # run_reference_image_stage never conditions on other references (it's
    # plain text-to-image), so it only ever takes image_fn -- edit_fn is
    # for run_beat_image_stage specifically, which does condition on
    # character/location references.
    image_kwargs = {"image_fn": _mock_image} if args.mock else {}
    beat_image_kwargs = (
        {"image_fn": _mock_image, "edit_fn": _mock_image_edit} if args.mock else {}
    )
    review_kwargs = {"completion_fn": _mock_review_completion} if args.mock else {}
    scene_planning_kwargs = (
        {"completion_fn": _mock_scene_planning_completion} if args.mock else {}
    )

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
        _beat_gallery_dir(out_dir)  # exists from the very start -- see its own docstring
        log = {"time": time, "place": place, "description": description, "mock": args.mock}
        log["fixture"] = str(args.fixture)
        # A fixture is always a replay of a previously completed *real*
        # research + fact-check run -- --genre didn't exist when it was
        # captured, and there's nothing to un-ground.
        requires_grounding = True
        log["genre"] = "historical"
        log["tone"] = args.tone

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
        _beat_gallery_dir(out_dir)  # exists from the very start -- see its own docstring
        log = {"time": time, "place": place, "description": description, "mock": args.mock}
        # docs/decisions/0035: genre, not a binary flag, is what determines
        # this -- "historical" (the default) is the only value that needs
        # real-world grounding; every other genre skips it.
        requires_grounding = args.genre.strip().lower() == "historical"
        log["genre"] = args.genre
        log["tone"] = args.tone
        log["requires_grounding"] = requires_grounding

        if not requires_grounding:
            # docs/decisions/0034/0035: skip research + fact-check entirely
            # -- a scene that was never claiming to be real gets no value
            # from historical-accuracy machinery, and the machinery's own
            # framing (premise conflicts, "verified claims") is actively
            # wrong for it, not just unhelpful overhead.
            print(f"\n--genre {args.genre!r}: skipping research and fact-check.")
            fact_sheet = FactSheet(time=time, place=place, description=description, claims=[])
            fact_check_result = FactCheckResult(fact_sheet=fact_sheet)
        else:
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
    fact_sheet, fact_check_result, resolution_type = resolved

    if original_premise_conflict is not None:
        log["premise_conflict_resolved_with_description"] = fact_sheet.description
        log["premise_conflict_resolution"] = resolution_type
    # docs/decisions/0027: re-written from the *resolved* state, not left
    # as the stale pre-resolution snapshot from before _resolve_premise_
    # conflict ran -- otherwise a --fixture replay of this exact run would
    # reconstruct a still-open conflict and immediately re-trip previz's
    # hard-refuse check, regardless of how this run actually resolved it.
    log["premise_conflict"] = (
        dataclasses.asdict(fact_check_result.premise_conflict)
        if fact_check_result.premise_conflict
        else None
    )
    log["acknowledged_fiction"] = fact_check_result.acknowledged_fiction
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

    # Wording (and whether to ask at all) depends on whether there's
    # actually a fact-check result to confirm -- a genre that skipped
    # research/fact-check entirely (requires_grounding=False) has nothing
    # here worth a human decision on; asking "proceed with this
    # fact-check result?" for a scene that was never fact-checked is a
    # confusing, pointless confirm, not a real checkpoint.
    if requires_grounding and not _confirm(
        "\nProceed to scene planning with this fact-check result?", auto_yes=args.yes
    ):
        print(f"Stopped by user. Run artifacts saved in {out_dir}")
        return

    # Scene planning (docs/decisions/0023): characters, locations, and
    # beats, planned and reviewed before any image generation. Not yet
    # wired into previz's actual generation calls -- that's
    # docs/decisions/0024. previz below still runs from fact_check_result
    # alone, same as before this stage existed.
    scene_planning_model = get_stage_model("scene_planning")
    log["scene_planning_model"] = scene_planning_model
    print(f"\n--- scene planning (model: {scene_planning_model}) ---")
    scene_plan = run_scene_planning_stage(
        fact_check_result,
        model=scene_planning_model,
        max_beats=args.max_beats,
        max_references=args.max_references,
        requires_grounding=requires_grounding,
        genre=args.genre,
        tone=args.tone,
        **scene_planning_kwargs,
    )
    log["scene_plan"] = dataclasses.asdict(scene_plan)
    _write_log(out_dir, log)

    scene_plan = _review_scene_plan(scene_plan, auto_yes=args.yes)
    log["scene_plan"] = dataclasses.asdict(scene_plan)
    _write_log(out_dir, log)

    previz_model = get_stage_model("previz")
    review_model = get_stage_model("previz_review")
    log["previz_model"] = previz_model
    log["previz_review_model"] = review_model

    # Cost visibility (docs/decisions/0024) -- a real, checked range, not a
    # guess: minimum is one image per reference plus one per beat; maximum
    # accounts for every beat needing all _MAX_PREVIZ_ATTEMPTS review
    # attempts. Rerolls/edits from the human choices below aren't counted
    # here since they're open-ended by nature -- this is the floor and the
    # automatic-review ceiling, not an absolute cap.
    # Counts only the references this run will actually generate, and the
    # candidates each beat attempt will actually cost. Both were previously
    # ignored here, so the figure a human confirmed against could be several
    # times under the real spend.
    num_references = (len(scene_plan.characters) if args.references in ("both", "character") else 0) + (
        len(scene_plan.locations) if args.references in ("both", "location") else 0
    )
    num_beats = len(scene_plan.beats)
    per_attempt = num_beats * args.candidates
    min_images = num_references + per_attempt
    max_images = num_references + per_attempt * _MAX_PREVIZ_ATTEMPTS
    candidate_note = f" x {args.candidates} candidates" if args.candidates > 1 else ""
    print(
        f"\nThis scene plan needs {num_references} reference image(s) + {num_beats} beat "
        f"image(s){candidate_note} = {min_images} previz image(s) minimum "
        f"({_estimate_image_cost(previz_model, min_images)}), up to {max_images} if every "
        f"beat needs all {_MAX_PREVIZ_ATTEMPTS} automatic review attempts "
        f"({_estimate_image_cost(previz_model, max_images)})."
    )
    if not _confirm("Proceed with reference and beat image generation?", auto_yes=args.yes):
        log["stopped_reason"] = "declined_before_image_generation"
        _write_log(out_dir, log)
        print(f"Stopped by user. Run artifacts saved in {out_dir}")
        return

    if args.candidates < 1:
        print(f"--candidates must be at least 1, got {args.candidates}.")
        return

    character_refs, location_refs = _generate_scene_references(
        scene_plan,
        previz_model=previz_model,
        image_kwargs=image_kwargs,
        out_dir=out_dir,
        style=args.style,
        auto_yes=args.yes,
        want_character=args.references in ("both", "character"),
        want_location=args.references in ("both", "location"),
    )
    if args.references != "both":
        print(
            f"\n--references {args.references}: beats will be conditioned on "
            + (
                "no reference images at all."
                if args.references == "none"
                else f"the {args.references} reference only."
            )
        )
    log["character_references"] = {k: str(v) for k, v in character_refs.items()}
    log["location_references"] = {k: str(v) for k, v in location_refs.items()}
    _write_log(out_dir, log)

    def _persist_beats(results: list[dict]) -> None:
        """Write the log after every finished beat, so an interrupted run
        still has a record of what it already produced and paid for."""
        log["previz_beats"] = results
        _write_log(out_dir, log)

    beat_results = _generate_beats_with_choices(
        scene_plan,
        fact_check_result,
        character_refs=character_refs,
        location_refs=location_refs,
        previz_model=previz_model,
        review_model=review_model,
        image_kwargs=beat_image_kwargs,
        review_kwargs=review_kwargs,
        out_dir=out_dir,
        style=args.style,
        requires_grounding=requires_grounding,
        auto_yes=args.yes,
        candidates=args.candidates,
        on_beat_complete=_persist_beats,
    )
    _persist_beats(beat_results)
    # Gallery is already fully populated by this point -- each beat was
    # linked in immediately on acceptance (_link_beat_into_gallery), not
    # batched here at the end.

    accepted = sum(1 for b in beat_results if b["image_path"] is not None)
    print(f"\nDone: {accepted}/{len(beat_results)} beat(s) produced an accepted image.")
    print(f"Run artifacts saved in {out_dir}")
    print(f"All accepted beat images linked in {out_dir / 'all_beats'}")


if __name__ == "__main__":
    main()
