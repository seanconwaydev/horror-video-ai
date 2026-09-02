import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from historical_video_ai.cli import (
    _check_video_prompt_practices,
    _confirm,
    _generate_beats_with_choices,
    _generate_previz_with_review,
    _generate_scene_references,
    _load_fact_sheet_from_fixture,
    _load_fixture,
    _load_previz_output,
    _load_video_gen_targets,
    _project_root,
    _prompt_if_missing,
    _resolve_flags,
    _resolve_premise_conflict,
    _review_scene_plan,
    _run_dir,
    _run_research_and_fact_check,
    _run_video_generation_only,
    _slugify,
)
from historical_video_ai.stages.fact_check import ClaimFlag, FactCheckResult, PremiseConflict
from historical_video_ai.stages.research import Claim, FactSheet
from historical_video_ai.stages.scene_planning import Beat, Character, Location, ScenePlan

_TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _write_fixture(tmp_path, **overrides):
    payload = {
        "time": "December 1903",
        "place": "Kitty Hawk, North Carolina",
        "description": "watches a flying machine lift off from the dunes.",
        "research_claims": [
            {
                "text": "The dunes at Kitty Hawk were largely undeveloped in 1903.",
                "source": "NPS",
                "date": None,
                "names": [],
            }
        ],
        "fact_check_flags": [],
        **overrides,
    }
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(payload))
    return path


def test_load_fixture_reconstructs_fact_check_result(tmp_path):
    path = _write_fixture(tmp_path)

    result = _load_fixture(path)

    assert result == FactCheckResult(
        fact_sheet=FactSheet(
            time="December 1903",
            place="Kitty Hawk, North Carolina",
            description="watches a flying machine lift off from the dunes.",
            claims=[
                Claim(
                    text="The dunes at Kitty Hawk were largely undeveloped in 1903.",
                    source="NPS",
                )
            ],
        ),
        flags=[],
    )


def test_load_fixture_reconstructs_flags(tmp_path):
    path = _write_fixture(
        tmp_path,
        fact_check_flags=[
            {
                "claim_text": "The dunes at Kitty Hawk were largely undeveloped in 1903.",
                "concern": "Source doesn't specifically support 'largely'.",
                "severity": "uncertain",
            }
        ],
    )

    result = _load_fixture(path)

    assert result.flags == [
        ClaimFlag(
            claim_text="The dunes at Kitty Hawk were largely undeveloped in 1903.",
            concern="Source doesn't specifically support 'largely'.",
            severity="uncertain",
        )
    ]


def test_load_fact_sheet_from_fixture_works_without_fact_check_flags(tmp_path):
    # Regression test: a fixture saved after a real fact-check-stage crash
    # has research but no "fact_check_flags" key at all (docs/decisions/
    # 0015 persists research before fact-check runs) -- this must still
    # load, unlike _load_fixture which requires a completed fact-check.
    payload = {
        "time": "December 1903",
        "place": "Kitty Hawk, North Carolina",
        "description": "watches a flying machine lift off from the dunes.",
        "research_claims": [
            {"text": "A claim.", "source": "A source", "date": None, "names": []}
        ],
    }
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(payload))

    fact_sheet = _load_fact_sheet_from_fixture(path)

    assert fact_sheet.time == "December 1903"
    assert fact_sheet.claims == [Claim(text="A claim.", source="A source")]


@pytest.mark.parametrize("missing_field", ["time", "place", "description"])
def test_load_fixture_raises_for_empty_required_field(tmp_path, missing_field):
    path = _write_fixture(tmp_path, **{missing_field: ""})

    with pytest.raises(ValueError, match=missing_field):
        _load_fixture(path)


def test_load_fixture_reconstructs_premise_conflict(tmp_path):
    path = _write_fixture(
        tmp_path,
        premise_conflict={
            "explanation": "Nothing like this existed yet.",
            "suggested_alternative": "A close, true version.",
        },
    )

    result = _load_fixture(path)

    assert result.premise_conflict == PremiseConflict(
        explanation="Nothing like this existed yet.",
        suggested_alternative="A close, true version.",
    )


def test_load_fixture_defaults_premise_conflict_to_none_when_absent(tmp_path):
    path = _write_fixture(tmp_path)

    result = _load_fixture(path)

    assert result.premise_conflict is None


def test_load_fixture_reconstructs_acknowledged_fiction(tmp_path):
    # docs/decisions/0027: a fixture saved after a scene was kept as
    # intentional fiction must round-trip that decision back out, not
    # just the (by-then-null) premise_conflict.
    path = _write_fixture(
        tmp_path,
        premise_conflict=None,
        acknowledged_fiction="A smartphone did not exist in 79 AD.",
    )

    result = _load_fixture(path)

    assert result.premise_conflict is None
    assert result.acknowledged_fiction == "A smartphone did not exist in 79 AD."


def test_load_fixture_defaults_acknowledged_fiction_to_none_when_absent(tmp_path):
    # A fixture saved before 0027 won't have this key at all.
    path = _write_fixture(tmp_path)

    result = _load_fixture(path)

    assert result.acknowledged_fiction is None


def test_load_fixture_raises_when_flag_claim_text_does_not_match(tmp_path):
    path = _write_fixture(
        tmp_path,
        fact_check_flags=[
            {
                "claim_text": "The dunes at Kitty Hawk were largely undeveloped in 1903. "
                "(date: null) [source: NPS]",
                "concern": "Paraphrased instead of copied verbatim.",
                "severity": "uncertain",
            }
        ],
    )

    with pytest.raises(ValueError, match="doesn't exactly match any research claim"):
        _load_fixture(path)


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


def test_confirm_auto_yes_returns_true_without_calling_input(monkeypatch):
    def _explode(_prompt):
        raise AssertionError("input() should not be called under auto_yes")

    monkeypatch.setattr("builtins.input", _explode)

    assert _confirm("Proceed?", auto_yes=True) is True


def test_prompt_if_missing_auto_yes_raises_on_empty_value():
    with pytest.raises(ValueError, match="Time is required"):
        _prompt_if_missing(None, "Time", auto_yes=True)


def test_prompt_if_missing_auto_yes_passes_through_a_given_value():
    # auto_yes only matters when the value is missing -- an already-given
    # value (e.g. from a CLI flag) is returned as-is.
    assert _prompt_if_missing("July 1969", "Time", auto_yes=True) == "July 1969"


def test_resolve_flags_auto_yes_accepts_uncertain_flags_without_calling_input(monkeypatch):
    def _explode(_prompt):
        raise AssertionError("input() should not be called under auto_yes")

    monkeypatch.setattr("builtins.input", _explode)
    fact_sheet = _fact_sheet_with_two_claims()
    flags = [
        ClaimFlag(claim_text="Claim A", concern="Might be off.", severity="uncertain"),
        ClaimFlag(claim_text="Claim B", concern="Also might be off.", severity="uncertain"),
    ]

    resolved = _resolve_flags(fact_sheet, flags, auto_yes=True)

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

    resolved = _resolve_flags(fact_sheet, flags, auto_yes=True)

    assert resolved is None


def test_resolve_flags_returns_same_fact_sheet_when_no_flags():
    fact_sheet = _fact_sheet_with_two_claims()

    resolved = _resolve_flags(fact_sheet, [])

    assert resolved is fact_sheet


def test_resolve_flags_accept_keeps_claim_unchanged(monkeypatch):
    fact_sheet = _fact_sheet_with_two_claims()
    flags = [ClaimFlag(claim_text="Claim A", concern="Might be off.", severity="uncertain")]
    monkeypatch.setattr("builtins.input", lambda _: "a")

    resolved = _resolve_flags(fact_sheet, flags)

    assert resolved.claims == fact_sheet.claims


def test_resolve_flags_cut_removes_the_claim(monkeypatch):
    fact_sheet = _fact_sheet_with_two_claims()
    flags = [ClaimFlag(claim_text="Claim A", concern="Wrong.", severity="contradicted")]
    monkeypatch.setattr("builtins.input", lambda _: "c")

    resolved = _resolve_flags(fact_sheet, flags)

    assert [c.text for c in resolved.claims] == ["Claim B"]


def test_resolve_flags_soften_replaces_claim_text_only(monkeypatch):
    fact_sheet = _fact_sheet_with_two_claims()
    flags = [ClaimFlag(claim_text="Claim A", concern="Too strong.", severity="uncertain")]
    responses = iter(["s", "A softened version of claim A"])
    monkeypatch.setattr("builtins.input", lambda _: next(responses))

    resolved = _resolve_flags(fact_sheet, flags)

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

    resolved = _resolve_flags(fact_sheet, flags)

    assert len(resolved.claims) == 1
    assert resolved.claims[0].source == "Source B"


def test_resolve_flags_reprompts_on_invalid_action(monkeypatch):
    fact_sheet = _fact_sheet_with_two_claims()
    flags = [ClaimFlag(claim_text="Claim A", concern="Wrong.", severity="contradicted")]
    responses = iter(["x", "c"])  # invalid choice, then a valid one
    monkeypatch.setattr("builtins.input", lambda _: next(responses))

    resolved = _resolve_flags(fact_sheet, flags)

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
                            "names": [],
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

    result = _run_research_and_fact_check(
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

    result = _run_research_and_fact_check(
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
                                        "names": [],
                                    }
                                ]
                            }
                        )
                    )
                )
            ]
        )

    with pytest.raises(RuntimeError, match="simulated fact-check crash"):
        _run_research_and_fact_check(
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

    result = _resolve_premise_conflict(
        fact_sheet, fact_check_result, **_resolve_premise_conflict_kwargs(None)
    )

    assert result == (fact_sheet, fact_check_result, None)


def test_resolve_premise_conflict_accepts_suggested_alternative_and_reverifies(monkeypatch):
    fact_check_result = _premise_conflict_fact_check_result("A close, true version of the scene.")
    responses = iter(["u", "y"])  # use suggested alternative; proceed to fact-check on reverify
    monkeypatch.setattr("builtins.input", lambda _: next(responses))

    result = _resolve_premise_conflict(
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

    result = _resolve_premise_conflict(
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

    result = _resolve_premise_conflict(
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

    result = _resolve_premise_conflict(
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

    result = _resolve_premise_conflict(
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

    result = _resolve_premise_conflict(
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

    result = _resolve_premise_conflict(
        fact_check_result.fact_sheet,
        fact_check_result,
        **_resolve_premise_conflict_kwargs(_fake_reverify_completion(still_conflicted_payload)),
    )

    assert result is None


def _fact_check_result_for_previz() -> FactCheckResult:
    return FactCheckResult(fact_sheet=_fact_sheet_with_two_claims())


def _fake_image_fn(**kwargs):
    return SimpleNamespace(data=[SimpleNamespace(b64_json=_TINY_PNG_B64)])


def _fake_review_completion(verdicts):
    """verdicts: list of (accepted, concern) tuples, one per call, in order."""
    responses = iter(verdicts)

    def _completion(**kwargs):
        accepted, concern = next(responses)
        content = json.dumps({"accepted": accepted, "concern": concern})
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )

    return _completion


def _generate_previz_with_review_kwargs(review_completion_fn, out_dir):
    return {
        "previz_model": "openai/gpt-image-1-mini",
        "review_model": "anthropic/claude-sonnet-5",
        "image_kwargs": {"image_fn": _fake_image_fn},
        "review_kwargs": {"completion_fn": review_completion_fn},
        "out_dir": out_dir,
    }


def test_generate_previz_with_review_accepts_on_first_attempt(tmp_path):
    result, attempts = _generate_previz_with_review(
        _fact_check_result_for_previz(),
        **_generate_previz_with_review_kwargs(_fake_review_completion([(True, None)]), tmp_path),
    )

    assert result is not None
    assert result.image_path == tmp_path / "previz.png"
    assert attempts == [{"attempt": 1, "accepted": True, "concern": None}]


def test_generate_previz_with_review_retries_then_accepts(tmp_path):
    verdicts = [(False, "Depicts something anachronistic."), (True, None)]

    result, attempts = _generate_previz_with_review(
        _fact_check_result_for_previz(),
        **_generate_previz_with_review_kwargs(_fake_review_completion(verdicts), tmp_path),
    )

    assert result is not None
    assert result.image_path == tmp_path / "previz.png"
    # the rejected first attempt was archived, not left at previz.png or lost
    assert (tmp_path / "previz_attempt_1_rejected.png").exists()
    assert [a["accepted"] for a in attempts] == [False, True]


def test_generate_previz_with_review_gives_up_after_max_attempts(tmp_path):
    verdicts = [(False, "Wrong.")] * 3

    result, attempts = _generate_previz_with_review(
        _fact_check_result_for_previz(),
        **_generate_previz_with_review_kwargs(_fake_review_completion(verdicts), tmp_path),
    )

    assert result is None
    assert len(attempts) == 3
    assert all(not a["accepted"] for a in attempts)
    # every rejected attempt archived, no final previz.png left behind
    for n in (1, 2, 3):
        assert (tmp_path / f"previz_attempt_{n}_rejected.png").exists()


def _character() -> Character:
    return Character(
        id="influencer",
        face_build="young woman, mid-20s",
        hair="light brown wavy",
        wardrobe_signature="white crop top, gray leggings",
        wardrobe_flexible="accessories may vary",
        distinguishing_detail="a glowing phone",
    )


def _location() -> Location:
    return Location(
        id="street",
        architecture="stone-paved Pompeii street",
        fixed_props="an archway entrance",
        ambient_light="bright midday sun",
    )


def _beat(location_id="street", action="checks her phone") -> Beat:
    return Beat(
        location_id=location_id,
        subject="The influencer",
        action=action,
        camera="medium shot",
        lighting="bright midday sun",
        style="photorealistic",
        audio="street ambience",
        duration_seconds="3",
    )


def test_review_scene_plan_accepts_everything_under_auto_yes():
    plan = ScenePlan(characters=[_character()], locations=[_location()], beats=[_beat()])

    reviewed = _review_scene_plan(plan, auto_yes=True)

    assert reviewed == plan


def test_review_scene_plan_recatches_a_beat_edited_to_an_unknown_location(monkeypatch):
    # docs/decisions/0028: editing a beat's location_id to something that
    # doesn't match any reviewed location must not silently drop all
    # location grounding -- it should re-prompt for that beat specifically.
    # Each failed round re-enters _review_item from the top (a)ccept/(e)dit
    # choice, so recovering means editing *again* with a valid id, not
    # just re-accepting the still-broken beat.
    plan = ScenePlan(characters=[], locations=[_location()], beats=[_beat()])
    responses = iter(
        ["a"]  # location: accept
        + ["e", "nonexistent-typo", "", "", "", "", "", "", ""]  # beat round 1: bad location_id
        + ["e", "street", "", "", "", "", "", "", ""]  # beat round 2: fixed
    )
    monkeypatch.setattr("builtins.input", lambda _: next(responses))

    reviewed = _review_scene_plan(plan, auto_yes=False)

    assert reviewed.beats[0].location_id == "street"


def test_review_scene_plan_recatches_duplicate_location_ids_after_edit(monkeypatch):
    # docs/decisions/0028: editing a second location's id to collide with
    # the first must not silently corrupt character_refs/location_refs.
    plan = ScenePlan(
        characters=[],
        locations=[_location(), Location(id="other", architecture="x", fixed_props="y", ambient_light="z")],
        beats=[_beat()],
    )
    # Location 1: accept. Location 2: edit id to collide with location 1,
    # blank the rest -- caught, re-reviewed: accept location 1, then edit
    # location 2's id back to something unique.
    responses = iter(
        [
            "a",  # location 1: accept
            "e", "street", "", "", "",  # location 2: edit id to collide ("street")
            "a",  # re-review location 1: accept
            "e", "other-fixed", "", "", "",  # re-review location 2: fix id
            "a",  # beat: accept
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _: next(responses))

    reviewed = _review_scene_plan(plan, auto_yes=False)

    ids = [loc.id for loc in reviewed.locations]
    assert len(ids) == len(set(ids))
    assert "other-fixed" in ids


def test_generate_scene_references_generates_and_accepts(tmp_path, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "y")

    character_refs, location_refs = _generate_scene_references(
        ScenePlan(characters=[_character()], locations=[_location()], beats=[_beat()]),
        previz_model="gemini/gemini-2.5-flash-image",
        image_kwargs={"image_fn": _fake_image_fn},
        out_dir=tmp_path,
    )

    assert character_refs["influencer"] == tmp_path / "character_influencer" / "reference.png"
    assert location_refs["street"] == tmp_path / "location_street" / "reference.png"


def test_generate_scene_references_passes_style_through_to_both_prompts(tmp_path, monkeypatch):
    # docs/decisions/0033
    monkeypatch.setattr("builtins.input", lambda _: "y")
    captured_prompts = []

    def _capturing_image_fn(**kwargs):
        captured_prompts.append(kwargs["prompt"])
        return SimpleNamespace(data=[SimpleNamespace(b64_json=_TINY_PNG_B64)])

    _generate_scene_references(
        ScenePlan(characters=[_character()], locations=[_location()], beats=[_beat()]),
        previz_model="gemini/gemini-2.5-flash-image",
        image_kwargs={"image_fn": _capturing_image_fn},
        out_dir=tmp_path,
        style="stylized",
    )

    assert len(captured_prompts) == 2
    assert all("stylized/cartoon" in p for p in captured_prompts)


def test_generate_scene_references_regenerates_until_accepted(tmp_path, monkeypatch):
    # First reference offered is rejected ("n"), the regenerated one accepted.
    responses = iter(["n", "y"])
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    calls = {"n": 0}

    def _counting_image_fn(**kwargs):
        calls["n"] += 1
        return SimpleNamespace(data=[SimpleNamespace(b64_json=_TINY_PNG_B64)])

    character_refs, _ = _generate_scene_references(
        ScenePlan(characters=[_character()], locations=[], beats=[_beat()]),
        previz_model="gemini/gemini-2.5-flash-image",
        image_kwargs={"image_fn": _counting_image_fn},
        out_dir=tmp_path,
    )

    assert calls["n"] == 2
    assert "influencer" in character_refs


def _write_reference_png(tmp_path, name):
    import base64

    path = tmp_path / name
    path.write_bytes(base64.b64decode(_TINY_PNG_B64))
    return path


def _generate_beats_with_choices_kwargs(out_dir, *, image_fn=_fake_image_fn, edit_fn=_fake_image_fn):
    return {
        "previz_model": "gemini/gemini-2.5-flash-image",
        "review_model": "anthropic/claude-sonnet-5",
        "image_kwargs": {"image_fn": image_fn, "edit_fn": edit_fn},
        "review_kwargs": {"completion_fn": _fake_review_completion([(True, None)])},
        "out_dir": out_dir,
    }


def test_generate_beats_with_choices_auto_accepts_under_yes(tmp_path):
    scene_plan = ScenePlan(characters=[_character()], locations=[_location()], beats=[_beat()])
    char_ref = _write_reference_png(tmp_path, "char_ref.png")
    loc_ref = _write_reference_png(tmp_path, "loc_ref.png")

    results = _generate_beats_with_choices(
        scene_plan,
        _fact_check_result_for_previz(),
        character_refs={"influencer": char_ref},
        location_refs={"street": loc_ref},
        auto_yes=True,
        **_generate_beats_with_choices_kwargs(tmp_path),
    )

    assert len(results) == 1
    assert results[0]["image_path"] is not None
    assert results[0]["beat"]["action"] == "checks her phone"


def test_generate_beats_with_choices_reroll_generates_again_then_accepts(tmp_path, monkeypatch):
    responses = iter(["r", "a"])
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    scene_plan = ScenePlan(characters=[], locations=[_location()], beats=[_beat()])
    calls = {"n": 0}

    def _counting_image_fn(**kwargs):
        calls["n"] += 1
        return SimpleNamespace(data=[SimpleNamespace(b64_json=_TINY_PNG_B64)])

    kwargs = _generate_beats_with_choices_kwargs(tmp_path, image_fn=_counting_image_fn)
    # Each generation attempt (the rerolled one and the accepted one) goes
    # through its own previz_review pass before the human choice is even
    # asked -- two accepted verdicts needed, not one.
    kwargs["review_kwargs"] = {"completion_fn": _fake_review_completion([(True, None), (True, None)])}

    results = _generate_beats_with_choices(
        scene_plan, _fact_check_result_for_previz(), character_refs={}, location_refs={}, **kwargs
    )

    assert calls["n"] == 2  # one rerolled attempt, then the accepted one
    assert results[0]["image_path"] is not None


def test_generate_beats_with_choices_edit_changes_the_beat_before_regenerating(tmp_path, monkeypatch):
    # "e" to edit, then a new action, blank for every other field, then "a" to accept.
    responses = iter(
        ["e", "street", "The influencer", "smiles warmly", "", "", "", "", "", "a"]
    )
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    scene_plan = ScenePlan(characters=[], locations=[_location()], beats=[_beat()])
    kwargs = _generate_beats_with_choices_kwargs(tmp_path)
    kwargs["review_kwargs"] = {"completion_fn": _fake_review_completion([(True, None), (True, None)])}

    results = _generate_beats_with_choices(
        scene_plan, _fact_check_result_for_previz(), character_refs={}, location_refs={}, **kwargs
    )

    assert results[0]["beat"]["action"] == "smiles warmly"


def test_generate_beats_with_choices_gives_up_when_every_review_attempt_rejected(
    tmp_path, monkeypatch
):
    # Blank input at the on-rejection prompt means "keep auto-retrying" --
    # this exercises the same all-3-attempts-rejected path as before that
    # hook existed, just with the human declining to intervene each time.
    monkeypatch.setattr("builtins.input", lambda _: "")
    scene_plan = ScenePlan(characters=[], locations=[_location()], beats=[_beat()])
    kwargs = _generate_beats_with_choices_kwargs(tmp_path)
    kwargs["review_kwargs"] = {"completion_fn": _fake_review_completion([(False, "Wrong.")] * 3)}

    results = _generate_beats_with_choices(
        scene_plan, _fact_check_result_for_previz(), character_refs={}, location_refs={}, **kwargs
    )

    assert results[0]["image_path"] is None
    assert len(results[0]["attempts"]) == 3


def test_generate_beats_with_choices_passes_character_and_beat_to_review(tmp_path):
    # docs/decisions/0032: the review call must know which character/beat
    # it's reviewing so it can trust their already-approved details instead
    # of re-deriving plausibility from scratch.
    captured = {}

    def _review_completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps({"accepted": True, "concern": None}))
                )
            ]
        )

    scene_plan = ScenePlan(characters=[_character()], locations=[_location()], beats=[_beat()])
    char_ref = _write_reference_png(tmp_path, "char_ref.png")
    loc_ref = _write_reference_png(tmp_path, "loc_ref.png")
    kwargs = _generate_beats_with_choices_kwargs(tmp_path)
    kwargs["review_kwargs"] = {"completion_fn": _review_completion}

    _generate_beats_with_choices(
        scene_plan,
        _fact_check_result_for_previz(),
        character_refs={"influencer": char_ref},
        location_refs={"street": loc_ref},
        auto_yes=True,
        **kwargs,
    )

    prompt_text = next(
        part["text"] for part in captured["messages"][0]["content"] if part["type"] == "text"
    )
    assert "already deliberately planned and human-reviewed" in prompt_text
    assert "white crop top, gray leggings" in prompt_text


def test_generate_beats_with_choices_passes_style_through(tmp_path):
    # docs/decisions/0033
    captured_prompts = []

    def _capturing_image_fn(**kwargs):
        captured_prompts.append(kwargs["prompt"])
        return SimpleNamespace(data=[SimpleNamespace(b64_json=_TINY_PNG_B64)])

    scene_plan = ScenePlan(characters=[], locations=[_location()], beats=[_beat()])
    kwargs = _generate_beats_with_choices_kwargs(tmp_path, image_fn=_capturing_image_fn)

    _generate_beats_with_choices(
        scene_plan,
        _fact_check_result_for_previz(),
        character_refs={},
        location_refs={},
        style="semi-realistic",
        auto_yes=True,
        **kwargs,
    )

    assert len(captured_prompts) == 1
    assert "Pixar/Disney" in captured_prompts[0]


def test_generate_beats_with_choices_gives_up_early_when_human_declines_to_keep_retrying(
    tmp_path, monkeypatch
):
    # Only one rejected attempt should happen -- (g)ive up at the very
    # first on-rejection prompt must stop the retry loop immediately
    # rather than burning the remaining automatic attempts.
    responses = iter(["g"])
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    scene_plan = ScenePlan(characters=[], locations=[_location()], beats=[_beat()])
    kwargs = _generate_beats_with_choices_kwargs(tmp_path)
    kwargs["review_kwargs"] = {"completion_fn": _fake_review_completion([(False, "Wrong.")])}

    results = _generate_beats_with_choices(
        scene_plan, _fact_check_result_for_previz(), character_refs={}, location_refs={}, **kwargs
    )

    assert results[0]["image_path"] is None
    assert len(results[0]["attempts"]) == 1


def test_generate_beats_with_choices_lets_human_edit_beat_on_rejection_and_retry(
    tmp_path, monkeypatch
):
    # docs/decisions/0028-era work follow-up: a rejection caused by
    # something baked into the beat's own text (not bad luck) needs an
    # edit-and-retry path, not just three guaranteed-to-fail blind
    # attempts. (e)dit at the on-rejection prompt, then blank through
    # every Beat field (keep as-is for this test), should restart a fresh
    # attempt cycle that can then be accepted normally.
    responses = iter(["e", "", "", "", "", "", "", "", "", "a"])
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    scene_plan = ScenePlan(characters=[], locations=[_location()], beats=[_beat()])
    kwargs = _generate_beats_with_choices_kwargs(tmp_path)
    kwargs["review_kwargs"] = {
        "completion_fn": _fake_review_completion([(False, "Wrong."), (True, None)])
    }

    results = _generate_beats_with_choices(
        scene_plan, _fact_check_result_for_previz(), character_refs={}, location_refs={}, **kwargs
    )

    assert results[0]["image_path"] is not None
    # The restarted attempt cycle is a fresh _generate_image_with_review
    # call -- only its own attempt log is recorded, not the discarded
    # first cycle's single rejected attempt.
    assert len(results[0]["attempts"]) == 1
    assert results[0]["attempts"][0]["accepted"] is True


def test_generate_beats_with_choices_stops_early_under_auto_yes_on_repeated_concern(tmp_path):
    # docs/decisions/0029: under auto_yes there's no human to ask, so an
    # identical rejection concern twice in a row is treated as doomed and
    # stops the retry loop early instead of spending the third attempt on
    # a near-certain repeat.
    scene_plan = ScenePlan(characters=[], locations=[_location()], beats=[_beat()])
    kwargs = _generate_beats_with_choices_kwargs(tmp_path)
    kwargs["review_kwargs"] = {
        "completion_fn": _fake_review_completion([(False, "Same reason."), (False, "Same reason.")])
    }

    results = _generate_beats_with_choices(
        scene_plan,
        _fact_check_result_for_previz(),
        character_refs={},
        location_refs={},
        auto_yes=True,
        **kwargs,
    )

    assert results[0]["image_path"] is None
    assert len(results[0]["attempts"]) == 2


def test_generate_beats_with_choices_keeps_retrying_under_auto_yes_when_concern_differs(tmp_path):
    scene_plan = ScenePlan(characters=[], locations=[_location()], beats=[_beat()])
    kwargs = _generate_beats_with_choices_kwargs(tmp_path)
    kwargs["review_kwargs"] = {
        "completion_fn": _fake_review_completion(
            [(False, "First reason."), (False, "Second, different reason."), (True, None)]
        )
    }

    results = _generate_beats_with_choices(
        scene_plan,
        _fact_check_result_for_previz(),
        character_refs={},
        location_refs={},
        auto_yes=True,
        **kwargs,
    )

    assert results[0]["image_path"] is not None
    assert len(results[0]["attempts"]) == 3


def test_generate_beats_with_choices_uses_first_character_for_every_beat(tmp_path):
    # Documented v1 simplification (docs/decisions/0024): Beat has no
    # character_id field, so with multiple characters the first is used
    # for every beat.
    second_character = Character(
        id="second",
        face_build="a man",
        hair="short",
        wardrobe_signature="a tunic",
        wardrobe_flexible="none",
        distinguishing_detail="a beard",
    )
    scene_plan = ScenePlan(
        characters=[_character(), second_character], locations=[_location()], beats=[_beat()]
    )
    char_ref = _write_reference_png(tmp_path, "char.png")
    second_char_ref = _write_reference_png(tmp_path, "char2.png")
    loc_ref = _write_reference_png(tmp_path, "loc.png")
    captured = {}

    def _capturing_edit_fn(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(data=[SimpleNamespace(b64_json=_TINY_PNG_B64)])

    _generate_beats_with_choices(
        scene_plan,
        _fact_check_result_for_previz(),
        character_refs={"influencer": char_ref, "second": second_char_ref},
        location_refs={"street": loc_ref},
        auto_yes=True,
        **_generate_beats_with_choices_kwargs(tmp_path, edit_fn=_capturing_edit_fn),
    )

    assert captured["image"][0] == char_ref.read_bytes()
    assert not (tmp_path / "previz.png").exists()


def _write_previz_run_log(run_dir, *, image_path=None, prompt="A prompt from previz."):
    run_dir.mkdir(parents=True, exist_ok=True)
    if image_path is None:
        image_path = run_dir / "previz.png"
        # A real PNG already at Sora's target size -- video_generation
        # genuinely opens and resizes this with Pillow now, so arbitrary
        # bytes no longer work here.
        Image.new("RGB", (720, 1280), color="blue").save(image_path, format="PNG")
    log = {"previz_image_path": str(image_path), "previz_prompt_used": prompt}
    (run_dir / "run_log.json").write_text(json.dumps(log))
    return image_path


def test_load_previz_output_returns_image_path_and_prompt(tmp_path):
    run_dir = tmp_path / "run_1"
    image_path = _write_previz_run_log(run_dir, prompt="Scene one's prompt.")

    result_image_path, prompt = _load_previz_output(run_dir)

    assert result_image_path == image_path
    assert prompt == "Scene one's prompt."


def test_load_previz_output_prompt_override_replaces_saved_prompt(tmp_path):
    # --video-prompt: test a hand-written prompt against an already-
    # approved image without a fresh previz pass. Image path still comes
    # from the saved run -- only the prompt text is substituted.
    run_dir = tmp_path / "run_1"
    image_path = _write_previz_run_log(run_dir, prompt="Scene one's prompt.")

    result_image_path, prompt = _load_previz_output(
        run_dir, prompt_override="A hand-written video-specific prompt."
    )

    assert result_image_path == image_path
    assert prompt == "A hand-written video-specific prompt."


def test_load_previz_output_raises_when_no_run_log(tmp_path):
    run_dir = tmp_path / "run_missing"
    run_dir.mkdir()

    with pytest.raises(FileNotFoundError, match="No run_log.json"):
        _load_previz_output(run_dir)


def test_load_previz_output_raises_when_previz_incomplete(tmp_path):
    run_dir = tmp_path / "run_incomplete"
    run_dir.mkdir()
    (run_dir / "run_log.json").write_text(json.dumps({"time": "1969"}))

    with pytest.raises(ValueError, match="no completed previz result"):
        _load_previz_output(run_dir)


def test_load_previz_output_raises_when_image_file_missing(tmp_path):
    run_dir = tmp_path / "run_stale"
    run_dir.mkdir()
    missing_image = run_dir / "previz.png"
    log = {"previz_image_path": str(missing_image), "previz_prompt_used": "A prompt."}
    (run_dir / "run_log.json").write_text(json.dumps(log))

    with pytest.raises(FileNotFoundError, match="no longer exists"):
        _load_previz_output(run_dir)


def _write_beat_image(run_dir, name, *, action="checks her phone") -> dict:
    beat_dir = run_dir / name
    beat_dir.mkdir(parents=True, exist_ok=True)
    image_path = beat_dir / "previz.png"
    Image.new("RGB", (720, 1280), color="blue").save(image_path, format="PNG")
    return {
        "index": int(name.split("_")[1]),
        "beat": {"action": action},
        "image_path": str(image_path),
        "prompt_used": f"Prompt for {name}.",
        "attempts": [{"attempt": 1, "accepted": True, "concern": None}],
    }


def _write_multi_beat_run_log(run_dir, *, beats=None):
    """A new-style scene-plan run (docs/decisions/0023/0024) -- one
    real image per accepted beat, mirroring _generate_beats_with_choices's
    actual output shape."""
    run_dir.mkdir(parents=True, exist_ok=True)
    if beats is None:
        beats = [_write_beat_image(run_dir, "beat_1"), _write_beat_image(run_dir, "beat_2")]
    log = {"previz_beats": beats}
    (run_dir / "run_log.json").write_text(json.dumps(log))
    return beats


def test_load_video_gen_targets_old_style_returns_single_target(tmp_path):
    run_dir = tmp_path / "run_old"
    image_path = _write_previz_run_log(run_dir, prompt="Scene A's prompt.")

    targets = _load_video_gen_targets(run_dir)

    assert len(targets) == 1
    assert targets[0].image_path == image_path
    assert targets[0].prompt_used == "Scene A's prompt."
    assert targets[0].output_dir == run_dir
    assert targets[0].beat_index is None


def test_load_video_gen_targets_multi_beat_returns_one_target_per_accepted_beat(tmp_path):
    run_dir = tmp_path / "run_new"
    beats = _write_multi_beat_run_log(run_dir)

    targets = _load_video_gen_targets(run_dir)

    assert len(targets) == 2
    assert targets[0].image_path == Path(beats[0]["image_path"])
    assert targets[0].prompt_used == "Prompt for beat_1."
    assert targets[0].output_dir == Path(beats[0]["image_path"]).parent
    assert targets[0].beat_index == 1
    assert targets[1].beat_index == 2


def test_load_video_gen_targets_skips_beats_with_no_accepted_image(tmp_path):
    run_dir = tmp_path / "run_new"
    accepted = _write_beat_image(run_dir, "beat_1")
    rejected = {
        "index": 2,
        "beat": {"action": "rejected beat"},
        "image_path": None,
        "attempts": [{"attempt": 1, "accepted": False, "concern": "Anachronism."}] * 3,
    }
    _write_multi_beat_run_log(run_dir, beats=[accepted, rejected])

    targets = _load_video_gen_targets(run_dir)

    assert len(targets) == 1
    assert targets[0].beat_index == 1


def test_load_video_gen_targets_raises_when_no_beat_has_an_accepted_image(tmp_path):
    run_dir = tmp_path / "run_new"
    rejected = {
        "index": 1,
        "beat": {"action": "rejected beat"},
        "image_path": None,
        "attempts": [],
    }
    _write_multi_beat_run_log(run_dir, beats=[rejected])

    with pytest.raises(ValueError, match="no beat produced an accepted image"):
        _load_video_gen_targets(run_dir)


def test_load_video_gen_targets_raises_when_accepted_beat_has_no_prompt_used(tmp_path):
    run_dir = tmp_path / "run_new"
    beat = _write_beat_image(run_dir, "beat_1")
    del beat["prompt_used"]
    _write_multi_beat_run_log(run_dir, beats=[beat])

    with pytest.raises(ValueError, match="no recorded 'prompt_used'"):
        _load_video_gen_targets(run_dir)


def test_load_video_gen_targets_prompt_override_applies_to_every_beat(tmp_path):
    run_dir = tmp_path / "run_new"
    _write_multi_beat_run_log(run_dir)

    targets = _load_video_gen_targets(run_dir, prompt_override="A hand-written prompt.")

    assert all(t.prompt_used == "A hand-written prompt." for t in targets)


def test_run_video_generation_only_generates_one_video_per_beat(tmp_path):
    run_dir = tmp_path / "run_new"
    _write_multi_beat_run_log(run_dir)

    _run_video_generation_only([run_dir], mock=True, video_model="openai/sora-2")

    log = json.loads((run_dir / "run_log.json").read_text())
    assert len(log["previz_beats"][0]["videos"]) == 1
    assert len(log["previz_beats"][1]["videos"]) == 1
    assert list((run_dir / "beat_1").glob("video_*.mp4"))
    assert list((run_dir / "beat_2").glob("video_*.mp4"))


def test_run_video_generation_only_writes_video_into_source_run_dir(tmp_path):
    # The video lands directly in the source previz run's own directory --
    # right next to the previz.png it came from -- rather than a separate
    # new folder that only ever held a copy of the image.
    source_a = tmp_path / "source_run_a"
    source_b = tmp_path / "source_run_b"
    _write_previz_run_log(source_a, prompt="Scene A's prompt.")
    _write_previz_run_log(source_b, prompt="Scene B's prompt.")

    _run_video_generation_only([source_a, source_b], mock=True, video_model="openai/sora-2")

    videos_a = list(source_a.glob("video_*.mp4"))
    videos_b = list(source_b.glob("video_*.mp4"))
    assert len(videos_a) == 1
    assert len(videos_b) == 1
    assert (source_a / "previz.png").exists()  # untouched, still there too


def test_run_video_generation_only_appends_to_existing_run_log(tmp_path):
    # Regression test: this used to write a brand new run_log.json into a
    # separate output folder ("mode": "video_generation_only") instead of
    # extending the scene's own existing log -- fragmenting one scene's
    # history (research through video) across two files in two folders.
    source_a = tmp_path / "source_run_a"
    _write_previz_run_log(source_a, prompt="Scene A's prompt.")
    original_log = json.loads((source_a / "run_log.json").read_text())

    _run_video_generation_only([source_a], mock=True, video_model="openai/sora-2")

    log = json.loads((source_a / "run_log.json").read_text())
    # Everything previz/research/fact-check already wrote is still there.
    assert log["previz_prompt_used"] == original_log["previz_prompt_used"]
    assert len(log["videos"]) == 1
    assert log["videos"][0]["video_generation_model"] == "openai/sora-2"
    assert Path(log["videos"][0]["video_path"]).parent == source_a


def test_run_video_generation_only_records_prompt_used_per_video(tmp_path):
    source_a = tmp_path / "source_run_a"
    _write_previz_run_log(source_a, prompt="Scene A's prompt.")

    _run_video_generation_only([source_a], mock=True, video_model="openai/sora-2")

    log = json.loads((source_a / "run_log.json").read_text())
    assert log["videos"][0]["prompt_used"] == "Scene A's prompt."


def test_run_video_generation_only_video_prompt_overrides_saved_prompt(tmp_path):
    # --video-prompt: test a hand-written prompt against an already-
    # approved image without a fresh previz pass.
    source_a = tmp_path / "source_run_a"
    _write_previz_run_log(source_a, prompt="Scene A's original previz prompt.")

    _run_video_generation_only(
        [source_a],
        mock=True,
        video_model="openai/sora-2",
        video_prompt="A hand-written, timecoded video prompt.",
    )

    log = json.loads((source_a / "run_log.json").read_text())
    assert log["videos"][0]["prompt_used"] == "A hand-written, timecoded video prompt."
    # The original previz prompt on record is untouched -- only this
    # video attempt used the override.
    assert log["previz_prompt_used"] == "Scene A's original previz prompt."


def test_check_video_prompt_practices_flags_missing_character_block():
    found = _check_video_prompt_practices("Just a plain description with no structure.")
    assert any("CHARACTER" in w for w in found)


def test_check_video_prompt_practices_flags_missing_audio():
    found = _check_video_prompt_practices("CHARACTER: Someone\nAction: walks.")
    assert any("Audio" in w for w in found)


def test_check_video_prompt_practices_flags_too_many_beats():
    prompt = "CHARACTER: Someone\nAudio: footsteps.\n" + "".join(
        f"({n}-{n + 1}s) Something happens.\n" for n in range(5)
    )
    found = _check_video_prompt_practices(prompt)
    assert any("beats" in w for w in found)


def test_check_video_prompt_practices_flags_too_many_beats_with_en_dash_timecodes():
    # Regression test: the playbook's own documented timecode format uses
    # an en-dash ("(0–3s)"), not an ASCII hyphen -- a prompt written
    # exactly that way must still be counted.
    prompt = "CHARACTER: Someone\nAudio: footsteps.\n" + "".join(
        f"({n}–{n + 1}s) Something happens.\n" for n in range(5)
    )
    found = _check_video_prompt_practices(prompt)
    assert any("beats" in w for w in found)


def test_check_video_prompt_practices_flags_risky_wording():
    prompt = "CHARACTER: Someone\nAudio: footsteps.\nAction: prepares to attack with a weapon."
    found = _check_video_prompt_practices(prompt)
    assert any("attack" in w and "weapon" in w for w in found)


def test_check_video_prompt_practices_flags_inflected_risky_wording():
    # Regression test: an exact-word match let inflected forms of the same
    # risk words through undetected.
    prompt = "CHARACTER: Someone\nAudio: footsteps.\nAction: soldiers attacking with weapons."
    found = _check_video_prompt_practices(prompt)
    assert any("attack" in w and "weapon" in w for w in found)


def test_check_video_prompt_practices_returns_nothing_for_a_well_formed_prompt():
    prompt = (
        "CHARACTER: Someone\n"
        "ROLE: main\n"
        "(0-3s) Action: walks calmly across a room.\n"
        "Audio: footsteps on wood."
    )
    assert _check_video_prompt_practices(prompt) == []


def test_run_video_generation_only_prints_practice_warnings_but_still_generates(
    tmp_path, capsys
):
    # Advisory only -- warnings are printed, generation still proceeds.
    source_a = tmp_path / "source_run_a"
    _write_previz_run_log(source_a, prompt="Scene A's original previz prompt.")

    _run_video_generation_only(
        [source_a],
        mock=True,
        video_model="openai/sora-2",
        video_prompt="No structure at all here.",
    )

    captured = capsys.readouterr()
    assert "doesn't follow known best practice" in captured.out
    assert "CHARACTER" in captured.out
    log = json.loads((source_a / "run_log.json").read_text())
    assert len(log["videos"]) == 1  # still generated despite the warnings


def test_run_video_generation_only_accumulates_multiple_video_attempts(tmp_path):
    # Re-running against the same previz output (e.g. trying a different
    # --video-seconds) should add another video, not overwrite the last one.
    source_a = tmp_path / "source_run_a"
    _write_previz_run_log(source_a, prompt="Scene A's prompt.")

    _run_video_generation_only([source_a], mock=True, video_model="openai/sora-2")
    _run_video_generation_only([source_a], mock=True, video_model="openai/sora-2")

    assert len(list(source_a.glob("video_*.mp4"))) == 2
    log = json.loads((source_a / "run_log.json").read_text())
    assert len(log["videos"]) == 2


def test_slugify_lowercases_and_hyphenates():
    assert _slugify("A Young Dockworker Wades!") == "a-young-dockworker-wades"


def test_slugify_truncates_at_a_word_boundary():
    text = ("a" * 20) + " " + ("b" * 20)  # 41 chars once hyphenated
    result = _slugify(text, max_length=25)
    assert len(result) <= 25
    assert result == "a" * 20  # cut back to the hyphen boundary, not mid-word


def test_slugify_returns_empty_for_content_free_input():
    assert _slugify("   ...   ") == ""


def test_project_root_raises_when_no_pyproject_toml_found(monkeypatch):
    # Regression test: the old fallback silently guessed a fixed parents[2]
    # offset instead of failing loud when no ancestor has a pyproject.toml.
    monkeypatch.setattr(Path, "exists", lambda self: False)

    with pytest.raises(RuntimeError, match="Could not find pyproject.toml"):
        _project_root()


def test_run_dir_includes_slug_in_directory_name(tmp_path, monkeypatch):
    monkeypatch.setattr("historical_video_ai.cli._project_root", lambda: tmp_path)

    d = _run_dir("a-flood-rescue-scene")

    assert d.parent == tmp_path / "outputs"
    assert re.match(r"^run_\d{8}-\d{6}_a-flood-rescue-scene$", d.name)
    assert d.exists()


def test_run_dir_omits_slug_when_not_given(tmp_path, monkeypatch):
    monkeypatch.setattr("historical_video_ai.cli._project_root", lambda: tmp_path)

    d = _run_dir()

    assert re.match(r"^run_\d{8}-\d{6}$", d.name)


def test_generate_previz_with_review_calls_on_image_generated_before_review(tmp_path):
    calls = []

    result, _ = _generate_previz_with_review(
        _fact_check_result_for_previz(),
        **_generate_previz_with_review_kwargs(_fake_review_completion([(True, None)]), tmp_path),
        on_image_generated=calls.append,
    )

    assert len(calls) == 1
    assert calls[0] == result


def test_generate_previz_with_review_on_image_generated_survives_a_review_crash(tmp_path):
    # Regression test: a real run hit exactly this -- previz generated a
    # real image, but previz_review raised (missing ANTHROPIC_API_KEY)
    # before returning a verdict at all. on_image_generated must still have
    # fired for that image, so a caller logging progress (main()'s
    # run_log.json) doesn't lose track of an already-generated, already
    # paid-for image just because the next stage blew up.
    calls = []

    def _crashing_review(**kwargs):
        raise RuntimeError("simulated previz_review crash (e.g. missing API key)")

    with pytest.raises(RuntimeError, match="simulated previz_review crash"):
        _generate_previz_with_review(
            _fact_check_result_for_previz(),
            **_generate_previz_with_review_kwargs(_crashing_review, tmp_path),
            on_image_generated=calls.append,
        )

    assert len(calls) == 1
    assert calls[0].image_path == tmp_path / "previz.png"


def test_resolve_premise_conflict_stops_if_reverify_research_declined(monkeypatch):
    fact_check_result = _premise_conflict_fact_check_result("A suggested version.")
    responses = iter(["u", "n"])  # use alternative; decline "proceed to fact-check" on reverify
    monkeypatch.setattr("builtins.input", lambda _: next(responses))

    result = _resolve_premise_conflict(
        fact_check_result.fact_sheet,
        fact_check_result,
        **_resolve_premise_conflict_kwargs(_fake_reverify_completion()),
    )

    assert result is None
