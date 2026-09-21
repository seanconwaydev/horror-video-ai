# 8. Refuse to depict a scene premise that's historically impossible

Date: 2026-08-24

Status: Accepted

Superseded in part by [0025](./0025-keep-premise-conflict-as-intentional-fiction.md)
(the refusal became an intentional-fiction path) and finally by
[0051](./0051-remove-the-single-image-previz-flow.md), which deleted the refusal
with the flow that carried it.


Voided by [0069](./0069-delete-historical-grounding.md): fact-check no longer runs, so nothing
detects an impossible premise and nothing refuses one. Impossible is now
allowed by default.
## Context

Manual testing (`--time "1995 sept 20" --place "harbin, china" --description
"people are getting on and off the subway"`) surfaced a real gap: Harbin had
no subway until 2013, and the research stage correctly said so in its own
output -- but nothing compared that finding against the scene actually
requested. `fact_check`'s adversarial pass only cross-checks individual
claims against each other; it had no concept of the *scene's own premise*
conflicting with what research established. The run sailed through with "no
issues flagged," and previz dutifully generated an image of people boarding
a subway that never existed at that time and place.

This is a different failure mode from a wrong claim. A claim being wrong is
a research error, correctable by fixing or dropping the claim (see
`ClaimFlag` and `cli.py`'s `_resolve_flags`, covering exactly that case).
A premise conflict means the scene as described cannot be depicted at all
without fabricating something -- there's no claim to fix, because the
problem is the request itself.

## Decision

`fact_check` now also checks the scene's premise (not just its claims)
against what research found, and can report a `PremiseConflict`:
an explanation of why the premise is impossible, plus an optional
`suggested_alternative` -- a genuinely close, historically plausible version
of the scene, or `None` if no reasonable one exists (asking the model not to
force a strained guess, e.g. for a scene with a fictional or physically
impossible premise rather than merely an anachronistic one).

When a premise conflict is detected, this pipeline refuses to generate an
image of the requested scene as asked. `cli.py`'s `_resolve_premise_conflict`
pushes back interactively: offers the suggested alternative if there is one,
or lets the human supply their own corrected description; declining both
stops the run. Accepting either triggers one fresh, real research +
fact-check pass on the corrected description (not a reuse of the old
claims, which were shaped by the original, impossible premise) -- if that
re-verification still finds a premise conflict, the run stops rather than
looping indefinitely; a genuinely different description needs a fresh
invocation.

`previz.run_previz_stage` independently refuses (raises `PrevizError`) if
the `FactCheckResult` it's given still carries an unresolved
`premise_conflict`. This is a deliberate second enforcement point, not
redundant with the CLI's interactive gate: the CLI's flow already prevents
an unresolved conflict from reaching previz today, but this pipeline may
eventually be driven by something other than an interactive human (see
`docs/architecture.md`'s open questions) -- a caller that can't answer
interactive prompts must not be able to bypass this by skipping straight to
`run_previz_stage`.

## Consequences

`FactCheckResult` gains a `premise_conflict: PremiseConflict | None` field.
Fixtures (`tests/fixtures/`, loaded via `cli.py`'s `_load_fixture`) written
before this decision don't have this field and default it to `None` on
load -- backward compatible, no fixture needs updating unless it should
demonstrate this behavior.

Explicitly out of scope for this decision: how a non-interactive caller
(another service, not a human at a terminal) should resolve a premise
conflict without a human to ask. `docs/architecture.md` doesn't yet commit
to that usage mode, so this decision only builds the human-facing
interaction; `run_previz_stage`'s refusal is the safety net for that case
until it's actually decided.
