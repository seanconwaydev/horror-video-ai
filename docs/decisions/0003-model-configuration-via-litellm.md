# 3. Per-stage model configuration via LiteLLM, pinned versions only

Date: 2026-08-12

Status: Accepted

## Context

Each pipeline stage needs an LLM call, and the specific model/provider used at each stage needs to be easy to change — different providers (Claude, DeepSeek, and others) are expected to be tried and compared per stage on quality vs. price, and models update over time.

## Decision

Each stage's model choice (provider + specific version) lives in configuration, not hardcoded into that stage's code. The integration layer is [LiteLLM](https://docs.litellm.ai/) (open-source Python library), which exposes one `completion(model="<provider>/<model-name>", messages=[...])` call that works uniformly across 100+ providers including Anthropic and DeepSeek, normalizing the response format so stage code doesn't need provider-specific branches.

Model versions are pinned in config and changed only by explicit human decision — never automatically. LiteLLM's optional Router feature (auto-fallback to a different model on failure/rate-limit) will not be used, specifically to prevent any model substitution happening without the person running the pipeline being aware of it. Only plain `completion()` calls with an explicit pinned model string are used.

## Consequences

Swapping a model at a given stage, or upgrading to a newer version of a model already in use, is a config edit, not a code change. The tradeoff: no automatic resilience to a provider's model changing or going down — a pinned model failing requires a human to update config and retry, by design.
