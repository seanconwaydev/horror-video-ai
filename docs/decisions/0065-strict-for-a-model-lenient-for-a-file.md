# 65. Strict for a model's answer, lenient for a file

Date: 2026-09-19

Status: Accepted

Narrows [0049](./0049-per-character-staging-in-beats.md) and
[0059](./0059-blocking-and-size-replace-frame-position.md): the
backward-compatibility fallbacks both ADRs relied on now apply only when
reading a stored plan, never to a live model response. Nothing is
superseded.

## Context

`load_scene_plan` is deliberately one parse path for two different jobs.
It reads a planning model's JSON answer, and it reads a plan back off disk
for `--fixture`, `--video-gen-from` and the eval harness. Sharing it was
right, and finding 4 of `docs/playbook/repo-audit-brief.md` exists because
the eval scripts once had their own parser and it rotted.

Two fallbacks live in that shared path, both added for archived plans:

- A beat with no `staging` becomes one entry for `characters[0]`, with
  empty `blocking`, `size_in_frame` and `occlusion`. Its stated reason is
  that this is how every beat rendered before 0041.
- A staging entry with no `size_in_frame` gets `""`.

Because the path is shared, both fire identically on a *fresh* model
response. A planner that ignores `staging` produces a beat whose prompt
has no `STANDS:`, no `SIZE IN FRAME:` and no `HIDDEN BY:` line, and the
run continues without saying anything. That image is then generated, paid
for, and put in front of a human to review, who has no way to tell it apart
from one whose staging was honoured.

This is the same failure as
[0064](./0064-eval-fixtures-are-frozen-evidence.md), one layer in. There,
a stale fixture degraded gracefully and so measured the wrong thing for
weeks. Here the degradation happens on the live path, where it costs money
per occurrence. The shape is identical: a compatibility shim doing its job
in a place that needs no compatibility, with graceful degradation hiding
it.

`size_in_frame` matters more than a defaulted field usually would. 0059
measured world placement without it rendering the right depth ordering in
**0 of 10** blind runs, and with it in **14 of 14**. An empty one is not a
small loss of detail; it removes the strongest placement instruction this
project has found.

That both fallbacks were reachable live was not obvious from reading
either ADR, and the existing test
`test_a_beat_without_staging_falls_back_to_the_first_character` asserted
the behaviour through `run_scene_planning_stage` -- the live path -- with
a docstring presenting it as correct. The rot was load-bearing and
tested.

## Decision

`load_scene_plan(data, *, strict=False)`. `_parse_scene_plan`, the only
caller holding a model's answer, passes `strict=True`; every archive
reader keeps the lenient default.

Under `strict`, two things that were quietly repaired now raise
`ScenePlanningError`: a beat with no `staging` entries, and a staging
entry with no `size_in_frame`. Both are decidable predicates about the
response's shape, which is what [0048](./0048-heuristic-gates-warn-rather-than-fail.md)
permits to fail a run -- neither is a judgement about whether the writing
is any good.

`occlusion` stays optional in both modes. After
[0060](./0060-threat-is-hidden-not-distant.md) and
[0061](./0061-the-threat-must-act-on-the-person.md) concealment is
conditional on what the beat is doing, so a character standing in the open
has nothing to put there. Requiring it would invent the field's value
rather than check it.

## Consequences

A planner that ignores `staging` now fails the run instead of producing a
degraded image. That is the intended trade: the run costs nothing at that
point, and the alternative was spending a generation and a human's review
on a beat that had already lost its instructions.

There is no retry around it. `run_scene_planning_stage` lets
`ScenePlanningError` propagate, as every stage does, so a model having a
bad moment ends the run rather than being asked again. If that turns out
to be common in practice, a retry belongs in the CLI where the human can
see it happen, not in the parser -- but it should be added because it was
observed, not in anticipation.

The fixtures under `tests/` that this broke -- one shared `_valid_payload`
helper, 47 failing tests from a single missing field -- were themselves
pre-0059. That the repo's own canonical test plan predated the field is
worth noting as evidence for how quiet this class of drift is: nothing was
failing, because the fallback was absorbing it.

`--fixture`, `--video-gen-from`, the three eval scripts and the `--mock`
path were each run end to end after this change, since the whole point is
that the two modes route differently and a wrong default would only show
up on one of them.
