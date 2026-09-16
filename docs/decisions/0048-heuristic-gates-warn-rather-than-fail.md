# 48. A heuristic gate warns; only a decidable one may fail a run

Date: 2026-09-16

## Status

Accepted. Amends [0042](0042-identity-fields-are-appearance-not-behaviour.md),
which introduced the check this ADR demotes.

## Context

ADR 0042 added `check_identity_fields_describe_appearance`, a keyword
check that raised `ScenePlanningError` when a character's `face_build`,
`hair` or `distinguishing_detail` looked like a pose rather than
persistent appearance. The reasoning was sound: those fields are emitted
verbatim into every beat's prompt, so a pose written there is one the
character can never escape.

The first time it fired on a real run, it was wrong. It rejected:

> stands a full head taller than an ordinary adult, with wrists so thin
> the glove leather hangs loose and bunched at the cuff

That is a description of **height**, not posture. The check keyed on the
sentence-initial verb "stands" and could not tell the two apart --
because in English they genuinely are the same word.

Two things made this worse than an ordinary false positive:

1. **It failed at parse time, not review time.** ADR 0042 argued the
   failure was "loud and fixable at review time." It isn't: the exception
   is raised inside `_parse_scene_plan`, so the run dies *before* the
   human is shown anything. A paid planning call is spent and discarded,
   and the field the human would have fixed in five seconds is never
   displayed.
2. **The predicate is not decidable.** "Is this a pose?" is a judgement
   call, not a property of the string. `head tilted` is in the pattern
   list and is a perfectly legitimate *permanent* trait for exactly the
   uncanny figures this project generates. The check was guaranteed to
   keep rejecting good plans.

## Decision

The check warns instead of raising. `identity_field_pose_warnings()`
returns a list of strings; `_review_scene_plan` prints them immediately
before the human reviews the characters, and re-runs them afterwards to
note any that survived the edit pass. `_parse_scene_plan` no longer calls
it at all.

The heuristic itself is unchanged, and stays deliberately over-eager. Its
error rate was only a problem because of where it sat: as a warning, a
false positive costs one printed line, so there is no reason to trade
recall away for precision.

The general rule, which is the part worth carrying to the next gate:

> A validator may fail a run only if its predicate is decidable from the
> artifact. If the predicate is a judgement call, it warns, and it warns
> in front of the human who is already reviewing that field.

`check_unique_ids` and `check_beat_character_references` stay hard
failures -- "two characters share an id" and "this beat names a character
that does not exist" are decidable, and a wrong answer there breaks
prompt assembly outright. "This reads like a pose" is not in that
category and never was.

## Consequences

A genuine pose can now reach the beat prompts if the human accepts the
character without reading the warning. That is the accepted cost, and it
is recoverable: it shows up as a repeated posture across beats, which is
visible in the images and fixable on the next run. An unrecoverable
false failure that burns a planning call is worse than a recoverable
false pass.

Tier-wise (see the five-tier fix framework in the playbook), this moves
the control from a schema constraint back to an instruction plus human
review. The tier-1 instruction added by 0042 -- the planning prompt
telling the planner these fields are appearance-only -- remains in place
and is still tested; it is now the primary control rather than the
backstop.
