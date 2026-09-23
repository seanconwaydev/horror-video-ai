# 79. Previz moves to gemini-3.1-flash-lite-image

Date: 2026-09-23

Status: Accepted

Supersedes [0011](./0011-previz-image-model-for-video-aspect-ratio-fit.md),
which picked the pin this replaces. Triggers, and leaves open, the
re-verification [0073](./0073-re-verify-hard-bans-on-a-model-change.md)
requires on a model-family change.

## Context

`gemini/gemini-2.5-flash-image` has been previz's pinned image model since
[0011](./0011-previz-image-model-for-video-aspect-ratio-fit.md). Google has
deprecated it and shuts it down on **2026-10-02**. That is not a quality
judgement and not optional: the pin stops working on a known date, and
`config/models.yaml` fails loud rather than substituting anything, so the
stage simply stops.

This is the second time a pinned model has retired underneath this project
([0018](./0018-fact-check-model-retired.md) was the first), and the failure
mode `config/models.yaml`'s own header warns about.

The named successors are `gemini-3.1-flash-image` ($0.067 per 1K image) and
`gemini-3.1-flash-lite-image` ($0.0336). Both are in litellm 1.101.0's model
map -- the version this project pins -- as `gemini`-provider
`image_generation` models, so no upgrade or workaround is needed to call
either.

0011's stated reason for its choice was aspect-ratio fit with the
video-generation stage. That reason is already void:
[0038](./0038-video-generation-on-replicate-and-moderation-rescope.md)
established that Wan takes its output aspect ratio from whatever image it is
handed, so previz owns the choice outright and no longer has a ratio to
match.

## Decision

Pin previz to `gemini/gemini-3.1-flash-lite-image`.

Lite over the full Flash Image on price. Previz is the iteration loop, not
the final render -- the owner's real runs regenerate a beat several times
before keeping the least-bad candidate
([0076](./0076-rejections-carry-a-reason-code.md)'s premise), so this
stage's cost is multiplied by attempts in a way no other stage's is. At
$0.0336 it is also cheaper than the model it replaces ($0.039), so the
switch does not cost anything to try. If Lite proves visibly worse, the full
Flash Image is a one-line change and roughly doubles the per-image price.

## The hard bans are now unverified, and stay that way until someone looks

[0073](./0073-re-verify-hard-bans-on-a-model-change.md) says a
`MODEL-BAN(...)` does not survive a model-family change on its own merits,
because a ban suppresses the only evidence that would retire it. This change
crosses a model family. All eight bans in `stages/scene_planning.py` were
measured on `gemini-2.5-flash-image` and **none has been re-tested against
the new pin**:

1. A threat is never distant, only occluded ([0060](./0060-threat-is-hidden-not-distant.md)).
2. No reflected people.
3. One beat is one space -- no interior plus the structure outside its windows.
4. No physical minutiae (visible breath, beads of condensation).
5. One dominant light source per beat.
6. No camera world-position in a location's floor plan ([0044](./0044-camera-specified-at-a-granularity-models-follow.md)).
7. No process verbs in staging -- name the frozen instant.
8. Escalation must show in the body, not only in `size_in_frame` ([0049](./0049-per-character-staging-in-beats.md)).

Their markers deliberately still read `gemini/gemini-2.5-flash-image`.
Relabelling them to the new pin would assert a verification that has not
happened, which is exactly the silent-and-forever failure 0073 exists to
prevent. Each marker already carries its own re-test instruction; a ban gets
its label updated when, and only when, someone generates the forbidden thing
against Flash Lite and looks at the result.

Until that happens the pipeline is running 2.5's bans against a 3.1 model.
That is the correct default -- a stale ban costs some expressive range,
while dropping all eight untested would cost the accumulated findings of
roughly thirty ADRs -- but it is a debt, not a clean state.

## Consequences

Previz gets marginally cheaper and survives 2026-10-02. Nothing else in the
pipeline changes: the call shape, the 9:16 size hint, and the `image_edit`
reference path are all unchanged, and `cli/app.py`'s cost table keeps the
old model's price so replaying an archived run still reports what that run
actually cost.

Three things are explicitly *not* settled here. The eight bans above. Any
quality comparison -- this is a forced move plus a price preference, and the
bake-off against `gpt-image-1-mini` and others that `architecture.md` has
carried as open since 0011 is still untried. And `evals/`, which hardcodes
`gemini-2.5-flash-image` as a model key in four scripts
(`run_eval.py`, `conditioning_bakeoff.py`, `camera_obedience.py`,
`blocking_space.py`); those are comparison registries rather than the
pipeline's own pin, and they break on the same date unless updated
separately.
