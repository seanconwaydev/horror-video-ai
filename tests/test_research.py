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
        "claims": [
            {
                "text": "Kitty Hawk in Dec. 1903 was a remote, sparsely populated coastal area.",
                "source": "Smithsonian National Air and Space Museum",
                "date": "1903-12-17",
                # An extra key the parser does not know: research prompts
                # asked for "names" until it was deleted as dead weight,
                # and a model can return anything. Ignored, not fatal.
                "names": ["Kitty Hawk"],
            }
        ],
    }

    fact_sheet = run_research_stage(
        "December 1903",
        "Kitty Hawk, North Carolina",
        "A man watches a flying machine lift off from the dunes.",
        model="anthropic/claude-sonnet-5",
        completion_fn=_fake_completion(json.dumps(payload)),
    )

    assert fact_sheet.time == "December 1903"
    assert fact_sheet.place == "Kitty Hawk, North Carolina"
    assert fact_sheet.description == "A man watches a flying machine lift off from the dunes."
    assert len(fact_sheet.claims) == 1
    assert fact_sheet.claims[0].source == "Smithsonian National Air and Space Museum"
    assert fact_sheet.claims[0].date == "1903-12-17"


def test_run_research_stage_parses_response_wrapped_in_markdown_fence():
    # Regression test: observed for real against a live claude-sonnet-5
    # call (during previz_review testing, same underlying prompt pattern)
    # -- a model can wrap "respond with ONLY JSON" output in a ```json
    # fence anyway. See historical_video_ai.json_utils.
    payload = {"claims": []}

    fact_sheet = run_research_stage(
        "December 1903",
        "Kitty Hawk, North Carolina",
        "A man watches a flying machine lift off from the dunes.",
        model="anthropic/claude-sonnet-5",
        completion_fn=_fake_completion(f"```json\n{json.dumps(payload)}\n```"),
    )

    assert fact_sheet.claims == []


def test_run_research_stage_raises_for_invalid_json():
    with pytest.raises(ResearchError, match="not valid JSON"):
        run_research_stage(
            "Anything",
            "Anywhere",
            "Anything happens.",
            model="anthropic/claude-sonnet-5",
            completion_fn=_fake_completion("not json"),
        )


def test_run_research_stage_raises_for_claim_missing_source():
    payload = {"claims": [{"text": "A claim with no source."}]}

    with pytest.raises(ResearchError, match="missing a 'source'"):
        run_research_stage(
            "Anything",
            "Anywhere",
            "Anything happens.",
            model="anthropic/claude-sonnet-5",
            completion_fn=_fake_completion(json.dumps(payload)),
        )


def test_run_research_stage_raises_for_missing_claims_key():
    with pytest.raises(ResearchError, match="missing 'claims'"):
        run_research_stage(
            "Anything",
            "Anywhere",
            "Anything happens.",
            model="anthropic/claude-sonnet-5",
            completion_fn=_fake_completion(json.dumps({"not_claims": []})),
        )


def test_run_research_stage_resolves_model_from_config_when_not_passed():
    captured = {}

    def _completion(**kwargs):
        captured["model"] = kwargs["model"]
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content=json.dumps({"claims": []})))
            ]
        )

    run_research_stage("Anything", "Anywhere", "Anything happens.", completion_fn=_completion)

    assert captured["model"] == get_stage_model("research")
