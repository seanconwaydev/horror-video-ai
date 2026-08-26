# 14. Fact-check flags reference claims by number, not by copied text

Date: 2026-08-26

Status: Accepted

## Context

`fact_check`'s flag-to-claim correlation relied on the model copying a
flagged claim's text back byte-for-byte in `claim_text`, matched by exact
string equality against `fact_sheet.claims`. This crashed twice in real
runs -- both times with `deepseek/deepseek-v4-flash`, used via
`--experiment-model` because `PERPLEXITY_API_KEY` wasn't set up yet, not
the actually-pinned `fact_check` model (Gemini, never yet exercised for
real in this project as of this ADR). Concretely, from one real crash:

> Flag 0's 'claim_text' doesn't exactly match any claim from research:
> 'A Scud missile at night was visible from the ground as a fast, bright
> streak with a glowing engine plume... (date: 1991-01-18) [source:
> Associated Press, 18 Jan. 1991, accounts from rooftop observers in Tel
> Aviv]'

DeepSeek appended `(date: ...) [source: ...]` instead of leaving the claim
text untouched -- not a real accuracy concern, a pure bookkeeping mismatch
that made this pipeline unable to tell which claim the flag was about.
Per this project's existing fail-loud convention (deliberate, not an
oversight -- see the code this replaced), that raised `FactCheckError`
and crashed the whole run rather than guessing.

## Decision

Claims are now numbered in the prompt sent to the model, and a flag
references a claim by that number (`"claim_number": 2`) instead of
copying its text. `_parse_flags` resolves `claim_text` on `ClaimFlag`
itself, by indexing into `fact_sheet.claims` -- the model never supplies
the text at all anymore, so there's nothing for it to get wrong. This
doesn't just harden the prompt (asking more insistently for a verbatim
copy); it removes the failure mode structurally, the same way this
project's other real bugs this session got fixed at the root rather than
patched around (see, e.g., [0011](./0011-previz-image-model-for-video-aspect-ratio-fit.md)'s
aspect-ratio fix, [0013](./0013-python-3.11-upgrade.md)'s workaround
deletions).

`ClaimFlag`'s public shape (`claim_text`, `concern`, `severity`) is
unchanged, deliberately: `cli.py`'s `_resolve_flags`, `previz.py`, and
`--fixture` loading all match/consume flags by `claim_text`, and since
that field is now always populated correctly by this project's own code
(not the model), none of those call sites needed to change at all. Only
`fact_check.py`'s internal parsing and prompt changed.

This was a deliberate, scoped fix, not a preemptive one -- it directly
addresses an observed, repeated failure, rather than adding speculative
robustness elsewhere in the pipeline that hasn't shown the same problem.

## Consequences

`fact_check.py`'s `_format_claims` now numbers each claim in the prompt;
the JSON schema's `flags[].claim_number` (an integer) replaces
`flags[].claim_text`. `_parse_flags` validates `claim_number` is a real
integer (explicitly rejecting `bool`, since Python's `bool` is an `int`
subclass and `isinstance(True, int)` is `True`) in range `[1, len(claims)]`,
raising `FactCheckError` otherwise -- the same fail-loud posture as
before, just checking a condition a model is far less likely to violate
by accident.

Whether Gemini (the actually-pinned model) would ever have hit the
original bug is now moot -- this fix isn't model-specific, so it doesn't
matter which model resolves the flags going forward.
