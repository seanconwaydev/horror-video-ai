# 20. video_generation validates `seconds` client-side after all

Date: 2026-08-27

Status: Accepted

Implementation half superseded by
[0038](./0038-video-generation-on-replicate-and-moderation-rescope.md).

Supersedes part of [0012](./0012-video-generation-duration.md): the
"passed through unvalidated, a rejected value surfaces as a normal API
error" decision. Everything else in 0012 (the duration enum itself, the
`seconds_requested`/`seconds_actual` recording) is unchanged.

## Context

0012 deliberately chose not to validate `seconds` client-side, reasoning
that a bad value would "surface as a normal API error, same as any other
bad parameter" -- a reasonable bet at the time, since OpenAI's own docs
disagreed with each other about the valid range and there was no evidence
yet of what an out-of-range value actually did.

That assumption turned out to be wrong. A real run requested
`seconds="6"` (outside the documented enum) and did **not** get a clean
rejection. Instead, the exact same request that worked fine with
`seconds="8"` failed with:

> `"Invalid type for 'input_reference': expected an object, but got a
> file instead."`

-- an error about a completely different parameter, with no mention of
`seconds` at all. Diagnosed by direct reproduction: reusing the identical
image and prompt with `seconds="8"` instead of `"6"` got past this error
entirely (and reached the API's actual moderation step). So an
undocumented `seconds` value doesn't fail loud and clear -- it corrupts
something in how the request gets serialized, in a way that points
someone debugging it at entirely the wrong parameter.

## Decision

`run_video_generation_stage` now validates `seconds` against the
documented enum (`"4"`, `"8"`, `"12"`, `"16"`, `"20"` -- the same set from
0012) before making any API call, raising `VideoGenerationError` naming
the accepted values. `"4"`, `"8"`, and `"20"` are confirmed directly
against the real API by this project; `"12"` and `"16"` aren't
individually confirmed yet but are accepted since they're consistently
documented and there's no evidence against them specifically.

## Consequences

`--video-seconds`'s CLI help text and `video_generation.py`'s module
docstring updated to describe the validated behavior instead of the old
"not validated client-side" claim. A future real test showing `"12"` or
`"16"` actually work (or don't) should update this ADR's confirmed set,
not require a new ADR on its own.
