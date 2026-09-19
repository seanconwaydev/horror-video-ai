"""Research, fact-check, and the refusal path (cli/research_flow.py).

Split out of test_cli.py alongside the module itself. Two things here are
policy rather than mechanics and are worth reading as such: --yes accepts
an "uncertain" flag but refuses a "contradicted" one
(docs/decisions/0019), and a premise conflict is never auto-resolved
(docs/decisions/0008).
"""

import json
from types import SimpleNamespace

import pytest

from historical_video_ai.cli.research_flow import (
    resolve_flags,
    resolve_premise_conflict,
    run_research_and_fact_check,
)
from historical_video_ai.stages.fact_check import ClaimFlag, FactCheckResult, PremiseConflict
from historical_video_ai.stages.research import Claim, FactSheet


def _fact_sheet_with_two_claims() -> FactSheet:
    return FactSheet(
        time="December 1903",
        place="Kitty Hawk, North Carolina",
        description="watches a flying machine lift off from the dunes.",
        claims=[
            Claim(text="Claim A", source="Source A"),
            Claim(text="Claim B", source="Source B"),
        ],
    )


def test_resolve_flags_auto_yes_accepts_uncertain_flags_without_calling_input(monkeypatch):
    def _explode(_prompt):
        raise AssertionError("input() should not be called under auto_yes")

    monkeypatch.setattr("builtins.input", _explode)
    fact_sheet = _fact_sheet_with_two_claims()
    flags = [
        ClaimFlag(claim_text="Claim A", concern="Might be off.", severity="uncertain"),
        ClaimFlag(claim_text="Claim B", concern="Also might be off.", severity="uncertain"),
    ]

    resolved = resolve_flags(fact_sheet, flags, auto_yes=True)

    assert resolved.claims == fact_sheet.claims


def test_resolve_flags_auto_yes_stops_on_a_contradicted_flag(monkeypatch):
    # A "contradicted" flag means fact-check asserts a specific competing
    # fact, not just soft doubt -- --yes must not blind-accept that (a real
    # run did exactly this once; the flag happened to itself be a
    # fact-check false positive, but --yes had no way to know that either
    # way). See docs/decisions/0019.
    def _explode(_prompt):
        raise AssertionError("input() should not be called under auto_yes")

    monkeypatch.setattr("builtins.input", _explode)
    fact_sheet = _fact_sheet_with_two_claims()
    flags = [
        ClaimFlag(claim_text="Claim A", concern="Might be off.", severity="uncertain"),
        ClaimFlag(claim_text="Claim B", concern="Actually wrong.", severity="contradicted"),
    ]

    resolved = resolve_flags(fact_sheet, flags, auto_yes=True)

    assert resolved is None


def test_resolve_flags_returns_same_fact_sheet_when_no_flags():
    fact_sheet = _fact_sheet_with_two_claims()

    resolved = resolve_flags(fact_sheet, [])

    assert resolved is fact_sheet


def test_resolve_flags_accept_keeps_claim_unchanged(monkeypatch):
    fact_sheet = _fact_sheet_with_two_claims()
    flags = [ClaimFlag(claim_text="Claim A", concern="Might be off.", severity="uncertain")]
    monkeypatch.setattr("builtins.input", lambda _: "a")

    resolved = resolve_flags(fact_sheet, flags)

    assert resolved.claims == fact_sheet.claims


def test_resolve_flags_cut_removes_the_claim(monkeypatch):
    fact_sheet = _fact_sheet_with_two_claims()
    flags = [ClaimFlag(claim_text="Claim A", concern="Wrong.", severity="contradicted")]
    monkeypatch.setattr("builtins.input", lambda _: "c")

    resolved = resolve_flags(fact_sheet, flags)

    assert [c.text for c in resolved.claims] == ["Claim B"]


def test_resolve_flags_soften_replaces_claim_text_only(monkeypatch):
    fact_sheet = _fact_sheet_with_two_claims()
    flags = [ClaimFlag(claim_text="Claim A", concern="Too strong.", severity="uncertain")]
    responses = iter(["s", "A softened version of claim A"])
    monkeypatch.setattr("builtins.input", lambda _: next(responses))

    resolved = resolve_flags(fact_sheet, flags)

    resolved_a = next(c for c in resolved.claims if c is not resolved.claims[1])
    assert resolved_a.text == "A softened version of claim A"
    assert resolved_a.source == "Source A"  # only text changes, not the rest of the claim
    assert resolved.claims[1].text == "Claim B"


def test_resolve_flags_cut_does_not_affect_an_unflagged_claim_with_identical_text(monkeypatch):
    # Regression test: nothing upstream prevents two distinct claims from
    # sharing identical text. Cutting the flagged one must not silently
    # remove an unflagged claim that merely happens to match by text.
    fact_sheet = FactSheet(
        time="December 1903",
        place="Kitty Hawk, North Carolina",
        description="watches a flying machine lift off from the dunes.",
        claims=[
            Claim(text="Duplicate text", source="Source A"),
            Claim(text="Duplicate text", source="Source B"),
        ],
    )
    flags = [ClaimFlag(claim_text="Duplicate text", concern="Wrong.", severity="contradicted")]
    monkeypatch.setattr("builtins.input", lambda _: "c")

    resolved = resolve_flags(fact_sheet, flags)

    assert len(resolved.claims) == 1
    assert resolved.claims[0].source == "Source B"


def test_resolve_flags_reprompts_on_invalid_action(monkeypatch):
    fact_sheet = _fact_sheet_with_two_claims()
    flags = [ClaimFlag(claim_text="Claim A", concern="Wrong.", severity="contradicted")]
    responses = iter(["x", "c"])  # invalid choice, then a valid one
    monkeypatch.setattr("builtins.input", lambda _: next(responses))

    resolved = resolve_flags(fact_sheet, flags)

    assert [c.text for c in resolved.claims] == ["Claim B"]


def _fake_reverify_completion(fact_check_payload=None):
    """Stand-in for a real research + fact-check re-verification pass: the
    research call returns one clean claim, the fact-check call returns
    fact_check_payload (defaulting to clean -- no flags, no conflict)."""

    def _completion(**kwargs):
        prompt = kwargs["messages"][0]["content"]
        if "Claims to check" in prompt:
            content = json.dumps(fact_check_payload or {"flags": [], "premise_conflict": None})
        else:
            content = json.dumps(
                {
                    "claims": [
                        {
                            "text": "A newly researched claim for the corrected scene.",
                            "source": "Some source",
                            "date": None,
                        }
                    ]
                }
            )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )

    return _completion


def _premise_conflict_fact_check_result(suggested_alternative) -> FactCheckResult:
    return FactCheckResult(
        fact_sheet=_fact_sheet_with_two_claims(),
        premise_conflict=PremiseConflict(
            explanation="This depicts something that didn't exist yet.",
            suggested_alternative=suggested_alternative,
        ),
    )


def _resolve_premise_conflict_kwargs(completion_fn):
    return {
        "time": "December 1903",
        "place": "Kitty Hawk, North Carolina",
        "research_model": "anthropic/claude-sonnet-5",
        "fact_check_model": "anthropic/claude-sonnet-5",
        "completion_kwargs": {"completion_fn": completion_fn},
    }


def test_run_research_and_fact_check_skips_research_when_fact_sheet_given(monkeypatch):
    # Resuming a research-only fixture (docs/decisions/0015/0018): research
    # is already known, so this should jump straight to fact-check without
    # calling run_research_stage (which would need a real research call).
    monkeypatch.setattr("builtins.input", lambda _: "y")  # "Proceed to fact-check?"
    existing_fact_sheet = _fact_sheet_with_two_claims()
    research_calls = []

    def _completion(**kwargs):
        research_calls.append(kwargs["messages"][0]["content"])
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"flags": []})))]
        )

    result = run_research_and_fact_check(
        existing_fact_sheet.time,
        existing_fact_sheet.place,
        existing_fact_sheet.description,
        research_model="anthropic/claude-sonnet-5",
        fact_check_model="anthropic/claude-sonnet-5",
        completion_kwargs={"completion_fn": _completion},
        fact_sheet=existing_fact_sheet,
    )

    assert result is not None
    new_fact_sheet, fact_check_result = result
    assert new_fact_sheet is existing_fact_sheet
    assert fact_check_result.flags == []
    # Only one completion call happened -- fact-check's -- not a research one.
    assert len(research_calls) == 1
    assert "Claims to check" in research_calls[0]


def test_run_research_and_fact_check_calls_on_research_completed_before_fact_check(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "y")  # "Proceed to fact-check?"
    calls = []

    result = run_research_and_fact_check(
        "December 1903",
        "Kitty Hawk, North Carolina",
        "A man watches a flying machine lift off from the dunes.",
        research_model="anthropic/claude-sonnet-5",
        fact_check_model="anthropic/claude-sonnet-5",
        completion_kwargs={"completion_fn": _fake_reverify_completion()},
        on_research_completed=calls.append,
    )

    assert result is not None
    assert len(calls) == 1
    assert calls[0].claims[0].text == "A newly researched claim for the corrected scene."


def test_run_research_and_fact_check_on_research_completed_survives_a_fact_check_crash(
    monkeypatch,
):
    # Regression test: research succeeding, then fact-check's own response
    # parsing crashing, used to mean the research output was never
    # persisted anywhere -- on_research_completed must still fire for it.
    monkeypatch.setattr("builtins.input", lambda _: "y")
    calls = []

    def _crashing_fact_check(**kwargs):
        prompt = kwargs["messages"][0]["content"]
        if "Claims to check" in prompt:
            raise RuntimeError("simulated fact-check crash")
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(
                            {
                                "claims": [
                                    {
                                        "text": "A claim from research.",
                                        "source": "A source",
                                        "date": None,
                                    }
                                ]
                            }
                        )
                    )
                )
            ]
        )

    with pytest.raises(RuntimeError, match="simulated fact-check crash"):
        run_research_and_fact_check(
            "December 1903",
            "Kitty Hawk, North Carolina",
            "A man watches a flying machine lift off from the dunes.",
            research_model="anthropic/claude-sonnet-5",
            fact_check_model="anthropic/claude-sonnet-5",
            completion_kwargs={"completion_fn": _crashing_fact_check},
            on_research_completed=calls.append,
        )

    assert len(calls) == 1
    assert calls[0].claims[0].text == "A claim from research."


def test_resolve_premise_conflict_returns_unchanged_when_no_conflict():
    fact_sheet = _fact_sheet_with_two_claims()
    fact_check_result = FactCheckResult(fact_sheet=fact_sheet)

    result = resolve_premise_conflict(
        fact_sheet, fact_check_result, **_resolve_premise_conflict_kwargs(None)
    )

    assert result == (fact_sheet, fact_check_result, None)


def test_resolve_premise_conflict_accepts_suggested_alternative_and_reverifies(monkeypatch):
    fact_check_result = _premise_conflict_fact_check_result("A close, true version of the scene.")
    responses = iter(["u", "y"])  # use suggested alternative; proceed to fact-check on reverify
    monkeypatch.setattr("builtins.input", lambda _: next(responses))

    result = resolve_premise_conflict(
        fact_check_result.fact_sheet,
        fact_check_result,
        **_resolve_premise_conflict_kwargs(_fake_reverify_completion()),
    )

    assert result is not None
    new_fact_sheet, new_fact_check_result, resolution_type = result
    assert new_fact_sheet.description == "A close, true version of the scene."
    assert new_fact_check_result.premise_conflict is None
    assert resolution_type == "corrected"


def test_resolve_premise_conflict_declines_alternative_and_provides_own(monkeypatch):
    fact_check_result = _premise_conflict_fact_check_result("A suggested version.")
    responses = iter(["o", "my own corrected description", "y"])
    monkeypatch.setattr("builtins.input", lambda _: next(responses))

    result = resolve_premise_conflict(
        fact_check_result.fact_sheet,
        fact_check_result,
        **_resolve_premise_conflict_kwargs(_fake_reverify_completion()),
    )

    assert result is not None
    new_fact_sheet, _, resolution_type = result
    assert new_fact_sheet.description == "my own corrected description"
    assert resolution_type == "corrected"


def test_resolve_premise_conflict_no_alternative_provides_own(monkeypatch):
    fact_check_result = _premise_conflict_fact_check_result(None)
    responses = iter(["o", "my own corrected description", "y"])
    monkeypatch.setattr("builtins.input", lambda _: next(responses))

    result = resolve_premise_conflict(
        fact_check_result.fact_sheet,
        fact_check_result,
        **_resolve_premise_conflict_kwargs(_fake_reverify_completion()),
    )

    assert result is not None
    new_fact_sheet, _, _ = result
    assert new_fact_sheet.description == "my own corrected description"


def test_resolve_premise_conflict_stop_declines_everything(monkeypatch):
    fact_check_result = _premise_conflict_fact_check_result("A suggested version.")
    monkeypatch.setattr("builtins.input", lambda _: "s")

    result = resolve_premise_conflict(
        fact_check_result.fact_sheet,
        fact_check_result,
        **_resolve_premise_conflict_kwargs(None),
    )

    assert result is None


def test_resolve_premise_conflict_keep_as_intentional_fiction(monkeypatch):
    # docs/decisions/0025: acknowledges the conflict and proceeds with the
    # description exactly as written, clearing premise_conflict. The
    # explanation is carried forward as acknowledged_fiction, not
    # discarded (docs/decisions/0026), so previz_review can be told about
    # it -- broadened (docs/decisions/0030) to also cover natural knock-on
    # consequences of the acknowledged premise, not just its literal text.
    fact_check_result = _premise_conflict_fact_check_result("A suggested version.")
    monkeypatch.setattr("builtins.input", lambda _: "k")

    result = resolve_premise_conflict(
        fact_check_result.fact_sheet,
        fact_check_result,
        **_resolve_premise_conflict_kwargs(None),
    )

    assert result is not None
    new_fact_sheet, new_fact_check_result, resolution_type = result
    assert new_fact_sheet.description == fact_check_result.fact_sheet.description
    assert new_fact_check_result.premise_conflict is None
    assert fact_check_result.premise_conflict.explanation in new_fact_check_result.acknowledged_fiction
    assert "knock-on" in new_fact_check_result.acknowledged_fiction
    assert resolution_type == "kept_as_intentional_fiction"


def test_resolve_premise_conflict_auto_yes_never_auto_resolves(monkeypatch):
    # --yes has no sound basis to guess between "keep as fiction" and "use
    # the corrected version" -- must stop, not silently pick one.
    def _explode(_prompt):
        raise AssertionError("input() should not be called under auto_yes")

    monkeypatch.setattr("builtins.input", _explode)
    fact_check_result = _premise_conflict_fact_check_result("A suggested version.")

    result = resolve_premise_conflict(
        fact_check_result.fact_sheet,
        fact_check_result,
        auto_yes=True,
        **_resolve_premise_conflict_kwargs(None),
    )

    assert result is None


def test_resolve_premise_conflict_stops_if_reverify_still_conflicted(monkeypatch):
    fact_check_result = _premise_conflict_fact_check_result("A suggested version.")
    responses = iter(["u", "y"])  # use alternative; proceed to fact-check on reverify
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    still_conflicted_payload = {
        "flags": [],
        "premise_conflict": {
            "explanation": "Still impossible even with the corrected description.",
            "suggested_alternative": None,
        },
    }

    result = resolve_premise_conflict(
        fact_check_result.fact_sheet,
        fact_check_result,
        **_resolve_premise_conflict_kwargs(_fake_reverify_completion(still_conflicted_payload)),
    )

    assert result is None


def test_resolve_premise_conflict_stops_if_reverify_research_declined(monkeypatch):
    fact_check_result = _premise_conflict_fact_check_result("A suggested version.")
    responses = iter(["u", "n"])  # use alternative; decline "proceed to fact-check" on reverify
    monkeypatch.setattr("builtins.input", lambda _: next(responses))

    result = resolve_premise_conflict(
        fact_check_result.fact_sheet,
        fact_check_result,
        **_resolve_premise_conflict_kwargs(_fake_reverify_completion()),
    )

    assert result is None


# --- archived attempts must never be overwritten by a later cycle ---


def _one_claim_sheet(text="Apollo 11 launched in July."):
    return FactSheet(
        time="1969",
        place="Florida",
        description="she watches",
        claims=[Claim(text=text, source="s", date="1969")],
    )


def test_two_flags_on_one_claim_ask_once_and_show_both(monkeypatch, capsys):
    """Nothing in the fact-check prompt limits a model to one concern per
    claim, and two is an ordinary answer. Resolving by matching claim_text
    consumed the claim on the first flag and then raised a bare
    StopIteration on the second -- mid-review, after the human had already
    answered one prompt."""
    fact_sheet = _one_claim_sheet()
    flags = [
        ClaimFlag(
            claim_text=fact_sheet.claims[0].text,
            concern="the date is uncertain",
            severity="uncertain",
            claim_number=1,
        ),
        ClaimFlag(
            claim_text=fact_sheet.claims[0].text,
            concern="the launch site is wrong",
            severity="uncertain",
            claim_number=1,
        ),
    ]
    answers = iter(["a"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    resolved = resolve_flags(fact_sheet, flags)

    assert [c.text for c in resolved.claims] == [fact_sheet.claims[0].text]
    out = capsys.readouterr().out
    assert "the date is uncertain" in out
    assert "the launch site is wrong" in out
    assert next(answers, None) is None, "should have asked exactly once"


def test_cutting_a_claim_with_two_flags_cuts_it_once(monkeypatch):
    fact_sheet = _one_claim_sheet()
    flags = [
        ClaimFlag(claim_text=fact_sheet.claims[0].text, concern="a", severity="uncertain", claim_number=1),
        ClaimFlag(claim_text=fact_sheet.claims[0].text, concern="b", severity="uncertain", claim_number=1),
    ]
    monkeypatch.setattr("builtins.input", lambda _prompt: "c")

    assert resolve_flags(fact_sheet, flags).claims == []


def test_flags_from_a_log_without_claim_numbers_still_resolve_by_text(monkeypatch):
    """--fixture replays a run log, and one written before claim_number
    existed reconstructs flags with claim_number 0. resolve_flags is
    called on that path too (cli/app.py), so the text fallback is load
    bearing, not decoration."""
    fact_sheet = _one_claim_sheet()
    flags = [ClaimFlag(claim_text=fact_sheet.claims[0].text, concern="a", severity="uncertain")]
    monkeypatch.setattr("builtins.input", lambda _prompt: "c")

    assert resolve_flags(fact_sheet, flags).claims == []


def test_two_same_text_claims_with_one_flag_each_resolve_independently(monkeypatch):
    """The case the old text-matching logic existed for: nothing upstream
    stops two distinct claims sharing identical text, and cutting one must
    not cut the other."""
    fact_sheet = FactSheet(
        time="t",
        place="p",
        description="d",
        claims=[Claim(text="same", source="a"), Claim(text="same", source="b")],
    )
    flags = [
        ClaimFlag(claim_text="same", concern="first", severity="uncertain"),
        ClaimFlag(claim_text="same", concern="second", severity="uncertain"),
    ]
    answers = iter(["c", "a"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    resolved = resolve_flags(fact_sheet, flags)

    assert [c.source for c in resolved.claims] == ["b"]


def test_a_flag_naming_a_missing_claim_is_reported_not_fatal(capsys):
    fact_sheet = _one_claim_sheet()
    flags = [ClaimFlag(claim_text="a claim that is not here", concern="orphan", severity="uncertain")]

    resolved = resolve_flags(fact_sheet, flags, auto_yes=True)

    assert len(resolved.claims) == 1
    assert "no longer in this fact sheet" in capsys.readouterr().out
