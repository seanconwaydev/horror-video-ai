import json

import pytest

from historical_video_ai.cli import _load_fixture, _resolve_flags
from historical_video_ai.stages.fact_check import ClaimFlag, FactCheckResult
from historical_video_ai.stages.research import Claim, FactSheet


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


@pytest.mark.parametrize("missing_field", ["time", "place", "description"])
def test_load_fixture_raises_for_empty_required_field(tmp_path, missing_field):
    path = _write_fixture(tmp_path, **{missing_field: ""})

    with pytest.raises(ValueError, match=missing_field):
        _load_fixture(path)


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


def test_resolve_flags_reprompts_on_invalid_action(monkeypatch):
    fact_sheet = _fact_sheet_with_two_claims()
    flags = [ClaimFlag(claim_text="Claim A", concern="Wrong.", severity="contradicted")]
    responses = iter(["x", "c"])  # invalid choice, then a valid one
    monkeypatch.setattr("builtins.input", lambda _: next(responses))

    resolved = _resolve_flags(fact_sheet, flags)

    assert [c.text for c in resolved.claims] == ["Claim B"]
