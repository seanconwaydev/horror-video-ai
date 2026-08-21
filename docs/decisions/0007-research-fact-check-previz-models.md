# 7. Research, fact-check, and previz model choices

Date: 2026-08-20

Status: Accepted (research, fact_check); previz is a placeholder, not a settled decision (see Consequences)

## Context

[architecture.md](../architecture.md)'s open questions listed two things this
resolves in part: a research/grounding model ("needs real web search
capability, not just training-data recall") and an image model for previz
("needs to be cheap and fast"). `research.py`'s own docstring already flagged
its output as a placeholder until a real grounding decision was made -- it
was calling a plain chat model with no search capability.

A comparison (see
[docs/research/model-comparison.md](../research/model-comparison.md))
evaluated grounded-search options across cost, citation quality, and
provider diversity for a generate-then-verify pattern: one pass produces
claims, a second pass on a *different* provider tries to corroborate or
contradict them, so a blind spot specific to one model's training data or
search ranking doesn't survive its own check.

## Decision

**`research` stage**: Perplexity Sonar, via LiteLLM as `perplexity/sonar-deep-research`
(per [0003](./0003-model-configuration-via-litellm.md), LiteLLM's Perplexity
provider accepts any model from Perplexity's own model cards as
`perplexity/<model-name>`). Chosen because Perplexity is search-first by
design -- citations are native to the response format, not a bolted-on tool
-- which fits pipeline.md stage 2's "nothing here should be unsourced"
requirement directly.

**`fact_check` stage**: Gemini with Google Search grounding, via LiteLLM as
`gemini/gemini-2.5-flash` with LiteLLM's grounding-tool support enabled.
Deliberately a *different* provider than research, not the same one checking
its own work. The stage's prompt should be written to actively look for
reasons a claim could be wrong, not to confirm it -- generic "verify this"
prompting measurably under-performs an explicit "try to falsify this"
framing for reducing confirmation bias in model outputs.

**`previz` stage**: OpenAI's image API, as a starting placeholder --
`gpt-image-1-mini` or similar. Unlike the two decisions above, this has
**not** been rigorously compared; it's picked to unblock building the stage,
not because it won an evaluation. LiteLLM also supports Gemini's own image
generation (`gemini-2.5-flash-image-preview` via `litellm.image_generation()`),
which is a real alternative worth comparing once previz is actually being
iterated on.

## Consequences

`config/models.yaml`'s `research` and `fact_check` entries move off the
`anthropic/claude-sonnet-5` placeholder value. A new `previz` entry is added.
`PERPLEXITY_API_KEY` and `GEMINI_API_KEY` (in addition to the existing
`OPENAI_API_KEY` for previz) need to be set in `.env` before these stages can
make real calls -- none of the three model choices in this ADR have been run
against live credentials yet from this repo; treat the first real run as a
test, not a known-working thing.

The "Research/grounding model" open question in architecture.md is resolved
by this ADR and should be removed from that list. "Image model for previz"
stays listed there, with a note pointing here for the current placeholder --
it is explicitly not resolved by this ADR.
