"""Stage 8 (scoped down for v1): Previz -- render one still image from a
verified scene, skipping the script/shot-list/per-scene-prompt stages this
normally sits downstream of.

See docs/pipeline.md ("8. Previz") for the stage's full role in the eventual
pipeline, and docs/decisions/0006-narrow-v1-scope-single-image.md for why
this v1 version builds its prompt directly from the fact-check stage's
output instead of a per-scene video prompt.

Model note: pinned to Gemini's image model (gemini/gemini-2.5-flash-image),
moved off the original OpenAI placeholder from docs/decisions/0007 -- see
docs/decisions/0011-previz-image-model-for-video-aspect-ratio-fit.md for
why: Sora-2 (the video_generation stage's model) requires an exact-pixel
match to one of its two fixed sizes (720x1280 or 1280x720), and none of
gpt-image-1-mini's three fixed sizes even shares that aspect ratio, forcing
a large, content-losing crop. Gemini's 9:16 output is a near-exact match
(within ~0.8%), letting video_generation resize instead of crop -- no scene
content lost. Requests a 9:16-ish `size` (mapped internally to Gemini's
`imageConfig.aspectRatio`, not an exact pixel size -- gemini-2.5-flash-image
doesn't support requesting an exact size, only an aspect ratio) so the
output is close to Sora's target ratio.

The request/response call shape (litellm.image_generation() normalizing
Gemini's response to the same ImageResponse/b64_json shape OpenAI's API
uses) was verified by direct reproduction against litellm's real
request-building code, bypassing the network -- unlike the previous OpenAI
placeholder, this isn't a blind guess at the call shape. It has still not
been exercised against a live Gemini key from this repo, though -- treat
the first real run as a test for actual output quality/behavior, not for
whether the call shape itself works (same caveat as the research and
fact_check stages' real backends).
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import litellm

from historical_video_ai import _litellm_workarounds  # noqa: F401 -- see CLAUDE.md
from historical_video_ai.config import get_stage_model
from historical_video_ai.json_utils import strip_markdown_json_fence
from historical_video_ai.stages.fact_check import FactCheckResult


class PrevizError(Exception):
    """Raised when the previz stage's image response is missing or malformed."""


# Requests the aspect ratio closest to Sora-2's fixed 720x1280 portrait size
# (video_generation.py's own target size for the same reason -- see
# docs/decisions/0011). gemini-2.5-flash-image only supports requesting an
# aspect ratio, not an exact pixel size, so this is a hint litellm maps to
# Gemini's nearest named ratio ("9:16"), not a literal request for these
# exact pixels -- video_generation.py still resizes the actual output to
# Sora's exact required dimensions before submission.
_PREVIZ_SIZE_HINT = "720x1280"


@dataclass(frozen=True)
class PrevizResult:
    """The reviewable artifact stage 8 produces: the image itself, plus the
    prompt actually used to generate it (so a human reviewing it can see
    what was asked for, not just what came back)."""

    image_path: Path
    prompt_used: str


@dataclass(frozen=True)
class PrevizReview:
    """The result of an independent, adversarial pass over previz's
    generated *image* -- not the text prompt, the actual pixels. See
    docs/decisions/0009-previz-image-review.md: a hedged, accurate prompt
    ("people believe a distant shape resembles X") can still produce an
    image that unambiguously depicts X as literally, physically present --
    a known failure mode of text-to-image models, which this stage exists
    to catch rather than let through unreviewed."""

    accepted: bool
    concern: str | None


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

    Raises PrevizError if fact_check_result still carries an unresolved
    premise conflict (see docs/decisions/0008-refuse-impossible-premises.md
    -- this pipeline refuses to depict a scene fact-check flagged as
    historically impossible, rather than fabricate it) or if the response
    doesn't contain image data in a recognized shape, rather than silently
    producing an empty/broken file.
    """
    if fact_check_result.premise_conflict is not None:
        raise PrevizError(
            "Refusing to generate an image: the scene's premise was flagged "
            "as historically impossible and was never resolved -- "
            f"{fact_check_result.premise_conflict.explanation}"
        )

    resolved_model = model or get_stage_model("previz")
    prompt = _build_prompt(fact_check_result)

    response = image_fn(model=resolved_model, prompt=prompt, size=_PREVIZ_SIZE_HINT)

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


_REVIEW_PROMPT_TEMPLATE = """\
You are independently reviewing a generated image against a historically \
accurate scene description. Your job is to find reasons the IMAGE could be \
WRONG -- specifically, does it depict anything that could not have existed \
or happened at this time and place? This includes anachronistic objects or \
technology, and an outright fictional or fantastical element shown as if \
it's literally, physically present in the scene -- even if the text \
description was appropriately hedged ("resembles", "believed to be"), a \
generated image can still render that thing as unambiguously real, which \
is exactly the failure mode you're checking for.

Scene -- Time: {time} | Place: {place} | What happens: {description}

Claims the image should be consistent with:
{claims_block}

Look at the image and respond with ONLY a JSON object (no prose, no \
markdown fences) matching this exact shape:

{{
  "accepted": <true if the image is historically plausible given the scene and claims
    above, false if it depicts something that could not have existed or happened>,
  "concern": "<if accepted is false, specifically what's wrong with the image; null
    if accepted is true>"
}}
"""


def _parse_review(raw_content: str) -> PrevizReview:
    try:
        data = json.loads(strip_markdown_json_fence(raw_content))
    except json.JSONDecodeError as exc:
        raise PrevizError(f"Previz review response was not valid JSON: {exc}") from exc

    if not isinstance(data, dict) or "accepted" not in data:
        raise PrevizError("Previz review response is missing 'accepted'")
    accepted = data["accepted"]
    if not isinstance(accepted, bool):
        raise PrevizError(f"Previz review's 'accepted' must be true or false, got {accepted!r}")

    concern = data.get("concern") if not accepted else None
    if not accepted and not concern:
        raise PrevizError("Previz review rejected the image but is missing 'concern'")

    return PrevizReview(accepted=accepted, concern=concern)


def run_previz_review_stage(
    image_path: Path,
    fact_check_result: FactCheckResult,
    *,
    model: str | None = None,
    completion_fn: Callable = litellm.completion,
) -> PrevizReview:
    """Independently review a previz-generated image against the scene it
    was supposed to depict -- an adversarial check on the actual image, not
    just the text prompt (see docs/decisions/0009-previz-image-review.md,
    and PrevizReview's docstring for why this is needed even when the
    prompt itself was accurate).

    `model` defaults to the pinned model for the "previz_review" stage in
    config/models.yaml -- deliberately vision-capable and a different
    provider than previz's own image model, same "not the same model
    checking its own work" reasoning as fact_check vs. research.
    `completion_fn` defaults to litellm.completion and exists as an
    injection point for tests -- pass a fake to avoid a real API call.

    Unverified: this call (vision input via litellm.completion(), i.e. a
    message content list with a text block and an image_url block) has not
    been exercised against a live key from this repo -- ANTHROPIC_API_KEY
    was never set during development. Treat the first real run as a test,
    not a known-working thing (same caveat as run_previz_stage's own image
    generation call).

    Raises PrevizError if the model's response isn't valid JSON or is
    missing required fields, matching this project's fail-loud convention.
    """
    resolved_model = model or get_stage_model("previz_review")
    fact_sheet = fact_check_result.fact_sheet
    detail_lines = "\n".join(f"- {c.text}" for c in fact_sheet.claims)
    prompt = _REVIEW_PROMPT_TEMPLATE.format(
        time=fact_sheet.time,
        place=fact_sheet.place,
        description=fact_sheet.description,
        claims_block=detail_lines or "(no claims)",
    )

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
    return _parse_review(raw_content)
