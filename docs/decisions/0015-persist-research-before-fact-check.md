# 15. Persist research output before fact-check runs, not after

Date: 2026-08-26

Status: Accepted

## Context

While debugging [decisions/0014](./0014-fact-check-claims-by-number.md)'s
crash, a related gap surfaced: `main()` only wrote `research_claims` into
`run_log.json` after `_run_research_and_fact_check` returned successfully
-- meaning research *and* fact-check both had to complete before anything
was persisted. When fact-check crashed on its own response parsing (the
exact bug 0014 fixed), the real, already-paid-for research output that had
already succeeded and printed to the terminal was gone with no way to
recover it -- `--fixture` had nothing to load, forcing a full, real,
paid re-run of research from scratch just to get back to where the run
already was.

This is the same shape of gap [0009](./0009-previz-image-review.md) and a
later fix in this session already closed for previz: `_generate_previz_
with_review`'s `on_image_generated` callback persists a generated image
the moment it exists, specifically because the *next* step (previz_review)
can itself fail, and previz's docstring already noted this same class of
gap in its own history.

## Decision

`_run_research_and_fact_check` gained an `on_research_completed` callback,
called with the finished `FactSheet` immediately after research succeeds
and before fact-check ever runs. `main()` passes a shared
`_record_research_claims` helper (defined once, at module level, taking
`out_dir`/`log`/`research_model` as explicit parameters rather than as a
closure) from both of its call sites -- the initial research+fact-check
pass, and `_resolve_premise_conflict`'s re-verification pass on a
corrected description, since that path calls
`_run_research_and_fact_check` again and deserves the same protection.

A plain top-level helper (not a nested closure) was chosen specifically
because it's needed from two different points in `main()`'s control flow
that don't share a lexical scope cleanly (one is inside an `if/else`
branch, the other is after it) -- passing `out_dir`/`log` explicitly
avoids duplicating the same closure logic twice.

## Consequences

No schema change to `run_log.json` -- `research_claims`/`research_model`
land in the same place they always did, just earlier in the timeline
relative to fact-check. A run that now crashes inside fact-check leaves a
`run_log.json` with real, usable `research_claims`, recoverable via
`--fixture` the same way a previz-review crash already leaves a usable
`previz_image_path`.
