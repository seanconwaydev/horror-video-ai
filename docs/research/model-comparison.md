# Research-stage model comparison

Comparison behind the model choices in [decisions/0007](../decisions/0007-research-fact-check-previz-models.md).
Ported over from earlier scoping conversations; kept here going forward
since `docs/research/` is where this project keeps supporting evidence
for its ADRs (see `youtube-monetization-policy.md` for the existing
example of that pattern).

## Why this comparison exists

The `research` stage needs to produce accurate, citable claims that
`fact_check` and (eventually) `previz`/`narrative` can build on without
silently inheriting hallucinations. The core insight driving the
comparison below: for this task, **grounding quality (live search +
verifiable citations) matters more than raw benchmark "intelligence."**
A smarter model answering from training memory is a worse research tool
than a weaker model that cites a live, checkable source.

## Model-tier policy

Not every stage needs the same caliber of model. Where accuracy
genuinely matters — historical research specifically — it's fine to
reach for a more specialized, more expensive model. Where a stage's job
is more generic (formatting, light synthesis, non-grounded checks), a
cheaper or more general-purpose model is preferred. This is the standing
default for picking a stage's `model` value in `config/models.yaml` —
not "use the best model everywhere," and not "use the cheapest
everywhere," but matched to what that stage actually needs to get right.

## Options compared (as of Aug 2026)

**OpenAI deep research models.** `o3-deep-research` ($10 / $40 per 1M
input/output tokens) runs multi-step search-read-synthesize loops with
inline citations — best for the hardest/most ambiguous topics.
`o4-mini-deep-research` ($2 / $8 per 1M tokens, web search billed
separately at ~$0.01/search; a real logged 77-search run cost ~$1.10
total) is the more practical default of the two, since `o3` buys
thoroughness rather than accuracy for most topics. Both go through the
Responses API rather than standard chat completions.

**Google Gemini + Search grounding.** Not a dedicated "deep research"
model — any current Gemini model can be given a `google_search` tool
that fires mid-generation. Returns `url_citation` annotations tied to
exact text spans, which is convenient for programmatically auditing
claims against sources. Billing: 5,000 free search queries/month, then
$14 per 1,000 queries, on top of normal token pricing (Flash-Lite:
$0.25–0.30 input / $1.50–2.50 output per 1M — cheap). **Chosen as the
`fact_check` backend** — a different provider than `research`'s
Perplexity backend, on purpose (see "Why a different provider" below).

**Perplexity Sonar API.** Built search-first rather than
search-bolted-on; citations are a first-class part of the response
format, not an add-on tool call. Sonar Deep Research: $2 / $8 per 1M
input/output + $2/1M citation tokens + $3/1M reasoning tokens + $5 per
1,000 search queries — tuned for exhaustive multi-source synthesis.
Sonar Pro (lighter, non-exhaustive): $3 / $15 per 1M tokens + a flat
per-request fee. **Chosen as the `research` backend** — its search-first
design fits the "nothing here should be unsourced" requirement directly,
and it's the "specialized, worth paying for" tier under the policy
above.

**Claude (Anthropic).** Has a web search tool with citation support and
strong general reasoning, but no packaged "deep research" product — the
multi-step search/synthesize loop has to be composed rather than invoked
as one feature. More control, more engineering effort to match what
OpenAI/Perplexity give out of the box. Currently the placeholder model
for the four not-yet-built stages (`narrative`, `narrative_review`,
`shot_list`, `video_prompts`).

**DeepSeek V4-Flash.** Verified pricing as of Aug 2026: **$0.14 input /
$0.28 output per 1M tokens** (cache-hit input $0.0028), 1M-token context
— dramatically cheaper than every option above. DeepSeek positions it as
the default cheap/fast workhorse for chat, extraction, and high-volume
work, with V4-Pro ($0.435 / $0.87 per 1M) reserved for harder
reasoning/agentic/coding tasks. Nothing in DeepSeek's own positioning of
V4-Flash mentions native web-search grounding or citation output the way
Gemini's `google_search` tool or Perplexity's Sonar models do — so it's
not an obvious fit for `research` (needs live grounding) or `fact_check`
as currently designed (needs an independent *grounded* check, not just a
second opinion from memory) without wiring a separate search tool to it.
Under the tier policy above, it reads as a strong candidate for the
non-grounded stages once they're built.

## Why a different provider for fact_check, not the same one twice

A single grounded-search call is still one model's read of the web at
one moment — it can miscite, over-generalize from a weak source, or
simply not find the source that would have contradicted it. Verifying
with the same provider that generated the claim risks the same training
data and the same search-ranking biases producing the same mistake
twice; a different provider (Perplexity generates, Gemini checks) is a
genuinely independent check, not just a repeated one.

This should also show up in the `fact_check` prompt itself, not just the
provider split: LLMs have a documented tendency toward confirmation bias
— when asked to test a claim, they default to searching for evidence
that supports it rather than evidence that would falsify it ([Failing to
Falsify: Evaluating and Mitigating Confirmation Bias in Language
Models](https://arxiv.org/html/2604.02485v1)). That research found
explicitly instructing a model to construct the *opposing* case — "think
in opposites," i.e. actively search for reasons a claim could be wrong,
not just reasons it's right — meaningfully reduced the bias beyond what
model choice alone achieved. `fact_check.py`'s prompt is written this
way for that reason. No direct benchmark was found comparing these
specific tools on adversarial contradiction-finding — that citation is
general LLM research, not a study of these tools in this exact use case,
so treat "which provider is best at this" as untested until it's tried
against real runs.

## The gap that matters most for this project

All of the above ground against live web search — mostly current,
well-indexed web pages. None of them search Google Books, JSTOR,
newspaper archives, or digitized primary-source repositories (Library of
Congress, national archives, etc.) by default. For a history-focused
channel whose audience will fact-check, this is the real risk, more than
model "intelligence." Not addressed by anything in v1; worth revisiting
if `fact_check` output quality turns out to need it.

## Next: experimenting with Gemini 2.5 Flash and DeepSeek V4-Flash

Beyond the `fact_check` role Gemini 2.5 Flash already has, the plan is
to specifically try both Gemini 2.5 Flash and DeepSeek V4-Flash in the
non-specialized/non-grounded spots (the currently-dormant `narrative`,
`narrative_review`, `shot_list`, `video_prompts` stages, once built) to
see how each actually performs there — not just on cost, on real output
quality. That includes mixing and matching across stages rather than
assuming one model wins every non-grounded spot: different stages may
end up on different models both for quality reasons and deliberately,
for the experimentation itself. No results yet — this is a plan, not a
finding.

## Open questions

- Does DeepSeek V4-Flash's output quality hold up well enough (once
  there's a non-grounded stage to try it on) to justify the cost gap
  versus the reference backends above?
- Do we need archival/primary-source search (JSTOR, Google Books, LOC)
  wired in as a tool, or is flagging unverifiable claims sufficient for
  v1?
- Cost ceiling per episode — this determines whether
  `o3-deep-research`-tier thoroughness is ever justified vs. always
  defaulting to the cheaper tier.
- Which of Gemini 2.5 Flash / DeepSeek V4-Flash (or a mix) ends up
  assigned to each of the four dormant stages, once they're built.
