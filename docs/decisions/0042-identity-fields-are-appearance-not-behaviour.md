# 42. A character's identity fields describe appearance, never behaviour

Date: 2026-09-16

Status: Accepted

Amended by [0048](./0048-heuristic-gates-warn-rather-than-fail.md), which demotes
the check this ADR introduced.

## Context

[0041](./0041-beats-name-every-character-present.md) made it possible for a planned antagonist to appear in a beat at all. The first run after it worked: a stalking figure showed up in every frame. It also stood in exactly the same posture in every frame -- arms hanging straight down, head tilted, motionless -- which the project owner described as "almost t-posing out there".

That was the plan working as written. Scene planning had given the figure this:

```
distinguishing_detail: Stands perfectly still with both arms straight at its
                       sides and its head tilted slightly to one shoulder.
```

`distinguishing_detail` is emitted verbatim into **every** beat's image prompt, and it is also baked into the character's reference image, which every beat is then conditioned on. So the pose was bolted down twice over, in all four beats, and no beat's own `action` text could move it.

The field is meant for a persistent physical marker -- a scar, a piercing, glasses. A pose written there is not a description; it is an instruction the character can never escape.

This is the same *shape* as [0029](./0029-on-rejection-edit-and-retry.md)'s motivating case, where "purple hair" ended up in `face_build` and every beat inherited it. The lesson did not generalise at the time: it was treated as a retry-loop problem, and the underlying issue -- identity fields are repeated everywhere, so anything in them is permanent -- was never enforced.

## Decision

1. **`check_identity_fields_describe_appearance`** rejects a plan whose `face_build`, `hair` or `distinguishing_detail` describes a pose or behaviour, with a message naming the field and explaining why it cannot go there.
2. **A planning rule** states the same thing positively: those fields are what a character permanently looks like, physical markers only, and anything about posture, movement or habitual behaviour belongs in a beat's `action` where it can change shot to shot.

Detection is a small evidence-based pattern set plus a check for a sentence-initial verb, and the verb check is anchored to the start of the field deliberately so garment terms like "a standing collar" do not trip it. The list is expected to be incomplete, in the same spirit as every other pattern list in this project -- each entry comes from a real plan rather than a guess.

## Consequences

**A plan that puts a pose in an identity field now fails to parse**, rather than silently producing a character frozen in one posture for a whole scene. That is the right trade: the failure is loud and fixable at review time, where a silent one costs a full set of paid images.

**The pattern list will miss cases.** It catches what has actually been observed. A pose phrased differently will get through until it is seen and added, and the reference image will still bake in whatever pose the sheet renders -- this decision constrains the text, not the image.

**Unresolved, and visible in the same run**: a beat can say *who* is present but not what each of them is *doing*. The second character's behaviour is describable only inside the focal character's `action` prose. That worked well enough for position ("a figure stands motionless at the far end of the aisle"), but there is no structured slot for a non-focal character's action, and adding one is a larger change than this.

**Also unresolved**: images still over-favour the subject facing camera even with [0040](./0040-character-reference-is-an-in-world-frame.md)'s in-world reference in place. The reviewer flagged it directly on one attempt -- "Mara is shown facing the camera rather than in rear-quarter profile walking away as specified". 0040 improved this measurably; it did not solve it.
