# 18. fact_check moves off gemini-2.5-flash after Google retired it

Date: 2026-08-26

Status: Accepted


Voided by [0069](./0069-delete-historical-grounding.md): the fact_check stage and its model pin
are deleted. The lesson stands and is recorded in 0063 -- a pinned model
can be retired underneath you.
## Context

The first real run of `fact_check` against its actually-pinned model
(`gemini/gemini-2.5-flash`, per [0007](./0007-research-fact-check-previz-models.md))
-- every prior real run had used `--experiment-model` to substitute
DeepSeek instead, since Perplexity/Gemini keys weren't set up yet --
failed immediately with a real 404, not a transient error:

> "This model models/gemini-2.5-flash is no longer available to new
> users. Please update your code to use models/gemini-3.6-flash for the
> latest features and improvements."

litellm's own model registry still lists `gemini-2.5-flash` (confirmed by
inspection -- this is stale registry metadata, not a litellm bug), but
Google's live API rejects it outright for this account. This is a real,
permanent retirement, not something a retry or a workaround fixes.

## Decision

`fact_check` moves to `gemini/gemini-3.6-flash` -- Google's own suggested
replacement in the error message itself, verified working with a direct
real call before committing to it (a newer `gemini-3.7-flash` also exists
but returned a transient 503 "high demand" on the same check; not chosen
since it isn't confirmed working, not because anything is wrong with it).
Per [0003](./0003-model-configuration-via-litellm.md), this is a
deliberate, hand-edited pin change, not an automatic fallback.

## Consequences

`config/models.yaml`'s `fact_check` entry updated; no code changes needed
(the model string is the only thing that changed). `previz`'s separate
image model (`gemini/gemini-2.5-flash-image`) is a different model family
and wasn't affected by this specific retirement, but given Google appears
to be actively retiring the 2.5 generation, it's worth treating as exposed
to the same risk -- if a future real previz run hits a similar 404, the
fix is the same: verify a real successor works, then update the pin here,
not patch around it.
