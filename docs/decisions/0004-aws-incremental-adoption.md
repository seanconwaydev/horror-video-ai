# 4. Adopt AWS services incrementally, chosen for genuine fit only

Date: 2026-08-12

Status: Accepted (for the principle and the two services named below; other AWS services remain open questions, not decisions — see architecture.md)

## Context

This project has a second, explicit goal alongside the pipeline itself: real practice with AWS (motivated by a recent AWS developer certification) and a codebase that reads well to a technical interviewer browsing it on GitHub. The stated risk to avoid: adding AWS services because they look good on a resume, not because they solve a real problem the project actually has (SQS was raised specifically as an example of a service that's easy to cram in without a genuine reason).

## Decision

AWS services get adopted incrementally, after the plain pipeline logic is proven out locally (consistent with the existing "build and review the cheap stages before adding infrastructure" approach), and only where a service solves a problem the design already has — not proactively.

Two services are confirmed now because the fit is specific and genuine, not general:

**SQS**, for stage 9 (video generation) specifically. A video's shot list produces N independent scenes, each requiring its own expensive, potentially slow, retry-prone API call to a video generation model. That's a real fan-out-with-retry problem, and a queue plus a worker pool is the standard pattern for it. This is deliberately the one place SQS is used, not a general messaging layer for the whole pipeline.

**Step Functions**, for the overall pipeline orchestration. This isn't a new decision so much as an implementation of one already made: the pipeline's design (sequential stages, each pausing for human review before continuing) already matches a state machine with human-approval wait states, which is what Step Functions is for.

Explicitly rejected as a default: using Lambda uniformly for every stage. Lambda's 15-minute execution ceiling doesn't fit well with the video-generation stage, which calls long-running/async external APIs. Fast, short-lived text stages (research, script, shot list, prompts) remain reasonable Lambda candidates; the video-generation stage needs a different compute choice (see Consequences).

## Consequences

Fargate is a candidate for the video-generation stage's compute, given the Lambda timeout concern, but is not yet decided — needs more research before committing (tracked in architecture.md's open questions).

Other natural-fit candidates were identified but are deliberately not yet committed, to avoid adopting them before there's an actual need: S3 for artifact storage (previz stills, generated clips, final video), Secrets Manager or Parameter Store for provider API keys, and DynamoDB or RDS for tracking per-video pipeline state and review decisions. These get their own ADR each if and when they're actually adopted, following the same "why this, not that" reasoning as this one — the reasoning itself is treated as part of the interview-facing value of the project, not just the fact that AWS was used.
