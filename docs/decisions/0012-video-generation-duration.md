# 12. Sora-2 video duration: how it's controlled, and resolving conflicting docs

Date: 2026-08-25

Status: Accepted

Superseded in part by [0020](./0020-video-seconds-validated-client-side.md)
(client-side validation) and in its implementation half by
[0038](./0038-video-generation-on-replicate-and-moderation-rescope.md).

## Context

Testing the video-generation stage against a more deliberately "commercial"
scene (a 15-20 second action beat, not just a proof-of-concept clip) raised
a real question this project hadn't needed to answer yet: how is a Sora-2
clip's length actually controlled, and what durations does it support?

OpenAI's own docs disagree with each other on this. The API reference
(`developers.openai.com/api/reference/resources/videos/methods/create`)
documents the `seconds` parameter as a strict enum:

> `seconds: optional VideoSeconds` — Clip duration in seconds (allowed
> values: 4, 8, 12). Defaults to 4 seconds.

The video-generation guide (`developers.openai.com/api/docs/guides/video-
generation`) separately states, verbatim:

> "Both `sora-2` and `sora-2-pro` support `16`- and `20`-second
> generations."
>
> "Generate videos up to `20` seconds when you need longer beats, fuller
> scenes, or fuller spots."

Reading further didn't resolve this -- the two pages just keep disagreeing.
This was resolved by trying it against the real API instead.

## Decision

**`seconds` is a real, directly controllable parameter, and the guide was
right: `sora-2` accepts values beyond the reference page's documented
enum.** Verified by requesting `seconds="20"` against the real API (source
image and prompt otherwise identical to an already-working `seconds="4"`
run): the job completed and the returned `VideoObject.seconds` field
confirmed the delivered clip really was 20 seconds, not silently clamped
to 12 or rejected. The reference page's enum is stale, incomplete, or
scoped to something narrower than plain `video.create()` -- not something
this project needs to resolve further; what matters is confirmed, real
behavior against the real endpoint, which now exists.

**Duration measurably affects generation time, not just output size.**
Comparing two otherwise-equivalent real runs: `seconds="4"` produced a
3.7MB file after 11 status-poll cycles; `seconds="20"` produced a 16.9MB
file (roughly proportional to the 5x duration increase) after 31
status-poll cycles -- a clear signal that a longer requested clip takes
meaningfully longer to render, not just occupies more disk space.
`run_video_generation_stage`'s existing bounded polling
(`max_poll_attempts`, `docs/decisions/0010`) already accommodates this;
no change needed there, just a data point worth recording for anyone
tuning those bounds later for consistently longer clips.

`run_video_generation_stage` gained a `seconds` parameter (default `"4"`,
Sora's own documented default), passed through to the provider
unvalidated -- this project doesn't maintain its own copy of an enum that
OpenAI's own docs can't agree on. A value the provider actually rejects
surfaces as a normal API error, same as any other bad parameter, rather
than this code guessing at a boundary that might just be wrong. The CLI's
new `--video-gen-from` companion flag, `--video-seconds`, exposes this per
run. `VideoGenerationResult` now also records `seconds_requested` and
`seconds_actual` (read back from the completed job) side by side, so a
future run's log is self-documenting about whether the two matched,
instead of assuming they always will.

## Consequences

No new dependency or ADR-worthy risk beyond what's stated above. This
doesn't change the pinned model or its placeholder status
(`docs/decisions/0010`) -- it's a parameter of the existing pinned model,
not a new decision about which model to use.

Not yet tested: durations between 12 and 16 (does `"14"` work?), above 20,
or the separate `/videos/extensions` endpoint the guide mentions for
chaining clips past a single generation's limit (up to 120 seconds total
across six extensions) -- out of scope for what this ADR needed to answer,
and untried.
