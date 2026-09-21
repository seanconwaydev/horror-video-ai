# 27. FactCheckResult's decision-state fields must round-trip through --fixture

Date: 2026-09-02

Status: Accepted


Voided by [0069](./0069-delete-historical-grounding.md): --fixture is deleted, because what it
saved -- a paid research and fact-check pass -- no longer happens.
## Context

Right after 0026 fixed `previz_review` not knowing about a human's
"keep as intentional fiction" decision, a second instance of the exact
same root cause was found by inspection, not by hitting it live:
`--fixture` replay has the identical gap, at a different handoff point.

`main()` writes `run_log.json`'s `"premise_conflict"` field once, from
`fact_check_result.premise_conflict` *before* `_resolve_premise_conflict`
runs, and never updates it afterward -- so a fully resolved scene
(corrected, or kept as fiction) permanently shows in the log as if its
conflict were still open. `acknowledged_fiction` (0026) is never written
to the log at all. `_load_fixture` reconstructs a fresh `FactCheckResult`
directly from those raw log fields. Combined: replaying *any* fixture
whose scene ever had a premise conflict -- regardless of how it was
resolved -- reconstructs a `FactCheckResult` with a stale, still-open
`premise_conflict` and a missing `acknowledged_fiction`, which immediately
trips `run_previz_stage`'s own hard-refuse check on replay. `--fixture`
was broken for exactly the runs most worth replaying.

The underlying pattern, not just this one field: `FactCheckResult` is
already, in practice, the one object every review layer in this pipeline
consults for "what's already been decided about this scene" (previz_review
reads it directly; more stages are expected to be added over time). It
doesn't need to become a new, separate object -- it needs its
serialization to actually be complete and correct, on every path a scene
can take through this pipeline (a live run, and a `--fixture` replay),
not just the live in-process path that happened to get exercised first.

## Decision

`main()`'s log-writing is corrected to reflect the *post-resolution*
state, not a stale pre-resolution snapshot: after
`_resolve_premise_conflict` returns, `log["premise_conflict"]` is
re-written from the resolved `fact_check_result.premise_conflict`
(correctly `null` once resolved, whether corrected or kept as fiction),
and a new `log["acknowledged_fiction"]` field is written from
`fact_check_result.acknowledged_fiction`.

`_load_fixture` reads `acknowledged_fiction` from the log and sets it on
the reconstructed `FactCheckResult`. Combined with the log fix above, a
replayed fixture now reconstructs the actual final state a scene reached,
not a snapshot of the moment fact-check first ran.

**Standing discipline this establishes, for future stages** (not
speculative -- directly why this bug happened twice in immediate
succession): any new field added to `FactCheckResult` representing an
outcome or decision (not raw fact-check output) must be added to both (a)
the post-resolution log write in `main()`, and (b) `_load_fixture`'s
reconstruction, in the same change. A field that's only ever set
in-memory and never threaded through both sides of that round trip will
silently vanish on `--fixture` replay -- exactly this bug, recurring.
Should a future stage need its own resumable/replayable decision state
(scene planning doesn't have one today; every `--fixture` run replans
fresh), the same round-trip discipline applies to whatever record that
stage produces, whether or not it's `FactCheckResult` itself.

## Consequences

`cli.py`'s `main()` and `_load_fixture` change; no new dataclass fields
beyond 0026's `acknowledged_fiction`, no config/CLI surface change.
Existing fixtures captured before this ADR won't have an
`acknowledged_fiction` key -- `_load_fixture` treats it as `None` via
`.get()`, the same graceful-absence handling already used for
`premise_conflict` itself, not a hard requirement on old fixtures.
