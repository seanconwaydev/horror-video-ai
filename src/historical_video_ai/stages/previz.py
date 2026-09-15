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
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import litellm

from historical_video_ai.config import get_stage_model
from historical_video_ai.image_utils import build_image_content_block
from historical_video_ai.json_utils import parse_json_response
from historical_video_ai.stages.fact_check import FactCheckResult
from historical_video_ai.stages.scene_planning import Beat, Character, Location
from historical_video_ai.stages.video_generation import _TARGET_VIDEO_SIZE_STR

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
# -- imported from video_generation.py rather than a second hardcoded
# "720x1280", so the two modules can't silently drift apart (see
# docs/decisions/0011). gemini-2.5-flash-image only supports requesting an
# aspect ratio, not an exact pixel size, so this is a hint litellm maps to
# Gemini's nearest named ratio ("9:16"), not a literal request for these
# exact pixels -- video_generation.py still resizes the actual output to
# Sora's exact required dimensions before submission.
_PREVIZ_SIZE_HINT = _TARGET_VIDEO_SIZE_STR


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


def _call_with_transient_retry(
    fn: Callable,
    *,
    sleep_fn: Callable[[float], None],
    on_transient_retry: Callable[[int, Exception], None] | None,
    **kwargs: object,
) -> object:
    """Shared retry loop for both run_previz_stage and
    run_reference_image_stage -- identical transient-error handling
    (docs/decisions/0016), regardless of which underlying call (plain
    generation or image-conditioned edit) is being made."""
    for attempt in range(1, _MAX_TRANSIENT_RETRIES + 1):
        try:
            return fn(**kwargs)
        except _TRANSIENT_IMAGE_ERRORS as exc:
            if attempt == _MAX_TRANSIENT_RETRIES:
                raise
            if on_transient_retry is not None:
                on_transient_retry(attempt, exc)
            sleep_fn(_TRANSIENT_RETRY_DELAY_SECONDS)
    raise AssertionError("unreachable")  # loop always returns or raises


def _extract_and_save_image(response: object, output_dir: Path, filename: str) -> Path:
    """Shared response-parsing/saving logic for both image-generation
    functions in this module."""
    data = getattr(response, "data", None)
    if data is not None and len(data) == 0:
        # A present-but-empty `data` list, distinct from a malformed
        # response object entirely (AttributeError/TypeError below) --
        # observed in a real run for a religious-imagery-adjacent prompt
        # (a "Buddha face" collage element), no error detail beyond the
        # empty list, no litellm-surfaced block reason to inspect further.
        # Not confirmed as content moderation specifically, but a
        # provider silently refusing is the most likely explanation for
        # an otherwise-valid-looking call returning nothing at all.
        raise PrevizError(
            "Image response had no image data -- the request returned "
            "successfully but with zero images. Most likely cause: the "
            "provider silently refused the prompt (e.g. a content-"
            "moderation block) without surfacing a specific reason. "
            "Try rephrasing the prompt before assuming this is a bug."
        )
    try:
        item = response.data[0]
    except (AttributeError, IndexError, TypeError) as exc:
        raise PrevizError(f"Image response had no image data: {exc}") from exc

    item_b64 = item.get("b64_json") if isinstance(item, dict) else None
    b64 = getattr(item, "b64_json", None) or item_b64
    if not b64:
        raise PrevizError(
            "Image response did not include b64_json image data -- this stage "
            "does not yet handle a URL-only response shape."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    image_path = output_dir / filename
    image_path.write_bytes(base64.b64decode(b64))
    return image_path


def _generate_image_response(
    prompt: str,
    *,
    reference_paths: list[Path],
    model: str,
    image_fn: Callable,
    edit_fn: Callable,
    sleep_fn: Callable[[float], None],
    on_transient_retry: Callable[[int, Exception], None] | None,
) -> object:
    """Shared branch between plain text-to-image and image-conditioned
    edit, used by both run_previz_stage and run_beat_image_stage. Reads
    reference images as raw bytes, not `Path` objects -- see
    run_previz_stage's docstring for why (litellm's Gemini image_edit
    PathLike bug)."""
    if reference_paths:
        image_bytes = [p.read_bytes() for p in reference_paths]
        return _call_with_transient_retry(
            edit_fn,
            sleep_fn=sleep_fn,
            on_transient_retry=on_transient_retry,
            model=model,
            image=image_bytes if len(image_bytes) > 1 else image_bytes[0],
            prompt=prompt,
            size=_PREVIZ_SIZE_HINT,
        )
    return _call_with_transient_retry(
        image_fn,
        sleep_fn=sleep_fn,
        on_transient_retry=on_transient_retry,
        model=model,
        prompt=prompt,
        size=_PREVIZ_SIZE_HINT,
    )


def run_previz_stage(
    fact_check_result: FactCheckResult,
    *,
    model: str | None = None,
    image_fn: Callable = litellm.image_generation,
    edit_fn: Callable = litellm.image_edit,
    character_reference: Path | None = None,
    location_reference: Path | None = None,
    output_dir: Path = Path("outputs"),
    sleep_fn: Callable[[float], None] = time.sleep,
    on_transient_retry: Callable[[int, Exception], None] | None = None,
) -> PrevizResult:
    """Generate one still image from a fact-checked scene.

    `model` defaults to the pinned "previz" model; `image_fn`/`edit_fn`/
    `sleep_fn` are injection points for tests (avoid a real API call /
    real waiting).

    `character_reference`/`location_reference` (docs/decisions/0024), if
    given, condition the generation on those reference image(s) via
    `edit_fn` instead of a plain `image_fn` text-to-image call -- see
    `run_reference_image_stage` for generating the references themselves.
    Reference images are read as raw bytes, not passed as `Path` objects:
    litellm's Gemini `image_edit` provider advertises `os.PathLike` as an
    accepted `image` type, but its `_read_all_bytes` only actually handles
    `bytes`/`BytesIO`/`BufferedReader` and raises `ValueError` on a bare
    `Path` -- confirmed directly against litellm 1.98.0's source.
    TODO(WORKAROUND): file a litellm issue for this and link it here; none
    of the existing open issues checked matched this exactly.

    Retries the image call up to _MAX_TRANSIENT_RETRIES times on errors
    judged transient (_TRANSIENT_IMAGE_ERRORS, docs/decisions/0016) --
    added after real, repeated Gemini 503s, observed on both plain
    generation and image-conditioned edit calls. Non-transient errors
    (content rejection, bad request, auth) fail immediately.
    `on_transient_retry`, if given, is called with (attempt number,
    exception) before each retry.

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
    response = _generate_image_response(
        prompt,
        reference_paths=[p for p in (character_reference, location_reference) if p is not None],
        model=resolved_model,
        image_fn=image_fn,
        edit_fn=edit_fn,
        sleep_fn=sleep_fn,
        on_transient_retry=on_transient_retry,
    )
    image_path = _extract_and_save_image(response, output_dir, "previz.png")
    return PrevizResult(image_path=image_path, prompt_used=prompt)


def run_reference_image_stage(
    prompt: str,
    *,
    model: str | None = None,
    image_fn: Callable = litellm.image_generation,
    output_dir: Path = Path("outputs"),
    sleep_fn: Callable[[float], None] = time.sleep,
    on_transient_retry: Callable[[int, Exception], None] | None = None,
) -> PrevizResult:
    """Generate a character-sheet or location-reference image
    (docs/decisions/0024) -- plain text-to-image, no `FactCheckResult`,
    since a reference image isn't tied to one specific historical scene
    the way a beat's final image is. Same transient-retry behavior as
    `run_previz_stage`; `model` defaults to the same pinned "previz" model
    (a reference image and a beat's final image use the same image model,
    just a different call shape).
    """
    resolved_model = model or get_stage_model("previz")
    response = _call_with_transient_retry(
        image_fn,
        sleep_fn=sleep_fn,
        on_transient_retry=on_transient_retry,
        model=resolved_model,
        prompt=prompt,
        size=_PREVIZ_SIZE_HINT,
    )
    image_path = _extract_and_save_image(response, output_dir, "reference.png")
    return PrevizResult(image_path=image_path, prompt_used=prompt)


# docs/decisions/0033: the single authoritative source for realism level,
# replacing three previously-independent, driftable sources (this
# module's own two hardcoded "STYLE: Photorealistic..." lines, plus every
# beat's own separately LLM-generated `style` text). Real terminology,
# not invented -- see docs/playbook/failure-taxonomy.md's style-consistency
# entry. Explicit negative constraints on each, since a bare positive
# adjective ("photorealistic") wasn't enough to prevent drift toward an
# unrequested style in real runs.
_STYLE_INSTRUCTIONS = {
    "photorealistic": (
        "Photorealistic -- an actual photograph of a real person/place, "
        "documentary-realistic color grade. Explicitly NOT 3D-rendered, "
        "NOT CGI, NOT a game character model, NOT anime, NOT a cartoon or "
        "stylized illustration."
    ),
    "semi-realistic": (
        "Semi-realistic 3D animation in the Pixar/Disney tradition -- "
        "believable human proportions and anatomy, expressive but not "
        "exaggerated, subsurface-scattering skin, soft realistic lighting. "
        "Explicitly NOT photorealistic/live-action, and NOT flat-shaded "
        "cartoon or anime -- a controlled balance between realism and "
        "stylization."
    ),
    "stylized": (
        "Deliberately stylized/cartoon illustration, loosely interpreted -- "
        "flat or graphic cel-shaded rendering with bold outlines and strong "
        "color blocking is one welcome direction among several (games like "
        "Jet Set Radio and Killer7 are examples of that particular look, "
        "not a required or exclusive target) -- softer, rounder, more "
        "conventional cartoon/animation looks are equally valid; consistency "
        "with other videos using "
        "this same style setting is not required or expected. Exaggerated "
        "or simplified proportions and expressions are welcome, and a cute "
        "or wholesome character design is a legitimate choice, not "
        "something to avoid. Explicitly NOT photorealistic, and not "
        "attempting real-world material/lighting fidelity."
    ),
}


def _style_instruction(style: str) -> str:
    try:
        return _STYLE_INSTRUCTIONS[style]
    except KeyError:
        raise PrevizError(
            f"Unknown style {style!r} -- must be one of {sorted(_STYLE_INSTRUCTIONS)}"
        ) from None


def build_character_sheet_prompt(character: Character, *, style: str = "photorealistic") -> str:
    """Build a neutral, non-narrative reference-sheet prompt for a
    Character (docs/decisions/0023, 0024) -- deliberately not a story
    moment, per the playbook's finding that a dedicated neutral reference
    anchors identity better than reusing a busy narrative beat."""
    return (
        f"CHARACTER: {character.face_build}, {character.hair}.\n"
        f"WARDROBE (signature): {character.wardrobe_signature}.\n"
        f"WARDROBE (flexible): {character.wardrobe_flexible}.\n"
        f"DISTINGUISHING DETAIL: {character.distinguishing_detail}.\n\n"
        "SUBJECT: The character described above, alone.\n"
        "ACTION: Standing in a simple, neutral, relaxed pose, facing "
        "slightly off-camera (three-quarter angle), calm neutral "
        "expression -- this is a character reference sheet, not a story "
        "moment.\n"
        "SETTING: A plain, softly out-of-focus neutral backdrop -- no "
        "specific location, nothing narrative.\n"
        "CAMERA: Medium-full shot, eye-level, centered.\n"
        "LIGHTING: Soft, even, shadowless studio-quality light.\n"
        f"STYLE: {_style_instruction(style)} No on-screen text, no logos, "
        "no watermark."
    )


def build_location_reference_prompt(location: Location, *, style: str = "photorealistic") -> str:
    """Build a no-character establishing-shot prompt for a Location
    (docs/decisions/0023, 0024) -- the canonical reference every beat set
    there conditions on, per the playbook's location-consistency finding."""
    return (
        f"SETTING: {location.architecture}. Fixed props: {location.fixed_props}.\n"
        "CAMERA: Wide establishing shot, eye-level, no main subject in the "
        "foreground -- this is a location reference, not a character shot.\n"
        f"LIGHTING: {location.ambient_light}.\n"
        f"STYLE: {_style_instruction(style)} No on-screen text, no logos."
    )


def _build_beat_prompt(
    beat: Beat,
    *,
    character: Character | None,
    location: Location | None,
    style: str = "photorealistic",
) -> str:
    """Build one beat's image prompt directly from its 7-part fields
    (docs/decisions/0023) -- deliberately not routed through _build_prompt,
    whose "historically accurate scene, Time: X, Place: Y" template is
    scoped to the original single-scene flow, not a planned multi-beat
    shot list.

    `beat.style` (the scene-planning LLM's own per-beat text -- lens,
    grain, framing notes) is kept, since that's legitimate beat-to-beat
    cinematographic variety, not the realism level. `style`
    (docs/decisions/0033) is appended after it as an explicit override so
    the realism level stays the single authoritative source across every
    beat and reference in a run, rather than competing with whatever
    beat.style happened to say on a given call.
    """
    parts = []
    if character is not None:
        parts.append(
            f"CHARACTER: {character.face_build}, {character.hair}.\n"
            f"WARDROBE (signature): {character.wardrobe_signature}.\n"
            f"WARDROBE (flexible): {character.wardrobe_flexible}.\n"
            f"DISTINGUISHING DETAIL: {character.distinguishing_detail}."
        )
    parts.append(f"SUBJECT: {beat.subject}")
    parts.append(f"ACTION: {beat.action}")
    if location is not None:
        parts.append(f"SETTING: {location.architecture}. Fixed props: {location.fixed_props}.")
    parts.append(f"CAMERA: {beat.camera}")
    parts.append(f"LIGHTING: {beat.lighting}")
    parts.append(f"STYLE: {beat.style}")
    parts.append(
        f"OVERRIDING STYLE REQUIREMENT (takes priority over anything above): "
        f"{_style_instruction(style)}"
    )
    return "\n".join(parts)


def run_beat_image_stage(
    beat: Beat,
    *,
    character: Character | None = None,
    location: Location | None = None,
    character_reference: Path | None = None,
    location_reference: Path | None = None,
    style: str = "photorealistic",
    model: str | None = None,
    image_fn: Callable = litellm.image_generation,
    edit_fn: Callable = litellm.image_edit,
    output_dir: Path = Path("outputs"),
    sleep_fn: Callable[[float], None] = time.sleep,
    on_transient_retry: Callable[[int, Exception], None] | None = None,
) -> PrevizResult:
    """Generate one beat's image from a ScenePlan (docs/decisions/0023) --
    the beat-driven counterpart to run_previz_stage, which stays scoped to
    the original single-scene (time/place/description) flow. `character`/
    `location` supply the text description woven into the prompt (see
    `_build_beat_prompt`); `character_reference`/`location_reference`
    (docs/decisions/0024) additionally condition the generation on those
    images, same mechanism and same retry behavior as `run_previz_stage`.
    `style` (docs/decisions/0033) is the run's single authoritative
    realism-level source -- see `_build_beat_prompt`.
    """
    resolved_model = model or get_stage_model("previz")
    prompt = _build_beat_prompt(beat, character=character, location=location, style=style)
    response = _generate_image_response(
        prompt,
        reference_paths=[p for p in (character_reference, location_reference) if p is not None],
        model=resolved_model,
        image_fn=image_fn,
        edit_fn=edit_fn,
        sleep_fn=sleep_fn,
        on_transient_retry=on_transient_retry,
    )
    image_path = _extract_and_save_image(response, output_dir, "previz.png")
    return PrevizResult(image_path=image_path, prompt_used=prompt)


_REVIEW_PROMPT_TEMPLATE = """\
You are independently reviewing a generated image against a historically \
accurate scene description. Your job has two parts:

1. Does the image depict anything that could not have existed or happened \
at this time and place -- anachronistic objects or technology, or an \
outright fictional/fantastical element shown as if it's literally, \
physically present? Even if the text description was appropriately hedged \
("resembles", "believed to be"), a generated image can still render that \
thing as unambiguously real, which is exactly the failure mode you're \
checking for here.
2. Does the image actually match what was planned -- the right character \
in the right role doing the right thing, not some other person performing \
an action that was never described (e.g. the wrong character shown \
running a shop, serving food, or holding an object that belongs to \
someone else in the scene)?

Scene -- Time: {time} | Place: {place} | What happens: {description}

Claims the image should be consistent with:
{claims_block}
{acknowledged_fiction_block}{planned_details_block}{previous_concerns_block}
Look at the image and respond with ONLY a JSON object (no prose, no \
markdown fences) matching this exact shape:

{{
  "accepted": <true if the image is historically plausible AND matches what was
    planned, false if it depicts something that could not have existed or
    happened, or fails to match what was planned>,
  "concern": "<if accepted is false, specifically what's wrong with the image; null
    if accepted is true>"
}}
"""

# docs/decisions/0034: for a scene that was never claiming to be real, the
# anachronism-detection framing above is actively wrong, not just extra
# overhead -- "could not have existed" is the point of a creative/meme
# scene, not a defect. Only the plan-fidelity check (0032) still applies.
_UNGROUNDED_REVIEW_PROMPT_TEMPLATE = """\
You are independently reviewing a generated image against a planned \
creative scene. This scene is not meant to be historically or factually \
accurate -- do NOT flag anything as implausible, anachronistic, or \
"could not have existed" on those terms; that's the point, not a defect.

Your only job: does the image actually match what was planned -- the \
right character in the right role doing the right thing, not some other \
person performing an action that was never described (e.g. the wrong \
character shown running a shop, serving food, or holding an object that \
belongs to someone else in the scene)?

Scene -- Setting: {time}, {place} | What happens: {description}
{planned_details_block}{previous_concerns_block}
Look at the image and respond with ONLY a JSON object (no prose, no \
markdown fences) matching this exact shape:

{{
  "accepted": <true if the image matches what was planned, false if it fails
    to match what was planned>,
  "concern": "<if accepted is false, specifically what's wrong with the image; null
    if accepted is true>"
}}
"""


def _parse_review(raw_content: str) -> PrevizReview:
    data = parse_json_response(raw_content, PrevizError, "Previz review response")

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
    character: Character | None = None,
    beat: Beat | None = None,
    requires_grounding: bool = True,
    previous_concerns: list[str] | None = None,
    model: str | None = None,
    completion_fn: Callable = litellm.completion,
) -> PrevizReview:
    """Independently review a previz-generated image against the scene it
    was supposed to depict -- an adversarial check on the actual image, not
    just the text prompt (docs/decisions/0009).

    `character`/`beat`, if given (docs/decisions/0032), list their already
    scene-plan-approved details (wardrobe, distinguishing detail, the
    beat's own action) as settled and not to be re-flagged as
    anachronisms -- a re-derived-from-scratch historical-plausibility
    judgment is the wrong check for something a human already reviewed and
    approved at scene-plan-review time (docs/decisions/0023). Only the
    single-scene flow (which predates scene-planning) omits these.

    `requires_grounding` (docs/decisions/0034), when False, drops the
    anachronism-detection check entirely -- wrong, not just unnecessary,
    for a scene that was never claiming to be real -- and only checks
    plan-fidelity (0032).

    `previous_concerns`, if given, lists the rejection reason(s) from
    earlier automatic-retry attempts on this same beat -- observed in a
    real run to matter: each call here is otherwise an independent
    judgment with no memory of a prior attempt, so a retry with the exact
    same flaw (e.g. a described extreme fisheye distortion never actually
    rendering) could get waved through on the second try even though it's
    unchanged, because nothing forced the reviewer to specifically re-check
    the thing it flagged before. Passing prior concerns forward makes the
    review explicitly re-verify each one rather than re-deriving a fresh,
    potentially inconsistent judgment every attempt.

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
    # docs/decisions/0032: a further, distinct allowlist -- these details
    # were approved at scene-plan-review time (0023), not derived from the
    # original premise-conflict text, so they need naming here separately.
    planned_details_block = ""
    if character is not None or beat is not None:
        planned_lines = []
        if character is not None:
            planned_lines.append(
                f"- This character's appearance was already deliberately planned "
                f"and human-reviewed, including anything that looks anachronistic "
                f"in isolation -- do NOT flag it: wardrobe is "
                f"{character.wardrobe_signature} ({character.wardrobe_flexible}); "
                f"{character.distinguishing_detail}"
            )
        if beat is not None:
            planned_lines.append(
                f"- This beat's action was already deliberately planned -- do NOT "
                f"flag it as wrong on its own terms: {beat.subject} {beat.action}"
            )
        planned_details_block = (
            "\nThe following specific details were already deliberately planned "
            "and human-reviewed as part of this scene -- do NOT flag them as "
            "anachronisms or problems on their own, no matter how implausible "
            "they'd look in isolation; only flag if the image fails to actually "
            "depict them faithfully, or introduces a DIFFERENT, new problem not "
            "covered here:\n" + "\n".join(planned_lines) + "\n"
        )
    previous_concerns_block = ""
    if previous_concerns:
        concern_lines = "\n".join(f"- {c}" for c in previous_concerns)
        previous_concerns_block = (
            "\nThis is a retry: an earlier attempt at this same image was "
            "rejected for the reason(s) below. Specifically check whether "
            "each one has actually been resolved in THIS image -- don't just "
            "judge the image acceptable in general. If the same issue is "
            f"still present, reject again for it:\n{concern_lines}\n"
        )
    if requires_grounding:
        detail_lines = "\n".join(f"- {c.text}" for c in fact_sheet.claims)
        # docs/decisions/0026: an explicit allowlist, not left to inference --
        # LLM judges are documented to have high refusal rates on exceptions
        # to a stated policy unless told about them directly.
        acknowledged_fiction_block = ""
        if fact_check_result.acknowledged_fiction:
            acknowledged_fiction_block = (
                "\nThe following has already been explicitly acknowledged as "
                "intentional, deliberate fiction by a human reviewer -- do NOT "
                "flag this specific thing as a problem, only flag genuinely "
                f"new or different issues:\n{fact_check_result.acknowledged_fiction}\n"
            )
        prompt = _REVIEW_PROMPT_TEMPLATE.format(
            time=fact_sheet.time,
            place=fact_sheet.place,
            description=fact_sheet.description,
            claims_block=detail_lines or "(no claims)",
            acknowledged_fiction_block=acknowledged_fiction_block,
            planned_details_block=planned_details_block,
            previous_concerns_block=previous_concerns_block,
        )
    else:
        prompt = _UNGROUNDED_REVIEW_PROMPT_TEMPLATE.format(
            time=fact_sheet.time,
            place=fact_sheet.place,
            description=fact_sheet.description,
            planned_details_block=planned_details_block,
            previous_concerns_block=previous_concerns_block,
        )

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
    return _parse_review(raw_content)
