import base64
from types import SimpleNamespace

import pytest

from horror_video_ai.config import get_stage_model
from horror_video_ai.stages.moderation import (
    ModerationError,
    run_moderation_policy_check,
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

    assert captured["model"] == get_stage_model("moderation_check").removeprefix("openai/")


def test_run_moderation_policy_check_strips_openai_prefix_before_calling_moderation_fn(tmp_path):
    """WORKAROUND(https://github.com/BerriAI/litellm/issues/6020): litellm's
    synchronous moderation() doesn't strip a provider prefix the way
    completion()/image_generation() do, so the pinned
    "openai/omni-moderation-latest" format must be stripped at this call
    site or OpenAI's real API rejects it with a 400."""
    image_path = _write_tiny_png(tmp_path)
    captured = {}

    def _moderation(**kwargs):
        captured["model"] = kwargs["model"]
        return SimpleNamespace(results=[SimpleNamespace(flagged=False, categories={})])

    run_moderation_policy_check(
        "prompt", image_path, model="openai/omni-moderation-latest", moderation_fn=_moderation
    )

    assert captured["model"] == "omni-moderation-latest"
