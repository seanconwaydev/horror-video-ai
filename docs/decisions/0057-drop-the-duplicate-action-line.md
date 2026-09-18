# 57. Drop the duplicate ACTION line; corrections get their own field

Date: 2026-09-18

Status: Accepted

Completes the move [0049](./0049-per-character-staging-in-beats.md)
started and [0054](./0054-one-fact-per-field.md) generalised. Neither is
superseded; this applies their rule to a line both left in place.

## Context

The project owner's longest-standing complaint about generated images is
that a beat's non-focal character is "just standing there... a permanent
issue since extra characters were added."

0049 moved each character's physicality into their own `Staging` entry,
so `_build_beat_prompt` emits a labelled block per character with a
`DOING:` line bound to that person. It did not remove the beat-level
`ACTION: {beat.action}` line that the per-character blocks replaced.
`beat.action` describes the focal character, so a two-character prompt
reached the image model like this:

```
CHARACTER influencer: ...
  DOING: checks her phone            <- focal
CHARACTER figure: ...
  DOING: stands between the pillars
ALL OF THESE CHARACTERS ARE IN THIS SHOT: ...
SUBJECT: The influencer              <- focal, again
ACTION: checks her phone             <- focal, a third time
```

Three mentions to one before a word of the image is decided. That is the
same failure 0054 names -- a field making a claim that belongs to another
field -- except here the duplicate is not prose inside a field, it is a
whole line the schema change was supposed to retire.

One thing made this more than a deletion. `beat.action` was also the
carrier for human `(f)eedback`: the CLI appended the typed note to it
(`dataclasses.replace(beat, action=f"{beat.action} {note}")`), and the
`ACTION:` line was the *only* route by which that note reached the image
model. [0055](./0055-delete-the-automated-previz-reviewer.md) deleted the
machine's corrections and deliberately kept the human's, calling the
review prompt "the actual work". Removing the line without noticing this
would have silently deleted the highest-value text in the loop, and
every test would still have passed.

## Decision

Remove `ACTION: {beat.action}` from the beat prompt, and give human
corrections their own field and their own prompt line.

- The line survives only as a fallback, emitted when no character block
  produced a `DOING:` line at all -- a plan captured before 0049, or one
  whose staging names nobody in `characters`, would otherwise reach the
  model with no verb anywhere.
- `run_beat_image_stage` takes `corrections: Sequence[str]`, and
  `_build_beat_prompt` emits one `CORRECTION -- fix this, keep everything
  else: <note>` line per entry, after `STYLE`, because a correction
  modifies everything stated above it. Phrased plainly and not as an
  "overriding requirement (takes priority over anything above)" --
  [0039](./0039-committed-style-presets-and-single-style-slot.md) measured that construction losing
  a blind A/B 5-0.
- The CLI accumulates corrections in a list that spans attempt cycles,
  the same way `all_attempts` does, and stops rewriting `beat.action`. A
  planned action and a correction to a render are different facts;
  `run_log.json` now records the beat as it was actually written.

`SUBJECT: {beat.subject}` stays. It names the focal character once, which
is what a subject line is for.

## Consequences

The prompt no longer weights the protagonist 3:1 over everyone else. What
it still does not have is any **relational** statement: both characters
get an absolute `frame_position` and nothing anywhere says who is behind
whom, how far apart they are, or where each is looking. The owner's
complaint has two causes and this ADR addresses one; the other is a
schema gap and needs its own decision.

Nothing here has been validated against a real image yet -- the same
caveat 0054 carries. The next horror run tests both at once.

A behaviour change worth knowing about when reading old runs: a beat's
recorded `action` in runs before this ADR may have feedback text appended
to it, and in runs after it never does. The feedback is in the attempt
record's `human.feedback` either way, which is where 0053 puts it.
