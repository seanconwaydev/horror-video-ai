# 45. The `cinematography` field is deleted

Date: 2026-09-16

Status: Accepted

Completes what [0039](./0039-committed-style-presets-and-single-style-slot.md) started and [0044](./0044-camera-specified-at-a-granularity-models-follow.md) made visible.

## Context

A beat carried a `cinematography` field for per-shot lens and grade notes. In a real run it produced things like:

```
18mm, deep focus, fine 35mm grain, cold desaturated grade with a sickly
green-cyan fluorescent cast, blacks crushed
```

and was appended to the `CAMERA` line, giving prompts like:

```
CAMERA: extreme wide / high above / from behind. 18mm, deep focus, fine 35mm
        grain, cold desaturated grade with a sickly green-cyan fluorescent cast...
STYLE:  Stylized horror comic panel -- heavy inked black shadows, bold confident
        linework, flat colour fills. Explicitly NOT photorealistic.
```

Two problems, both measurable rather than aesthetic.

**It drowned the camera instruction.** Across that run's four beats, `cinematography` was **68%, 75%, 77% and 77%** of the CAMERA line. 0044 had just reduced camera to a short, model-actionable phrase precisely because the long version was being ignored; this field immediately buried the short version under three times its own length in something else.

**It was a second style source contradicting the first.** "35mm grain", "harsh specular highlights", "cold grade" are photographic rendering instructions, sitting directly above a STYLE line reading "flat colour fills... explicitly NOT photorealistic." That is exactly the competing-style-claims failure 0039 was written to eliminate. 0039 moved the field out of the `STYLE:` slot and kept it, so the conflict survived in a new location rather than being resolved.

The project owner raised it independently, from the output rather than the code: "is this cinematography field doing anything useful, or maybe even hurting?... it all seems like info that isn't particularly being respected."

Worth recording one thing they got slightly wrong, because the correction matters: 28mm and 35mm are not contradictory -- one is a lens focal length, the other a film gauge, and shooting a 28mm lens on 35mm film is ordinary. The field's problem is not internal contradiction, it is that photographic vocabulary is being applied to an explicitly non-photographic render, and at a length that swamps the instruction beside it.

## Decision

The field is removed: from `Beat`, from the planning prompt's JSON shape and required fields, from its own planning rule, and from the assembled image prompt.

`check_cinematography_is_not_a_style_claim` goes with it. That validator existed solely to stop this field making art-style claims -- with the field gone, the class of error it guarded against cannot occur, so keeping the guard would be dead weight that a future reader has to understand before they can delete it.

## Consequences

**Per-shot lens and grade control is gone.** A human cinematographer would want it, and it is a real expressive loss on paper. It was not being honoured -- the same run that produced those fields also produced images the reviewer repeatedly flagged for wrong camera and wrong lighting -- so what is actually lost is the appearance of control rather than control.

**The beat prompt is now one instruction per line**: SUBJECT, ACTION, SETTING, CAMERA, LIGHTING, STYLE. Every field has exactly one job, and no two fields describe the same thing.

**This is the third field-level fix of the same shape**, and the pattern is worth naming: 0039 found two competing style claims, 0044 found camera specified in a vocabulary the model does not act on, and this found a field that was both. In each case the field was added for a real reason, and in each case the reason was a different project -- one that cared about photographic fidelity.

Which suggests the follow-up the project owner proposed, recorded here so it is not lost: **audit every field in the scene, character and location descriptors the same way.** Now that the genre is fixed as stylized horror, and neither historical accuracy nor photographic realism is a goal, each field should have to justify that it changes the output in a direction anyone wants. `wardrobe_flexible` is one known candidate -- 0040 already stopped sending it to the character sheet because it produced two-figure turnarounds, but it is still carried on `Character` and still reaches the beat prompt. `audio` and `duration_seconds` reach no image call at all and exist for a video stage that consumes them differently. None of that is decided here.
