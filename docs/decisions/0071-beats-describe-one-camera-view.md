# 71. A beat describes what one camera can see

Date: 2026-09-21

Status: Accepted

## Context

A four-beat horror run on 2026-09-21 (a fire lookout tower, a figure with
a lantern) produced beats that read well as prose and could not be
rendered as images. Four distinct failures, reported by the owner while
reviewing the run:

1. **Beat 2's geometry was impossible.** Its `camera` was "medium, low,
   from behind" — inside the glass cab, behind the protagonist. The
   threat's `blocking` put it "on the tower's stair landing one flight
   below the catwalk" and its `occlusion` said "the tower's diagonal steel
   leg and the floor grating of the catwalk above cover everything but the
   lantern" — outside, below, behind a metal floor. It was nonetheless
   given `size_in_frame: roughly a sixth of the image height`. A thing
   cannot be both invisible and a stated fraction of the picture. The
   image model settled the contradiction by putting the figure wherever it
   liked, and the owner's correction ("he is too large and too close")
   moved it somewhere else arbitrary — tiny, beside her — because no
   correction can name a position the plan never gave.

2. **Physical contact never rendered.** Beat 4's `action` read "its bare
   hand is clamped around Rook's right wrist". In `staging` that existed
   as two separate sentences in two separate entries — "keeps its bare
   hand clamped on her wrist" for one character, "hauls her right arm back
   toward her sternum" for the other. Nothing anywhere stated the shape
   the two bodies make together, and the image came back as two people
   standing near each other, not touching. The protagonist even held her
   arm up where the hand would have been.

3. **Nothing ever moved.** Every field a beat carries is positional:
   `blocking` (where), `size_in_frame` (how big), `occlusion` (what
   hides). The planner had no vocabulary for force, so the threat stood
   still and held a lantern in every beat of every run. As the owner put
   it, "a lot of horror will just involve the enemy being violent and loud
   and angry and visceral and thrashing about, which is never really
   depicted in these images". A silent motionless watcher is a legitimate
   horror register, but it is the only one this pipeline could express.

4. **Beats exceeded what an image model can hold.** Beat 2 asked one frame
   for a cabin interior, the tower structure below its floor, fog, a
   lantern beam through fogged glass, a breath bloom on the pane, and the
   protagonist's own reflection. Beat 3, which stayed on the catwalk,
   rendered cleanly. Reflections in particular do not work at all: an
   image model renders a reflected person as a second copy of that person
   standing in the frame.

These are one fault in four costumes. A beat is a specification for a
single photograph, and the schema let it describe things no single
photograph contains: two spaces at once, a character outside the frame,
and force that a set of positions cannot express.

## Decision

A beat describes what one camera can see, in one space, at one moment.
Four changes enforce that.

**`Beat.contact`** — the single composed shape two characters make where
they touch, written once from the camera's point of view. Optional; empty
when nobody is touching. It leads the image prompt, ahead of the
per-character blocks, as `PHYSICAL CONTACT`. When present it replaces the
generic "these characters must react to each other" line, which is a
weaker restatement of the same thing.

**Visibility consistency** — `check_staging_visibility` raises
`ScenePlanningError` when a staged character's `occlusion` says the camera
cannot see it at all. A character the camera genuinely cannot see belongs
out of `staging` entirely. Partial occlusion, which is how this project
renders threat presence ([0060](./0060-threat-is-hidden-not-distant.md)),
is untouched: an explicit exception clause ("covers everything but one
shoulder") names what survives and passes. A second, softer heuristic,
`beat_visibility_warnings`, prints — rather than raises — when a character
is hidden behind a floor, ceiling, grating, roof or the ground, which
usually means it is in a different space from the camera, and when any
beat describes a reflection.

**`Beat.intensity`** — how much physical force is in the moment, plus what
a frozen frame shows of it ("violent — the slicker flared out mid-lunge,
the lantern swung wide on its arc, one boot clear of the grating"). It
leads the image prompt as `INTENSITY`. Required of a live model response
like `size_in_frame` is ([0065](./0065-strict-for-a-model-lenient-for-a-file.md));
optional when loading an archived plan. A companion prompt rule requires
intensity to change across the scene and to reach a real peak.

**A complexity budget** — unconditional prompt rules, like the base
composition rule ([0052](./0052-composition-vocabulary-is-unconditional.md)), because
the ceiling belongs to the image model and not to a genre: no more than
about five things per beat that the image must get right; one beat is one
space; no character reflections (reflected *light* is fine and often
good); no minutiae a phone-resolution still cannot carry; one dominant
light source.

`contact` and `intensity` also join `BEAT_QUICK_EDIT_FIELDS` and the
text shown at the candidate-review prompt, because "are they touching" and
"is anything happening" are the fastest checks a human makes against a
rendered image and the two these images fail most often
([0053](./0053-human-judgements-are-recorded-as-data.md)).

## Consequences

The planner can now say things it previously could not, and the two hard
checks refuse plans that contradict themselves rather than spending an
image on them. A live planning response missing `intensity` fails the
parse, costing one planning call — the same trade
[0065](./0065-strict-for-a-model-lenient-for-a-file.md) accepted for `size_in_frame`,
and cheaper than a paid image whose prompt silently lost a line.

Archived plans keep loading: both new fields default to empty, and a
prompt built from a plan that has neither carries neither label. That is
what `--video-gen-from` and the eval harness replay.

The visibility check is textual, not geometric. It catches a plan that
states its own contradiction in the `occlusion` field; it cannot catch one
that places a character somewhere unseeable without saying so. The
warnings exist for that gap, and they are deliberately fallible keyword
matches put in front of a human who is already reviewing every beat, in
the manner of [0048](./0048-heuristic-gates-warn-rather-than-fail.md).

The complexity budget is a prompt rule with no mechanical enforcement, and
the reflection ban is the only part of it with even a warning behind it.
Whether beats actually get simpler is a measurable question the next runs
answer.
