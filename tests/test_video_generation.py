from pathlib import Path

import pytest

from horror_video_ai.config import get_stage_model
from horror_video_ai.stages.video_generation import (
    MAX_VIDEO_SECONDS,
    MIN_VIDEO_SECONDS,
    VideoGenerationError,
    run_video_generation_stage,
)

_OUTPUT_URL = "https://replicate.delivery/fake/out.mp4"


def _write_fake_image(tmp_path) -> Path:
    """The stage only base64-encodes this file, so arbitrary bytes are
    enough -- unlike the Sora-era stage, nothing opens or resizes it."""
    path = tmp_path / "previz.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n fake png bytes")
    return path


def _prediction_fn(output=_OUTPUT_URL, record=None):
    def _fn(model, input_payload, **kwargs):
        if record is not None:
            record.append({"model": model, "input": input_payload, "kwargs": kwargs})
        return {"id": "pred-1", "status": "succeeded", "output": output, "error": None}

    return _fn


def _download_fn(content=b"fake video bytes", record=None):
    def _fn(url, **kwargs):
        if record is not None:
            record.append(url)
        return content

    return _fn


def test_writes_video_and_returns_result(tmp_path):
    image_path = _write_fake_image(tmp_path)

    result = run_video_generation_stage(
        image_path,
        "a hallway, slow push in",
        model="replicate/owner/model",
        prediction_fn=_prediction_fn(),
        download_fn=_download_fn(),
        output_dir=tmp_path / "out",
    )

    assert result.video_path.read_bytes() == b"fake video bytes"
    assert result.video_path.name == "video.mp4"
    assert result.prompt_used == "a hallway, slow push in"
    assert result.source_image_path == image_path


def test_sends_image_as_data_uri_with_prompt_and_frame_settings(tmp_path):
    image_path = _write_fake_image(tmp_path)
    calls = []

    run_video_generation_stage(
        image_path,
        "a shape at the top of the stairs",
        model="replicate/owner/model",
        prediction_fn=_prediction_fn(record=calls),
        download_fn=_download_fn(),
        output_dir=tmp_path / "out",
    )

    payload = calls[0]["input"]
    assert payload["image"].startswith("data:image/png;base64,")
    assert payload["prompt"] == "a shape at the top of the stairs"
    assert payload["frames_per_second"] == 16
    assert payload["resolution"] == "480p"
    assert calls[0]["model"] == "owner/model"


def test_strips_replicate_prefix_before_calling_the_api(tmp_path):
    image_path = _write_fake_image(tmp_path)
    calls = []

    run_video_generation_stage(
        image_path,
        "prompt",
        model="replicate/wan-video/wan-2.2-i2v-fast",
        prediction_fn=_prediction_fn(record=calls),
        download_fn=_download_fn(),
        output_dir=tmp_path / "out",
    )

    assert calls[0]["model"] == "wan-video/wan-2.2-i2v-fast"


def test_raises_when_model_is_missing_the_replicate_prefix(tmp_path):
    image_path = _write_fake_image(tmp_path)

    with pytest.raises(VideoGenerationError, match="must start with 'replicate/'"):
        run_video_generation_stage(
            image_path,
            "prompt",
            model="openai/sora-2",
            prediction_fn=_prediction_fn(),
            download_fn=_download_fn(),
            output_dir=tmp_path / "out",
        )


def test_default_duration_is_the_models_minimum_frame_count(tmp_path):
    image_path = _write_fake_image(tmp_path)
    calls = []

    result = run_video_generation_stage(
        image_path,
        "prompt",
        model="replicate/owner/model",
        prediction_fn=_prediction_fn(record=calls),
        download_fn=_download_fn(),
        output_dir=tmp_path / "out",
    )

    assert calls[0]["input"]["num_frames"] == 81
    assert result.seconds_actual == pytest.approx(81 / 16)


def test_requested_seconds_are_converted_to_a_frame_count(tmp_path):
    image_path = _write_fake_image(tmp_path)
    calls = []

    result = run_video_generation_stage(
        image_path,
        "prompt",
        model="replicate/owner/model",
        seconds=7.0,
        prediction_fn=_prediction_fn(record=calls),
        download_fn=_download_fn(),
        output_dir=tmp_path / "out",
    )

    assert calls[0]["input"]["num_frames"] == 112
    assert result.seconds_requested == 7.0
    # Actual differs from requested whenever the request doesn't land on a
    # whole frame -- recording both is the point (docs/decisions/0012).
    assert result.seconds_actual == pytest.approx(112 / 16)


@pytest.mark.parametrize("seconds", [4.0, MIN_VIDEO_SECONDS - 0.1, MAX_VIDEO_SECONDS + 0.1, 20.0])
def test_rejects_durations_outside_the_models_range_before_any_call(tmp_path, seconds):
    image_path = _write_fake_image(tmp_path)

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("no API call should happen for an out-of-range duration")

    with pytest.raises(VideoGenerationError, match="outside what this model supports"):
        run_video_generation_stage(
            image_path,
            "prompt",
            model="replicate/owner/model",
            seconds=seconds,
            prediction_fn=_must_not_be_called,
            download_fn=_must_not_be_called,
            output_dir=tmp_path / "out",
        )


def test_accepts_720p_and_rejects_anything_else(tmp_path):
    image_path = _write_fake_image(tmp_path)
    calls = []

    run_video_generation_stage(
        image_path,
        "prompt",
        model="replicate/owner/model",
        resolution="720p",
        prediction_fn=_prediction_fn(record=calls),
        download_fn=_download_fn(),
        output_dir=tmp_path / "out",
    )
    assert calls[0]["input"]["resolution"] == "720p"

    with pytest.raises(VideoGenerationError, match="isn't supported"):
        run_video_generation_stage(
            image_path,
            "prompt",
            model="replicate/owner/model",
            resolution="1080p",
            prediction_fn=_prediction_fn(),
            download_fn=_download_fn(),
            output_dir=tmp_path / "out",
        )


def test_raises_when_reference_image_is_missing(tmp_path):
    with pytest.raises(VideoGenerationError, match="Reference image not found"):
        run_video_generation_stage(
            tmp_path / "nope.png",
            "prompt",
            model="replicate/owner/model",
            prediction_fn=_prediction_fn(),
            download_fn=_download_fn(),
            output_dir=tmp_path / "out",
        )


def test_accepts_a_list_output_as_well_as_a_bare_url(tmp_path):
    image_path = _write_fake_image(tmp_path)
    downloaded = []

    run_video_generation_stage(
        image_path,
        "prompt",
        model="replicate/owner/model",
        prediction_fn=_prediction_fn(output=[_OUTPUT_URL, "second.mp4"]),
        download_fn=_download_fn(record=downloaded),
        output_dir=tmp_path / "out",
    )

    assert downloaded == [_OUTPUT_URL]


@pytest.mark.parametrize("output", [None, "", [], 42])
def test_raises_when_the_finished_prediction_has_no_usable_url(tmp_path, output):
    image_path = _write_fake_image(tmp_path)

    with pytest.raises(VideoGenerationError, match="no usable video URL"):
        run_video_generation_stage(
            image_path,
            "prompt",
            model="replicate/owner/model",
            prediction_fn=_prediction_fn(output=output),
            download_fn=_download_fn(),
            output_dir=tmp_path / "out",
        )


def test_passes_extra_kwargs_through_to_the_prediction_client(tmp_path):
    image_path = _write_fake_image(tmp_path)
    calls = []

    run_video_generation_stage(
        image_path,
        "prompt",
        model="replicate/owner/model",
        prediction_fn=_prediction_fn(record=calls),
        download_fn=_download_fn(),
        output_dir=tmp_path / "out",
        max_poll_attempts=3,
    )

    assert calls[0]["kwargs"]["max_poll_attempts"] == 3


def test_resolves_model_from_config_when_not_passed(tmp_path):
    image_path = _write_fake_image(tmp_path)
    calls = []

    run_video_generation_stage(
        image_path,
        "prompt",
        prediction_fn=_prediction_fn(record=calls),
        download_fn=_download_fn(),
        output_dir=tmp_path / "out",
    )

    expected = get_stage_model("video_generation").removeprefix("replicate/")
    assert calls[0]["model"] == expected
