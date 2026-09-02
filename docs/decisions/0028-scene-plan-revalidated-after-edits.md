# 28. ScenePlan is re-validated after human edits, not just LLM output

Date: 2026-09-02

Status: Accepted

## Context

Found by inspection, in the same audit that led to 0027: `_parse_scene_plan`
validates a beat's `location_id` against the set of defined locations, and
(as of this ADR) checks characters/locations for duplicate ids -- but only
once, against the LLM's raw output. `cli.py`'s `_review_scene_plan` lets a
human edit any field on any `Character`, `Location`, or `Beat`, including
`id` and `location_id` themselves, with no re-validation afterward.

Two concrete, silent failure modes follow directly from that gap:

- Editing a beat's `location_id` to a typo, or editing a `Location`'s own
  `id` after beats already reference the old one, makes the lookup
  (`locations_by_id.get(beat.location_id)`) silently return `None` --
  the beat generates with no setting text and no location-reference
  image conditioning, with nothing telling a human it happened.
- If an edit (or, in principle, the LLM's own output) ever produces two
  characters or locations sharing an `id`, `character_refs`/
  `location_refs` -- plain dicts keyed by id -- silently collide, and a
  lookup can end up returning the wrong item's reference image.

Both are the same shape as 0027's finding: something assumed to stay
consistent across a handoff was never actually re-checked at the next
point it mattered.

## Decision

Two validation functions already used by `_parse_scene_plan`
(`check_unique_ids`, `check_beat_location_references`, both exported from
`scene_planning.py`) are reused by `cli.py`'s review flow, not just the
initial parse:

- `_review_list_with_unique_ids` reviews a list of Characters (or
  Locations) item-by-item, then checks the *whole reviewed list* for a
  duplicate id. On a collision, it re-reviews the whole list rather than
  crash a review session the human just finished -- there's no way to
  know from a duplicate alone which of the two colliding items is "the
  wrong one," so asking the human to look at both again is the only
  correct move.
- Each beat's review loop re-checks its `location_id` against the
  already-finalized, reviewed locations immediately after that beat is
  edited, and loops that one beat back for another edit if it fails --
  targeted, since a bad `location_id` is always attributable to the one
  beat that has it.

Under `--yes`, no edit can happen at all (`_review_item` returns items
unchanged), so these checks can only ever fail there if `_parse_scene_plan`
itself already should have caught the same problem on the LLM's raw
output -- a safety net, not an expected path; a failure under `--yes`
raises rather than silently guessing a fix.

## Consequences

`cli.py` imports `ScenePlanningError`, `check_unique_ids`, and
`check_beat_location_references` from `scene_planning.py`. No new
dataclass fields, no config/CLI surface change. Both validation functions
are now genuinely shared, not duplicated logic between the parse step and
the review step.
