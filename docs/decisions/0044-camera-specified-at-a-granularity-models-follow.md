# 44. Camera is specified in terms an image model acts on, not world coordinates

Date: 2026-09-16

Status: Accepted

Refines the coverage and 180-degree rules added to `scene_planning.py` after [0023](./0023-scene-planning-stage.md).

## Context

A real run produced beats specifying camera like this:

```
camera: high wide shot from a ceiling corner at the west end of the aisle,
        looking down its full length so Wren reads small at the left of frame;
        camera stays on her left-hand side of the aisle
camera: side-on low angle from her left, camera beside the boot of the
        neighbouring parked car in bay 15
```

The image model produced an eye-level shot every time, across three attempts on one beat and two on another, and `previz_review` correctly reported the miss each time. The project owner's summary: "the concerns related to camera are certainly basically never addressed."

The instruction was not malformed. It was positive, it was in the `CAMERA` field, and it was in the prompt from the first attempt. It simply was not acted on.

Two of this project's own rules were driving that phrasing. The coverage rule demanded "shots from genuinely different camera *positions* in that space -- move the camera to a different part of the room or street". The 180-degree rule demanded the camera stay on one side of the line of action. Both were added to fix real, observed problems -- repetitive same-location beats, and broken spatial continuity -- and both ask the planner to reason in world coordinates.

An image model does not place a virtual camera in a floor plan. And per [0040](./0040-character-reference-is-an-in-world-frame.md), a beat's composition comes largely from its reference image regardless. So the planner was writing checks the generator could not cash, which then guaranteed a rejection on every beat and burned the retry budget on something no retry could fix.

## Decision

The `camera` field is written in three terms and nothing else:

- **Shot size** -- extreme wide / wide / medium / close-up / extreme close-up
- **Camera height** -- high above / eye level / low / ground level
- **Subject orientation** -- facing camera / three-quarter / profile / from behind

Specifying where the camera stands in the world is explicitly forbidden, with the reason stated in the rule so it does not get "helpfully" reinstated later.

**Coverage keeps its intent and changes its vocabulary.** No two consecutive beats sharing a location should repeat the same combination of those three terms. That preserves what the rule was for -- beats at one location not reading as the same image -- while asking for something the model can act on.

**The 180-degree rule is reduced to its enforceable half.** Screen direction -- which way the subject faces within the frame -- is something an image model can honour. Which side of an imaginary line the camera occupies is not. The rule now states the former and forbids the latter.

## Consequences

**This does not, on its own, make camera direction work** -- but an earlier draft of this ADR went further and suggested camera might not be promptable at all. That was wrong, and the project owner caught it.

This project's own style A/B (`evals/results/20260915-225950`) produced images that obeyed their camera specs plainly: "high angle looking down at her on the floor" produced exactly that. Two things differed from the pipeline. Those prompts were ~80 words with a 9-word camera line, against the pipeline's ~450 with 30+ words of world geometry. And crucially they called `image_generation` with **no reference images at all**, where the pipeline calls `image_edit` conditioned on two or three.

So the live hypothesis is not "models ignore camera". It is that **reference-image conditioning overrides camera direction**, with prompt bloat as a likely second factor. The anchor experiment already pointed here and it was not connected at the time: its no-reference arm won camera picks while the shipped reference arm won none.

`evals/camera_obedience.py` therefore tests the conditioning, not just the model -- the same unmistakable camera specs, generated with and without references, so the decisive variable is isolated. If references are the cause, the options are conditioning that encodes geometry directly (depth or pose control, already researched in `failure-taxonomy.md`), weakening or dropping reference conditioning for composition while keeping it for identity, or accepting that the reference chooses the shot.

**Some genuine expressive range is given up.** "Camera beside the boot of the neighbouring car" describes a real shot a human cinematographer could execute. The pipeline cannot execute it, so writing it down only produced a failed comparison -- but the vocabulary is now genuinely coarser than a storyboard would normally be, and that is a real cost, not a free win.
