# 56. Persist work in flight, not at the end of a unit

Date: 2026-09-17

Status: Accepted

## Context

The run log was written after every *finished* beat
([0043](./0043-one-review-prompt-the-human-decides.md)-era fix for a run
that recorded zero beats despite two being paid for). That still lost
whatever was in flight, and the project owner abandons most runs partway
through -- "i've been ending most runs early, so their actual costs were
different than projected costs." So the interrupted case is the common one,
not an edge one.

Measured across 26 real runs: **290 images on disk, 212 in the logs. 27%
of everything generated had no record at all**, and several runs logged
zero despite holding paid-for images.

Since [0053](./0053-human-judgements-are-recorded-as-data.md) the same gap
loses human judgements, which cost more to produce than the images do.

The precise window matters. A first attempt at this persisted after
candidate *selection*, and a kill test still lost everything: the images
are paid for the moment they exist, and the very next thing is a "Keep
which?" prompt a human may never answer. That is where a run actually
gets abandoned.

## Decision

`_generate_image_with_retries` takes an `on_attempt` callback and fires it
three times per attempt: once as soon as the candidates exist, before any
prompt; again once a candidate is chosen; and again with the final record
once the human's decision is known. Later writes for the same attempt
supersede earlier ones.

The beat loop writes a partial beat entry on every one of those, marked
`in_progress`, replaced by the real entry when the beat finishes.

Verified by killing a real `--mock` run at the candidate prompt: 3 of 3
images recorded with their exact prompts, where the same test recorded 0
of 3 before.

Two consequences for the judgement dataset, both about not inventing
labels:

- An `in_progress` beat is **not** a give-up. It has no `image_path` for
  the same reason a give-up does, but the human never ruled on it.
- An attempt recorded with `accepted: None` was written before the human
  answered. Its candidates carry no judgement, so `export_judgements.py`
  skips them rather than counting them as rejections.

## Consequences

A run log now contains entries for work that was never ruled on. That is
the point -- the spend is real whether or not a decision followed -- but
anything reading the log has to distinguish "rejected" from "never
answered", which is why both markers exist rather than relying on
`image_path` alone.

The general lesson, which is the part worth keeping: **flush at the moment
a cost is incurred, not when a unit of work completes.** Assume the process
dies at the least convenient point, because here it usually does.
