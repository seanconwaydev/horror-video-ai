# 10. Video generation: model placeholder and a standalone-runnable stage

Date: 2026-08-25

Status: Accepted (standalone stage input/orchestration); model choice is a placeholder, not a settled decision (see Consequences)

## Context

[decisions/0006](./0006-narrow-v1-scope-single-image.md) scoped stages 9-12
as untouched, future work, once the pipeline up through previz was proven
out. That validation is now done enough that Sean wants to try the next
handoff specifically: take one already-approved previz image (a real,
plausible scene -- the happy path, not a premise-conflict or
previz-rejection case) and actually generate a video clip from it, per
[pipeline.md](../pipeline.md)'s stage 9 ("using the scene's text prompt plus
its approved reference image").

Two things needed resolving before any code could be written, both flagged
as open in [architecture.md](../architecture.md): which video-gen model to
target, and -- new, not previously a listed open question -- how a "run just
this stage" invocation should take its input, since Sean also wants the
ability to run stage 9 in isolation, seeded by one or more previously
generated images, ahead of the future multi-scene work where each scene has
its own anchor image.

Checked before writing any code: the installed `litellm` (1.97.0, per
`uv.lock`) has first-class video generation support --
`litellm.video_generation()`, `video_status()`, `video_content()` -- for two
provider families: OpenAI (`sora-2`) and Google (`veo-3.x`, via both the
`vertex_ai` and `gemini` providers). Each call takes one prompt and one
`input_reference` image and returns an async job (create -> poll `status` ->
fetch bytes once `completed`), not a synchronous response like previz's
`image_generation()` call.

## Decision

**Model**: `openai/sora-2`, pinned in `config/models.yaml` as the
`video_generation` stage. Picked to unblock building the stage, exactly the
same "not a rigorous comparison" reasoning [0007](./0007-research-fact-check-previz-models.md)
used for previz's own image model -- not because it won an evaluation. It
reuses the `OPENAI_API_KEY` already required for previz, so no new
credential to set up. Whether this OpenAI account actually has Sora API
access is genuinely unverified -- consistent with every other real-backend
call in this project (research, fact-check, previz, previz_review all
carried the same "treat the first real run as a test" caveat when they were
built) -- and per this project's cost-conscious design, that first real
call is Sean's to make and pay for, not something to trigger automatically
while building the stage. Google's Veo is a real next candidate Sean wants
to try -- litellm already supports it (via `vertex_ai`), so switching later
is a `config/models.yaml` edit, not new integration work; it needs Vertex AI
project/service-account setup rather than a single API key, which is a
reason it wasn't the first pick, not a reason it's ruled out.

**Standalone stage input**: a new `--video-gen-from <run_dir> [<run_dir>
...]` CLI flag on the existing `historical-video-ai` command. Each path is
an existing run's `outputs/run_.../` directory that already completed
previz; the stage reads that run's `run_log.json` for `previz_image_path`
and `previz_prompt_used` rather than inventing a separate manifest file
format for (image, prompt) pairs -- these are real artifacts the pipeline
already writes, and reusing them means no new format to design, validate,
or keep in sync with previz's actual output shape. Passing multiple
directories generates one clip per directory, each treated as one scene's
anchor image + prompt -- standing in now for the future multi-scene case,
where each approved shot becomes its own image-to-video job. This flag
bypasses research, fact-check, and previz entirely for that invocation.

**Execution model**: blocks and polls each job to completion, one at a time,
before moving to the next directory -- matching previz's synchronous,
one-thing-at-a-time CLI style, and simplest for validating the happy path
right now. This is deliberately not the SQS fan-out-with-retry worker pool
[0004](./0004-aws-incremental-adoption.md) already named for this exact
stage ("A video's shot list produces N independent scenes, each requiring
its own expensive, potentially slow, retry-prone API call to a video
generation model. That's a real fan-out-with-retry problem, and a queue plus
a worker pool is the standard pattern for it.") -- that decision already has
a home and doesn't need restating here. Per 0004's own "adopt incrementally,
after the plain logic is proven out locally, and only where a service solves
a problem the design already has" principle, SQS gets adopted once there's
real multi-scene volume to fan out, not proactively for a CLI flag that
today takes at most a handful of directories typed by hand.

## Consequences

`config/models.yaml` gains a `video_generation` entry;
`tests/test_config.py`'s `expected_stages` updated to match.
`src/historical_video_ai/stages/video_generation.py` is new: a
`run_video_generation_stage(image_path, prompt, ...)` function taking one
image and one prompt (not a directory or a list) -- looping over multiple
scenes is `cli.py`'s job, same division of responsibility as previz's own
retry loop living in `cli.py` rather than in `previz.py`. It raises
`VideoGenerationError` on a missing reference image, a missing job id, a
terminal failure status, exhausting `max_poll_attempts` without reaching a
terminal status, or empty video content -- fail-loud, matching every other
stage's convention, rather than silently producing a broken or empty file.

`docs/architecture.md`'s "Video generation model" open question is updated
to point here, with the same "placeholder, not resolved" framing the
"Image model for previz" entry already carries -- not removed, since Sean
explicitly still intends to compare Veo. The "Compute for the video-
generation stage" open question is untouched by this ADR: a local CLI
blocking-poll loop answers "how do I run this once, by hand" for now, not
"what runs this in production," which is a separate question this doesn't
resolve.
