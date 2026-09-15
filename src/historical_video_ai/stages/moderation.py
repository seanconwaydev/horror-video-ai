"""Pre-flight moderation check gating every real video-generation call --
not a pipeline.md-numbered stage of its own. See
docs/decisions/0022-video-generation-moderation-preflight.md.

Two independent layers, both run before every paid `run_video_generation_
stage` call in cli.py's `_run_video_generation_only`:

- Layer 1 (`run_moderation_policy_check`, free): OpenAI's own
  omni-moderation-latest endpoint via litellm.moderation(), checking the
  final prompt text and the reference image together against literal
  policy categories (violence, self-harm, sexual content, hate).
- Layer 2 (`run_moderation_risk_review`, paid): an independent
  vision-capable model checking the reference image specifically for pose/
  action patterns known to trip Sora's own moderation even when no literal
  policy category is violated -- see `_KNOWN_MODERATION_RISK_PATTERNS`,
  kept in sync by hand with docs/playbook/video-generation-prompting.md's
  "Content moderation" section.

Neither layer is a guarantee -- see 0022's Consequences for why a
`moderation_blocked` failure at the real Sora call is still possible after
both pass clean.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import litellm

from historical_video_ai.config import get_stage_model
from historical_video_ai.image_utils import build_image_content_block
from historical_video_ai.json_utils import parse_json_response


class ModerationError(Exception):
    """Raised when either moderation check's response is missing or malformed."""


@dataclass(frozen=True)
class ModerationPolicyResult:
    """Layer 1's result: which of omni-moderation-latest's own policy
    categories, if any, were flagged for the submitted text + image."""

    flagged: bool
    flagged_categories: list[str]


@dataclass(frozen=True)
class ModerationRiskReview:
    """Layer 2's result: whether the reference image's pose/action
    plausibly reads as violent, threatening, or forced entry to an
    automated classifier, per an independent model's judgment."""

    flagged: bool
    concern: str | None


def run_moderation_policy_check(
    prompt: str,
    image_path: Path,
    *,
    model: str | None = None,
    moderation_fn: Callable = litellm.moderation,
) -> ModerationPolicyResult:
    """Layer 1: submit `prompt` and the image at `image_path` together to
    OpenAI's free omni-moderation-latest endpoint. `model` defaults to the
    pinned "moderation_check" model. `moderation_fn` is an injection point
    for tests.

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


# Evidence-only, not speculative -- each entry here is a real, diagnosed
# moderation_blocked incident, not a guess at what might also trip it
# (plain running and jumping already passed cleanly in the same scene this
# first entry came from, so a broader "avoid all dynamic action" guess
# would already be known-wrong). Add an entry only once a real incident is
# root-caused, and add the matching narrative to docs/playbook/video-
# generation-prompting.md's "Content moderation" section at the same time.
_KNOWN_MODERATION_RISK_PATTERNS = (
    (
        "A lunging stride or a hand pressed flat against a closed door, reading as forced "
        "entry into a building rather than ordinary movement."
    ),
)

_RISK_REVIEW_PROMPT_TEMPLATE = """This image is a reference frame that will be submitted to an AI video \
generation service (Sora) to animate. Sora's own content moderation is more \
conservative than general policy categories -- it can reject an image for \
plausibly reading as violent, threatening, or a forced-entry/break-in \
scenario, even when the image depicts ordinary, non-violent action and no \
explicit policy violation (no weapons, no depicted injury, no real people).

Known patterns that have actually tripped this moderation before, in this project:
{known_patterns}

Question: does this image's pose or action plausibly read as violent, \
threatening, or forced entry to an automated safety classifier -- whether \
or not it matches one of the patterns above?

Respond with JSON only, no markdown fence:
{{
  "flagged": <true if this image plausibly risks tripping moderation, false otherwise>,
  "concern": "<if flagged is true, specifically what about the pose/action reads this way; \
null if flagged is false>"
}}
"""


def _parse_risk_review(raw_content: str) -> ModerationRiskReview:
    data = parse_json_response(raw_content, ModerationError, "Moderation risk review response")

    if not isinstance(data, dict) or "flagged" not in data:
        raise ModerationError("Moderation risk review response is missing 'flagged'")
    flagged = data["flagged"]
    if not isinstance(flagged, bool):
        raise ModerationError(f"Moderation risk review's 'flagged' must be true or false, got {flagged!r}")

    concern = data.get("concern") if flagged else None
    if flagged and not concern:
        raise ModerationError("Moderation risk review flagged the image but is missing 'concern'")

    return ModerationRiskReview(flagged=flagged, concern=concern)


def run_moderation_risk_review(
    image_path: Path,
    *,
    model: str | None = None,
    completion_fn: Callable = litellm.completion,
) -> ModerationRiskReview:
    """Layer 2: send the image at `image_path` to an independent
    vision-capable model, asking whether its pose/action plausibly reads
    as violent, threatening, or forced entry -- see
    `_KNOWN_MODERATION_RISK_PATTERNS`. `model` defaults to the pinned
    "moderation_review" model. `completion_fn` is an injection point for
    tests.

    Raises ModerationError if the response isn't valid JSON or is missing
    required fields.
    """
    resolved_model = model or get_stage_model("moderation_review")
    known_patterns_block = "\n".join(f"- {p}" for p in _KNOWN_MODERATION_RISK_PATTERNS)
    prompt = _RISK_REVIEW_PROMPT_TEMPLATE.format(known_patterns=known_patterns_block)

    response = completion_fn(
        model=resolved_model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    build_image_content_block(image_path),
                ],
            }
        ],
    )
    raw_content = response.choices[0].message.content
    return _parse_risk_review(raw_content)
