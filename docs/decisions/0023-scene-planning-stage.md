# 23. Scene-planning stage: characters, locations, and beats before any image generation

Date: 2026-09-01

Status: Accepted

## Context

Every real multi-beat scene built so far (Agent Voss, the Pompeii influencer
scene) required a human (in practice, this session's Claude instance)
manually writing each beat's description, manually deciding which beats
share a location, and manually re-describing a location's specific
architecture in each beat's text -- with no code support for any of it.
This is exactly the deferred work `docs/decisions/0006` named: stages 4
(narrative/script), 6 (shot list), and 7 (per-scene prompts), skipped for
v1's original single-image scope, now needed because this project is
routinely producing multi-beat scenes by hand.

Two concrete lessons from the Pompeii experiments make the required output
shape clear (see `docs/playbook/video-generation-prompting.md`):
location consistency needs its own reference, generated once and reused
across every beat set there, separate from character consistency -- so
planning has to produce **locations** as a distinct concept from
**beats**, not just a flat list of shot descriptions. A scene, in the
standard filmmaking sense, is one location's worth of continuous beats;
this project's shot-list stage needs to think in those terms.

## Decision

New stage, `stages/scene_planning.py`, inserted between fact-check and
previz. One LLM call (`deepseek/deepseek-v4-flash` pinned as the starting
placeholder in `config/models.yaml`'s new `scene_planning` entry -- same
"unblock the stage, compare rigorously later" status as previz's own model
and every other stage placeholder in this project) takes the verified
fact sheet and produces a `ScenePlan`:

- `Character` -- the playbook's CHARACTER block fields (face/build, hair,
  wardrobe signature/flexible, distinguishing detail).
- `Location` -- the playbook's new LOCATION block fields (architecture,
  fixed props, ambient light) -- the text description that will later
  drive generating that location's one canonical reference image
  (docs/decisions/0024, previz's image-conditioning capability).
- `Beat` -- the 7-part shot fields (subject, action, camera, lighting,
  style, audio) plus duration, tagged with which `Location` it belongs to.
- `ScenePlan` -- the three lists together; the reviewable artifact this
  stage produces.

**Review gate:** a per-item accept-or-edit loop, reusing `cli.py`'s
`_resolve_flags` pattern (already proven for fact-check flags) rather than
0008's single-suggestion premise-conflict pattern -- a `ScenePlan` is
multiple independently-reviewable items across three lists, not one field
needing a single correction. Reviewed in a fixed order -- Characters, then
Locations, then Beats -- and strictly linear: once Locations are approved,
Beats are reviewed against that already-finalized set, with no going back
to reopen an earlier list. This is a deliberate v1 simplification (matches
this project's standing preference for the simplest mechanism that solves
the observed problem, revisited only if it proves insufficient), not an
oversight.

An edited Character/Location/Beat is **not** re-verified through another
LLM pass, unlike 0008's premise-conflict correction. 0008 re-verifies
because it's checking historical plausibility -- a factual claim. A
character's hairstyle or a location's lighting description is creative
content, not a claim to verify; a human's edit becomes final as typed.

## Consequences

`config/models.yaml` gains a `scene_planning` entry; `tests/test_config.py`'s
`expected_stages` updated to match. `cli.py`'s `main()` flow gains a stage
between fact-check and previz, plus the new three-list review loop.
Previz itself doesn't consume `ScenePlan` yet -- that's
[decisions/0024](./0024-previz-image-conditioning.md), previz gaining the
ability to take a character reference and a location reference as actual
generation inputs, which is what makes a `Location`'s text description
matter beyond documentation. Until 0024 lands, this stage produces a
reviewed plan that isn't yet wired into image generation.

Explicitly out of scope here, raised but not resolved: whether the
axis-of-action/screen-direction consistency question (`docs/architecture.md`'s
open questions) needs to be checked at planning time, and the
`--overall-style` genre-preset idea (same section) -- both real, both
future work, neither blocking this stage's initial shape.
