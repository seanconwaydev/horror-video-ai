# 67. Retry a POST only on a throttle

Date: 2026-09-19

Status: Accepted

Narrows the transport-retry behaviour added with
[0038](./0038-video-generation-on-replicate-and-moderation-rescope.md)'s Replicate client.
Nothing is superseded; polling and throttle handling are unchanged.

## Context

`replicate_client._default_request_fn` retried every call on 408, 429,
500, 502, 503, 504 and on any transport error, up to five times. The
transport-error branch was added for a real, repeatedly observed failure
-- `[SSL: SSLV3_ALERT_BAD_RECORD_MAC]`, which killed two images of a paid
batch -- and the status branch for Replicate's throttle, which drops to
"6 requests per minute with a burst of 1" under $5 of credit, a limit a
clip-per-beat run walks straight into.

The retry was applied uniformly to every method, and one of those calls
is not safe to repeat. `run_prediction` POSTs to
`/v1/models/{model}/predictions` to create a prediction. A 5xx, a 408 or
a dropped connection on that call is **ambiguous**: it can mean the
request never landed, or that Replicate accepted it and only the response
was lost. Retrying the second case starts a second paid generation while
the first runs to completion, orphaned and billed, with nothing on disk
recording that it ever existed -- `_record_video_gen_result` only writes
after a successful download.

429 is the exception, and the distinction is the whole decision. A
throttle means the request was rejected *before* being processed, so a
retry cannot duplicate work. It is also the failure that actually recurs
here, while the ambiguous ones are rare.

Replicate offers no idempotency key for prediction creation (checked
2026-09-19). Its documented idempotency guidance is about deduplicating
webhook deliveries on `prediction.id`, which does not help a caller whose
creation response was lost. So the usual fix is unavailable.

The exposure is small and worth stating rather than inflating: a clip
costs roughly $0.05 (`docs/playbook/video-generation-prompting.md`, from
a real run). This is a correctness decision about not paying twice for
work nobody asked for, not a cost emergency.

## Decision

Retryability is now a function of the method as well as the failure.

- **429, any method.** Retried, waiting for the interval Replicate names.
- **408/5xx and transport errors, `GET`/`HEAD` only.** Polling and
  downloads change nothing, so repeating them is free of consequence.
- **408/5xx and transport errors on anything else.** Fail loud, first
  attempt, no retry.

A failed creation costs a re-run of a step that has not spent anything
yet, which is the cheapest possible thing to lose.

## Consequences

Prediction creation is now more fragile than it was against exactly the
SSL error that motivated the retry. That is the accepted trade: the
failure it prevents is silent and costs money, and the failure it
introduces is loud and costs a retry of something free. Polling keeps the
full retry budget, so the long part of a generation -- minutes of
polling, where a blip is far more likely -- is as resilient as before.

Two options were considered and rejected for now. Never retrying a POST
at all would also have dropped the throttle handling, which is the case
that genuinely recurs. Reconciling after an ambiguous failure -- listing
recent predictions and adopting a match instead of creating a new one --
is the fully correct answer and keeps both properties, but needs input
hashing over a multi-megabyte data URI, a listing call and clock-skew
tolerance. That belongs in the codebase if a duplicate is ever actually
observed, not ahead of it.

Still outstanding and deliberately not addressed here: `download_output`
has no retry at all, so a transport blip while fetching a finished clip
discards work already generated and paid for. The asymmetry is now
sharper -- the cheap, safe GET has five retries and the irreplaceable one
has none.
