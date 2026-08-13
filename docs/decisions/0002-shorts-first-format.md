# 2. Start with Shorts, not long-form

Date: 2026-08-12

Status: Accepted

## Context

The project could target long-form video (10+ minutes), YouTube Shorts, or both. Length also interacts with the pipeline itself, since video generation models produce short clips and length just changes how many scenes get produced, not the pipeline's structure. Separately, long-form video carries meaningfully higher viewer expectations (pacing variation, escalation, act structure) that go beyond simply writing more scenes — how to actually meet that bar is not yet understood.

## Decision

Three phases, all within this same project (a second project was considered and rejected — the pipeline doesn't structurally change with length, so there's no architectural reason to split repos):

1. Shorts only, while the pipeline and its review gates are still being calibrated against real output and real platform behavior. Target pacing: roughly 30–60 seconds (YouTube's Shorts max is 3 minutes, but 50–60 second Shorts substantially outperform anything under 10 seconds, per YouTube Shorts performance data).
2. Once Shorts are proven out, experiment with long-form as its own distinct effort — not a small extension of Shorts scripts, since the higher-expectations gap noted above is still unresolved.
3. Long-form becomes the primary artifact, with Shorts derived from it as a repurposing stage. This is the eventual steady state, not the starting point.

## Consequences

Faster, cheaper iteration while the pipeline is unproven. Long-form's "meets higher viewer expectations" problem is explicitly deferred, not solved — phase 2 needs its own design discussion when it starts, not just "write a longer script."
