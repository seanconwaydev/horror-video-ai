# 60. An embodied threat is made ominous by occlusion, not by distance

Date: 2026-09-19

Status: Accepted

Rewrites the threat-presence rule added to `scene_planning.py` after the
2026-09-14 horror run, which never had an ADR of its own. No existing
decision is narrowed or superseded -- in particular the composition rule
is deliberately left intact, for the reason given under Decision.

## Context

Four blind runs of `evals/blocking_space.py` measured whether a figure
written as distant renders as distant. It does not: **1 success in 22
images**, across world-space phrasing, frame coordinates, and an explicit
"roughly a twentieth of the image". The project owner, scoring blind:
"he's never more than ~10 feet in front of her, i don't consider that 'far
away', a parking garage could have him 50-100+ feet away easily."

[0059](./0059-blocking-and-size-replace-frame-position.md) recorded that as
a scene-writing constraint rather than a schema one and left it there. A
plan-only run the same day (`run_20260919-003600`) showed why that was not
enough. Beat 1 placed the figure "far down the aisle beyond her" at
"roughly a twentieth of the image height" -- precisely the unrenderable
shot, on the first beat of the first plan written after 0059 shipped.

The planner was not misbehaving. Two rules ask for that shot by name. The
threat-presence rule offered "a shape at the edge of vision" as a way to
keep the threat present, and the composition rule offers "a subject small
and low with the space around them dominating" as one of three deliberate
choices. The audit had already noted the planner copying those example
phrasings near-verbatim. A prompt that asks for the one thing the image
model reliably fails will keep getting it.

What the same evals show *does* render is the opposite shot. Occlusion
works -- the owner's best images are an antagonist with a hand braced on
the pillar he is hiding behind, and a pillar covering half a face. And
near-field depth ordering works now that `size_in_frame` exists, 14/14.

## Decision

The threat-presence rule stops offering distance and says so explicitly:

> An embodied threat is made ominous by OCCLUSION, not by distance. Do NOT
> place it far away from the protagonist or deep in the background: a
> figure written as distant rendered as merely a few feet off in 21 of 22
> measured images, whatever `size_in_frame` said, so the shot reads as a
> mistake rather than as distance. Put it CLOSE and HIDDEN instead --
> behind the near edge of a pillar, a door frame, a parked car, with
> `occlusion` naming exactly how much of it survives.

"A shape at the edge of vision" is replaced by "a shape partly behind a
near object", so the menu item that produced the failure is gone rather
than merely counterbalanced by a later rule -- 0049's lesson is that a
buried correction loses to a concrete suggestion stated elsewhere.

**The composition rule is left alone.** "A subject small and low with the
space around them dominating" stays available. The evidence covers a
*background figure at depth in a two-character shot*; it does not cover a
lone subject small in a large empty frame, which is a different image and
was never tested. Deleting an untested option would be the mistake
[0058](./0058-delete-rules-by-judgement-not-ablation.md) named in the
opposite direction.

## Consequences

This narrows what horror scenes this pipeline will write. A threat noticed
at the far end of a space is a real and common horror shot, and the
pipeline now declines to plan it. That is a genuine loss of range, taken
deliberately because the alternative is planning a shot that arrives
broken and burns paid retries on something no retry fixes.

The rule also makes a claim beyond renderability -- that close and hidden
is *scarier* than far and small. That is an opinion, not a measurement,
and it is in the prompt because a rule a model can act on needs a reason
attached. If a future run suggests otherwise, this is the sentence to cut
first.

Unresolved: whether the same distance limit applies to a *lone* subject,
and whether it is specific to this image model at this prompt length. The
1-in-22 result is from `gemini-2.5-flash-image` with ~450-word prompts.
`evals/blocking_space.py` takes `--scenarios` and `--arms` and would answer
the first cheaply.
