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

import base64
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import litellm

from historical_video_ai.config import get_stage_model
from historical_video_ai.json_utils import strip_markdown_json_fence


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
    image_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    response = moderation_fn(
        input=[
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
        ],
        model=resolved_model,
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
    try:
        data = json.loads(strip_markdown_json_fence(raw_content))
    except json.JSONDecodeError as exc:
        raise ModerationError(f"Moderation risk review response was not valid JSON: {exc}") from exc

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

    image_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    response = completion_fn(
        model=resolved_model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                    },
                ],
            }
        ],
    )
    raw_content = response.choices[0].message.content
    return _parse_risk_review(raw_content)
