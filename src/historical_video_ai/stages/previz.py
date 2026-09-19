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
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import litellm

from historical_video_ai.config import get_stage_model
from historical_video_ai.image_utils import build_image_content_block
from historical_video_ai.json_utils import parse_json_response
from historical_video_ai.stages.fact_check import FactCheckResult
from historical_video_ai.stages.scene_planning import Beat, Character, Location

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


# 9:16 portrait, for this project's Shorts-only format
# (docs/decisions/0002).
#
# Until docs/decisions/0038 this was imported from video_generation.py,
# because Sora required its reference image to be pixel-exact to the video
# size and the two modules could not be allowed to drift. Wan derives the
# video's aspect ratio from whatever image it is handed, so that coupling
# is gone and previz now owns this choice outright -- which is also why
# docs/decisions/0011's reason for pinning this stage's model no longer
# holds.
#
# gemini-2.5-flash-image only supports requesting an aspect ratio, not an
# exact pixel size, so this is a hint litellm maps to Gemini's nearest
# named ratio ("9:16"), not a literal request for these exact pixels.
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


def _call_with_transient_retry(
    fn: Callable[..., Any],
    *,
    sleep_fn: Callable[[float], None],
    on_transient_retry: Callable[[int, Exception], None] | None,
    **kwargs: object,
) -> Any:
    """Shared transient-error retry loop (docs/decisions/0016), wrapping
    whichever underlying call is being made -- plain generation or
    image-conditioned edit."""
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


def _extract_and_save_image(response: Any, output_dir: Path, filename: str) -> Path:
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
    image_fn: Callable[..., Any],
    edit_fn: Callable[..., Any],
    sleep_fn: Callable[[float], None],
    on_transient_retry: Callable[[int, Exception], None] | None,
) -> Any:
    """Shared branch between plain text-to-image and image-conditioned
    edit, used by every stage here that can take a reference image.

    WORKAROUND(unfiled -- litellm Gemini image_edit rejects os.PathLike):
    reference images are read as raw bytes, not passed as `Path` objects.
    litellm's Gemini `image_edit` advertises `os.PathLike` in its `image`
    type hint, but `GeminiImageEditConfig._read_all_bytes` handles only
    `bytes`/`BytesIO`/`BufferedReader` and raises `ValueError` on a bare
    `Path`. Re-confirmed by calling it against the installed litellm
    1.101.0, so the upgrade from 1.98.0 did not fix it. Its Vertex sibling
    has the identical gap while `vertex_imagen_transformation` does resolve
    paths, so this is an inconsistency upstream rather than a deliberate
    contract. No upstream issue tracks it and none will be filed, so
    re-check by running the `_read_all_bytes` call above after an
    upgrade rather than by watching a URL."""
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


def run_reference_image_stage(
    prompt: str,
    *,
    model: str | None = None,
    image_fn: Callable[..., Any] = litellm.image_generation,
    output_dir: Path = Path("outputs"),
    sleep_fn: Callable[[float], None] = time.sleep,
    on_transient_retry: Callable[[int, Exception], None] | None = None,
) -> PrevizResult:
    """Generate a character-sheet or location-reference image
    (docs/decisions/0024) -- plain text-to-image, no `FactCheckResult`,
    since a reference image isn't tied to one specific historical scene
    the way a beat's final image is. Same transient-retry behavior as
    the beat stage; `model` defaults to the same pinned "previz" model
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
# Named style presets. Every entry is written the same way on purpose:
# one committed direction plus hard negatives, short enough to be read as
# a single instruction.
#
# This replaces a three-value set whose "stylized" entry was ~100 words of
# hedging -- several directions offered, each disclaimed, consistency
# explicitly "not required or expected". A blind A/B over five horror
# scenes (evals/, docs/decisions/0039) had it lose on style 5-0 against
# committed instructions, and the project owner's read of every hedged
# image was the same word: mush.
#
# The hedging was an attempt to preserve stylistic range. Range is instead
# preserved by having several committed presets and picking one per run --
# commit within a video, vary between videos. Adding a preset is the
# supported way to widen the range; loosening one is not.
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
    "horror-comic": (
        "Stylized horror comic panel -- heavy inked black shadows, bold "
        "confident linework, flat colour fills, high contrast between lit "
        "and unlit areas. Explicitly NOT photorealistic, NOT 3D-rendered, "
        "NOT cute, NOT a soft or rounded children's cartoon."
    ),
    "graphic-poster": (
        "High-contrast graphic poster art -- two or three flat colours "
        "only, bold silhouettes, screen-printed texture. Explicitly NO "
        "rendering, NO gradients, NO photorealism."
    ),
    "painterly": (
        "Dark painterly illustration -- visible brushwork, soft edges "
        "dissolving into shadow, a limited palette of bone white and deep "
        "umber. Explicitly NO hard outlines, NOT photorealistic, NOT "
        "flat-shaded cartoon."
    ),
    "cel-shaded": (
        "Cel-shaded animation still -- clean flat colour blocking, "
        "hard-edged shadow shapes, thick uniform outlines, a saturated "
        "sickly palette. Explicitly NOT photorealistic, NO soft gradients, "
        "NO painterly rendering."
    ),
    "grainy-16mm": (
        "Grainy 16mm horror photography -- halation around light sources, "
        "heavy film grain, crushed blacks, muted green-grey colour timing. "
        "Explicitly NOT illustrated, NOT cartoon, NOT digitally clean."
    ),
}

#: Public name for the preset table -- callers pick a style by name.
STYLE_PRESETS = _STYLE_INSTRUCTIONS

DEFAULT_STYLE = "horror-comic"

#: Styles that render as a real photograph. Kept as data rather than a
#: comment because it is load-bearing: a controlled eval (2026-09-15,
#: docs/playbook/failure-taxonomy.md) found gemini-2.5-flash-image refused
#: an identical violent scene 3 times in 4 when asked for photorealism,
#: and 0 times in 5 when asked for a stylized treatment. Callers can warn
#: rather than discover it as an unexplained empty response.
PHOTOREAL_STYLES = frozenset({"photorealistic", "grainy-16mm"})


def _style_instruction(style: str) -> str:
    try:
        return _STYLE_INSTRUCTIONS[style]
    except KeyError:
        raise PrevizError(
            f"Unknown style {style!r} -- must be one of {sorted(_STYLE_INSTRUCTIONS)}"
        ) from None


def build_character_sheet_prompt(character: Character, *, style: str = DEFAULT_STYLE) -> str:
    """Build the identity reference every beat is conditioned on
    (docs/decisions/0023, 0024, 0040).

    This is an in-world frame, not a turnaround sheet, and that is the
    whole point. Every beat is generated as an *edit* of this image, so
    whatever it establishes as normal, the beats inherit. The previous
    version specified a grey void, shadowless studio light, a centred
    eye-level camera and a calm neutral expression -- and every beat then
    had to fight all four to reach a dark room, one hard source, an
    off-axis camera and visible fear.

    A blind A/B measured it: the neutral sheet was chosen 0 times out of 9
    on action, camera and mood, and this one 9 out of 9 (evals/, ADR 0040).

    Two details that are load-bearing rather than decorative. The wardrobe
    is stated once with explicit negatives, because listing a "signature"
    and a "flexible" wardrobe made the model render a two-figure
    turnaround -- and every beat was then conditioned on an image
    containing two people. And the subject is described, not just named:
    the beat's own SUBJECT line carries a character id, so this is where
    who they are actually gets said.
    """
    return (
        f"CHARACTER: {character.face_build}, {character.hair}.\n"
        f"DISTINGUISHING DETAIL: {character.distinguishing_detail}.\n\n"
        "WARDROBE -- EXACT. The character wears precisely this and nothing "
        f"else: {character.wardrobe_signature}. Do not substitute, restyle, "
        "recolour, add layers, lengthen sleeves, or change the fabric, even "
        "if the pose or setting would suggest different clothing.\n\n"
        "SUBJECT: The character described above, alone. Exactly ONE person "
        "in frame -- not a turnaround, not a costume sheet, no second "
        "figure, no inset panel, no alternate outfit shown alongside.\n"
        "ACTION: Caught mid-movement in an unguarded moment, weight "
        "off-centre, expression alert and uneasy rather than composed. The "
        "face and wardrobe must read clearly, but this must not look like a "
        "posed portrait.\n"
        "SETTING: A dark, unremarkable interior, deliberately vague -- a "
        "real space with depth, not a backdrop.\n"
        "CAMERA: Three-quarter view from slightly below eye level, subject "
        "off-centre in frame.\n"
        "LIGHTING: One hard, directional source from low and to one side, "
        "throwing a defined shadow across the far side of the face and the "
        "surface behind.\n"
        f"STYLE: {_style_instruction(style)} No on-screen text, no logos, "
        "no watermark."
    )


def build_location_reference_prompt(location: Location, *, style: str = DEFAULT_STYLE) -> str:
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
    characters: Sequence[Character] = (),
    location: Location | None,
    style: str = DEFAULT_STYLE,
    corrections: Sequence[str] = (),
) -> str:
    """Build one beat's image prompt from its fields (docs/decisions/0023)
    -- deliberately not routed through _build_prompt, whose "historically
    accurate scene, Time: X, Place: Y" template is scoped to the original
    single-scene flow, not a planned multi-beat shot list.

    STYLE appears exactly once, and only the run's chosen preset can
    supply it. The beat's own `cinematography` text (lens, depth of field,
    grain, colour grade) is legitimate beat-to-beat variety, so it is kept
    -- but attached to CAMERA, where it cannot compete for the same slot.

    Until docs/decisions/0039 this emitted `STYLE: {beat.style}` followed
    by an "OVERRIDING STYLE REQUIREMENT (takes priority over anything
    above)" line, which shipped a live contradiction in every prompt and
    left the model to adjudicate it. A blind A/B over five horror scenes
    (evals/) had that construction lose on style 5-0.
    """
    parts = []
    # One block per character present, labelled, so a beat with more than
    # one has a way to say which is which. Before docs/decisions/0041 only
    # the scene's first character was ever passed here, so a planned
    # antagonist could not be rendered at all.
    staging_by_id = {s.character_id: s for s in beat.staging}
    anyone_is_doing_something = False
    for character in characters:
        label = f"CHARACTER {character.id}" if len(characters) > 1 else "CHARACTER"
        block = (
            f"{label}: {character.face_build}, {character.hair}.\n"
            f"WARDROBE (signature): {character.wardrobe_signature}.\n"
            f"WARDROBE (flexible): {character.wardrobe_flexible}.\n"
            f"DISTINGUISHING DETAIL: {character.distinguishing_detail}."
        )
        # Each character's action sits in their own block rather than in one
        # shared ACTION paragraph, so the model binds the verb to the person
        # it belongs to (docs/decisions/0049). A single blob reliably gave
        # the focal character the verb and left everyone else a static pose.
        staged = staging_by_id.get(character.id)
        if staged is not None:
            anyone_is_doing_something = True
            block += f"\nDOING: {staged.action}"
            # STANDS before SIZE IN FRAME, and both before HIDDEN BY: this
            # is the wording the blind eval measured, where world placement
            # plus a size beat a frame coordinate plus the same size 6/6
            # against 3/6 on depth ordering (docs/decisions/0059).
            if staged.blocking:
                block += f"\nSTANDS: {staged.blocking}"
            if staged.size_in_frame:
                block += f"\nSIZE IN FRAME: {staged.size_in_frame}"
            if staged.occlusion:
                block += f"\nHIDDEN BY: {staged.occlusion}"
        parts.append(block)
    if len(characters) > 1:
        present = ", ".join(c.id for c in characters)
        parts.append(
            f"ALL OF THESE CHARACTERS ARE IN THIS SHOT: {present}. Every one of "
            "them must be visible in the frame, even if only partially -- a "
            "silhouette, a figure in the background, a hand at the frame edge."
        )
    parts.append(f"SUBJECT: {beat.subject}")
    # `beat.action` describes the focal character, and since
    # docs/decisions/0049 every character's physicality already has its own
    # DOING line -- so emitting it here too described the protagonist twice
    # and everyone else once before the model read a word
    # (docs/decisions/0057). Kept only as a fallback: a beat whose staging
    # covers nobody in `characters` would otherwise carry no verb at all,
    # which is the shape of a plan captured before 0049 and replayed.
    if not anyone_is_doing_something:
        parts.append(f"ACTION: {beat.action}")
    if len(beat.staging) > 1:
        parts.append(
            "These characters are in the same moment and must react to each other -- "
            "their gazes, distances and body angles have to agree, not read as separate "
            "figures posed independently and placed in one frame."
        )
    if location is not None:
        parts.append(f"SETTING: {location.architecture}. Fixed props: {location.fixed_props}.")
    parts.append(f"CAMERA: {beat.camera}")
    parts.append(f"LIGHTING: {beat.lighting}")
    parts.append(f"STYLE: {_style_instruction(style)}")
    # Last, because a correction modifies everything stated above it.
    # Phrased plainly rather than as an "overriding requirement (takes
    # priority over anything above)" -- that construction lost a blind A/B
    # 5-0 (docs/decisions/0039).
    for correction in corrections:
        parts.append(f"CORRECTION -- fix this, keep everything else: {correction}")
    parts.append("No on-screen text, no UI, no logos, no watermark.")
    return "\n".join(parts)


def run_beat_image_stage(
    beat: Beat,
    *,
    characters: Sequence[Character] = (),
    location: Location | None = None,
    character_references: Sequence[Path] = (),
    location_reference: Path | None = None,
    style: str = DEFAULT_STYLE,
    model: str | None = None,
    image_fn: Callable[..., Any] = litellm.image_generation,
    edit_fn: Callable[..., Any] = litellm.image_edit,
    output_dir: Path = Path("outputs"),
    #: Lets a caller generate several candidates for one beat into the same
    #: directory without each overwriting the last (docs/decisions/0046).
    filename: str = "previz.png",
    #: Human-typed corrections from earlier attempts on this same beat,
    #: oldest first (docs/decisions/0057). Ephemeral per-attempt text, not
    #: part of the plan -- the recorded beat stays as it was written.
    corrections: Sequence[str] = (),
    sleep_fn: Callable[[float], None] = time.sleep,
    on_transient_retry: Callable[[int, Exception], None] | None = None,
) -> PrevizResult:
    """Generate one beat's image from a ScenePlan (docs/decisions/0023) --
    the beat-driven image stage -- the only image-generation entry point
    for a scene plan (docs/decisions/0051). `character`/
    `location` supply the text description woven into the prompt (see
    `_build_beat_prompt`); `character_reference`/`location_reference`
    (docs/decisions/0024) additionally condition the generation on those
    images, with the same transient-retry behaviour as every other call
    here (see `_call_with_transient_retry`).
    `style` (docs/decisions/0033) is the run's single authoritative
    realism-level source -- see `_build_beat_prompt`.
    """
    resolved_model = model or get_stage_model("previz")
    prompt = _build_beat_prompt(
        beat, characters=characters, location=location, style=style, corrections=corrections
    )
    response = _generate_image_response(
        prompt,
        reference_paths=[
            *character_references,
            *([location_reference] if location_reference is not None else []),
        ],
        model=resolved_model,
        image_fn=image_fn,
        edit_fn=edit_fn,
        sleep_fn=sleep_fn,
        on_transient_retry=on_transient_retry,
    )
    image_path = _extract_and_save_image(response, output_dir, filename)
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
    characters: Sequence[Character] = (),
    beat: Beat | None = None,
    requires_grounding: bool = True,
    previous_concerns: list[str] | None = None,
    model: str | None = None,
    completion_fn: Callable[..., Any] = litellm.completion,
    sleep_fn: Callable[[float], None] = time.sleep,
    on_transient_retry: Callable[[int, Exception], None] | None = None,
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
    if characters or beat is not None:
        planned_lines = []
        for character in characters:
            planned_lines.append(
                f"- Character {character.id} is deliberately planned and present in this "
                f"shot -- do NOT flag them as unplanned or unexpected, and do NOT flag "
                f"their appearance as anachronistic in isolation: wardrobe is "
                f"{character.wardrobe_signature} ({character.wardrobe_flexible}); "
                f"{character.distinguishing_detail}"
            )
        if beat is not None:
            # Every planned field, not just subject/action. The threat in a
            # horror beat is specified in `lighting` -- scene_planning's own
            # threat rule requires its placement and occlusion to be stated
            # there -- so a reviewer shown only the action had no idea the
            # monster was planned, and rejected real runs for "an unplanned
            # humanoid silhouette figure". It was burning all three paid
            # attempts on exactly the beats that had worked.
            #
            # docs/decisions/0032 anticipated this: it noted that a further
            # recurrence of "reviewer re-derives something the plan already
            # approved" should mean handing over the whole plan rather than
            # adding one more named exception. This is that.
            planned_lines.append(
                f"- This beat was already deliberately planned in full -- do NOT "
                f"flag any of it as wrong on its own terms, and in particular do "
                f"NOT report anything described here as unplanned or unexpected. "
                f"SUBJECT: {beat.subject}. ACTION: {beat.action} "
                f"CAMERA: {beat.camera} LIGHTING: {beat.lighting}"
            )
        planned_details_block = (
            "\nThe following specific details were already deliberately planned "
            "and human-reviewed as part of this scene -- do NOT flag them as "
            "anachronisms or problems on their own, no matter how implausible "
            "they'd look in isolation; only flag if the image fails to actually "
            "depict them faithfully, or introduces a DIFFERENT, new problem not "
            "covered here. A physical distinguishing detail (a scar, a chipped "
            "tooth, a piercing) only needs to be visible when the beat's own "
            "described pose, camera angle, or action would naturally reveal it "
            "-- do NOT reject an image for failing to show a detail that the "
            "described framing wouldn't show anyway (e.g. a forearm scar when "
            "that arm/side isn't presented to camera, a chipped tooth when the "
            "mouth isn't open toward camera). Only flag a missing detail when "
            "the described pose/angle genuinely would have shown it:\n"
            + "\n".join(planned_lines)
            + "\n"
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

    # Same transient-retry treatment the image calls have had since
    # docs/decisions/0016. It was never applied here, so a single network
    # blip on the review call killed an entire run -- after its images had
    # already been generated and paid for. Observed twice in one session,
    # as an SSL "bad record mac" surfacing as litellm.InternalServerError,
    # which was already in the transient set; only this call site was
    # missing.
    response = _call_with_transient_retry(
        completion_fn,
        sleep_fn=sleep_fn,
        on_transient_retry=on_transient_retry,
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
