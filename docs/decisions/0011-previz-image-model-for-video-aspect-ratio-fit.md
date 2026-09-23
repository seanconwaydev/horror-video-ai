# 11. Move previz off OpenAI to fit Sora-2's required aspect ratio

Date: 2026-08-25

Status: Accepted

Stated rationale voided by [0038](./0038-video-generation-on-replicate-and-moderation-rescope.md).

Superseded by [0079](./0079-previz-moves-to-gemini-3-1-flash-lite-image.md), which repinned this stage when the model chosen here was shut down.

## Context

Building stage 9 ([0010](./0010-video-generation-model-and-standalone-stage.md))
against a real previz image surfaced a problem [0007](./0007-research-fact-check-previz-models.md)
never had reason to consider: previz's placeholder image model
(`openai/gpt-image-1-mini`) and stage 9's placeholder video model
(`openai/sora-2`) don't produce and consume compatible image shapes.

A real Sora-2 call against a real previz image failed with `"Inpaint image
must match the requested width and height"`. Checked against OpenAI's own
docs: Sora-2 only accepts two fixed sizes, `720x1280` (portrait) or
`1280x720` (landscape), and requires the reference image to match one of
them exactly, pixel-for-pixel -- the reference image becomes the video's
literal first frame, with no outpainting or masking to reconcile a
different shape. gpt-image-1-mini's own fixed sizes (`1024x1024`,
`1024x1536`, `1536x1024` -- also verified against OpenAI's docs, not
guessed) don't include a size matching Sora-2's, and previz wasn't even
requesting one of the three -- it was getting the landscape default,
`1536x1024`, which doesn't even share Sora-2's aspect ratio (3:2 vs 9:16).

Three ways to reconcile this were considered:

**Padding/letterboxing** -- rejected. Verified against OpenAI's Sora docs
that the reference image's pixels, padding included, are treated as
literal visible content and animated as-is; there's no invisible-margin
mechanism like a video player's own letterboxing. Padding would bake
visible fake bars into the actual generated video.

**Crop to fit**, in one of two places:
- Crop only in `video_generation`, previz unchanged (still `1536x1024`
  landscape): scaling to cover a `720x1280` target and cropping the
  excess works out to **~62.5% of the frame area cropped away** -- only
  ~37.5% of the original horizontal field of view survives.
- Change previz to request its portrait option (`1024x1536`, still not
  Sora-2's exact ratio -- 2:3 vs 9:16) and crop that instead: **~15.6% of
  the frame area cropped**, from the sides only.

Both crop options put real scene content at risk of being cut from the
video that wasn't cut from the still Sean approves at the previz review
gate -- undermining pipeline.md's stage 8 review gate, which exists
specifically so "the approved still... becomes the reference image fed
into the video model" for that scene, not a differently-framed crop of it.

**Switch previz's model to one whose native aspect ratio is close enough
to Sora-2's that only a resize is needed, not a crop.** Checked litellm's
own installed source for Gemini's image aspect-ratio-to-resolution table
(`litellm/llms/gemini/common_utils.py`, itself sourced from Google's own
docs): `gemini-2.5-flash-image`'s `9:16` output measures `1.7917`
(e.g. `768x1376`) against Sora-2's exact `1.7778` (`720x1280`) -- a
**~0.8% difference**. A resize from one to the other is a barely-perceptible
sub-1% stretch, not a crop -- **no scene content is lost**.

## Decision

`previz`'s model moves from `openai/gpt-image-1-mini` to
`gemini/gemini-2.5-flash-image` (`config/models.yaml`), requesting a `size`
close to `9:16` (`gemini-2.5-flash-image` only supports requesting an
aspect ratio, not an exact pixel size, so this is a hint, not a literal
request). This resolves [0007](./0007-research-fact-check-previz-models.md)'s
previously-open "previz image model" question -- not because Gemini won a
rigorous side-by-side comparison (it didn't get one, same "unblock, not a
rigorous decision" status previz's model choice has always had), but
because the aspect-ratio fit with Sora-2 is now a concrete, measured
requirement, not just a placeholder choice with no basis to compare on.

`video_generation` resizes the reference image to Sora-2's exact
`720x1280` immediately before submission (`_resize_reference_image` in
`stages/video_generation.py`), and explicitly passes `size="720x1280"` to
the video-generation call -- confirmed by reproduction that Sora validates
the reference image against whatever `size` was *requested*, not just its
own unstated default, so omitting `size` fails even with a correctly-sized
image. A safety check refuses (raises `VideoGenerationError`) rather than
silently resizing if the source image's aspect ratio deviates from the
target by more than 10% -- comfortably above Gemini's measured ~0.8% gap,
comfortably below a landscape image's, so a stale or wrongly-shaped previz
image gets a clear error instead of a badly distorted video.

Both the Gemini image-generation request/response call shape and the
Sora-2 multipart request-building path were verified by direct
reproduction against litellm's real code (bypassing the network, no
charges incurred) before this was wired into real stage code -- not a
blind guess at either provider's behavior.

## Consequences

`config/models.yaml`'s `previz` entry changes; no `expected_stages` change
needed in `tests/test_config.py` (the stage name is unchanged, only its
model). `pyproject.toml` gains `pillow` as a dependency -- needed for the
resize/aspect-ratio check in `video_generation.py`, and not previously
needed anywhere in this codebase.

`GEMINI_API_KEY` (already required for `fact_check`) now also covers
`previz`; `OPENAI_API_KEY` moves from being previz's key to being
`video_generation`'s (`.env.example` updated accordingly). `previz_review`
staying on `anthropic/claude-sonnet-5` still satisfies
[0009](./0009-previz-image-review.md)'s "not the same model checking its
own work" reasoning -- Gemini and Anthropic are still different providers.

`docs/architecture.md`'s "Image model for previz" open question is updated
to point here instead of 0007, with the same "not the ceiling, just what's
needed to unblock this" framing carried forward -- Kling, Runway, and a
rigorous quality comparison against gpt-image-1-mini are all still
untried.

Not yet exercised against a live key from either previz's new model or
`video_generation`'s resize path together in one real, paid run -- the
call shapes are verified, the actual output quality and whether Sora-2
accepts the resized image in practice are not. Treat that first real run
as a test, same caveat as everywhere else in this project.
