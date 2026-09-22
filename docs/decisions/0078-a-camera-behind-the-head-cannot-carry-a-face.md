# 78. A camera behind the head cannot carry a face

Date: 2026-09-22

Status: Accepted

Nothing superseded. Repairs a gap in
[0075](./0075-a-perception-moment-is-two-beats.md), which introduced the
shot this fails in, and applies
[0071](./0071-beats-describe-one-camera-view.md)'s principle -- do not
stage what the camera cannot see -- one level down, to a feature of a
character rather than a whole character.

## Context

0075 told the planner to build a noticing moment out of two beats: the
look, then the reverse from behind her. The first run to use it produced
the construction correctly and a bad image, and the owner's complaint
was precise: she never really looks at the entity, and when she does she
looks "calm and casual".

The plan was not at fault in the way that complaint suggests. Beat 2's
`staging` entry for her read "her eyes driven up and forward onto the
figure's face", "the corner of her open mouth visible past her own
shoulder", "head tipped back", and the beat's own `action` named "shock
pulling her mouth open". Every one of those is a fact about a face the
camera is standing behind. None of them can appear in the picture.

What the camera *could* see of the plan was one clause: "one hand still
holding the keys against her hip". The model rendered exactly that --
she stands hand-on-hip, arm loose, while the figure leans over the
bleachers above her. Hand-on-hip is a resting posture, so the only
visible body fact in the beat was one that reads as calm, and it set the
mood for the whole frame.

Two rules already in the prompt drove toward this. The facial-expression
rule requires EVERY beat's `action` to name an expression, which in a
from-behind beat demands something unrenderable. 0075 then requires the
reverse angle without saying what that camera forbids. A planner obeying
both writes precisely the beat that failed.

The retry loop then made it worse, which is the same pattern recorded as
open task 4. Told "she's not looking at the monster", the model's only
remaining lever inside a from-behind camera was to rotate her head
further away -- deleting the last sliver of face, leaving both arms
hanging straight down. Feedback aimed at a face the shot cannot show can
only move the body further from the camera's reach.

## Decision

When a beat's `camera` orientation is "from behind", the reaction is
carried by a **held silhouette** in that character's `staging` action --
shoulders hunched or wrenched square, head pulled back or dropped,
weight back on one heel, hands open and tense away from the sides -- and
the beat's emotional payload must not be placed in eyes, mouth or brow.
This is stated as the one explicit exception to the facial-expression
rule.

Two specifics are part of the decision, because both are what actually
failed:

- **A transition is not a shape.** "Her shoulders have snapped square"
  names a movement; a still frame can only show the position it ended
  in. The prompt now says to write the end position.
- **A relaxed incidental sets the mood by itself.** In a shot where the
  face is absent, whatever prop-holding or resting detail is mentioned
  becomes the only readable body fact. Naming one in a beat about dread
  is not a small inaccuracy, it is the frame's entire emotional content.

This is not tagged `MODEL-BAN(...)`. Those mark rules that forbid
something because one image model rendered it badly and which must be
re-verified when the pin moves (0073). A camera behind a head does not
see the face on any renderer, or on a physical camera, so there is
nothing here that a better model would retire.

## Consequences

The shot 0075 introduced now has a stated vocabulary, which it did not
before: the planner was told to use the reverse angle and left to guess
what could be expressed in it.

Film has always known this -- an actor plays a shot from behind with
their shoulders and their weight, and a director who wanted the face
would have cut to it. The pair 0075 already mandates *is* that cut: the
face belongs in beat A, and the prompt now says so in both directions
rather than only one.

This does not fix the beat the run gave up on, and it is one instance,
not a measurement. What makes it worth shipping on one instance is that
the failure is geometric rather than statistical: the claim is not "this
model renders faces from behind badly", it is that there is no face in
the frame to render. The evidence that it helps will be the next run's
reverse beats, which is the only evidence a rule that *asks* for
something ever produces (0073).

Untouched: the same run's beat 2 asked for a close-up with "her head and
near shoulder fill the left half of the image" and rendered a full-body
wide. That is camera obedience, measured separately by
`evals/camera_obedience.py`, and nothing here addresses it.
