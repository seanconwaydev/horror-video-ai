# 16. Retry previz's image call on transient errors, hand-rolled

Date: 2026-08-26

Status: Accepted

## Context

`previz`'s image generation call (Gemini) hit a real, repeated transient
failure across multiple real runs this session: `503 UNAVAILABLE`,
`"This model is currently experiencing high demand."` Each time, the fix
was simply to run the exact same command again -- a textbook case for an
automatic retry, and specifically scoped to `previz`, per
[the reactive-not-preemptive principle established this session](../../CLAUDE.md):
only `previz` has actually failed this way in a real run; `research` and
`fact_check` haven't, so they aren't getting this treatment preemptively.

Before writing a retry loop, litellm's own `num_retries` kwarg was checked
first, per this project's "prefer an upgrade/library feature over rolling
your own" convention. It turned out not to apply here at all -- verified
by direct reproduction (mocking the HTTP layer to raise a real 503, the
same technique used throughout this project to verify litellm behavior
before writing code against it), not assumed from the kwarg merely
existing on the function signature. Reading litellm's own source
confirmed why: the retry loop inside its `client` decorator lives only in
the *async* wrapper, and is further gated to only fire when
`call_type == CallTypes.acompletion.value` -- i.e. it doesn't even cover
async `image_generation()`, let alone the synchronous version this project
calls. `num_retries=3` was passed to a real (mocked-at-the-HTTP-layer)
`litellm.image_generation()` call and it made exactly one attempt, not
three -- confirming this isn't a documentation gap, it's a real absence of
the feature for this call.

## Decision

A small, bounded retry loop was added directly in `run_previz_stage`,
around the `image_fn` call only. It retries up to `_MAX_TRANSIENT_RETRIES`
(3) times, with a fixed delay (`_TRANSIENT_RETRY_DELAY_SECONDS`, 5s)
between attempts, and only for a specific allowlist of exception types
judged genuinely transient: `ServiceUnavailableError`, `RateLimitError`,
`Timeout`, `InternalServerError`, `APIConnectionError`, `BadGatewayError`.
Anything else -- a real content rejection, a bad request, an
authentication failure -- fails on the first attempt, since retrying an
identical request that was rejected for a non-transient reason would just
produce the identical rejection again (this project already has a
different, existing mechanism for a rejection that *should* trigger a
fresh attempt with a different image: `_generate_previz_with_review`'s
regeneration loop on a failed review, which is conceptually distinct from
this and unaffected by this change).

`sleep_fn` (matching `video_generation.py`'s existing pattern) makes the
delay injectable for tests, and `on_transient_retry` is an optional
callback `cli.py` uses to print retry progress -- kept as a callback
rather than a `print()` inside `previz.py` itself, consistent with every
other stage module in this project not doing its own console output.

## Consequences

`previz.py` gains a `time` import and the retry constants/exception
allowlist. No change to `previz.py`'s public return shape or to any other
stage -- this is scoped entirely to one function's internal call, per the
"previz only, not preemptively extended to research/fact_check" decision.

If `research` or `fact_check` ever hit their own real transient failure
in a future run, the same treatment can be applied there then -- this ADR
doesn't rule that out, it just doesn't do it now without evidence it's
needed.
