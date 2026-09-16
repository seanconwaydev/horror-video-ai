# 38. Video generation implemented on Replicate; the moderation pre-flight is rescoped to one advisory layer

Date: 2026-09-15

Status: Accepted

Supersedes the implementation halves of [0012](./0012-video-generation-duration.md),
[0020](./0020-video-seconds-validated-client-side.md) and
[0022](./0022-video-generation-moderation-preflight.md); voids the stated
rationale of [0011](./0011-previz-image-model-for-video-aspect-ratio-fit.md).

## Context

[0037](./0037-horror-motion-comic-shorts-wan-via-replicate.md) decided that
video generation moves off `openai/sora-2` to Wan 2.2 hosted on Replicate, and
explicitly left the code changes as follow-up work. This ADR is that work.
It had a real deadline rather than a preference behind it: OpenAI removes the
Videos API on 2026-09-24.

The exact Replicate model slug behind 0037's testing was never recorded
anywhere in the repo. It was re-identified against Replicate's live API as
`wan-video/wan-2.2-i2v-fast`, matching 0037's stated ~$0.05/clip (Replicate
reports a $0.05-$0.145 per-video range for it, median $0.057).

Reading that model's real schema surfaced two differences from Sora that are
not cosmetic:

- **Duration is frames, not a seconds enum.** `num_frames` accepts 81-121 at a
  given `frames_per_second`, and Replicate bills against duration at 16fps.
  The real supported range is therefore roughly **5.06s to 7.56s** -- much
  narrower than Sora's 4-20s.
- **Aspect ratio follows the input image.** Sora required its reference image
  to be pixel-exact to the requested video size, which is the entire reason
  0011 pinned previz's image model and the reason `video_generation.py`
  carried resize-and-refuse machinery. Wan has no such requirement.

Separately, 0022's layer 2 (`run_moderation_risk_review`) was built to guess at
Sora's own unusually conservative moderation. Wan has no vendor-baked safety
alignment for it to predict, so the layer could only ever produce false
positives -- and had already done so on a real run, skipping two harmless beats
before any API call was attempted.

The same Sora-shaped assumption had leaked into `cli.py`'s advisory prompt
checks, which warned against "fight", "attack", "kill", "blood", "injury",
"weapon", "battle", "war" and "die". Against a project that has since committed
to horror (0037), that check actively steered prompts away from the vocabulary
the genre requires.

## Decision

1. **`stages/video_generation.py` calls Replicate directly** through a new
   `replicate_client.py` -- a thin REST module (create prediction, poll,
   download) with injectable `request_fn`/`download_fn` seams, matching the
   project's existing no-network-in-tests convention. Deliberately not the
   `replicate` SDK: the surface needed is three HTTP calls, and a client object
   fits this codebase's function-seam testing pattern poorly. `httpx` is now a
   declared dependency rather than one inherited transitively from litellm.
2. **`config/models.yaml` marks the stage with a `replicate/` prefix**
   (`replicate/wan-video/wan-2.2-i2v-fast`), stripped before the API call. The
   prefix is not a LiteLLM provider -- it exists so a reader can see at a glance
   which stage bypasses litellm, and a model string missing it is a config
   error rather than a silent guess.
3. **Duration is requested in seconds and validated against the model's real
   range**, then converted to a frame count at 16fps. Out-of-range values are
   refused before any call rather than clamped, keeping 0020's reasoning while
   replacing its Sora-specific enum. `--video-seconds` is now a float.
4. **The aspect-ratio machinery is deleted**, not ported: `_resize_reference_image`,
   `_TARGET_VIDEO_SIZE`, `_MAX_ASPECT_RATIO_DEVIATION`. `previz.py` no longer
   imports the video stage's size constant and owns its own 9:16 hint.
5. **Moderation keeps one layer, and it never blocks.**
   `run_moderation_risk_review`, `_KNOWN_MODERATION_RISK_PATTERNS` and the
   `moderation_review` config entry are deleted. The free
   omni-moderation-latest check remains, reporting flagged categories into the
   run log as a YouTube-policy signal for the human. Horror trips the violence
   category as a matter of course; treating that as a stop condition would block
   the project's own genre.
6. **The Sora-era prompt checks are removed** -- both the risk-word list and the
   audio-direction check (Wan generates no audio, so asking a prompt to describe
   sound is dead weight until a real sound-design step exists). A regression test
   now asserts that horror vocabulary is *not* flagged.

## Consequences

**0011's rationale is void, so previz's image model is an open choice again.**
0011 picked `gemini/gemini-2.5-flash-image` because its 9:16 output was a close
match to Sora's fixed size. That constraint no longer exists. This is not a
decision to change the model -- it is a decision to stop treating it as settled,
which matters because Gemini's image-side moderation is now the binding
constraint on how creepy or violent a panel this project can render, and the
video stage no longer is.

**`OPENAI_API_KEY` now has exactly one use**: the free moderation endpoint.
Nothing paid in this project runs on OpenAI any more.

**Duration planning changes.** Any beat written around a 4s or 8s clip needs
revisiting -- the floor is now ~5.06s and the ceiling ~7.56s.

**Still open, deliberately not addressed here:** Wan generates no audio, a real
regression against Sora that needs its own sound-design step (0037 flagged it;
the project owner has since confirmed it as a high priority once image quality
improves). And no real paid call has been made through this new code path yet --
it is verified against mocks and the real published schema, not a live
generation.
