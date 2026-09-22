# 75. A character noticing the threat is two beats, not one

Date: 2026-09-21

Status: Accepted

Extends the eyes-direction half of
[0062](./0062-eyes-point-somewhere-and-concealment-changes.md). Narrows
nothing; [0060](./0060-threat-is-hidden-not-distant.md)'s ban on distance
is the constraint this works around rather than one it revisits.

## Context

A four-beat horror run was reviewed beat by beat by the project owner and
came back largely working -- two beats retried, one corrected by feedback
and improved. The single remaining complaint was beat 3, the moment the
protagonist spots the entity: the image does not show her *seeing* it.
Their own reading of the cause, offered with both halves stated: either
the scene has too few beats to give the moment room, or it is the known
difficulty of rendering one character far from another.

Both are right, and they are the same problem seen from two sides.

"She notices it, and does not yet know what she is looking at" cannot be
one image. It needs her face readable and the thing she has not
identified in the same frame, and the only composition that does that is
a foreground face with a distant figure behind -- the exact shot 0060
measured as unrenderable, 1 success in 22 images. A planner obeying 0060
therefore has no way to write the beat at all. It is not a rule that is
losing; it is a shot the schema can describe and the model cannot draw.

Film does not draw it either. Perception is built from a pair -- the look,
then the reverse of what was looked at -- and the viewer assembles it
across the cut. Neither half needs distance. The look is a one-character
beat, which this model renders well. The reverse is an over-the-shoulder,
which is the occlusion shot 0060 found *does* work, with the protagonist's
own head and shoulder as the occluder.

Nothing in the planning prompt names that construction. 0060's own lesson
is that the planner writes what the menu offers, and the menu offered
nothing here, so the planner compressed a two-shot moment into one
unrenderable frame -- which is what the owner saw.

## Decision

The eyes-direction rule gains the pair. A beat where a character first
notices the threat is two consecutive beats:

- **The look.** The threat is not in `staging` at all. Her eyes are aimed
  off-frame at something the `location` contains, her face already
  reacting. The ambiguity the owner wanted comes from the viewer not
  having seen the thing either, not from rendering something indistinct --
  which this model will not do on request.
- **The reverse.** `camera` orientation "from behind", her head and near
  shoulder filling the foreground at a large `size_in_frame`, and the
  threat close and partly occluded beyond them. Her body is the occluder,
  so this is 0060's working shot rather than a new one.

It is written as an extension of the existing bullet rather than a new
one. [0058](./0058-delete-rules-by-judgement-not-ablation.md) is the
reason: this prompt reached 34 bullets by adding one per failure, and a
35th restating a 12th is how that happened.

The rule also states its own cost -- a noticing moment spends two of the
scene's beats -- because the budget is the real constraint and a planner
that does not know the price will not plan for it.

## Consequences

At four beats a scene, one noticing moment is half the run. That is a
genuine trade and the ADR does not hide it: scenes will have fewer story
moves, or runs will need more beats. Making the planner choose knowingly
is the improvement; the previous behaviour was to spend one beat on a
shot that could not be rendered, which bought nothing.

This is a **cross-beat sequencing** rule, and it is the first one. Every
existing tier holds a single beat -- fields describe one, validators check
one, genre routing selects rules for all of them -- so there was no
structural home for it and it stays prose. If more sequencing rules
arrive, that absence is the thing to fix, not the bullet count.

Unmeasured, like every other rule in this prompt. See
[the judge calibration note](../playbook/judge-calibration-scope.md) for
what would have to exist before a claim like this one could be tested
rather than argued.
