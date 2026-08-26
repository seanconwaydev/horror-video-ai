"""Stage 8 (scoped down for v1): Previz -- render one still image from a
verified scene, skipping the script/shot-list/per-scene-prompt stages this
normally sits downstream of. See docs/pipeline.md ("8. Previz") and
docs/decisions/0006-narrow-v1-scope-single-image.md.

Model: gemini/gemini-2.5-flash-image (docs/decisions/0011) -- moved off
the original OpenAI placeholder because its 9:16 output is a ~0.8% match
to Sora-2's exact required ratio, letting video_generation resize instead
of crop. Requests a 9:16-ish `size` (Gemini only supports an aspect-ratio
hint, not an exact pixel size). Confirmed working end to end against a
real key, not just a call-shape guess.
"""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import litellm

from historical_video_ai.config import get_stage_model
from historical_video_ai.json_utils import strip_markdown_json_fence
from historical_video_ai.stages.fact_check import FactCheckResult

# Errors worth retrying automatically -- transient in nature (server
# overload, a network blip, a rate limit that clears with time), unlike
# e.g. AuthenticationError or ContentPolicyViolationError, where retrying
# the identical request will just fail the identical way. Added after
# hitting real, repeated Gemini 503 "high demand" errors in real runs --
# litellm's own num_retries doesn't cover this: confirmed by direct
# reproduction that it's wired only into litellm.acompletion()'s async
# retry path, not sync image_generation() at all (see docs/decisions/0016).
_TRANSIENT_IMAGE_ERRORS = (
    litellm.exceptions.ServiceUnavailableError,
    litellm.exceptions.RateLimitError,
    litellm.exceptions.Timeout,
    litellm.exceptions.InternalServerError,
    litellm.exceptions.APIConnectionError,
    litellm.exceptions.BadGatewayError,
)
_MAX_TRANSIENT_RETRIES = 3
_TRANSIENT_RETRY_DELAY_SECONDS = 5.0


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
        f"Research claims about this place (these span its whole history, "
        f"not just the moment above -- some describe the place at other "
        f"times, e.g. a modern renovation or a technology from a different "
        f"era, and must NOT appear in the image if they don't hold at "
        f"{fact_sheet.time} specifically):\n{detail_lines}"
    )


def run_previz_stage(
    fact_check_result: FactCheckResult,
    *,
    model: str | None = None,
    image_fn: Callable = litellm.image_generation,
    output_dir: Path = Path("outputs"),
    sleep_fn: Callable[[float], None] = time.sleep,
    on_transient_retry: Callable[[int, Exception], None] | None = None,
) -> PrevizResult:
    """Generate one still image from a fact-checked scene.

    `model` defaults to the pinned "previz" model; `image_fn`/`sleep_fn`
    are injection points for tests (avoid a real API call / real waiting).

    Retries the image call up to _MAX_TRANSIENT_RETRIES times on errors
    judged transient (_TRANSIENT_IMAGE_ERRORS, docs/decisions/0016) --
    added after real, repeated Gemini 503s. Non-transient errors (content
    rejection, bad request, auth) fail immediately. `on_transient_retry`,
    if given, is called with (attempt number, exception) before each retry.

    Raises PrevizError if `fact_check_result` still carries an unresolved
    premise conflict (docs/decisions/0008 -- refuses rather than fabricate)
    or if the response has no recognizable image data.
    """
    if fact_check_result.premise_conflict is not None:
        raise PrevizError(
            "Refusing to generate an image: the scene's premise was flagged "
            "as historically impossible and was never resolved -- "
            f"{fact_check_result.premise_conflict.explanation}"
        )

    resolved_model = model or get_stage_model("previz")
    prompt = _build_prompt(fact_check_result)

    response = None
    for attempt in range(1, _MAX_TRANSIENT_RETRIES + 1):
        try:
            response = image_fn(model=resolved_model, prompt=prompt, size=_PREVIZ_SIZE_HINT)
            break
        except _TRANSIENT_IMAGE_ERRORS as exc:
            if attempt == _MAX_TRANSIENT_RETRIES:
                raise
            if on_transient_retry is not None:
                on_transient_retry(attempt, exc)
            sleep_fn(_TRANSIENT_RETRY_DELAY_SECONDS)

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
    just the text prompt (docs/decisions/0009).

    `model` defaults to the pinned "previz_review" model -- deliberately
    vision-capable and a different provider than previz's own image model,
    same reasoning as fact_check vs. research. `completion_fn` is an
    injection point for tests. Confirmed working against a real key,
    including catching real anachronisms in generated images.

    Raises PrevizError if the model's response isn't valid JSON or is
    missing required fields.
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
