# 66. Delete `--max-references`

Date: 2026-09-19

Status: Accepted

No ADR to supersede: `--max-references` arrived as a plain commit
(d0e95dd) and was never recorded as a decision, which is part of why the
premise underneath it could lapse unnoticed. `--max-beats`, the flag it
was modelled on, is unaffected.

## Context

`--max-references` capped characters + locations combined. Its stated
justification was cost: "these, not beats, set a run's real minimum image
cost (one reference image each, before a single beat generates)."

That premise is gone. [0050](./0050-no-reference-images-by-default.md)
turned reference images off by default; they now require `--references`.
So for an ordinary run the flag capped the count of something that is
never generated, and the cost it was controlling is zero.

What it did still do was corrupt plans. `_truncate_references_safely`
dropped every character past `characters[0]` unconditionally, justified in
its own docstring by the pre-[0049](./0049-per-character-staging-in-beats.md)
premise that a beat could only ever condition on the first character. 0049
gave `staging` a `character_id`, which made that false, and the function
popped from the end -- so in a horror plan the character it deleted first
was the threat.

The result failed `check_beat_character_references`, the validator in the
same module, which runs at parse time and not again after truncation. It
reached previz as something worse than an error: previz builds its prompt
by iterating `characters`, so the dropped character vanished from the
prompt entirely, while `len(beat.staging) > 1` still appended "These
characters are in the same moment and must react to each other." A prompt
describing one figure and insisting there were two.

That bug was fixed first, by making the character half usage-aware like
the location half always was. Deleting the flag afterwards is a separate
decision, and the sequence was deliberate: fixing it established what the
flag would have to keep doing correctly, which is what made it clear how
little it was doing.

## Decision

`--max-references`, the `max_references` parameter on
`run_scene_planning_stage`, its prompt block, and
`_truncate_references_safely` are deleted. Four tests go with them.

`--max-beats` stays. Its enforcement is a plain list truncation with no
cross-references to break, and beats remain the thing that actually costs
money per run.

## Consequences

A run's cast size is now the planning model's judgement plus the prompt's
own "prefer one character and one location unless the scene genuinely
needs more" instinct, with no hard cap. Nothing enforces a ceiling, and
nothing silently rewrites a plan after it has been validated.

The bug class goes with the feature. There is no longer any path that
mutates a `ScenePlan` after `_parse_scene_plan` has validated it, which
is the property that made this failure possible and invisible -- the
validator ran, passed, and then the plan changed underneath it.

Cost control for references, if it is ever wanted again, belongs with
`--references` itself, where the images are actually generated, rather
than in the planning stage guessing ahead of them.
