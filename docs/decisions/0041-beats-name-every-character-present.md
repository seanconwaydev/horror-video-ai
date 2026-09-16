# 41. A beat names every character present, not just one

Date: 2026-09-16

Status: Accepted

Its `character_ids` field superseded by
[0049](./0049-per-character-staging-in-beats.md).

Supersedes the single-character simplification carried since [0023](./0023-scene-planning-stage.md)/[0024](./0024-previz-image-conditioning.md).

## Context

A real horror run asked for "a woman walking to her car notices someone standing between the concrete pillars, and they are closer every time she looks". Scene planning did the right thing: it defined two Characters, the woman and a stalking figure, and both got reference images generated and paid for.

The figure then appeared in **zero of four beats**. It surfaced exactly once, inside beat 4's `lighting` field, as "the figure" -- a phrase with no antecedent, because the only character description sent to the image model was the woman's. The climactic beat, whose lighting specified "one hard-edged shadow of the figure across the concrete floor", rendered with no figure and no figure-shadow.

This was not a prompting failure. It was structural, and three facts make that plain:

- `Beat` carried a single `subject` string. There was no way to say a second character was in the shot.
- `cli.py` read `scene_plan.characters[0]` and nothing else, with a comment calling it a documented v1 simplification.
- So the second character's reference image was generated, paid for, and discarded unused.

The threat-presence rule added to scene planning asks for exactly this -- a threat visible across a majority of beats -- and the data model could not express it. A prose rule instructing a model to do something the schema forbids is the weakest possible arrangement, and this is the clearest instance of it the project has produced.

It also explains a result that had looked like a genre-generalisation problem. Earlier domestic-haunting scenes carried their threat well because that threat was a **shadow**, which is expressible in the `lighting` field. This scene's threat was a **person**, which needed a character slot that did not exist. The rules were not failing to generalise across horror sub-types; embodied threats simply had no representation.

## Decision

1. **`Beat` gains `character_ids`** -- every character visible in the shot, by id, including partially visible ones. `subject` still names which one the shot is *about*.
2. **`check_beat_character_references`** rejects a beat naming an id no Character defines, and is re-run after human edits for the reason in [0028](./0028-scene-plan-revalidated-after-edits.md).
3. **`_build_beat_prompt` emits one labelled block per present character**, plus an explicit line naming all of them as in-frame. A single-character beat is unchanged.
4. **`run_beat_image_stage` takes a sequence of character references**, all of which are passed as conditioning images alongside the location reference.
5. **`run_previz_review_stage` is told about every present character**, not just the first. Without this it would flag the second as unplanned -- the same failure fixed for a beat's lighting text earlier the same day.
6. **Two planning rules**: a general one requiring every beat to list everyone visible, and a horror-specific one requiring an embodied threat to be defined as a Character and listed on every beat where any part of it shows.

## Consequences

**A missing `character_ids` falls back to the first character, not to an error.** A planning model that ignores the new field still produces a usable single-character beat, which is exactly what every beat was before this decision. The fallback is deliberately *not* `subject`: that field has held both a bare id ("w1") and a description ("The influencer") in real plans, so it is not reliably an id.

**Beats with two characters now condition on three reference images** -- two characters plus a location. How the image model behaves with that many is untested. It may dilute conditioning, and it may cost more. This is a known unknown being accepted to unblock a scene shape the pipeline could not previously produce at all, and it should be watched on the first real multi-character run.

**Identity drift now has more surface.** [0040](./0040-character-reference-is-an-in-world-frame.md) already accepted drift on a single character; two characters in one frame gives the model more opportunity to blend or swap them. Untested, and worth a deliberate look rather than an assumption.

Deliberately unresolved: a beat's `SUBJECT` line still carries a bare id, so the most prominent line in the prompt conveys nothing about who the character is. That is tracked as its own hypothesis (see 0040's consequences) and is not fixed here.
