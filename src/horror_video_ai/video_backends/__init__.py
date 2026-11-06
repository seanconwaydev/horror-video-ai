"""Direct-to-vendor video backends.

One module per vendor, all first-party -- no aggregators. Replicate
marked a Kling generation up from ~$2.52 to $5 for the identical model,
which is what prompted going direct.

`build_backend` is the only entry point the CLI needs; it reads each
backend's model pin from `config/models.yaml` so a wrong or retired model
string is a config edit rather than a code change.
"""

from __future__ import annotations

from horror_video_ai.config import get_stage_model
from horror_video_ai.video_backends._http import VideoBackendError
from horror_video_ai.video_backends.base import (
    PORTRAIT_9_16,
    GeneratedVideo,
    VideoBackend,
    cost_per_second,
)
from horror_video_ai.video_backends.kling import KlingBackend
from horror_video_ai.video_backends.veo import VeoBackend
from horror_video_ai.video_backends.wan import WanBackend

BACKEND_NAMES = ("veo", "kling", "wan")

__all__ = [
    "BACKEND_NAMES",
    "PORTRAIT_9_16",
    "GeneratedVideo",
    "KlingBackend",
    "VeoBackend",
    "VideoBackend",
    "VideoBackendError",
    "WanBackend",
    "build_backend",
    "cost_per_second",
]


def build_backend(name: str, *, resolution: str = "720p") -> VideoBackend:
    """One backend by name, with its model read from the pinned config."""
    if name == "veo":
        return VeoBackend(get_stage_model("video_veo"), resolution=resolution)
    if name == "kling":
        return KlingBackend(
            get_stage_model("video_kling"), mode="standard" if resolution == "720p" else "pro"
        )
    if name == "wan":
        return WanBackend(get_stage_model("video_wan"), resolution=resolution)
    raise VideoBackendError(f"Unknown backend {name!r} -- expected one of {BACKEND_NAMES}")
