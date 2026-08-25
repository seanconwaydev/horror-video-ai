import json
from types import SimpleNamespace

import pytest

from historical_video_ai.config import get_stage_model
from historical_video_ai.stages.fact_check import ClaimFlag, FactCheckResult, PremiseConflict
from historical_video_ai.stages.previz import (
    PrevizError,
    run_previz_review_stage,
    run_previz_stage,
)
from historical_video_ai.stages.research import Claim, FactSheet

# A tiny valid 1x1 PNG, base64-encoded, so tests never touch a real API or
# write anything that isn't a real (if trivial) image file.
_TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _fact_check_result(flags=None) -> FactCheckResult:
    fact_sheet = FactSheet(
        time="December 1903",
        place="Kitty Hawk, North Carolina",
        description="watches a flying machine lift off from the dunes.",
        claims=[
            Claim(text="The dunes at Kitty Hawk were largely undeveloped in 1903.", source="NPS"),
            Claim(text="This claim will be contradicted.", source="somewhere"),
        ],
    )
    return FactCheckResult(fact_sheet=fact_sheet, flags=flags or [])


def _fake_image_fn(b64_json: str):
    def _image_fn(**kwargs):
        return SimpleNamespace(data=[SimpleNamespace(b64_json=b64_json)])

    return _image_fn


def test_run_previz_stage_writes_image_and_returns_prompt(tmp_path):
    result = run_previz_stage(
        _fact_check_result(),
        model="gemini/gemini-2.5-flash-image",
        image_fn=_fake_image_fn(_TINY_PNG_B64),
        output_dir=tmp_path,
    )

    assert result.image_path.exists()
    assert result.image_path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic bytes
    assert "Kitty Hawk" in result.prompt_used


def test_run_previz_stage_requests_a_video_aspect_ratio_hint(tmp_path):
    # See docs/decisions/0011: requests an aspect ratio close to Sora-2's
    # target size so video_generation only needs a barely-perceptible
    # resize, not a large content-losing crop.
    captured = {}

    def _image_fn(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(data=[SimpleNamespace(b64_json=_TINY_PNG_B64)])

    run_previz_stage(
        _fact_check_result(),
        model="gemini/gemini-2.5-flash-image",
        image_fn=_image_fn,
        output_dir=tmp_path,
    )

    assert captured["size"] == "720x1280"


def test_run_previz_stage_includes_all_fact_sheet_claims_unfiltered(tmp_path):
    # previz trusts fact_sheet.claims as already resolved -- flags no
    # longer cause any auto-exclusion here (see cli.py's _resolve_flags,
    # which is where a human now decides to accept/cut/soften a flagged
    # claim before it ever reaches this stage).
    flags = [
        ClaimFlag(
            claim_text="This claim will be contradicted.",
            concern="Doesn't hold up.",
            severity="contradicted",
        )
    ]

    result = run_previz_stage(
        _fact_check_result(flags),
        model="gemini/gemini-2.5-flash-image",
        image_fn=_fake_image_fn(_TINY_PNG_B64),
        output_dir=tmp_path,
    )

    assert "This claim will be contradicted." in result.prompt_used
    assert "undeveloped in 1903" in result.prompt_used


def test_run_previz_stage_refuses_unresolved_premise_conflict(tmp_path):
    result_with_conflict = FactCheckResult(
        fact_sheet=_fact_check_result().fact_sheet,
        premise_conflict=PremiseConflict(
            explanation="Nothing like this existed at this time and place.",
            suggested_alternative=None,
        ),
    )

    with pytest.raises(PrevizError, match="historically impossible"):
        run_previz_stage(
            result_with_conflict,
            model="gemini/gemini-2.5-flash-image",
            image_fn=_fake_image_fn(_TINY_PNG_B64),
            output_dir=tmp_path,
        )


def test_run_previz_stage_raises_when_no_image_data(tmp_path):
    def _empty_image_fn(**kwargs):
        return SimpleNamespace(data=[])

    with pytest.raises(PrevizError, match="no image data"):
        run_previz_stage(
            _fact_check_result(),
            model="gemini/gemini-2.5-flash-image",
            image_fn=_empty_image_fn,
            output_dir=tmp_path,
        )


def test_run_previz_stage_resolves_model_from_config_when_not_passed(tmp_path):
    captured = {}

    def _image_fn(**kwargs):
        captured["model"] = kwargs["model"]
        return SimpleNamespace(data=[SimpleNamespace(b64_json=_TINY_PNG_B64)])

    run_previz_stage(_fact_check_result(), image_fn=_image_fn, output_dir=tmp_path)

    assert captured["model"] == get_stage_model("previz")


def _write_tiny_png(tmp_path):
    import base64

    path = tmp_path / "previz.png"
    path.write_bytes(base64.b64decode(_TINY_PNG_B64))
    return path


def _fake_review_completion(content: str):
    def _completion(**kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )

    return _completion


def test_run_previz_review_stage_accepts(tmp_path):
    image_path = _write_tiny_png(tmp_path)
    payload = {"accepted": True, "concern": None}

    review = run_previz_review_stage(
        image_path,
        _fact_check_result(),
        model="anthropic/claude-sonnet-5",
        completion_fn=_fake_review_completion(json.dumps(payload)),
    )

    assert review.accepted is True
    assert review.concern is None


def test_run_previz_review_stage_parses_response_wrapped_in_markdown_fence(tmp_path):
    # Regression test: this is the exact failure observed for real against
    # a live claude-sonnet-5 call reviewing a real Gemini-generated previz
    # image -- the same prompt returned raw JSON on one call and a
    # ```json-fenced response on the next. See historical_video_ai.json_utils.
    image_path = _write_tiny_png(tmp_path)
    payload = {"accepted": True, "concern": None}

    review = run_previz_review_stage(
        image_path,
        _fact_check_result(),
        model="anthropic/claude-sonnet-5",
        completion_fn=_fake_review_completion(f"```json\n{json.dumps(payload)}\n```"),
    )

    assert review.accepted is True


def test_run_previz_review_stage_rejects_with_concern(tmp_path):
    image_path = _write_tiny_png(tmp_path)
    payload = {"accepted": False, "concern": "Depicts a car that didn't exist yet."}

    review = run_previz_review_stage(
        image_path,
        _fact_check_result(),
        model="anthropic/claude-sonnet-5",
        completion_fn=_fake_review_completion(json.dumps(payload)),
    )

    assert review.accepted is False
    assert review.concern == "Depicts a car that didn't exist yet."


def test_run_previz_review_stage_raises_when_rejected_without_concern(tmp_path):
    image_path = _write_tiny_png(tmp_path)
    payload = {"accepted": False}

    with pytest.raises(PrevizError, match="missing 'concern'"):
        run_previz_review_stage(
            image_path,
            _fact_check_result(),
            model="anthropic/claude-sonnet-5",
            completion_fn=_fake_review_completion(json.dumps(payload)),
        )


def test_run_previz_review_stage_raises_for_invalid_json(tmp_path):
    image_path = _write_tiny_png(tmp_path)

    with pytest.raises(PrevizError, match="not valid JSON"):
        run_previz_review_stage(
            image_path,
            _fact_check_result(),
            model="anthropic/claude-sonnet-5",
            completion_fn=_fake_review_completion("not json"),
        )


def test_run_previz_review_stage_raises_for_non_bool_accepted(tmp_path):
    image_path = _write_tiny_png(tmp_path)
    payload = {"accepted": "yes"}

    with pytest.raises(PrevizError, match="must be true or false"):
        run_previz_review_stage(
            image_path,
            _fact_check_result(),
            model="anthropic/claude-sonnet-5",
            completion_fn=_fake_review_completion(json.dumps(payload)),
        )


def test_run_previz_review_stage_sends_image_as_base64(tmp_path):
    image_path = _write_tiny_png(tmp_path)
    captured = {}

    def _completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps({"accepted": True}))
                )
            ]
        )

    run_previz_review_stage(
        image_path, _fact_check_result(), model="anthropic/claude-sonnet-5", completion_fn=_completion
    )

    content = captured["messages"][0]["content"]
    image_part = next(part for part in content if part["type"] == "image_url")
    assert image_part["image_url"]["url"].startswith("data:image/png;base64,")


def test_run_previz_review_stage_resolves_model_from_config_when_not_passed(tmp_path):
    image_path = _write_tiny_png(tmp_path)
    captured = {}

    def _completion(**kwargs):
        captured["model"] = kwargs["model"]
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps({"accepted": True}))
                )
            ]
        )

    run_previz_review_stage(image_path, _fact_check_result(), completion_fn=_completion)

    assert captured["model"] == get_stage_model("previz_review")
