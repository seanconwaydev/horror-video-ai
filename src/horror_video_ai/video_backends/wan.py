"""Wan via Alibaba's own Model Studio (DashScope), not an aggregator.

The project already runs Wan 2.2 through Replicate for the existing
image-to-video stage. This reaches a newer Wan directly at roughly
$0.07/second, and DashScope is also the only route that returns video
without a watermark.

**The wire format here is UNVERIFIED against a live account** -- written
to DashScope's documented asynchronous scheme but never exercised. Treat
the first live call as a probe. The model string is a config pin rather
than a constant precisely so a wrong guess is a one-line fix in
`config/models.yaml` and not a code change.

DashScope is asynchronous by header: the create request must carry
`X-DashScope-Async: enable`, which returns a task id to poll. Omitting
the header changes the response shape entirely, which is the kind of
thing that looks like a parsing bug.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any

from horror_video_ai.stages.shot_writing import ShotList
from horror_video_ai.video_backends._http import VideoBackendError, download, request_json
from horror_video_ai.video_backends.base import PORTRAIT_9_16, GeneratedVideo

API_BASE = "https://dashscope-intl.aliyuncs.com/api/v1"
_SYNTHESIS_PATH = "/services/aigc/video-generation/video-synthesis"

# Wan generates a single clip per call and has no multi-shot mode, so a
# multi-shot list is rendered as one continuous take from the joined
# prompts rather than as cuts.
MAX_SECONDS = 10

_POLL_INTERVAL_SECONDS = 10.0
_MAX_POLL_ATTEMPTS = 180
_LIST_PRICE_PER_SECOND_USD = 0.0708

_SIZE_FOR_RESOLUTION = {"720p": "720*1280", "1080p": "1080*1920"}


_MISSING_CREDENTIALS = (
    "DASHSCOPE_API_KEY is not set -- add it to .env (see .env.example). "
    "This is Alibaba Model Studio's key, not a Replicate token."
)


def credentials_problem() -> str | None:
    """Why this backend cannot be called, or None when it can. Read by
    `validate()` so a missing key skips this backend before the spend
    prompt rather than raising after other backends have been paid for."""
    return None if os.environ.get("DASHSCOPE_API_KEY") else _MISSING_CREDENTIALS


def resolve_api_key(api_key: str | None = None) -> str:
    key = api_key or os.environ.get("DASHSCOPE_API_KEY")
    if not key:
        raise VideoBackendError(_MISSING_CREDENTIALS)
    return key


class WanBackend:
    """Wan on DashScope. One continuous clip, no cuts."""

    supports_multishot = False
    max_seconds_per_call = MAX_SECONDS

    def __init__(
        self,
        model: str,
        *,
        resolution: str = "720p",
        request_fn: Callable[..., dict] = request_json,
        download_fn: Callable[[str], bytes] = download,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        if resolution not in _SIZE_FOR_RESOLUTION:
            raise VideoBackendError(
                f"Resolution {resolution!r} is not one of {sorted(_SIZE_FOR_RESOLUTION)}"
            )
        self.name = "wan"
        # Strip the config's "<provider>/" prefix -- see kling.py.
        self.model = model.removeprefix("dashscope/")
        self.resolution = resolution
        self._request_fn = request_fn
        self._download_fn = download_fn
        self._sleep_fn = sleep_fn

    def validate(self, shot_list: ShotList) -> list[str]:
        problems = []
        missing = credentials_problem()
        if missing is not None:
            problems.append(missing)
        if shot_list.total_seconds > MAX_SECONDS:
            problems.append(
                f"{shot_list.total_seconds}s requested -- Wan's ceiling is {MAX_SECONDS}s, "
                "so this will be truncated"
            )
        if len(shot_list.shots) > 1:
            problems.append(
                f"note: Wan has no multi-shot mode, so these {len(shot_list.shots)} shots "
                "become one continuous take rather than cuts"
            )
        return problems

    def estimate_cost_usd(self, seconds: int) -> float | None:
        return _LIST_PRICE_PER_SECOND_USD * min(seconds, MAX_SECONDS)

    def build_payload(self, shot_list: ShotList, *, aspect_ratio: str) -> dict[str, Any]:
        """The exact request body, separated so a test can assert it
        without a network call."""
        if aspect_ratio != PORTRAIT_9_16:
            raise VideoBackendError(
                f"This backend is wired for {PORTRAIT_9_16} only, got {aspect_ratio!r}"
            )
        joined = " ".join(shot.prompt for shot in shot_list.shots)
        return {
            "model": self.model,
            "input": {
                "prompt": f"{shot_list.look} {joined}",
                "negative_prompt": shot_list.negative_prompt,
            },
            "parameters": {
                "size": _SIZE_FOR_RESOLUTION[self.resolution],
                "duration": min(shot_list.total_seconds, MAX_SECONDS),
            },
        }

    def generate(
        self, shot_list: ShotList, *, aspect_ratio: str = PORTRAIT_9_16
    ) -> GeneratedVideo:
        headers = {
            "Authorization": f"Bearer {resolve_api_key()}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
        }
        payload = self.build_payload(shot_list, aspect_ratio=aspect_ratio)
        created = self._request_fn(
            "POST", f"{API_BASE}{_SYNTHESIS_PATH}", headers=headers, json_body=payload
        )
        task_id = (created.get("output") or {}).get("task_id")
        if not task_id:
            raise VideoBackendError(f"DashScope returned no task id: {created!r}")

        poll_headers = {"Authorization": headers["Authorization"]}
        status = ""
        attempts = 0
        result: dict[str, Any] = created
        while status not in {"SUCCEEDED", "FAILED", "CANCELED", "UNKNOWN"}:
            attempts += 1
            if attempts > _MAX_POLL_ATTEMPTS:
                raise VideoBackendError(
                    f"DashScope task {task_id} did not finish after "
                    f"{_MAX_POLL_ATTEMPTS} polls"
                )
            self._sleep_fn(_POLL_INTERVAL_SECONDS)
            result = self._request_fn(
                "GET", f"{API_BASE}/tasks/{task_id}", headers=poll_headers, json_body=None
            )
            status = str((result.get("output") or {}).get("task_status", ""))
        if status != "SUCCEEDED":
            raise VideoBackendError(
                f"DashScope task {task_id} ended as {status}: "
                f"{(result.get('output') or {}).get('message')}"
            )
        url = (result.get("output") or {}).get("video_url")
        if not url:
            raise VideoBackendError(f"DashScope returned no video url: {result!r}")
        return GeneratedVideo(
            data=self._download_fn(str(url)),
            backend=self.name,
            seconds=min(shot_list.total_seconds, MAX_SECONDS),
            request_payloads=[payload],
        )
