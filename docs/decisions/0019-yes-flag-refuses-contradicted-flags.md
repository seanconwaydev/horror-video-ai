# 19. --yes refuses to auto-accept a contradicted fact-check flag

Date: 2026-08-26

Status: Accepted

Supersedes part of [0017](./0017-non-interactive-mode.md): the "every
fact-check flag auto-resolves as accept" clause is replaced by the
per-severity behavior below. Everything else in 0017 (auto-answering
confirm prompts, the free-text-field and premise-conflict stop behavior)
is unchanged.

## Context

A real run under `--yes` hit two fact-check flags on the scene's own
premise: `[contradicted]` flags asserting a specific book title Tang
Shizeng supposedly wrote was fabricated. `--yes` auto-accepted both,
per 0017's original "always accept" rule. Independent verification after
the fact (web search against Chinese Wikipedia, Baidu Baike, and Douban)
showed fact-check was itself wrong here -- the claim was real -- but
`--yes` had no way to know that either way, and blind-accepting a claim
fact-check specifically flagged as contradicted is a real risk to the
core thing this project's fact-check stage exists to catch, regardless of
which side of a given flag turns out to be correct.

0017's "always accept, never auto-cut/auto-soften" rule conflated two
different severities. `[uncertain]` is a soft doubt with no competing
claim (e.g. a units nitpick) -- accepting it by default costs little.
`[contradicted]` means fact-check is asserting a specific, concrete
competing fact -- accepting it by default risks baking a claim already
flagged as likely wrong into the record, unexamined.

## Decision

`_resolve_flags` still auto-accepts `[uncertain]` flags under `--yes`.
For a `[contradicted]` flag, it prints the claim and concern and returns
`None` to stop the run -- the same "don't guess, stop" pattern `--yes`
already uses for an unresolved premise conflict with no suggested
alternative (0017). `main()` treats this the same way it treats that
existing stop case: write the log with a `stopped_reason`, print where
the run's artifacts landed, and return.

This still doesn't ask any model to adjudicate a flag -- that would just
be the same failure mode one level up (a second model judging a first
model's claim, with no more grounding than the first). It makes a
`contradicted` flag impossible to blow past unattended; resolving it for
real still requires a human rerunning without `--yes`.

## Consequences

`_resolve_flags`'s return type is now `FactSheet | None`; its one caller
in `main()` checks for `None` and stops, mirroring the existing
`_resolve_premise_conflict` stop path. No change for runs with only
`[uncertain]` flags or no flags at all -- `--yes` behaves exactly as
before for those.
