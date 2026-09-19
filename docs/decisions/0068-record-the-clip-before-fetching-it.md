# 68. Record the clip before fetching it, and retry the fetch

Date: 2026-09-19

Status: Accepted

Extends [0056](./0056-persist-work-in-flight.md) from previz to stage 9,
and completes the retry policy [0067](./0067-retry-a-post-only-on-a-throttle.md)
set. Nothing is superseded.

## Context

Stage 9 has three steps: create a prediction, poll it to `succeeded`,
then download the clip from the URL the finished prediction names. The
spend happens at step two. The download is a plain fetch of a file that
already exists and has already been paid for.

Two things were wrong with that last step, and they compounded.

`_default_download_fn` was a bare `httpx.get` with no retry at all, while
the polling GET beside it had five. That is precisely backwards: polling
is cheap and endlessly repeatable, and losing a poll costs one more poll.
The download is the one fetch in the module whose failure destroys
something irreplaceable. The `[SSL: SSLV3_ALERT_BAD_RECORD_MAC]` error
that motivated every other retry in this file applies here too.

And nothing recorded the prediction until *after* the download succeeded
-- `_record_video_gen_result` was called with the finished
`VideoGenerationResult`. So a failed download left no prediction id, no
output URL, and no entry in the run log. The clip existed on Replicate,
had been billed, and there was nothing on disk pointing at it.

0056 already solved this exact shape one stage earlier. Previz's
`on_image_generated` fires the moment an image is written and before
anything can block or fail, because "a review-stage crash left a real,
already-paid-for image on disk with no record of it in the log". Stage 9
had the same hole and no equivalent hook.

## Decision

**The fetch retries.** `_default_download_fn` uses the same policy as any
other GET -- `_is_retryable`, now the single place that policy lives,
extracted so 0067's method-dependent rule is not re-derived per call
site. A 404 still fails on the first attempt; a dropped connection or a
5xx is retried.

**The prediction is recorded before the fetch.**
`run_video_generation_stage` takes an `on_prediction` callback, fired
with `(prediction_id, output_url)` as soon as the clip exists on
Replicate. `cli/video_gen.py` writes a `videos` entry from it with
`downloaded: false`, and the full entry after a successful download
replaces it -- matched on `prediction_id` via `_record_video_gen_result`'s
new `supersede_on`, which is 0056's "later writes for the same attempt
supersede earlier ones" applied here. `VideoGenerationResult` gains
`prediction_id` so the final write can carry the same key.

## Consequences

A failed download now leaves a row naming the prediction and its output
URL, so the clip can be fetched again by hand or the prediction looked up
in Replicate's dashboard. The run does not recover automatically -- it
still raises -- but the information needed to recover is on disk instead
of gone.

Writing an entry that may never be completed means a run log can contain
a `downloaded: false` row. That is the intended state, not a bug, and it
is the honest record of what happened: the money was spent and the file
was not retrieved.

This surfaced a fidelity bug in the mocks. `mock_prediction` returned a
constant `"mock-prediction-id"`, where Replicate never returns the same
id twice, so superseding collapsed two separate mock runs into one entry
and an existing test caught it. The mock now generates a fresh id per
call. A mock that differs from the real API in a property the code
depends on is worth noting as its own small lesson.

The remaining gap is deliberate: an ambiguous failure while *creating* a
prediction (0067) still leaves an orphan nothing knows about, because
there is no id to record until the response arrives. Only reconciliation
against Replicate's prediction list would close that, and 0067 records
why it is not worth building yet.
