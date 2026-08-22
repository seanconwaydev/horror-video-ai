"""Stage 8 (scoped down for v1): Previz -- render one still image from a
verified scene, skipping the script/shot-list/per-scene-prompt stages this
normally sits downstream of.

See docs/pipeline.md ("8. Previz") for the stage's full role in the eventual
pipeline, and docs/decisions/0006-narrow-v1-scope-single-image.md for why
this v1 version builds its prompt directly from the fact-check stage's
output instead of a per-scene video prompt.

Model note: pinned to an OpenAI image model as a starting placeholder, not a
rigorously compared decision -- see docs/decisions/0007. Unverified: this
calls litellm.image_generation(), which LiteLLM documents as covering
OpenAI's image API, normalized to an OpenAI-style response; that call shape
has not been exercised against a live key from this repo. Treat the first
real run as a test, not a known-working thing (same caveat as the research
and fact_check stages' real backends).
"""

from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import litellm

from historical_video_ai import _litellm_workarounds  # noqa: F401 -- see CLAUDE.md
from historical_video_ai.config import get_stage_model
from historical_video_ai.stages.fact_check import FactCheckResult


class PrevizError(Exception):
    """Raised when the previz stage's image response is missing or malformed."""


@dataclass(frozen=True)
class PrevizResult:
    """The reviewable artifact stage 8 produces: the image itself, plus the
    prompt actually used to generate it (so a human reviewing it can see
    what was asked for, not just what came back)."""

    image_path: Path
    prompt_used: str


def _build_prompt(fact_check_result: FactCheckResult) -> str:
    """Build the image prompt from fact_check_result.fact_sheet.claims as
    given -- this stage trusts that list as already resolved. It used to
    auto-exclude any claim flagged "contradicted" itself, but that matching
    relied on exact string equality between a flag's claim_text and the
    original claim, which a real model response isn't guaranteed to
    preserve (see fact_check.py's claim_text validation) -- and more
    fundamentally, silently dropping a claim isn't this stage's call to
    make. Per docs/pipeline.md's stage 3 review gate, a human resolves each
    flag (accept, cut, or soften) before the fact sheet ever reaches here --
    see cli.py's _resolve_flags."""
    fact_sheet = fact_check_result.fact_sheet
    detail_lines = "\n".join(f"- {c.text}" for c in fact_sheet.claims)
    return (
        f"A historically accurate scene. Time: {fact_sheet.time}. "
        f"Place: {fact_sheet.place}. A generic, unnamed person (third "
        f"person, not a specific named historical figure unless stated) "
        f"{fact_sheet.description}\n\n"
        f"Accuracy details to reflect in the image:\n{detail_lines}"
    )


def run_previz_stage(
    fact_check_result: FactCheckResult,
    *,
    model: str | None = None,
    image_fn: Callable = litellm.image_generation,
    output_dir: Path = Path("outputs"),
) -> PrevizResult:
    """Generate one still image from a fact-checked scene.

    `model` defaults to the pinned model for the "previz" stage in
    config/models.yaml. `image_fn` defaults to litellm.image_generation and
    exists as an injection point for tests -- pass a fake to avoid making a
    real API call or writing a real file.

    Raises PrevizError if the response doesn't contain image data in a
    recognized shape, rather than silently producing an empty/broken file.
    """
    resolved_model = model or get_stage_model("previz")
    prompt = _build_prompt(fact_check_result)

    response = image_fn(model=resolved_model, prompt=prompt)

    try:
        item = response.data[0]
    except (AttributeError, IndexError, TypeError) as exc:
        raise PrevizError(f"Previz response had no image data: {exc}") from exc

    item_b64 = item.get("b64_json") if isinstance(item, dict) else None
    b64 = getattr(item, "b64_json", None) or item_b64
    if not b64:
        raise PrevizError(
            "Previz response did not include b64_json image data -- this stage "
            "does not yet handle a URL-only response shape."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    image_path = output_dir / "previz.png"
    image_path.write_bytes(base64.b64decode(b64))

    return PrevizResult(image_path=image_path, prompt_used=prompt)
