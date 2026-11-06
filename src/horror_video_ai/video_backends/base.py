"""What every video backend has to provide, and what it hands back.

The three supported vendors differ in call shape -- Kling takes a whole
multi-shot short in one request, Veo caps a single call at 8 seconds --
but the pipeline only needs four things from any of them: what it costs,
whether a shot list is legal for it, how to generate, and what came back.

Costs come from litellm's own price table rather than being hardcoded, so
a vendor price change arrives with a dependency upgrade instead of going
stale in a comment. Backends litellm has no entry for return None and the
CLI says "cost unknown" rather than inventing a number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import litellm

from horror_video_ai.stages.shot_writing import ShotList

PORTRAIT_9_16 = "9:16"


@dataclass(frozen=True)
class GeneratedVideo:
    """A finished video plus exactly what was asked for to get it. The
    payloads travel with the bytes so a run log records the real request,
    not a reconstruction of it."""

    data: bytes
    backend: str
    seconds: int
    request_payloads: list[dict[str, Any]] = field(default_factory=list)


@runtime_checkable
class VideoBackend(Protocol):
    """One vendor, reached directly."""

    name: str
    model: str
    supports_multishot: bool
    max_seconds_per_call: int

    def validate(self, shot_list: ShotList) -> list[str]:
        """This backend's own limit violations, as human-readable
        reasons, checked before anything is spent. Empty means legal."""
        ...

    def estimate_cost_usd(self, seconds: int) -> float | None:
        """None when the price is genuinely unknown, never a guess."""
        ...

    def generate(self, shot_list: ShotList, *, aspect_ratio: str = PORTRAIT_9_16) -> GeneratedVideo:
        ...


def cost_per_second(model: str) -> float | None:
    """Per-second output cost from litellm's price table, or None.

    Keyed on the litellm model string, so this only answers for backends
    that go through litellm. Direct-REST backends carry their own rate.
    """
    entry = litellm.model_cost.get(model)
    if not isinstance(entry, dict):
        return None
    for key in ("output_cost_per_second", "output_cost_per_video_per_second"):
        value = entry.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None
