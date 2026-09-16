# 17. A --yes flag for non-interactive runs

Date: 2026-08-26

Status: Accepted

Superseded in part by [0019](./0019-yes-flag-refuses-contradicted-flags.md).

## Context

Automated/scripted runs against this CLI (used repeatedly this session to
retry after real failures without re-typing the whole command) worked by
piping answers into stdin ahead of time -- `printf 'y\ny\n' | ...`. This is
fragile: it requires correctly predicting exactly how many prompts a given
run will hit (a fact-check flag adds an extra `a/c/s` prompt; a premise
conflict adds more), and guessing wrong doesn't fail cleanly -- it crashes
with a raw `EOFError` partway through a real, already-paid-for run, which
happened for real in this session.

## Decision

A `--yes` flag makes every confirm prompt auto-answer yes, and every
fact-check flag auto-resolve as "accept" (keep the claim exactly as
research produced it) -- never auto-cut or auto-soften, since rewriting a
claim's wording isn't a safe default without a human actually reading the
concern first. `_confirm`, `_prompt_if_missing`, and `_resolve_flags` all
gained an `auto_yes` parameter rather than reading a global/module-level
flag, keeping them testable and explicit about when they'd behave this
way.

`--time`/`--place`/`--description` must be given as real flags under
`--yes` -- there's nothing sensible to auto-answer for a missing free-text
field, so `_prompt_if_missing` raises a clear `ValueError` instead of
calling `input()` (which would just hang, or crash with the exact
`EOFError` this flag exists to avoid, in a genuinely non-interactive
context). The same reasoning applies to an unresolved premise conflict
with no suggested alternative: `--yes` stops the run with a clear message
rather than trying to invent a corrected description.

Every auto-answered prompt is still printed (e.g. `Proceed to fact-check
with this research? [y/n]: y (--yes)`), so a run's transcript stays a
complete, readable record of every decision point even though nothing was
actually typed.

## Consequences

No change to the default (interactive) behavior -- `--yes` defaults to
`False` everywhere it's threaded through
(`_run_research_and_fact_check`, `_resolve_premise_conflict`,
`_resolve_flags`, `_confirm`, `_prompt_if_missing`). Scripted/automated
runs (and this project's own future debugging sessions) can now use
`--yes` instead of hand-piped stdin answers.
