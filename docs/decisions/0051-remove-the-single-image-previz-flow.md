# 51. Remove the single-image previz flow

Date: 2026-09-16

## Status

Accepted. Supersedes [0009](0009-previz-image-review.md)'s flow and
closes out the narrow scope [0006](0006-narrow-v1-scope-single-image.md)
set.

## Context

ADR 0006 scoped v1 to a single previz image generated straight from the
fact-checked scene, skipping the shot-list stages. ADR 0009 added an
independent review pass over that image. ADR 0023 then introduced scene
planning, and every image the pipeline produces now comes from a beat via
`run_beat_image_stage`.

The single-image flow was never removed. Tracing reachability:

```
run_previz_stage()  <- cli.py, inside _generate_previz_with_review()  <- nothing
```

`main()` calls `run_scene_planning_stage` unconditionally, so no CLI
invocation reaches it. Its only callers were its own tests, which is
exactly why it went unnoticed: the suite passed, so the code looked
maintained.

Two things had rotted inside it. Its prompt builder was the historical
one -- "historically accurate scene, Time: X, Place: Y", with a warning
against claims from other eras -- which contradicts
[0031](0031-goal-is-quality-video-not-historical-accuracy.md). And it
opened with a hard refusal:

> Refusing to generate an image: the scene's premise was flagged as
> historically impossible and was never resolved

That was the last remaining validator in the codebase whose predicate is
a judgement call rather than a decidable property of the artifact (see
[0048](0048-heuristic-gates-warn-rather-than-fail.md)), and it refuses
precisely the kind of scene 0031 says is now fine.

## Decision

Delete `run_previz_stage`, `_build_prompt`, and
`_generate_previz_with_review`, along with the premise-conflict refusal
they contained.

Reading old artifacts stays. `VideoGenTarget` and `_load_previz_output`
still parse run logs in the old single-image shape, so `--video-gen-from`
keeps working against archived runs; only the generation path is gone.

Tests were ported rather than deleted wherever they covered machinery
that is still live. The transient-retry loop, the image-response parsing
and moderation hint, the model-from-config resolution, the aspect-ratio
hint and the reference-image handling are all shared with the beat path
and were only ever reached through the single-image flow in tests, so
those now exercise `run_beat_image_stage`. The review-loop tests now call
`_generate_image_with_review` directly. Only five tests were dropped
outright, all asserting on the deleted historical prompt or the refusal.

The `image_edit` PathLike finding -- litellm's Gemini provider advertises
`os.PathLike` but its `_read_all_bytes` raises on a bare `Path` -- lived
in the deleted docstring and was moved to `_generate_image_response`,
where the code it describes actually is.

## Consequences

One image-generation entry point instead of two, and the historical
framing is gone from the code that generates images at all.

The risk is that the single-image path was a simpler mode someone might
want back. It is recoverable from git, but the better answer is that
`--genre horror` already skips research and fact-check, which is the
lightweight path in practice; a plan with one beat is the rest of it.

`CLAUDE.md` described the deleted flow as the current build and was
updated in the same change. It also carried two other stale claims found
while checking: that video generation goes through
`litellm.video_generation()` (it has called Replicate directly since
[0037](0037-horror-motion-comic-shorts-wan-via-replicate.md)) and that video generation is
still deferred. A wider sweep for this kind of documentation rot is
recorded as an open question in `docs/architecture.md`.
