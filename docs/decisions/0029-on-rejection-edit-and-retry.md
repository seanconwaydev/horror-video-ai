# 29. A human can intervene on a rejection, not just after all attempts fail

Date: 2026-09-02

Status: Accepted

## Context

ADR 0009's automatic reject-and-regenerate loop (`_generate_image_with_review`,
capped at `_MAX_PREVIZ_ATTEMPTS`) assumes a rejection is "unlucky roll" noise
-- worth a blind retry, since the next roll of the dice might pass. That
assumption held up until a real run (Pompeii influencer scene) hit a
rejection that wasn't noise: a Character's `face_build` field had been
edited during scene-plan review to include "purple hair," an anachronistic
detail for 79 AD. `_build_beat_prompt` includes `character.face_build`/
`character.hair` as literal text in *every* beat's prompt, so the same
text was resubmitted unchanged on every attempt -- the rejection was
guaranteed to recur identically, 3 attempts for 3 dollars spent, every
single time, with zero chance of ever passing.

The existing UI only offers a choice *after* an attempt is accepted
(`(a)ccept`/`(r)eroll`/`(e)dit`) or after every attempt is exhausted (a
silent give-up, no choice at all). Nothing lets a human break out early
once it's clear a rejection is going to recur, short of killing the whole
run.

## Decision

`_generate_image_with_review` gains an optional `on_rejected(concern,
attempt) -> str` hook, called after *every* rejection (including the
final automatic attempt, not just the ones before it) -- returning
`"stop"` ends the retry loop immediately, same outcome as exhausting every
attempt; anything else keeps regenerating blind. This is the same
mechanism whether the human wants to interrupt attempt 1 or attempt 3, so
"stop wasting money on a doomed retry" and "let me intervene instead of
silently giving up" collapse into one code path instead of two.

`_generate_beats_with_choices` supplies the hook for the beat-generation
flow: blank/Enter keeps today's blind-retry behavior unchanged (default,
no behavior change for the common "genuine bad luck" case), `(e)dit`
opens the beat's fields via the existing 0023 per-item edit mechanism and
restarts a fresh attempt cycle, `(g)ive up` stops immediately without
editing. The single-scene flow (`_generate_previz_with_review`) does not
get this hook -- there's no beat-level text to edit there, and its retry
loop is unchanged.

Under `--yes` there's no human to ask, and `--yes` is how this pipeline
actually gets run for iteration/testing most of the time -- so a fix that
only engaged the interactive human wouldn't have helped the case that
motivated it. The hook applies a cheap, code-only heuristic instead: an
identical rejection `concern` string on two consecutive attempts gives up
immediately rather than spending the remaining attempt(s) on a near-
certain repeat. This is a naive proxy, not real judgment -- it only
catches a near-verbatim repeat, and a differently-worded critique of the
same underlying cause slips past it entirely. Genuinely deciding whether
a given rejection is structural (worth stopping/editing) or random (worth
another blind roll) needs semantic understanding a string comparison
can't provide.

That's explicitly future work: this project will eventually need a
"smart" middle mode for these per-stage accept/edit/reject decisions --
something between full interactive human review and blind `--yes` --
where a model makes the same kind of call a human currently does at each
review gate. Nothing here builds that; the auto_yes heuristic is a stopgap
that catches the exact-repeat case cheaply, without a model call, while
that fuller design is worked out.

Scope explicitly excludes editing the Character or Location themselves
mid-run (which would have been the more direct fix for the motivating
purple-hair case) -- a real, separate design question about what happens
to beats already accepted against the old reference, deferred rather than
bundled in here. The user's own judgment on this: some visual
inconsistency between beats -- in service of camera/pose/lighting variety
or even a follow-on edit -- is an acceptable, expected tradeoff, not a bug
to eliminate at all costs.

## Consequences

`cli.py`'s `_generate_image_with_review` and `_generate_beats_with_choices`
changed; no new dataclass fields, no config change. The give-up message
now reports the actual number of attempts made (`len(attempts)`) rather
than always claiming `_MAX_PREVIZ_ATTEMPTS`, since a human-initiated early
stop can end the loop before every automatic attempt runs.
