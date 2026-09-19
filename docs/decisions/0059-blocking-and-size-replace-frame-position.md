# 59. `blocking` and `size_in_frame` replace `frame_position`

Date: 2026-09-19

Status: Accepted

Narrows [0049](./0049-per-character-staging-in-beats.md), which introduced
`frame_position`; the rest of that ADR stands. Applies
[0054](./0054-one-fact-per-field.md)'s rule to the field 0054 itself split
`occlusion` out of.

Narrowed by [0065](./0065-strict-for-a-model-lenient-for-a-file.md): the
backward-compatibility fallback this relies on now applies only when reading
a stored plan, never to a live model response.

## Context

The project owner, on why images only came out well by accident: "the
camera, environment and characters all need to be working together, but
it's pretty common here that the character prompt will say 'she notices an
enemy far in the distance behind the pillars' but then the image will
specify 'enemy is on right side of screen'... as long as that's true,
these will never turn out good on purpose, only luck."

The diagnosis that followed was that `frame_position` asks for a
*projection*. Where someone appears in the frame is a function of where
they stand, where the camera is, and the lens -- and the planner authors
the world position in `action` prose, the frame position in
`frame_position`, and a camera that [0044](./0044-camera-specified-at-a-granularity-models-follow.md)
deliberately stripped of any world position. `run_20260918-221017`'s
floating figure is that arithmetic failing in public: "far background,
**upper-left of frame**" under a `wide, low, from behind` camera put a
standing man at ceiling height, and the image model invented a concrete
slab to hide him behind.

The proposed fix was world-space blocking, on the reasoning that it is
what a production's blocking diagram does. **That reasoning was wrong, and
four blind runs said so.** `evals/blocking_space.py` compared the two
architectures over 66 images, scored blind by the owner before the key was
opened, on "is he between the camera and her":

| arm | score |
|---|---|
| world placement, no size | **0/10** |
| `frame_position` -- a frame coordinate plus a size | 5/10 |
| world placement **plus a size** | **14/14** |

World placement on its own is *worse* than what ships today. It never once
produced the right depth ordering. The axis that matters is not frame
space versus world space at all -- it is whether a character's **apparent
size** is stated. In the final head-to-head against the incumbent at six
candidates per cell, world placement plus a size took 6/6 on depth
ordering and 6/6 on "close enough to touch, reacting", against 3/6 and 4/6.

`frame_position` already carried two facts by its own docstring: "where in
frame, and roughly how much of it they occupy". The runs show those two
halves are not equally effective, which is exactly the evidence 0054 acted
on when it split `occlusion` out of this same field.

## Decision

`Staging.frame_position` becomes two fields.

- **`blocking`** -- where this character stands: in the space, relative to
  the camera, and relative to the other characters. "On the same floor
  directly between her and the camera, near enough to touch her." The
  planning rules forbid a frame coordinate here and say why, so it does
  not get reinstated as a helpful clarification later.
- **`size_in_frame`** -- how much of the image they occupy. "Roughly a
  third of the image." Every character gets one, always; this is the field
  that makes depth render.

The beat prompt emits `STANDS:` and `SIZE IN FRAME:` on separate lines,
before `HIDDEN BY:`. That is the wording the winning arm used verbatim.

`camera` is untouched. 0044's three terms stand, and its finding -- that an
image model will not place a virtual camera in a floor plan -- is not in
tension with this: `blocking` positions *characters* relative to the camera,
not the camera relative to the room.

**No gaze field is added**, though one was considered. Gaze scored 6/6 in
both arms of the head-to-head and 12/12 in the run before it, and the owner
read it off posture every time: "he's actually closer to the camera and
thus partially turned away from the camera to look at her." Correct depth
ordering forces the turn, and the turn is what reads as gaze. Adding a
field for something already delivered is what
[0058](./0058-delete-rules-by-judgement-not-ablation.md) argued against.

A plan saved before this ADR still loads: `frame_position` is read into
`blocking`, and `size_in_frame` defaults to empty rather than being guessed
at, since nothing can separate the two facts out of one string after the
fact. `--fixture` and `--video-gen-from` both replay archived runs, so the
alternative is a stored plan that stops loading.

## Consequences

This does not fix the failure that prompted it. **Distance is not
promptable at all** -- across the same four runs, "does the far figure read
as far away" succeeded in 1 image out of 22, in every arm and every
phrasing tried, including an explicit "roughly a twentieth of the image".
The owner: "he's never more than ~10 feet in front of her... a parking
garage could have him 50-100+ feet away easily." A beat whose effect
depends on a figure reading as genuinely distant cannot be delivered by
this model at this prompt length, and has to be rewritten rather than
re-prompted. That is a scene-writing constraint, not a schema one, and no
field added here changes it.

What this does fix is the near field: whether two characters read as
occupying one space in a believable order. That was the owner's "x100
better than before" case and the one image he has called genuinely
acceptable, and it is now specified rather than lucky.

One cost worth naming: `blocking` is strictly harder for a planning model
to write than a frame coordinate. "Left third of frame" needs no model of
the room; "far down the aisle behind the fourth pillar on the left" does.
If plans start coming back with frame coordinates smuggled into `blocking`,
that is the rule losing, and by 0054's own logic the answer is a tier
change rather than a firmer sentence.
