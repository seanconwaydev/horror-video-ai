import base64
import json
from types import SimpleNamespace

import pytest

from historical_video_ai.config import get_stage_model
from historical_video_ai.stages.moderation import (
    ModerationError,
    run_moderation_policy_check,
    run_moderation_risk_review,
)

# A tiny valid 1x1 PNG, base64-encoded -- same fixture pattern as
# test_previz.py, so tests never touch a real API or file beyond this.
_TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _write_tiny_png(tmp_path):
    path = tmp_path / "previz.png"
    path.write_bytes(base64.b64decode(_TINY_PNG_B64))
    return path


def _fake_moderation_fn(*, flagged: bool, categories: dict | None = None):
    def _moderation(**kwargs):
        return SimpleNamespace(
            results=[SimpleNamespace(flagged=flagged, categories=categories or {})]
        )

    return _moderation


def _fake_completion(content: str):
    def _completion(**kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )

    return _completion


# --- Layer 1: run_moderation_policy_check ---


def test_run_moderation_policy_check_clean(tmp_path):
    image_path = _write_tiny_png(tmp_path)

    result = run_moderation_policy_check(
        "a person walks across a rooftop",
        image_path,
        model="openai/omni-moderation-latest",
        moderation_fn=_fake_moderation_fn(flagged=False),
    )

    assert result.flagged is False
    assert result.flagged_categories == []


def test_run_moderation_policy_check_flagged_reports_only_true_categories(tmp_path):
    image_path = _write_tiny_png(tmp_path)
    categories = {"violence": True, "violence/graphic": False, "harassment": True}

    result = run_moderation_policy_check(
        "a person walks across a rooftop",
        image_path,
        model="openai/omni-moderation-latest",
        moderation_fn=_fake_moderation_fn(flagged=True, categories=categories),
    )

    assert result.flagged is True
    assert result.flagged_categories == ["harassment", "violence"]


def test_run_moderation_policy_check_raises_when_no_results(tmp_path):
    image_path = _write_tiny_png(tmp_path)

    def _empty(**kwargs):
        return SimpleNamespace(results=[])

    with pytest.raises(ModerationError, match="no results"):
        run_moderation_policy_check(
            "prompt", image_path, model="openai/omni-moderation-latest", moderation_fn=_empty
        )


def test_run_moderation_policy_check_sends_text_and_image_together(tmp_path):
    image_path = _write_tiny_png(tmp_path)
    captured = {}

    def _moderation(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(results=[SimpleNamespace(flagged=False, categories={})])

    run_moderation_policy_check(
        "a person walks across a rooftop",
        image_path,
        model="openai/omni-moderation-latest",
        moderation_fn=_moderation,
    )

    input_parts = captured["input"]
    text_part = next(p for p in input_parts if p["type"] == "text")
    image_part = next(p for p in input_parts if p["type"] == "image_url")
    assert text_part["text"] == "a person walks across a rooftop"
    assert image_part["image_url"]["url"].startswith("data:image/png;base64,")


def test_run_moderation_policy_check_resolves_model_from_config_when_not_passed(tmp_path):
    image_path = _write_tiny_png(tmp_path)
    captured = {}

    def _moderation(**kwargs):
        captured["model"] = kwargs["model"]
        return SimpleNamespace(results=[SimpleNamespace(flagged=False, categories={})])

    run_moderation_policy_check("prompt", image_path, moderation_fn=_moderation)

    assert captured["model"] == get_stage_model("moderation_check")


# --- Layer 2: run_moderation_risk_review ---


def test_run_moderation_risk_review_clean(tmp_path):
    image_path = _write_tiny_png(tmp_path)
    payload = {"flagged": False, "concern": None}

    review = run_moderation_risk_review(
        image_path,
        model="anthropic/claude-sonnet-5",
        completion_fn=_fake_completion(json.dumps(payload)),
    )

    assert review.flagged is False
    assert review.concern is None


def test_run_moderation_risk_review_flagged_with_concern(tmp_path):
    image_path = _write_tiny_png(tmp_path)
    payload = {"flagged": True, "concern": "Reads as forced entry into a doorway."}

    review = run_moderation_risk_review(
        image_path,
        model="anthropic/claude-sonnet-5",
        completion_fn=_fake_completion(json.dumps(payload)),
    )

    assert review.flagged is True
    assert review.concern == "Reads as forced entry into a doorway."


def test_run_moderation_risk_review_parses_response_wrapped_in_markdown_fence(tmp_path):
    image_path = _write_tiny_png(tmp_path)
    payload = {"flagged": False, "concern": None}

    review = run_moderation_risk_review(
        image_path,
        model="anthropic/claude-sonnet-5",
        completion_fn=_fake_completion(f"```json\n{json.dumps(payload)}\n```"),
    )

    assert review.flagged is False


def test_run_moderation_risk_review_raises_when_flagged_without_concern(tmp_path):
    image_path = _write_tiny_png(tmp_path)
    payload = {"flagged": True}

    with pytest.raises(ModerationError, match="missing 'concern'"):
        run_moderation_risk_review(
            image_path,
            model="anthropic/claude-sonnet-5",
            completion_fn=_fake_completion(json.dumps(payload)),
        )


def test_run_moderation_risk_review_raises_for_invalid_json(tmp_path):
    image_path = _write_tiny_png(tmp_path)

    with pytest.raises(ModerationError, match="not valid JSON"):
        run_moderation_risk_review(
            image_path,
            model="anthropic/claude-sonnet-5",
            completion_fn=_fake_completion("not json"),
        )


def test_run_moderation_risk_review_raises_for_non_bool_flagged(tmp_path):
    image_path = _write_tiny_png(tmp_path)
    payload = {"flagged": "yes"}

    with pytest.raises(ModerationError, match="must be true or false"):
        run_moderation_risk_review(
            image_path,
            model="anthropic/claude-sonnet-5",
            completion_fn=_fake_completion(json.dumps(payload)),
        )


def test_run_moderation_risk_review_sends_image_as_base64(tmp_path):
    image_path = _write_tiny_png(tmp_path)
    captured = {}

    def _completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps({"flagged": False, "concern": None}))
                )
            ]
        )

    run_moderation_risk_review(image_path, model="anthropic/claude-sonnet-5", completion_fn=_completion)

    content = captured["messages"][0]["content"]
    image_part = next(part for part in content if part["type"] == "image_url")
    assert image_part["image_url"]["url"].startswith("data:image/png;base64,")


def test_run_moderation_risk_review_resolves_model_from_config_when_not_passed(tmp_path):
    image_path = _write_tiny_png(tmp_path)
    captured = {}

    def _completion(**kwargs):
        captured["model"] = kwargs["model"]
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps({"flagged": False, "concern": None}))
                )
            ]
        )

    run_moderation_risk_review(image_path, completion_fn=_completion)

    assert captured["model"] == get_stage_model("moderation_review")
