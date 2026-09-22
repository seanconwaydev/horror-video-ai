# 70. Rename the project to horror_video_ai

Date: 2026-09-21

Status: Accepted

Completes [0069](./0069-delete-historical-grounding.md), which deleted
historical grounding and explicitly deferred this rename as a separate
change. That deferral is now spent.

## Context

The package was `historical_video_ai` and the command was
`historical-video-ai`, from a project that grounded every scene in
researched, verified real-world claims.

Three decisions had already moved away from that.
[0031](./0031-goal-is-quality-video-not-historical-accuracy.md) reset the
goal to videos worth watching rather than accurate ones.
[0037](./0037-horror-motion-comic-shorts-wan-via-replicate.md) committed
to horror in a motion-comic style. [0069](./0069-delete-historical-grounding.md)
deleted research, fact-check and every form of real-world grounding.

After 0069 the name was not merely inaccurate, it was misleading in a way
that costs something. `CLAUDE.md` had to carry an explicit instruction not
to let the name steer a design decision toward accuracy — a warning label
compensating for a name, which is a sign the name is wrong rather than a
sign the label is needed.

0069 deferred the rename deliberately: it touches every import, the CI
workflow, every doc and the command the owner types, and mixing it into a
behavioural deletion would have made both harder to review and to revert.
Doing it as its own change keeps `git log` honest about which commit
changed behaviour and which only changed spelling.

## Decision

`src/historical_video_ai/` becomes `src/horror_video_ai/`, the
distribution becomes `horror-video-ai`, and the console script becomes
`horror-video-ai`. Applied across `src/`, `tests/`, `evals/`,
`pyproject.toml`, the CI workflow and the prose docs.

**ADRs 0001-0069 are not rewritten.** [0001](./0001-record-architecture-decisions.md)
makes an ADR write-once, and six of them refer to `src/historical_video_ai/`
or the old command. Those are accurate records of what the code was called
when the decision was made. A reader who greps an old ADR's path and finds
nothing should land here: **every pre-0070 ADR's `historical_video_ai` is
today's `horror_video_ai`, and its `historical-video-ai` is
`horror-video-ai`.** The same applies to 0069's closing paragraph, which
says the rename is still pending; it was, on the day it was written.

The repository directory itself is still `historical-video-ai` and is left
to the owner: renaming it changes a path outside this repo's control, and
nothing in the codebase depends on it.

## Consequences

`CLAUDE.md` loses the instruction not to let the name mislead. The name
now says what the project makes, so nothing needs to argue with it.

Anyone with a local checkout re-runs `uv sync`, and the old
`historical-video-ai` command stops existing. Existing run directories
under `outputs/` are unaffected -- nothing in a run log names the package.

`.claude/settings.local.json` holds a few stale permission entries naming
the old command. They are the owner's local config, harmless, and left
alone.

Horror being the committed genre is [0037](./0037-horror-motion-comic-shorts-wan-via-replicate.md)'s
decision, not this one. If that ever changes, this name becomes wrong in
exactly the way the old one was -- and the lesson from 0069 is that the
gap between what a project is called and what it does should be closed
quickly, not tolerated for months.
