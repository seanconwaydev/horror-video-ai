import io
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from historical_video_ai.config import get_stage_model
from historical_video_ai.stages.video_generation import (
    VideoGenerationError,
    run_video_generation_stage,
)


def _write_fake_image(tmp_path, size=(720, 1280)) -> Path:
    """A real (if trivial) PNG at `size` -- the stage genuinely opens and
    resizes this with Pillow now, so a real image is needed, not arbitrary
    bytes. Defaults to Sora's exact target size, so most tests exercise the
    "already the right shape" case without a test having to reason about
    the resize itself."""
    path = tmp_path / "previz.png"
    Image.new("RGB", size, color="blue").save(path, format="PNG")
    return path


def _immediate_job_fns(status="completed", error=None, content=b"fake video bytes"):
    """video_fn returns a job already in a terminal state -- no polling needed."""

    def _video_fn(**kwargs):
        return SimpleNamespace(id="job-1", status=status, error=error)

    def _status_fn(**kwargs):
        raise AssertionError("status_fn should not be called when the initial job is terminal")

    def _content_fn(**kwargs):
        return content

    return _video_fn, _status_fn, _content_fn


def test_run_video_generation_stage_writes_video_and_returns_result(tmp_path):
    image_path = _write_fake_image(tmp_path)
    video_fn, status_fn, content_fn = _immediate_job_fns()

    result = run_video_generation_stage(
        image_path,
        "a prompt",
        model="openai/sora-2",
        video_fn=video_fn,
        status_fn=status_fn,
        content_fn=content_fn,
        sleep_fn=lambda _seconds: None,
        output_dir=tmp_path,
        output_filename="video.mp4",
    )

    assert result.video_path == tmp_path / "video.mp4"
    assert result.video_path.read_bytes() == b"fake video bytes"
    assert result.prompt_used == "a prompt"
    assert result.source_image_path == image_path


def test_run_video_generation_stage_passes_resized_image_and_prompt_through(tmp_path):
    # Source is already 1280x2276 -- same 9:16-ish ratio Gemini produces,
    # not the exact target size -- so this exercises an actual resize, not
    # a no-op.
    image_path = _write_fake_image(tmp_path, size=(1280, 2276))
    captured = {}

    def _video_fn(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id="job-1", status="completed", error=None)

    run_video_generation_stage(
        image_path,
        "a very specific prompt",
        model="openai/sora-2",
        video_fn=_video_fn,
        status_fn=lambda **kw: None,
        content_fn=lambda **kw: b"x",
        sleep_fn=lambda _seconds: None,
        output_dir=tmp_path,
    )

    assert captured["prompt"] == "a very specific prompt"
    assert captured["model"] == "openai/sora-2"
    # Resized to Sora's exact target size, not the raw file bytes -- see
    # run_video_generation_stage's comment on why (Sora requires a
    # pixel-exact match to the requested `size`).
    assert captured["size"] == "720x1280"
    with Image.open(io.BytesIO(captured["input_reference"])) as resized:
        assert resized.size == (720, 1280)
    assert captured["input_reference"] != image_path.read_bytes()


def test_run_video_generation_stage_raises_when_aspect_ratio_too_different(tmp_path):
    # previz's old landscape default (3:2) -- wildly different from Sora's
    # portrait 9:16 target. Regression test for docs/decisions/0011: this
    # must refuse rather than silently produce a badly distorted video.
    image_path = _write_fake_image(tmp_path, size=(1536, 1024))
    video_fn, status_fn, content_fn = _immediate_job_fns()

    with pytest.raises(VideoGenerationError, match="too different"):
        run_video_generation_stage(
            image_path,
            "a prompt",
            model="openai/sora-2",
            video_fn=video_fn,
            status_fn=status_fn,
            content_fn=content_fn,
            sleep_fn=lambda _seconds: None,
            output_dir=tmp_path,
        )


def test_run_video_generation_stage_polls_until_completed(tmp_path):
    image_path = _write_fake_image(tmp_path)
    statuses = iter(["in_progress", "in_progress", "completed"])

    def _video_fn(**kwargs):
        return SimpleNamespace(id="job-1", status="queued", error=None)

    def _status_fn(**kwargs):
        return SimpleNamespace(id="job-1", status=next(statuses), error=None)

    sleeps: list[float] = []
    result = run_video_generation_stage(
        image_path,
        "a prompt",
        model="openai/sora-2",
        video_fn=_video_fn,
        status_fn=_status_fn,
        content_fn=lambda **kw: b"fake video bytes",
        sleep_fn=sleeps.append,
        output_dir=tmp_path,
    )

    assert result.video_path.exists()
    assert len(sleeps) == 3  # one poll per status_fn call above


def test_run_video_generation_stage_raises_on_missing_image(tmp_path):
    with pytest.raises(VideoGenerationError, match="not found"):
        run_video_generation_stage(
            tmp_path / "missing.png",
            "a prompt",
            model="openai/sora-2",
            video_fn=lambda **kw: SimpleNamespace(id="x", status="completed", error=None),
            status_fn=lambda **kw: None,
            content_fn=lambda **kw: b"x",
            output_dir=tmp_path,
        )


def test_run_video_generation_stage_raises_on_missing_job_id(tmp_path):
    image_path = _write_fake_image(tmp_path)

    def _video_fn(**kwargs):
        return SimpleNamespace(id=None, status="queued", error=None)

    with pytest.raises(VideoGenerationError, match="no job id"):
        run_video_generation_stage(
            image_path,
            "a prompt",
            model="openai/sora-2",
            video_fn=_video_fn,
            status_fn=lambda **kw: None,
            content_fn=lambda **kw: b"x",
            output_dir=tmp_path,
        )


def test_run_video_generation_stage_raises_on_failed_status(tmp_path):
    image_path = _write_fake_image(tmp_path)
    video_fn, status_fn, content_fn = _immediate_job_fns(
        status="failed", error={"message": "content policy violation"}
    )

    with pytest.raises(VideoGenerationError, match="content policy violation"):
        run_video_generation_stage(
            image_path,
            "a prompt",
            model="openai/sora-2",
            video_fn=video_fn,
            status_fn=status_fn,
            content_fn=content_fn,
            sleep_fn=lambda _seconds: None,
            output_dir=tmp_path,
        )


def test_run_video_generation_stage_raises_after_max_poll_attempts(tmp_path):
    image_path = _write_fake_image(tmp_path)

    def _video_fn(**kwargs):
        return SimpleNamespace(id="job-1", status="queued", error=None)

    def _status_fn(**kwargs):
        return SimpleNamespace(id="job-1", status="in_progress", error=None)

    with pytest.raises(VideoGenerationError, match="did not finish"):
        run_video_generation_stage(
            image_path,
            "a prompt",
            model="openai/sora-2",
            video_fn=_video_fn,
            status_fn=_status_fn,
            content_fn=lambda **kw: b"x",
            sleep_fn=lambda _seconds: None,
            max_poll_attempts=2,
            output_dir=tmp_path,
        )


def test_run_video_generation_stage_raises_on_empty_content(tmp_path):
    image_path = _write_fake_image(tmp_path)
    video_fn, status_fn, _ = _immediate_job_fns()

    with pytest.raises(VideoGenerationError, match="no video data"):
        run_video_generation_stage(
            image_path,
            "a prompt",
            model="openai/sora-2",
            video_fn=video_fn,
            status_fn=status_fn,
            content_fn=lambda **kw: b"",
            sleep_fn=lambda _seconds: None,
            output_dir=tmp_path,
        )


def test_run_video_generation_stage_resolves_model_from_config_when_not_passed(tmp_path):
    image_path = _write_fake_image(tmp_path)
    captured = {}

    def _video_fn(**kwargs):
        captured["model"] = kwargs["model"]
        return SimpleNamespace(id="job-1", status="completed", error=None)

    run_video_generation_stage(
        image_path,
        "a prompt",
        video_fn=_video_fn,
        status_fn=lambda **kw: None,
        content_fn=lambda **kw: b"x",
        sleep_fn=lambda _seconds: None,
        output_dir=tmp_path,
    )

    assert captured["model"] == get_stage_model("video_generation")
