# 30. Acknowledged fiction covers knock-on consequences, not just its literal text

Date: 2026-09-02

Status: Accepted

## Context

Found in a real Pompeii run, after ADR 0026's fix was already confirmed
working: fact-check's `premise_conflict` narrows in on one specific
anachronism -- for this scene, "a smartphone with a time-travel map app...
and time travel itself" -- and that literal explanation is what gets
carried forward as `acknowledged_fiction` when a human picks "keep as
intentional fiction" (0025).

Beat 1 (a tight over-the-shoulder crop) was accepted with no complaint.
Beat 2 (a wide shot that actually shows the character's full outfit) was
rejected: "The influencer is shown wearing entirely modern clothing...
while the smartphone/time-travel anachronism is already accepted, the
modern outfit is an additional, separate anachronism not covered by that
exemption." previz_review is correct given what it was told -- the
literal acknowledged text never mentions clothing -- but the human's
actual intent in choosing "keep as intentional fiction" for a
time-traveling modern visitor obviously covers her whole modern
appearance, not just the specific device fact-check happened to name.

## Decision

`_resolve_premise_conflict`'s "keep as intentional fiction" branch
appends a general broadening note to `conflict.explanation` before
storing it as `acknowledged_fiction`: the acknowledgment covers any other
detail that is a natural, expected consequence of the same acknowledged
premise, not just the literal anachronism fact-check named.

This keeps ADR 0026's own principle intact -- an explicit allowlist beats
asking the reviewer to infer more, since LLM judges have documented high
refusal rates on unstated exceptions -- by broadening what's explicitly
told to the reviewer, not by softening the reviewer's own judgment or
asking it to infer intent. The note is generic (not hardcoded to
"clothing" or "modern visitor"), since the same gap -- one narrowly-named
anachronism vs. its unstated knock-on consequences -- applies to any
future premise conflict, not just this one.

## Consequences

`cli.py`'s `_resolve_premise_conflict` changed; no new dataclass fields.
`acknowledged_fiction` is now `f"{explanation}\n\n<broadening note>"`
rather than the bare explanation -- tests checking it use `in` rather
than exact equality.
