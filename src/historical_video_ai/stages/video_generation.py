"""Stage 9: Video generation -- render one video clip from a single
approved previz image and the prompt that produced it.

See docs/pipeline.md ("9. Video generation") for the stage's role in the
eventual pipeline, and docs/decisions/0010-video-generation-model-and-
standalone-stage.md for why this is scoped to one image + one prompt per
call (multiple scenes are the caller's loop, not this function's job -- see
cli.py's `_run_video_generation_only`) and why the pinned model is a
placeholder.

Model note: pinned to an OpenAI video model (`openai/sora-2`) as a starting
placeholder, not a rigorously compared decision -- see docs/decisions/0010.
Google's Veo (via the vertex_ai/gemini providers) is a real next candidate,
per that ADR.

Unlike previz's synchronous image_generation() call, video generation is an
async job: video_generation() creates it, video_status() is polled until it
reaches a terminal state, and video_content() fetches the finished bytes.

Known-working, not just unverified-and-hoped-for: getting a real Sora-2
call to succeed took two rounds of direct reproduction against real (if
unpaid) requests, each surfacing a genuine litellm bug or a genuine API
requirement, not a mistake in this module -- see
_litellm_workarounds.py's video-generation workaround (internal params
leaking into the request body) and this module's own comments on passing
raw bytes instead of a Path (litellm's os.PathLike support for
input_reference is broken) and resizing to Sora's exact required size
(Sora rejects any reference image that doesn't pixel-match the requested
`size`). What's still genuinely unverified is a full, successful, paid
run all the way through to a downloaded video file.
"""

from __future__ import annotations

import io
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import litellm
from PIL import Image

from historical_video_ai import _litellm_workarounds  # noqa: F401 -- see CLAUDE.md
from historical_video_ai.config import get_stage_model

# Sora-2 only accepts two fixed sizes (720x1280 portrait or 1280x720
# landscape) and requires the reference image to match exactly. Portrait,
# matching this project's Shorts-only format (docs/decisions/0002). See
# docs/decisions/0011-previz-image-model-for-video-aspect-ratio-fit.md for
# why previz targets a close aspect ratio (Gemini's 9:16) instead of
# leaving this to a large, content-losing crop.
_TARGET_VIDEO_SIZE = (720, 1280)
_TARGET_VIDEO_SIZE_STR = "720x1280"

# How far a reference image's aspect ratio may deviate from the target
# before resizing it would visibly distort the scene (stretching people/
# objects) rather than a barely-perceptible sub-1% adjustment. Gemini's
# 9:16 output measured ~0.8% off Sora's exact ratio -- comfortably under
# this; a landscape image (previz's old default) is wildly over it. Refuse
# rather than silently produce a distorted video, same fail-loud principle
# as everything else in this stage.
_MAX_ASPECT_RATIO_DEVIATION = 0.10

_TERMINAL_SUCCESS_STATUS = "completed"
# Covers the terminal-failure vocabulary used by both provider families
# litellm currently supports for video generation (OpenAI's Sora API and
# Google's Veo) -- if a provider's error status doesn't match this, the
# stage keeps polling until max_poll_attempts is exhausted rather than
# guessing at an unrecognized status, per this project's fail-loud
# convention.
_TERMINAL_FAILURE_STATUSES = {"failed", "cancelled", "canceled", "expired"}


class VideoGenerationError(Exception):
    """Raised when video generation fails, times out, or the response is malformed."""


@dataclass(frozen=True)
class VideoGenerationResult:
    """The reviewable artifact stage 9 produces: the video clip itself,
    plus the prompt and reference image actually used to generate it (so a
    human spot-checking it, per docs/pipeline.md's stage 9 review gate, can
    see what was asked for, not just what came back)."""

    video_path: Path
    prompt_used: str
    source_image_path: Path


def _resize_reference_image(image_bytes: bytes, target_size: tuple[int, int]) -> bytes:
    """Resize a reference image to exactly `target_size`, required because
    Sora rejects a reference image that isn't pixel-exact to the video's
    requested size (confirmed by reproduction: "Inpaint image must match
    the requested width and height"). A plain resize only makes sense when
    the source is already close to the target aspect ratio -- otherwise
    it's a distorting stretch, not the barely-perceptible adjustment this
    is meant to be (see docs/decisions/0011). Padding was considered and
    rejected instead of resizing: OpenAI's own docs confirm the reference
    image becomes the video's literal first frame with no
    outpainting/masking, so padding bars would get baked into the video as
    fake visible content, not held invisibly like real letterboxing.

    Raises VideoGenerationError if the source aspect ratio deviates from
    the target by more than _MAX_ASPECT_RATIO_DEVIATION, rather than
    silently stretching a mismatched image (e.g. previz's old landscape
    default) into a badly distorted video.
    """
    with Image.open(io.BytesIO(image_bytes)) as img:
        width, height = img.size
        source_ratio = width / height
        target_ratio = target_size[0] / target_size[1]
        deviation = abs(source_ratio - target_ratio) / target_ratio
        if deviation > _MAX_ASPECT_RATIO_DEVIATION:
            raise VideoGenerationError(
                f"Reference image is {width}x{height} (aspect ratio {source_ratio:.3f}), "
                f"too different from the target video size {target_size[0]}x{target_size[1]} "
                f"(aspect ratio {target_ratio:.3f}, {deviation:.1%} deviation, max allowed "
                f"{_MAX_ASPECT_RATIO_DEVIATION:.0%}) to resize without visibly distorting the "
                "scene -- regenerate previz with a model/size close to this aspect ratio "
                "(see docs/decisions/0011-previz-image-model-for-video-aspect-ratio-fit.md)."
            )
        resized = img.convert("RGB").resize(target_size)
        buffer = io.BytesIO()
        resized.save(buffer, format="PNG")
        return buffer.getvalue()


def run_video_generation_stage(
    image_path: Path,
    prompt: str,
    *,
    model: str | None = None,
    video_fn: Callable = litellm.video_generation,
    status_fn: Callable = litellm.video_status,
    content_fn: Callable = litellm.video_content,
    sleep_fn: Callable[[float], None] = time.sleep,
    poll_interval_seconds: float = 10.0,
    max_poll_attempts: int = 60,
    output_dir: Path = Path("outputs"),
    output_filename: str = "video.mp4",
) -> VideoGenerationResult:
    """Generate one video clip from a single reference image and prompt.

    `model` defaults to the pinned model for the "video_generation" stage in
    config/models.yaml. `video_fn`/`status_fn`/`content_fn` default to
    litellm's video_generation/video_status/video_content and exist as
    injection points for tests -- pass fakes to avoid a real API call, real
    waiting, or writing a real file. `sleep_fn` defaults to time.sleep for
    the same reason: tests inject a no-op so the polling loop doesn't
    actually wait in real time.

    Polls at `poll_interval_seconds` between checks, up to
    `max_poll_attempts` times, before giving up -- bounded the same way
    previz's regeneration loop is bounded (docs/decisions/0009), rather than
    waiting indefinitely on a job that may never finish.

    Raises VideoGenerationError if `image_path` doesn't exist, the creation
    response has no job id, the job ends in a recognized failure status, the
    job never reaches a terminal status within `max_poll_attempts`, or the
    finished job returns no video bytes -- fail-loud on anything unexpected
    rather than silently producing an empty or missing file.
    """
    if not image_path.exists():
        raise VideoGenerationError(f"Reference image not found: {image_path}")

    resolved_model = model or get_stage_model("video_generation")

    # Read the file ourselves and pass raw bytes rather than the Path
    # object itself: litellm's video_generation() signature advertises
    # os.PathLike as an accepted input_reference type, but the actual
    # OpenAI-provider code path for it is broken -- it hands the bare Path
    # straight to httpx's multipart file field, which only knows how to
    # render `bytes` or a real file-like object with .read()/.seek(), not
    # a Path (confirmed by reproduction: AttributeError: 'PosixPath'
    # object has no attribute 'read'). Passing bytes sidesteps that path
    # entirely -- litellm's own image-content-type detection and
    # multipart-attachment code both handle raw bytes correctly.
    #
    # The image also has to be resized to Sora's exact required pixel
    # size first (see _resize_reference_image) -- and `size` has to be
    # passed explicitly here too, since Sora checks the reference image
    # against whatever size was *requested*, not just its own default
    # (confirmed by reproduction: omitting `size` still rejected an image
    # that didn't match Sora's unstated default).
    resized_image_bytes = _resize_reference_image(image_path.read_bytes(), _TARGET_VIDEO_SIZE)
    job = video_fn(
        model=resolved_model,
        prompt=prompt,
        input_reference=resized_image_bytes,
        size=_TARGET_VIDEO_SIZE_STR,
    )
    job_id = getattr(job, "id", None)
    if not job_id:
        raise VideoGenerationError(f"Video generation response had no job id: {job!r}")

    status = getattr(job, "status", None)
    attempts = 0
    while status != _TERMINAL_SUCCESS_STATUS and status not in _TERMINAL_FAILURE_STATUSES:
        attempts += 1
        if attempts > max_poll_attempts:
            raise VideoGenerationError(
                f"Video generation job {job_id} did not finish after "
                f"{max_poll_attempts} polling attempts (last status: {status!r})."
            )
        sleep_fn(poll_interval_seconds)
        job = status_fn(video_id=job_id)
        status = getattr(job, "status", None)

    if status in _TERMINAL_FAILURE_STATUSES:
        error = getattr(job, "error", None)
        raise VideoGenerationError(
            f"Video generation job {job_id} ended with status {status!r}: {error}"
        )

    video_bytes = content_fn(video_id=job_id)
    if not video_bytes:
        raise VideoGenerationError(
            f"Video generation job {job_id} completed but returned no video data."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    video_path = output_dir / output_filename
    video_path.write_bytes(video_bytes)

    return VideoGenerationResult(
        video_path=video_path, prompt_used=prompt, source_image_path=image_path
    )
