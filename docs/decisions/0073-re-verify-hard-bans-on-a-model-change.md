# 73. Re-verify hard bans when the model changes

Date: 2026-09-21

Status: Accepted

Nothing superseded. Adds a maintenance rule the prompt layer never had,
and narrows the registry that [0058](./0058-delete-rules-by-judgement-not-ablation.md)
declined to build.

## Context

The scene-planning prompt is a pile of rules, each written because a real
run got something wrong. Two kinds live in there and they age completely
differently.

A rule that **asks** for something reports on itself every run. "State
where the eyes are pointed" either shows up in the next batch of images
or it doesn't, and the human at the review prompt sees which. It cannot
quietly become wrong.

A rule that **forbids** something never reports on itself at all. Since
[0071](./0071-beats-describe-one-camera-view.md) banned character
reflections, no beat has asked for one, so no image has been generated
that could show the ban is no longer needed. The ban is self-sealing: it
suppresses the only evidence that would retire it. If the image model
gains the ability to render a reflection tomorrow, nothing in this
project will ever notice, and the ban costs range forever.

That is not hypothetical here. [0011](./0011-previz-image-model-for-video-aspect-ratio-fit.md)
carries the line "Stated rationale voided by 0038" at the top: a decision
made to fit Sora-2's fixed aspect ratios outlived Sora-2 by a month
before anyone wrote that down. A prompt ban has the same failure mode with
none of 0011's visibility, because it is a sentence inside a string rather
than a file with a Status line.

Every hard ban this project has was measured against exactly one image
model, `gemini/gemini-2.5-flash-image`. None of them is a fact about image
models in general, however confidently the rule text states it.

## Decision

**Distinguish a hard ban from a schema rule.** A *hard ban* forbids
something because a specific model rendered it badly — reflections,
distant threats, process verbs, two spaces in one frame. It expires when
that model does. A *schema rule* forbids something because the data model
or physics forbids it — a frame coordinate in `blocking`, staging a
character the camera cannot see, stating facing in two fields at once.
Those are true regardless of model and are out of scope here.

**The trigger is a model change, not a schedule.** When `config/models.yaml`'s
`previz` (or `video_generation`) pin moves to a different model family or
a major version, re-verify every hard ban before shipping the new pin.
Not on a cadence: nothing decays while the model is fixed, and a
calendar-driven re-check of rules nobody has reason to doubt is how this
project's audits end up producing nothing.

**Bans get re-verified first, ahead of tuned wordings.** Field ordering,
the phrasings that won a blind A/B, the exact occlusion vocabulary — all
of those are also model-specific and all of them will need re-measuring
eventually. But they announce their own failure the next time someone
looks at four candidate images. The bans do not, so they go first.

**A greppable marker, mirroring the `WORKAROUND(...)` convention** this
project already uses for the same reason (CLAUDE.md, "Known upstream
workarounds"). Each hard ban gets a comment on the rule constant that
carries it:

```
MODEL-BAN(<model it was measured on> -- <how to re-test it directly>): <what is banned>
```

`grep -rn "MODEL-BAN(" src/` then lists every ban currently in force and
how to check each one. The re-test clause is mandatory and must be a
concrete thing to generate, for the same reason an unfiled `WORKAROUND`
must say how to re-test the bug: there is no external tracker to watch,
so a marker that only names the ban is a marker nobody can act on.

**The re-test is a generation, not an argument.** For each ban, ask the
new model for the forbidden thing directly — on the frozen anchor scene
([0064](./0064-eval-fixtures-are-frozen-evidence.md)) so the comparison is
against known material — look at the images, and then keep or delete the
rule on its merits, which is 0058's standard. Do not reason from the
model's documentation or its reputation about whether it can render a
reflection.

**A ban that survives gets its marker's model updated**, so the
measured-on model and the pinned model stay the same. This is the same
discipline CLAUDE.md already states for workarounds ("Keep the pinned
version and the verified version the same"), which was written after two
workarounds were verified against a version the project did not run.

The hard bans in force today, all measured on
`gemini/gemini-2.5-flash-image`:

| Ban | Why | ADR |
| --- | --- | --- |
| No character reflections in glass, mirrors, water or metal | renders a second copy of the person standing in frame | [0071](./0071-beats-describe-one-camera-view.md) |
| One beat is one space | an interior plus the structure outside its windows degrades the whole frame | [0071](./0071-beats-describe-one-camera-view.md) |
| No physical minutiae (visible breath, condensation beads) | does not survive to phone resolution and spends the complexity budget | [0071](./0071-beats-describe-one-camera-view.md) |
| One dominant light source per beat | two comparable sources render flat and sourceless | [0071](./0071-beats-describe-one-camera-view.md) |
| A threat is never distant, only occluded | written as distant, it rendered a few feet off in 21 of 22 measured images | [0060](./0060-threat-is-hidden-not-distant.md) |
| No camera position in the location's floor plan | the model places no virtual camera; the shot fails its own description | [0044](./0044-camera-specified-at-a-granularity-models-follow.md) |
| No process verbs ("turning", "spinning") in a staging action | a still frame has no before-and-after, so it renders as stillness | [0071](./0071-beats-describe-one-camera-view.md) |
| Escalation never encoded only as a larger `size_in_frame` | produced one motionless man at four zoom levels | [0049](./0049-per-character-staging-in-beats.md) |

## Consequences

This is a registry, which 0058 declined to build — but a much smaller one
than the design it declined, and it answers a different question. That
design made every rule individually switchable so it could be ablated and
measured; 0058 refused it because the project has no automated scorer to
ablate against, and that is still true. This one is a list of eight rules
and a re-test recipe for each, judged by a human looking at images. It
adds no machinery and no switching, and it does not extend to the rest of
the prompt.

The marker convention's real risk is the one CLAUDE.md already documents
for workarounds: a variant spelling that the grep cannot find. `MODEL-BAN(`
is the only accepted form.

A model change is now more expensive than editing one line of
`config/models.yaml`, which is the point. It was already more expensive
than that and the cost was simply unrecorded.
