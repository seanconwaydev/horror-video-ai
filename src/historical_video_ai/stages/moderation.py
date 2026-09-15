"""Advisory pre-flight on every video-generation call -- not a
pipeline.md-numbered stage of its own. See docs/decisions/0022 (original
two-layer design) and docs/decisions/0038 (this rescoping).

One layer remains: OpenAI's free omni-moderation-latest endpoint, run
against the final prompt text and reference image together. It reports;
it never blocks.

The original layer 2 -- a paid vision call asking whether an image
"plausibly reads as" violent or forced-entry, primed with patterns that
had tripped Sora before -- was deleted along with Sora itself. Its entire
premise was predicting one specific vendor's conservative moderation, and
Wan (docs/decisions/0037) has no vendor-baked safety alignment to
predict, so the layer could only ever produce false positives. It had
already done exactly that on a real run, skipping two harmless beats
before any API call was attempted.

What remains is kept as a YouTube-policy signal for the human reviewing a
run, not as a generation gate: this project makes horror, so tripping the
violence category is expected and routine, and treating that as a stop
condition would block the project's actual genre.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import litellm

from historical_video_ai.config import get_stage_model
from historical_video_ai.image_utils import build_image_content_block


class ModerationError(Exception):
    """Raised when the moderation check's response is missing or malformed."""


@dataclass(frozen=True)
class ModerationPolicyResult:
    """Which of omni-moderation-latest's own policy categories, if any,
    were flagged for the submitted text + image."""

    flagged: bool
    flagged_categories: list[str]


def run_moderation_policy_check(
    prompt: str,
    image_path: Path,
    *,
    model: str | None = None,
    moderation_fn: Callable = litellm.moderation,
) -> ModerationPolicyResult:
    """Submit `prompt` and the image at `image_path` together to OpenAI's
    free omni-moderation-latest endpoint. `model` defaults to the pinned
    "moderation_check" model. `moderation_fn` is an injection point for
    tests.

    Raises ModerationError if the response has no results or is missing
    'flagged'.
    """
    resolved_model = model or get_stage_model("moderation_check")
    # WORKAROUND(https://github.com/BerriAI/litellm/issues/6020): litellm's
    # synchronous moderation() passes `model` straight through to
    # openai_client.moderations.create() with no provider-prefix stripping
    # at all (unlike completion()/image_generation()), so config.yaml's
    # pinned "openai/omni-moderation-latest" -- the LiteLLM format every
    # other stage uses -- gets rejected by OpenAI's own API with a real
    # 400. Confirmed still present in litellm 1.100.1 (latest released,
    # checked 2026-09-14); the issue itself is closed "not planned", so
    # this strips the prefix at this one call site instead of waiting on
    # an upstream fix that was declined.
    response = moderation_fn(
        input=[
            {"type": "text", "text": prompt},
            build_image_content_block(image_path),
        ],
        model=resolved_model.removeprefix("openai/"),
    )
    if not response.results:
        raise ModerationError("Moderation response has no results")
    result = response.results[0]
    if result.flagged is None:
        raise ModerationError("Moderation response is missing 'flagged'")

    flagged_categories = sorted(
        category for category, is_flagged in (result.categories or {}).items() if is_flagged
    )
    return ModerationPolicyResult(flagged=bool(result.flagged), flagged_categories=flagged_categories)
