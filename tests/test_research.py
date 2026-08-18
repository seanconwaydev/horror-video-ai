import json
from types import SimpleNamespace

import pytest

from historical_video_ai.config import get_stage_model
from historical_video_ai.stages.research import ResearchError, run_research_stage


def _fake_completion(content: str):
    """Build a fake completion_fn returning `content` as the model's reply,
    shaped like litellm's real response object just enough to be read by
    run_research_stage (response.choices[0].message.content)."""

    def _completion(**kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )

    return _completion


def test_run_research_stage_parses_valid_response():
    payload = {
        "topic": "The Wright Flyer",
        "claims": [
            {
                "text": "The Wright Flyer's first flight lasted 12 seconds.",
                "source": "Smithsonian National Air and Space Museum",
                "date": "1903-12-17",
                "names": ["Orville Wright"],
            }
        ],
    }

    fact_sheet = run_research_stage(
        "The Wright Flyer",
        model="anthropic/claude-sonnet-5",
        completion_fn=_fake_completion(json.dumps(payload)),
    )

    assert fact_sheet.topic == "The Wright Flyer"
    assert len(fact_sheet.claims) == 1
    assert fact_sheet.claims[0].source == "Smithsonian National Air and Space Museum"
    assert fact_sheet.claims[0].date == "1903-12-17"
    assert fact_sheet.claims[0].names == ["Orville Wright"]


def test_run_research_stage_raises_for_invalid_json():
    with pytest.raises(ResearchError, match="not valid JSON"):
        run_research_stage(
            "Anything",
            model="anthropic/claude-sonnet-5",
            completion_fn=_fake_completion("not json"),
        )


def test_run_research_stage_raises_for_claim_missing_source():
    payload = {
        "topic": "Anything",
        "claims": [{"text": "A claim with no source."}],
    }

    with pytest.raises(ResearchError, match="missing a 'source'"):
        run_research_stage(
            "Anything",
            model="anthropic/claude-sonnet-5",
            completion_fn=_fake_completion(json.dumps(payload)),
        )


def test_run_research_stage_raises_for_missing_top_level_keys():
    with pytest.raises(ResearchError, match="missing 'topic' or 'claims'"):
        run_research_stage(
            "Anything",
            model="anthropic/claude-sonnet-5",
            completion_fn=_fake_completion(json.dumps({"claims": []})),
        )


def test_run_research_stage_resolves_model_from_config_when_not_passed():
    captured = {}

    def _completion(**kwargs):
        captured["model"] = kwargs["model"]
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps({"topic": "x", "claims": []}))
                )
            ]
        )

    run_research_stage("Anything", completion_fn=_completion)

    assert captured["model"] == get_stage_model("research")
