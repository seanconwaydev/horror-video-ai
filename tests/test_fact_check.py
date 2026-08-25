import json
from types import SimpleNamespace

import pytest

from historical_video_ai.config import get_stage_model
from historical_video_ai.stages.fact_check import (
    FactCheckError,
    run_fact_check_stage,
)
from historical_video_ai.stages.research import Claim, FactSheet


def _premise_conflict_payload(explanation: str, suggested_alternative):
    return {
        "flags": [],
        "premise_conflict": {
            "explanation": explanation,
            "suggested_alternative": suggested_alternative,
        },
    }


def _fake_completion(content: str):
    def _completion(**kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )

    return _completion


def _sample_fact_sheet() -> FactSheet:
    return FactSheet(
        time="December 1903",
        place="Kitty Hawk, North Carolina",
        description="A man watches a flying machine lift off from the dunes.",
        claims=[
            Claim(
                text="Kitty Hawk was a remote, sparsely populated coastal area in 1903.",
                source="Smithsonian National Air and Space Museum",
                date="1903-12-17",
                names=["Kitty Hawk"],
            )
        ],
    )


def test_run_fact_check_stage_parses_valid_response_with_no_flags():
    result = run_fact_check_stage(
        _sample_fact_sheet(),
        model="anthropic/claude-sonnet-5",
        completion_fn=_fake_completion(json.dumps({"flags": []})),
    )

    assert result.fact_sheet == _sample_fact_sheet()
    assert result.flags == []


def test_run_fact_check_stage_parses_response_wrapped_in_markdown_fence():
    # Regression test: see test_research.py's equivalent -- observed for
    # real that a model can wrap "respond with ONLY JSON" output in a
    # ```json fence anyway.
    result = run_fact_check_stage(
        _sample_fact_sheet(),
        model="anthropic/claude-sonnet-5",
        completion_fn=_fake_completion('```json\n{"flags": []}\n```'),
    )

    assert result.flags == []


def test_run_fact_check_stage_parses_flags():
    payload = {
        "flags": [
            {
                "claim_text": "Kitty Hawk was a remote, sparsely populated coastal area in 1903.",
                "concern": "Source doesn't specifically support 'sparsely populated'.",
                "severity": "uncertain",
            }
        ]
    }

    result = run_fact_check_stage(
        _sample_fact_sheet(),
        model="anthropic/claude-sonnet-5",
        completion_fn=_fake_completion(json.dumps(payload)),
    )

    assert len(result.flags) == 1
    assert result.flags[0].severity == "uncertain"
    assert "sparsely populated" in result.flags[0].concern


def test_run_fact_check_stage_raises_for_invalid_json():
    with pytest.raises(FactCheckError, match="not valid JSON"):
        run_fact_check_stage(
            _sample_fact_sheet(),
            model="anthropic/claude-sonnet-5",
            completion_fn=_fake_completion("not json"),
        )


def test_run_fact_check_stage_raises_for_missing_flags_key():
    with pytest.raises(FactCheckError, match="missing 'flags'"):
        run_fact_check_stage(
            _sample_fact_sheet(),
            model="anthropic/claude-sonnet-5",
            completion_fn=_fake_completion(json.dumps({"not_flags": []})),
        )


def test_run_fact_check_stage_raises_for_invalid_severity():
    payload = {
        "flags": [
            {
                "claim_text": "x",
                "concern": "y",
                "severity": "definitely_wrong",
            }
        ]
    }

    with pytest.raises(FactCheckError, match="invalid 'severity'"):
        run_fact_check_stage(
            _sample_fact_sheet(),
            model="anthropic/claude-sonnet-5",
            completion_fn=_fake_completion(json.dumps(payload)),
        )


def test_run_fact_check_stage_raises_when_claim_text_does_not_match():
    # A model that paraphrases or appends detail (date, source) instead of
    # copying claim_text verbatim -- observed in a real DeepSeek response --
    # breaks anything downstream trying to correlate the flag back to its
    # claim, so this must fail loud rather than let the mismatch through.
    payload = {
        "flags": [
            {
                "claim_text": "Kitty Hawk was a remote, sparsely populated coastal area in 1903. "
                "(date: 1903-12-17) [source: Smithsonian National Air and Space Museum]",
                "concern": "Paraphrased instead of copied verbatim.",
                "severity": "uncertain",
            }
        ]
    }

    with pytest.raises(FactCheckError, match="doesn't exactly match any claim"):
        run_fact_check_stage(
            _sample_fact_sheet(),
            model="anthropic/claude-sonnet-5",
            completion_fn=_fake_completion(json.dumps(payload)),
        )


def test_run_fact_check_stage_parses_null_premise_conflict():
    result = run_fact_check_stage(
        _sample_fact_sheet(),
        model="anthropic/claude-sonnet-5",
        completion_fn=_fake_completion(json.dumps({"flags": [], "premise_conflict": None})),
    )

    assert result.premise_conflict is None


def test_run_fact_check_stage_parses_premise_conflict_with_alternative():
    payload = _premise_conflict_payload(
        "The scene depicts a technology that didn't exist yet.",
        "A close, historically plausible version of the scene.",
    )

    result = run_fact_check_stage(
        _sample_fact_sheet(),
        model="anthropic/claude-sonnet-5",
        completion_fn=_fake_completion(json.dumps(payload)),
    )

    assert result.premise_conflict.explanation == "The scene depicts a technology that didn't exist yet."
    assert (
        result.premise_conflict.suggested_alternative
        == "A close, historically plausible version of the scene."
    )


def test_run_fact_check_stage_parses_premise_conflict_with_no_alternative():
    payload = _premise_conflict_payload("Nothing like this could have happened.", None)

    result = run_fact_check_stage(
        _sample_fact_sheet(),
        model="anthropic/claude-sonnet-5",
        completion_fn=_fake_completion(json.dumps(payload)),
    )

    assert result.premise_conflict.explanation == "Nothing like this could have happened."
    assert result.premise_conflict.suggested_alternative is None


def test_run_fact_check_stage_raises_when_premise_conflict_missing_explanation():
    payload = {"flags": [], "premise_conflict": {"suggested_alternative": None}}

    with pytest.raises(FactCheckError, match="missing 'explanation'"):
        run_fact_check_stage(
            _sample_fact_sheet(),
            model="anthropic/claude-sonnet-5",
            completion_fn=_fake_completion(json.dumps(payload)),
        )


def test_run_fact_check_stage_raises_when_suggested_alternative_not_string():
    payload = _premise_conflict_payload("Impossible.", 42)

    with pytest.raises(FactCheckError, match="must be a string or null"):
        run_fact_check_stage(
            _sample_fact_sheet(),
            model="anthropic/claude-sonnet-5",
            completion_fn=_fake_completion(json.dumps(payload)),
        )


def test_run_fact_check_stage_resolves_model_from_config_when_not_passed():
    captured = {}

    def _completion(**kwargs):
        captured["model"] = kwargs["model"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"flags": []})))]
        )

    run_fact_check_stage(_sample_fact_sheet(), completion_fn=_completion)

    assert captured["model"] == get_stage_model("fact_check")
