# 63. `models.yaml` pins only stages that have code

Date: 2026-09-19

Status: Accepted

Narrows [0003](./0003-model-configuration-via-litellm.md) on *which*
stages get a pinned model. 0003's rule -- that a stage's model is a hand-
edited pinned string, never routed or substituted -- is untouched.

## Context

`config/models.yaml` carried pins for `narrative`, `narrative_review`,
`shot_list` and `video_prompts`: stages 5-7 and 10-12 of
`docs/pipeline.md`, none of which have a module. All four still read
`anthropic/claude-sonnet-5` from the original scaffolding. A comment
explained them as placeholders, "so the full pipeline vision still has a
config slot waiting for it."

The re-audit of 2026-09-19 flagged them, and the argument against them is
not tidiness. It is that `test_real_project_config_is_valid` asserted only
that every stage *with* code was present -- a subset check -- so those
four pins were the one part of this file nothing could validate. A pin
nobody can validate is a pin that goes stale quietly.

This project has already been bitten by exactly that. `gemini-2.5-flash`
was retired by Google underneath a live pin and produced a real 404, "no
longer available to new users" ([0018](./0018-fact-check-model-retired.md)).
That was a stage with code, so it failed loudly on the next run. The same
retirement under `shot_list` would surface months later, during the first
run of a stage someone was in the middle of writing, framed as a bug in
the new code.

The placeholder also carried no information. Four identical
`anthropic/claude-sonnet-5` strings from scaffolding are not a decision
about which model suits narrative generation; they are the absence of one,
written in a syntax that looks like its presence. Whoever builds stage 5
will choose a model then, from the models that exist then.

## Decision

`config/models.yaml` defines a stage if and only if code reads it. The
four deferred blocks are deleted.

`test_real_project_config_is_valid` now asserts set equality rather than
`issubset`, so the config cannot drift in either direction: a stage whose
module lands without a pin fails, and a pin for a stage nobody has written
fails too. Adding a stage means adding its block and its name to that
test's `expected_stages`, in the same change as the module.

## Consequences

The deferred stages are still fully described -- `docs/pipeline.md` covers
all twelve, and `CLAUDE.md` says which are unbuilt. Nothing about the
vision is lost by not pre-pinning a model for it.

The cost is one extra step when a deferred stage is finally built: add its
block to `models.yaml` before the first run, or `load_stage_configs()`
raises `ConfigError`. That is the fail-loud behaviour 0003 wanted, arriving
at the moment someone is actually looking at that stage.

A second-order effect worth naming: the exact-match assertion makes the
config file a reliable answer to "which stages exist?", which the subset
check never was.
