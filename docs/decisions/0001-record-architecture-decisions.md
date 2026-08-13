# 1. Record architecture decisions

Date: 2026-08-12

Status: Accepted

## Context

As this project grows and a second developer eventually joins, "why did we build it this way" needs to be answerable without digging through chat history or git blame.

## Decision

We use short architecture decision records (ADRs), one file per decision, numbered sequentially in `docs/decisions/`. Each one is written once when the decision is made and left alone afterward — if a decision changes later, a new ADR supersedes it and says so explicitly, rather than editing the old one in place. `docs/architecture.md` stays a short, current-state overview; the ADRs are the permanent record of why that current state is what it is.

Format: Context (what problem/question prompted this), Decision (what we chose), Consequences (what this makes easier or harder, what it rules out).

## Consequences

Every real decision gets a short, durable, dated write-up. Undecided/open questions are not ADRs — they stay listed in `docs/architecture.md` until they're actually resolved, at which point they become one.
