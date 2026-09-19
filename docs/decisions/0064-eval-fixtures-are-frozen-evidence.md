# 64. An eval fixture is frozen evidence, or it is current — and it must say which

Date: 2026-09-19

Status: Accepted

Nothing superseded. Adds a rule to the measurement layer that no ADR
previously covered.

## Context

`evals/anchor_scene.json` is the fixture three eval scripts measure
against. It was frozen from `run_20260916-003118`, chosen because its
beats 1 and 2 had been rejected three times running for pose and
orientation errors that all pulled toward the character sheet's own
standing, camera-facing pose. Known failing cases, which is what those
experiments needed.

By the 2026-09-19 re-audit it was five ADRs out of date. It has no
`staging` key at all, predating [0049](./0049-per-character-staging-in-beats.md),
so `_parse_staging` takes its single-character fallback and the prompt
built from it has no `STANDS:`, no `SIZE IN FRAME:` and no `HIDDEN BY:`
line. Its `camera` field is the world-geometry style
[0044](./0044-camera-specified-at-a-granularity-models-follow.md) forbade,
and its occlusion is prose inside the action line, which
[0054](./0054-one-fact-per-field.md) split out.

Two things make this the exact failure `docs/playbook/repo-audit-brief.md`
exists to catch. It **degraded gracefully** -- the previous instance (0045
deleting `Beat.cinematography` while the fixture kept it) at least raised
`TypeError` on the next run; this one silently measured a prompt shape the
pipeline had not produced for weeks. And **CI could not see it**: the
smoke job runs the eval scripts' `--dry-run`s, which parse a fixture but
never build a prompt from one.

The tempting fix -- re-freeze from a current run -- destroys the fixture.
Its value is not that it is a scene plan; it is that it is *these* beats,
with a documented rejection history, and with arm results already recorded
under `evals/results/anchor-*` that are only comparable against it. Refresh
it and every one of those results becomes uninterpretable.

There is also less at stake than the staleness suggests. All three scripts
reading it answer questions that have since been closed:
`reference_anchor.py` asks whether the character reference flattens every
beat, and [0050](./0050-no-reference-images-by-default.md) turned
references off by default; `reviewer_reliability.py` asks whether
`previz_review` is a trustworthy grader, and
[0055](./0055-delete-the-automated-previz-reviewer.md) deleted it from the
pipeline. `blind_view.py` builds a human-scoring view over the runs those
two produced. None of them is feeding a live decision.

## Decision

A committed eval fixture is one of two things, and must declare which.

**Frozen evidence** carries `"_historical": true` and a `_note` saying
what it was frozen from, which ADRs it predates, and why refreshing it
would destroy something. `anchor_scene.json` is marked this way and is not
refreshed. Scripts reading it carry the same warning in their module
docstring, so the caveat reaches whoever runs one without opening the
JSON.

**Current** means anything else, and must match the prompt shape the
pipeline produces today.

`tests/test_eval_fixtures.py` enforces the split: every `evals/*.json`
holding a scene plan either declares itself historical with a non-empty
note, or is parsed with `load_scene_plan()` and asserted to carry beats
with `staging`, each entry having a non-empty `blocking` and
`size_in_frame`. The guard was checked by removing the marker and watching
it fail, because a guard over a single opted-out fixture would otherwise be
indistinguishable from one that passes vacuously.

No new current fixture is created. One gets written when an eval needs it,
and the guard is what keeps it honest from that day on.

## Consequences

The staleness is now stated in three places a reader will actually hit:
the fixture, the scripts that read it, and this ADR. What was silent is
loud, without paying the price of destroying the evidence.

Marking rather than deleting is a deliberate bet that frozen evidence stays
worth keeping. If a future session finds these scripts genuinely dead
rather than historical, deleting them is a separate decision -- and the
fixture goes with them, since nothing else reads it.

The obvious gap is that the guard checks *shape*, not *currency*. A fixture
written today passes forever, including after the next field is added. A
guard that could tell "carries staging" from "carries the fields today's
planner emits" would have to be regenerated alongside the schema, which is
the problem again one level up. Shape is what is cheaply checkable; the
ADR-number list in a historical note is what carries the rest.
