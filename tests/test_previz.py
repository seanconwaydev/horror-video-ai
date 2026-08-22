from types import SimpleNamespace

import pytest

from historical_video_ai.config import get_stage_model
from historical_video_ai.stages.fact_check import ClaimFlag, FactCheckResult
from historical_video_ai.stages.previz import PrevizError, run_previz_stage
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
        model="openai/gpt-image-1-mini",
        image_fn=_fake_image_fn(_TINY_PNG_B64),
        output_dir=tmp_path,
    )

    assert result.image_path.exists()
    assert result.image_path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic bytes
    assert "Kitty Hawk" in result.prompt_used


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
        model="openai/gpt-image-1-mini",
        image_fn=_fake_image_fn(_TINY_PNG_B64),
        output_dir=tmp_path,
    )

    assert "This claim will be contradicted." in result.prompt_used
    assert "undeveloped in 1903" in result.prompt_used


def test_run_previz_stage_raises_when_no_image_data(tmp_path):
    def _empty_image_fn(**kwargs):
        return SimpleNamespace(data=[])

    with pytest.raises(PrevizError, match="no image data"):
        run_previz_stage(
            _fact_check_result(),
            model="openai/gpt-image-1-mini",
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
