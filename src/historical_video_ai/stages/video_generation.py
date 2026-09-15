"""Stage 9: Video generation -- render one video clip from a single
approved previz image and the prompt that produced it. See
docs/pipeline.md ("9. Video generation") and docs/decisions/0010 for why
this is scoped to one image + one prompt per call (the caller loops for
multiple scenes -- cli.py's `_run_video_generation_only`).

Model: Wan 2.2 image-to-video, hosted on Replicate and called directly
rather than through litellm -- docs/decisions/0037 (the decision) and
0038 (this implementation). Replicate's prediction API is async; the
polling and HTTP live in `replicate_client`, not here.

Two real API-shape facts worth keeping, since a type signature can't
carry them:

- Duration is expressed as `num_frames` at a given `frames_per_second`,
  not a seconds enum. The model accepts 81-121 frames, so at Replicate's
  billing-reference 16fps the real duration range is ~5.06s to ~7.56s --
  much narrower than Sora's old 4-20s, and worth knowing before planning
  a beat around a specific length.
- The output video's aspect ratio follows the input image's, so no
  resizing or pixel-exact matching is needed (Sora required both). This
  is why previz's image model no longer has to be chosen for
  aspect-ratio fit -- see docs/decisions/0038 on 0011 being void.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from historical_video_ai.config import get_stage_model
from historical_video_ai.replicate_client import (
    download_output,
    file_to_data_uri,
    run_prediction,
)

# Replicate prices this model against duration at 16fps, so frame counts
# are converted at 16fps here too -- a different fps would silently change
# what a requested "5 seconds" costs.
_FPS = 16
_MIN_FRAMES = 81
_MAX_FRAMES = 121

MIN_VIDEO_SECONDS = _MIN_FRAMES / _FPS
MAX_VIDEO_SECONDS = _MAX_FRAMES / _FPS

# 81 frames -- the model card's own "81 frames give the best results".
_DEFAULT_VIDEO_SECONDS = _MIN_FRAMES / _FPS

# 480p (480x832 at 9:16) rather than 720p: this project generates many
# short iterations and 720p costs roughly double per clip. Overridable
# per call for a take actually intended for publishing.
_DEFAULT_RESOLUTION = "480p"
_VALID_RESOLUTIONS = frozenset({"480p", "720p"})


class VideoGenerationError(Exception):
    """Raised when video generation fails, times out, or the response is malformed."""


@dataclass(frozen=True)
class VideoGenerationResult:
    """The reviewable artifact stage 9 produces: the video clip itself,
    plus the prompt and reference image actually used to generate it (so a
    human spot-checking it, per docs/pipeline.md's stage 9 review gate, can
    see what was asked for, not just what came back).

    `seconds_requested` is what the caller asked for; `seconds_actual` is
    what the clip really is, which differs whenever the request didn't
    land exactly on a whole frame boundary (docs/decisions/0012's original
    reason for recording both)."""

    video_path: Path
    prompt_used: str
    source_image_path: Path
    seconds_requested: float
    seconds_actual: float


def _resolve_replicate_model(model: str) -> str:
    """Strip config/models.yaml's "replicate/" marker to get the bare
    "owner/name" slug Replicate's API expects.

    The prefix exists so a reader of models.yaml can tell at a glance that
    this one stage doesn't go through litellm like every other stage's
    "<provider>/<model>" string does (docs/decisions/0003, 0037). Missing
    prefix is a config error rather than a silent guess.
    """
    if not model.startswith("replicate/"):
        raise VideoGenerationError(
            f"video_generation model {model!r} must start with 'replicate/' -- this stage "
            "calls Replicate directly rather than litellm (docs/decisions/0037). Fix the "
            "'video_generation' entry in config/models.yaml."
        )
    return model.removeprefix("replicate/")


def _frames_for_seconds(seconds: float) -> int:
    """Convert a requested duration to a frame count, failing loud when
    it's outside what the model accepts.

    Refusing rather than clamping, on the same reasoning as
    docs/decisions/0020: a silently shortened clip is a confusing result
    to debug later, while a rejected request says exactly what's wrong
    before anything is spent.
    """
    if seconds < MIN_VIDEO_SECONDS or seconds > MAX_VIDEO_SECONDS:
        raise VideoGenerationError(
            f"Requested duration {seconds}s is outside what this model supports "
            f"({MIN_VIDEO_SECONDS:.2f}s to {MAX_VIDEO_SECONDS:.2f}s -- {_MIN_FRAMES} to "
            f"{_MAX_FRAMES} frames at {_FPS}fps)."
        )
    return round(seconds * _FPS)


def run_video_generation_stage(
    image_path: Path,
    prompt: str,
    *,
    model: str | None = None,
    seconds: float = _DEFAULT_VIDEO_SECONDS,
    resolution: str = _DEFAULT_RESOLUTION,
    prediction_fn: Callable = run_prediction,
    download_fn: Callable = download_output,
    output_dir: Path = Path("outputs"),
    output_filename: str = "video.mp4",
    **prediction_kwargs: object,
) -> VideoGenerationResult:
    """Generate one video clip from a single reference image and prompt.

    `model` defaults to the pinned "video_generation" model.
    `prediction_fn`/`download_fn` are injection points for tests; any
    extra `prediction_kwargs` (e.g. `sleep_fn`, `max_poll_attempts`) pass
    straight through to the Replicate client's polling loop.

    Raises VideoGenerationError if `seconds`/`resolution` are out of
    range, `image_path` doesn't exist, or the finished prediction has no
    usable output. ReplicateError propagates uncaught for transport and
    prediction failures -- same fail-loud convention as every other stage.
    """
    if resolution not in _VALID_RESOLUTIONS:
        raise VideoGenerationError(
            f"Resolution {resolution!r} isn't supported -- use one of "
            f"{sorted(_VALID_RESOLUTIONS)}."
        )
    if not image_path.exists():
        raise VideoGenerationError(f"Reference image not found: {image_path}")

    num_frames = _frames_for_seconds(seconds)
    resolved_model = _resolve_replicate_model(model or get_stage_model("video_generation"))

    prediction = prediction_fn(
        resolved_model,
        {
            "image": file_to_data_uri(image_path),
            "prompt": prompt,
            "num_frames": num_frames,
            "frames_per_second": _FPS,
            "resolution": resolution,
        },
        **prediction_kwargs,
    )

    # This model's output is a single URI string. A list is tolerated
    # because several Replicate video models return one, and a future
    # model swap shouldn't fail on a difference that costs one line here.
    output = prediction.get("output")
    if isinstance(output, list):
        output = output[0] if output else None
    if not isinstance(output, str) or not output:
        raise VideoGenerationError(
            f"Replicate prediction {prediction.get('id')!r} completed but returned no "
            f"usable video URL (output was {prediction.get('output')!r})."
        )

    video_bytes = download_fn(output)

    output_dir.mkdir(parents=True, exist_ok=True)
    video_path = output_dir / output_filename
    video_path.write_bytes(video_bytes)

    return VideoGenerationResult(
        video_path=video_path,
        prompt_used=prompt,
        source_image_path=image_path,
        seconds_requested=seconds,
        seconds_actual=num_frames / _FPS,
    )
