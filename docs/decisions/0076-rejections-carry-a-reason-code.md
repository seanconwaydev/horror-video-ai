# 76. A rejected candidate carries a reason code

Date: 2026-09-21

Status: Accepted

Extends [0053](./0053-human-judgements-are-recorded-as-data.md), which
made each keep-or-reject a labelled row, and
[0074](./0074-judgements-are-committed-and-merged.md), which made the
resulting dataset durable. Neither is narrowed.

## Context

The judgement dataset records which candidate won and which lost. It very
rarely records why. `feedback` is the field that could carry it -- the
owner's own words naming what a render got wrong, and by some distance
the highest-value text the loop produces -- but it is only collected on
the (f)eedback branch, so it is absent from most rows. The other four
choices, (r)etry, (e)dit, (g)ive up and rejecting every candidate, all
discard the reason entirely.

What survives is a binary. A binary is enough to measure a judge's
agreement, which is what [0055](./0055-delete-the-automated-previz-reviewer.md)
did, and not enough to build one: a judge cannot learn a rubric from
labels that never say what the rubric is. The same is true of a human
reading the corpus back. "31 of 62 kept images were rejected by the
reviewer" is a number; it does not say what the owner was seeing.

This matters now rather than later because labels only accumulate
forward. Every run recorded without a reason is a run whose data is
permanently thinner, and the corpus is currently 49 rows.

## Decision

Every non-accept choice collects a one-keystroke reason code from a
closed set (`cli/beats.py`'s `REJECTION_REASONS`): anatomy, staging,
framing, identity, mood, missing, other. It is stored on the attempt and
exported as a `reason_code` column.

Three details are the decision rather than the implementation:

- **Closed, short, and drawn from recorded failures.** Categories
  aggregate only if they repeat, so a free-text category is not a
  category. These come from
  [the failure taxonomy](../playbook/failure-taxonomy.md) rather than
  from a guess at what image models get wrong.
- **"other" is load-bearing.** A forced choice with no escape pushes
  every unclassifiable rejection onto the nearest label, which corrupts
  the labels that are real. A large "other" count is a signal the set
  needs a category, and it can only be read if the escape exists.
- **A reason that was never given is not "other".** The prompt asks a
  bounded number of times and then stops, rather than refusing to move
  on: it is a secondary question about a decision the human has already
  made, and a closed stdin would spin an unbounded loop rather than
  block it. What it records in that case is `unspecified`, which is
  deliberately not a member of the set above -- reading a silence as an
  answer corrupts "other" the same way a forced choice corrupts every
  other label.

- **It sits alongside `feedback`, not instead of it.** The code is the
  category and the text is the detail. Aggregating the first must not
  require reading the second, and the second stays optional because
  demanding prose on every rejection would slow the loop the owner
  actually drives.

The reason is asked **before** the chosen branch acts, because (e)dit and
(f)eedback both block on further input, and it is written to the run log
the moment it is typed.

That last point fixes a real gap this change would otherwise have
inherited. `human_actions` was folded into the attempt records only after
`generate_image_with_retries` returned -- that is, once the beat
finished. Runs here are routinely abandoned partway
([0056](./0056-persist-work-in-flight.md)), so every judgement in
an abandoned beat was already being lost, silently, exactly as the images
were before 0056. `_persist_human_action` now writes on each keystroke,
and `_on_attempt` merges the human's judgement forward instead of
replacing the entry that holds it.

## Consequences

One extra keystroke per rejection. That is a real cost on a loop driven
entirely by hand, and it is accepted because the alternative is another
corpus of labels that cannot answer "why".

Rows exported from runs recorded before this decision have
`reason_code: null`, which is correct and not backfillable -- the reason
was never collected. The merge in 0074 leaves them alone.

This does not build a judge. It makes the data a judge would need exist,
which is the part that cannot be done retroactively. The judge itself is
scoped, undecided, in
[playbook/judge-calibration-scope.md](../playbook/judge-calibration-scope.md).
