# 54. One fact per field; a losing instruction gets a field, not a firmer sentence

Date: 2026-09-17

Status: Accepted

Narrows [0052](./0052-composition-vocabulary-is-unconditional.md), whose
rule text this ADR replaces.

It also completes the tier move that
[0049](./0049-per-character-staging-in-beats.md) began, which stands
unchanged -- 0049's pattern is the evidence for this ADR, not its target.

## Context

A four-beat horror run on 2026-09-17 produced 16 rejected candidates, and
the project owner reviewed every camera and staging field in it. Sorting
those verdicts by *which field made a claim* against *what the claim was
about* gives a near-perfect split:

| field | claim about | verdict |
|---|---|---|
| `camera` | the camera (shot size, height, orientation) | good 4/4 |
| `camera` | where the figure is | wrong 4/4 |
| `frame_position` | position | good 3/4 |
| `frame_position` | occlusion | **wrong 4/4** |

The owner said it four times in near-identical words: "position is good,
but his hiddenness is 100% wrong."

This is one defect, not four. `frame_position` received its own schema
field and its own labelled line in the image prompt under 0049, and
position is respected. Occlusion had neither -- it was prose inside
`frame_position`'s sentence -- and it was ignored in every beat. Same
field, same sentence, same model, same beat: the half with structure is
obeyed and the half without is not.

Two further findings from the same run have the same shape.

**The `camera` pollution was self-inflicted.** [0044](./0044-camera-specified-at-a-granularity-models-follow.md)
already states that `camera` must carry shot size, camera height and
subject orientation "and nothing else". [0052](./0052-composition-vocabulary-is-unconditional.md),
written two days earlier, instructed the planner to write a compositional
choice into `camera` and offered four examples that are all subject
placement. Every camera failure in the run traces to one of those four:
"the empty wet deck fills the right two-thirds" (no such thing existed),
"pillars lead the eye past her to the corner where it waits" ("1000%
wrong"), "the car's wet flank fills the near left foreground" ("metal
doesn't look wet"). 0052 was written during the session whose stated
purpose was finding contradictions between decisions, and it introduced
one.

The contradiction also explains something the owner noticed and the
inspection had missed: "there's a conflict between where he's stated to be
and what the image actually shows." The figure's position was stated
twice, in `camera` and in `frame_position`, sometimes incompatibly -- at
the right frame edge *and* bending in past her shoulder in a close-up --
so the model satisfied one and dropped the other.

**Process verbs cannot render.** "Spinning", "trembling", "leaning out
past the edge" and "lowering head" all failed. A single frame has no
before-and-after, so a verb describing a transition renders as a
character standing still. The owner's "no indication of 'spinning'" is
the model doing its best with an unrenderable request.

## Decision

The general rule, which is the part meant to outlive these three fixes:

**A field states one kind of fact. When an instruction already exists and
keeps losing, give its fact a field of its own and a labelled slot in the
downstream prompt -- do not restate the instruction more firmly.** A
second sentence about the same thing adds a competitor rather than
removing one, and which competitor wins is a function of how concrete and
prominent each is rather than which is correct.

Applied here:

1. `Staging.occlusion` is a new field: what physically stands between the
   camera and this character, and roughly how much of them survives it.
   It emits as its own `HIDDEN BY:` line, exactly the shape that made
   `POSITION IN FRAME:` work. `frame_position` is WHERE; `occlusion` is
   WHAT HIDES THEM.
2. `camera` carries 0044's three terms only. 0052's rule text is replaced:
   it still demands one deliberate compositional choice instead of the
   centred default, but each part of that choice now names the field that
   controls it rather than being written as prose into `camera`.
3. A staging `action` must name the frozen instant -- which foot carries
   the weight, how far the torso is twisted, where the hair has already
   swung to -- rather than the movement through it.

The occlusion instruction was **moved, not added**: the threat rule that
previously asked for "what specifically occludes it" inside
`frame_position` now points at `occlusion`, and a test asserts the old
wording is gone from the prompt. Leaving both would have reproduced the
defect this ADR describes.

## Consequences

`occlusion` parses as optional and defaults to empty, the same allowance
`staging` itself carries from 0049, so a plan captured before this field
still loads. If a planner turns out to omit it, that is a reason to make
it required rather than to write a firmer rule about it.

This does **not** address the owner's longest-standing complaint, that the
non-focal character is "just standing there... a permanent issue since
extra characters were added". That has a separate, known, unfixed cause:
the image prompt's `ACTION:` line restates `beat.action`, which is the
focal character's physicality again, so a two-character prompt describes
the protagonist twice and the antagonist once before the model reads a
word. That is its own tier problem and belongs in its own ADR.

Also unaddressed: "from behind" was wrong in every shot of beat 1, which
is a direct counterexample to 0044's premise that those three terms are
the granularity models follow. Orientation may need narrowing to the
subset that actually survives; one run is not enough to decide which.

Nothing here has been validated against a real image yet. The evidence is
that structured fields are obeyed and prose inside them is not; whether a
dedicated occlusion field produces a genuinely half-hidden figure is the
next run's question, and the judgement dataset
([0053](./0053-human-judgements-are-recorded-as-data.md)) will hold the
answer in a form that can be compared against this run's 16 rejections.
