# 6. Narrow v1 scope: single scene, single image, no video yet

Date: 2026-08-20

Status: Accepted

## Context

The pipeline in [pipeline.md](../pipeline.md) was designed around a fairly open-ended
early vision, before any stage had real code or real output to react to. Now
that stage 2 (research) exists and produces actual output, Sean wants to
refocus effort on validating that the pipeline mechanically works end to end
-- input in, an image out, each step checkable -- before investing further in
the multi-scene/video machinery downstream of it. This isn't a change to the
project's ceiling (see [architecture.md](../architecture.md)'s Vision, which
stays the eventual goal, including Shorts per
[0002](./0002-shorts-first-format.md)) -- it's a deliberate narrowing of what
gets built *right now*.

## Decision

**Input**: the pipeline's input is no longer a bare topic string. It's three
required fields:

- `time` -- when the scene takes place (free text, can be historical)
- `place` -- where the scene takes place (free text)
- `description` -- what a main character does and what happens to/around
  them, in **third person**. The character is a generic/placeholder person
  for now; whether this becomes a consistent "brand" character used across
  every video, or stays input-determined, is an open question, not decided
  by this ADR.

This replaces `topic: str` as what `run_research_stage` takes in --
tracked as a code change alongside this ADR, not a future one.

**Stage scope for v1**: stages 1-3 (topic/scene selection, reframed as the
input above; research; fact-check) are followed directly by a scoped-down
Previz (stage 8) that builds one image prompt from the verified scene
description and generates a single image. Stages 4-7 (narrative/script,
script quality review, shot list, per-scene video prompts) are **skipped for
v1, not deleted** -- they decompose a multi-scene script into individual
shots, and there's no script to decompose when the deliverable is one image
from one described scene. They come back once an actual multi-scene Short is
being assembled. Stages 9-12 (video generation onward) are untouched and
still future work.

**Review gate for v1**: architecture.md's "Control flow" open question (how
stages pause for review) is answered for v1 as a simple interactive CLI
prompt after each stage -- see `src/historical_video_ai/cli.py`. This does
not resolve that open question for the full pipeline; Step Functions
(per [0004](./0004-aws-incremental-adoption.md)) remains the likely answer
once there's real multi-stage, multi-scene orchestration to manage, which
a single linear CLI run doesn't need yet.

## Consequences

`research.py`'s function signature, `FactSheet`, and `Claim` change to take
the new input shape instead of a topic string. `config/models.yaml` gains a
`fact_check` implementation and a new `previz` stage; the entries for
`narrative`, `narrative_review`, `shot_list`, and `video_prompts` stay in the
file as placeholders (harmless, unused by v1 code) rather than being deleted,
since the full 12-stage vision is still where this is headed.

`docs/architecture.md`'s "Research/grounding model" and "Image model for
previz" open questions are addressed by
[0007](./0007-research-fact-check-previz-models.md), a separate decision
from this one.
