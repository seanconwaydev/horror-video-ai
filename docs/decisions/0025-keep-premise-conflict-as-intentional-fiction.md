# 25. A flagged premise conflict can be kept as intentional fiction

Date: 2026-09-02

Status: Accepted

Supersedes part of [0008](./0008-refuse-impossible-premises.md): the "no
suggested alternative and no accepted correction means refuse" behavior
gains a third resolution path below. Everything else in 0008 (fact-check
flagging a premise as historically impossible in the first place, and
`run_previz_stage`'s own hard-refuse check as the last-resort safety net)
is unchanged.


Voided by [0069](./0069-delete-historical-grounding.md): with no fact-check there is no premise
conflict to acknowledge, and nothing left that would object to fiction.
## Context

The project's actual goal has shifted: historical accuracy is no longer
the point, producing good videos is -- explicitly stated, not inferred
("at this point it's just about generating good videos"). That still
means the parts of a scene meant to be real (the setting, the period
detail) should stay genuinely researched and grounded via real
research/fact-check, not abandoned -- but a scene deliberately mixing a
real historical setting with an openly fantastical element (a
time-traveling character, a piece of impossible technology, a fictional
creature) is now a legitimate, common case this pipeline needs to handle
smoothly, not an edge case to work around by hand every time.

Today, the only way to get such a scene past fact-check's premise-conflict
check was to bypass research/fact-check entirely -- hand-building a
`run_log.json` and calling previz directly, done for both the Agent Voss
and Pompeii test scenes. That workaround also skips real grounding for
the historically-real parts of the scene, which is exactly the thing
worth keeping. Needing a bypass script for something as common as "this
scene is deliberately part-fiction" was flagged directly as a real
problem, not a one-off annoyance.

Flags were considered and explicitly rejected for this, consistent with a
standing preference already expressed: avoid adding CLI flags until the
pipeline's output quality is pinned down and there's a concrete reason to
refine the interaction surface, rather than growing flags speculatively.
A "levels of implausibility" system was also discussed previously as a
possible future direction, but isn't needed for what's actually required
right now.

## Decision

`_resolve_premise_conflict` (cli.py) gains a third choice at the same
interactive gate it already presents, alongside using the suggested
alternative and providing your own corrected description: **keep as
intentional fiction**. Choosing it prints an explicit acknowledgment and
returns `(fact_sheet, fact_check_result)` with `premise_conflict` cleared
to `None` -- the flagged claim/premise itself is not altered, only
acknowledged. This satisfies `run_previz_stage`'s own hard-refuse check
(0008), whose actual purpose is requiring a human to have knowingly
acknowledged the conflict, not forbidding fictional content outright.

Under `--yes`, this choice is never auto-selected -- a premise conflict
still stops the run under `--yes`, same as before, since "keep as
fiction" and "use the corrected version" produce meaningfully different
videos and `--yes` has no sound basis to guess which one is wanted (same
reasoning as 0017/0019's other cases `--yes` refuses to guess at).

`main()`'s run log gains a `premise_conflict_resolution` field
(`"kept_as_intentional_fiction"` or `"corrected"`) alongside the existing
`premise_conflict_resolved_with_description`, so a run's history shows
*how* a conflict was resolved, not just what description ended up in use.

## Consequences

A scene like the Pompeii influencer test (a real Pompeii thermopolium,
genuinely researched, with an intentionally fictional time-traveling
framing) can now run through the real pipeline end to end -- research and
fact-check for real, one explicit acknowledgment at the existing gate,
then scene planning and previz as normal -- instead of requiring a
hand-built bypass that skips real grounding for the parts of the scene
that should stay grounded.

Not addressed here: any notion of "levels" of implausibility, or a
config-level default for how conflicts get handled -- this stays a
one-shot human decision at the existing interactive gate, revisited if
that proves insufficient once real usage shows what's actually needed.
