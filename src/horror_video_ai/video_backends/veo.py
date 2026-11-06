"""Veo 3.1 via the Gemini API, through litellm.

The cheapest direct option and the only one needing no new account: it
runs on the `GEMINI_API_KEY` already in `.env`, pay-as-you-go, and
litellm 1.101.0 ships a `gemini/videos` provider, so this stays on the
project's normal `litellm` path (docs/decisions/0003) instead of adding
another REST client.

Two real constraints, both verified against the installed litellm rather
than documentation:

- **8 seconds is the ceiling for one call**, and only 4, 6 or 8 are
  accepted. A 15-second short is therefore several calls concatenated,
  and shot durations are snapped to the nearest legal value -- so the
  finished runtime can differ by a second or two from what was written.
- litellm maps `size` to Veo's `aspectRatio` and `resolution` via a fixed
  table: "720x1280" is 9:16 at 720p, "1080x1920" is 9:16 at 1080p. Any
  other size silently becomes 16:9, which for a vertical short is a
  ruined generation, so only those two presets are offered here.

Concatenation shells out to `ffmpeg`, the same external dependency
`evals/motion_test.py` already needs. It is checked in `validate()` --
before anything is spent -- because discovering it is missing after
paying for four clips is exactly the failure that check exists to avoid.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import litellm

from horror_video_ai.stages.shot_writing import ShotList
from horror_video_ai.video_backends._http import VideoBackendError
from horror_video_ai.video_backends.base import (
    PORTRAIT_9_16,
    GeneratedVideo,
    cost_per_second,
)

_ALLOWED_SECONDS = (4, 6, 8)
_SIZE_FOR_RESOLUTION = {"720p": "720x1280", "1080p": "1080x1920"}
_PROVIDER = "gemini"
_POLL_INTERVAL_SECONDS = 10.0
_MAX_POLL_ATTEMPTS = 120
_TERMINAL_OK = {"completed", "succeeded"}
_TERMINAL_BAD = {"failed", "cancelled", "canceled"}


_MISSING_CREDENTIALS = (
    "GEMINI_API_KEY is not set -- add it to .env (see .env.example). It is the "
    "same key the rest of the pipeline already uses."
)


def credentials_problem() -> str | None:
    """Why this backend cannot be called, or None when it can.

    litellm reads `GEMINI_API_KEY` from the environment itself, so nothing
    here passes the value anywhere; this exists so that a missing key is
    reported by `validate()`, before the spend prompt, instead of failing
    the first generation call.
    """
    return None if os.environ.get("GEMINI_API_KEY") else _MISSING_CREDENTIALS


def snap_seconds(seconds: int) -> int:
    """The nearest duration Veo actually accepts, preferring the shorter
    on a tie so a snap never silently costs more than asked for."""
    return min(_ALLOWED_SECONDS, key=lambda allowed: (abs(allowed - seconds), allowed))


class VeoBackend:
    """Veo 3.1 (lite / fast / quality) on the Gemini API."""

    supports_multishot = False
    max_seconds_per_call = max(_ALLOWED_SECONDS)

    def __init__(
        self,
        model: str,
        *,
        resolution: str = "720p",
        generation_fn: Callable[..., Any] = litellm.video_generation,
        status_fn: Callable[..., Any] = litellm.video_status,
        content_fn: Callable[..., Any] = litellm.video_content,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        if resolution not in _SIZE_FOR_RESOLUTION:
            raise VideoBackendError(
                f"Resolution {resolution!r} is not one of {sorted(_SIZE_FOR_RESOLUTION)}"
            )
        self.name = "veo"
        self.model = model
        self.resolution = resolution
        self._generation_fn = generation_fn
        self._status_fn = status_fn
        self._content_fn = content_fn
        self._sleep_fn = sleep_fn

    def validate(self, shot_list: ShotList) -> list[str]:
        problems = []
        missing = credentials_problem()
        if missing is not None:
            problems.append(missing)
        if shutil.which("ffmpeg") is None:
            problems.append(
                "ffmpeg is not installed, and Veo needs it to join its 8-second "
                "clips into one short (macOS: brew install ffmpeg)"
            )
        snapped = sum(snap_seconds(s.duration_seconds) for s in shot_list.shots)
        if snapped != shot_list.total_seconds:
            problems.append(
                f"note: Veo only generates {_ALLOWED_SECONDS} second clips, so this "
                f"will run {snapped}s rather than {shot_list.total_seconds}s"
            )
        return problems

    def estimate_cost_usd(self, seconds: int) -> float | None:
        rate = cost_per_second(self.model)
        return None if rate is None else rate * seconds

    def generate(
        self, shot_list: ShotList, *, aspect_ratio: str = PORTRAIT_9_16
    ) -> GeneratedVideo:
        if aspect_ratio != PORTRAIT_9_16:
            raise VideoBackendError(
                f"This backend is wired for {PORTRAIT_9_16} only, got {aspect_ratio!r}"
            )
        payloads: list[dict[str, Any]] = []
        clips: list[bytes] = []
        for index, shot in enumerate(shot_list.shots, start=1):
            seconds = snap_seconds(shot.duration_seconds)
            payload = {
                "model": self.model,
                "prompt": f"{shot_list.look} {shot.prompt}",
                "seconds": str(seconds),
                "size": _SIZE_FOR_RESOLUTION[self.resolution],
                "negativePrompt": shot_list.negative_prompt,
            }
            payloads.append(payload)
            print(f"  shot {index}/{len(shot_list.shots)} ({seconds}s)...")
            clips.append(self._generate_one(payload))
        return GeneratedVideo(
            data=_concatenate(clips),
            backend=self.name,
            seconds=sum(snap_seconds(s.duration_seconds) for s in shot_list.shots),
            request_payloads=payloads,
        )

    def _generate_one(self, payload: dict[str, Any]) -> bytes:
        video = self._generation_fn(**payload)
        video_id = getattr(video, "id", None)
        if not video_id:
            raise VideoBackendError(f"Veo returned no video id: {video!r}")
        status = getattr(video, "status", None)
        attempts = 0
        while status not in _TERMINAL_OK:
            if status in _TERMINAL_BAD:
                raise VideoBackendError(
                    f"Veo generation {video_id} ended as {status!r}: "
                    f"{getattr(video, 'error', None)}"
                )
            attempts += 1
            if attempts > _MAX_POLL_ATTEMPTS:
                raise VideoBackendError(
                    f"Veo generation {video_id} did not finish after "
                    f"{_MAX_POLL_ATTEMPTS} polls (last status: {status!r})"
                )
            self._sleep_fn(_POLL_INTERVAL_SECONDS)
            video = self._status_fn(video_id=video_id, custom_llm_provider=_PROVIDER)
            status = getattr(video, "status", None)
        data = self._content_fn(video_id=video_id, custom_llm_provider=_PROVIDER)
        if not isinstance(data, bytes) or not data:
            raise VideoBackendError(f"Veo returned no content for {video_id}")
        return data


def _concatenate(clips: list[bytes]) -> bytes:
    """Join clips with ffmpeg's concat demuxer, which copies streams
    rather than re-encoding -- these come from one model at one size, so
    there is nothing to normalise and no generation loss to take."""
    if len(clips) == 1:
        return clips[0]
    if shutil.which("ffmpeg") is None:
        raise VideoBackendError("ffmpeg is required to join Veo's clips but is not installed.")
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        parts = []
        for index, clip in enumerate(clips):
            part = directory / f"part_{index:02d}.mp4"
            part.write_bytes(clip)
            parts.append(part)
        listing = directory / "parts.txt"
        listing.write_text("".join(f"file '{p.name}'\n" for p in parts))
        output = directory / "joined.mp4"
        result = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "concat",
                "-safe", "0", "-i", str(listing), "-c", "copy", str(output),
            ],
            cwd=directory,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or not output.exists():
            raise VideoBackendError(f"ffmpeg failed to join the clips: {result.stderr.strip()}")
        return output.read_bytes()
