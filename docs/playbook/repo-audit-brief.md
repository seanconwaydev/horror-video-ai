# Repo audit brief — documentation and instruction rot

Started 2026-09-16. A working brief, not a finished audit: findings 1-7
have been acted on, and the sections marked **open** still need doing.

## Why this exists

Four decisions have now outlived the premise that justified them, and each
was found by a bug rather than by looking:

- a dead model constant survived a month past ADR 0037
- reference conditioning outlived its premise until ADR 0050
- the entire single-image previz flow stayed reachable-*looking*, tests and
  all, until ADR 0051
- `CLAUDE.md` claimed video generation went through litellm long after it
  called Replicate directly

The shape is always the same: the code or doc is internally consistent, its
tests pass, and nothing points at it until something else breaks nearby.
Grepping for bugs will not find these. Only reading a claim against the code
that implements it will.

## Findings — all closed

### 1. Two planning rules contradicted each other — fixed

`scene_planning.py`'s "vary the character's body position" rule ended with
**"unless stillness is specifically the point of that beat."** ADR 0049
states that `"Stands"`, `"waits"` and `"watches"` are states, never a
staging `action`. For a horror stalker "stillness is the point" is the
most natural reading a planner could reach for, so the hatch licensed
exactly the T-posing 0049 exists to stop.

A second hatch of the identical shape was found next to it: "let the
subject sit off-centre **unless centring them is the point**". Both
clauses are deleted. `test_planning_rules_carry_no_unless_its_the_point_escape_hatches`
guards against reintroduction.

One conditional deliberately survives, in the horror-tone rule: "unless
the scene's own tone explicitly calls for something else (comedic,
deadpan, ...)". It reads the same but isn't — it branches on `tone`, a
real input, not on the planner's own judgement of what "the point" is.
Worth re-reading during the rule-tier sweep below, not worth deleting
blind.

### 2. A rule was stated twice — fixed

Coverage ("EVERY character visible gets a `staging` entry") appeared in
two rules from different edits. It now appears once, in the rule that
also says who counts as visible and what an unstaged character costs. The
second rule keeps only what it uniquely says: what an entry's `action`
has to be.

### 3. Horror could not reach the composition vocabulary — fixed, ADR 0052

`_resolve_composition_mode` routes on `_CHAOTIC_COMPOSITION_KEYWORDS`
(surreal, absurd, dreamlike, ...). `horror` matches none, so a horror run
always got `_STAGED_COMPOSITION_RULE` — "clarity beats complexity", which
says nothing about framing.

**The original finding overstated this and the correction matters.** ADR
0049's `frame_position` rule does say "let the subject sit off-centre",
and the threat rule does say "a background corner, a frame edge, never
centered" — both reachable by horror. Those are about *where a character
is placed*. What was unreachable is the geometry of the shot itself:
foreground occlusion, the location's own lines, what the empty part of
the frame is for.

Fixed by [ADR 0052](../decisions/0052-composition-vocabulary-is-unconditional.md):
`_BASE_COMPOSITION_RULE` is unconditional and the two mode rules layer on
top of it. A third horror-keyed mode was considered and rejected — it
would have left the same trap set for the next genre matching no keyword.

### 4. The eval harness was broken against saved plans — fixed

Worse than first written. `evals/reference_anchor.py` and
`evals/reviewer_reliability.py` rebuilt beats with `Beat(**beat)`, which:

- raised `TypeError` on the committed `anchor_scene.json` **today**, on a
  `cinematography` key whose field ADR 0045 deleted — so both scripts were
  already dead, not merely at risk
- would have left `staging` as plain dicts on a current plan, failing at
  the first `s.character_id` rather than at parse time

Both now call `load_scene_plan()`, the real parser, newly made public for
exactly this. It ignores unknown keys and builds real `Staging` objects,
so both failure modes are gone and there is one parse path instead of
three. The dead `cinematography` key is stripped from the fixture.

The fixture's beats are otherwise untouched, so the arm results already in
`evals/results/` stay comparable. It carries no explicit `staging`, so it
takes the documented single-character fallback and gets an empty
`frame_position`. Giving it real 0049-shaped staging would be better
coverage and would invalidate those recorded results — a deliberate call
someone should make, not a silent one.

### 5. Four configured stages have no code — no change needed

`config/models.yaml` defines `narrative`, `narrative_review`, `shot_list`
and `video_prompts` with no code referencing them. The config already
labels them: "Deferred stages (docs/decisions/0006): skipped for v1, not
deleted -- these stay as placeholders ... revisit when these stages are
actually built." The finding was already satisfied when it was written.

### 6. ADR supersession was only recorded forwards — fixed

A superseding ADR named the one it replaced; the replaced ADR said
nothing, so opening ADR 0024 returned a decision that read as current.

Sixteen ADRs now carry a backlink under their Status line: 0006, 0008,
0009, 0011, 0012, 0017, 0020, 0022, 0023, 0024, 0029, 0033, 0034, 0036,
0041 and 0042. The map was rebuilt by reading every superseding ADR's own
Status block, which turned up ten the original list had missed, including
partial and implementation-only supersessions. This does not violate ADR
0001, whose write-once rule protects the reasoning.

`tests/test_adr_supersession.py` now enforces this: an ADR whose Status
block declares it supersedes, amends or voids another fails unless that
other ADR's Status block links back. It reads 19 forward edges across the
set today. Only Status blocks are checked -- an ADR discussing a
supersession in its Context prose isn't making the claim this enforces.

### 7. Doc links were unchecked — fixed

`tests/test_docs_links.py` checks every relative markdown link in the
repo, one test per file. It found five more broken links on its first run,
all in ADR 0050, which merged after this brief was first written. In every
case the ADR *number* cited was right and only the filename was wrong, so
the filenames were corrected and no citation was repointed.

## Verified clean — do not re-check

- `README.md` leads with ADR 0031's goal framing; current.
- `.env.example` covers every key actually needed, `REPLICATE_API_TOKEN`
  included. The provider keys look unread by `src/` only because litellm
  reads them from the environment itself.
- Every `raise` site across all six stage modules has a decidable
  predicate (missing key, wrong type, enum, range, file existence,
  response shape). The one judgement-call gate was deleted with the
  single-image flow. No further ADR 0048 work is outstanding.

## Second pass, 2026-09-19 — findings

A re-audit run after the `cli.py` split and the 0057-0062 sequence. Seven
findings; the first is the serious one and is the same failure this
document was created for.

### 1. `evals/anchor_scene.json` is five ADRs out of date, and degrades silently

The fixture three eval scripts measure against (`reference_anchor.py`,
`reviewer_reliability.py`, `blind_view.py`) was frozen from
`run_20260916-003118` and has **no `staging` key at all**. It predates
[0049](../decisions/0049-per-character-staging-in-beats.md).

`_parse_staging` therefore takes its graceful fallback -- one entry for the
first character with empty `blocking`, `size_in_frame` and `occlusion` --
so the prompt those evals build has no `STANDS:`, no `SIZE IN FRAME:` and
no `HIDDEN BY:` line. Its `camera` field reads "Wide 24mm from a low
position on the floorboards in the far corner beside the radiator, looking
back across the room toward the door; Wren lies in the right mid-ground in
full profile", which is precisely the world-geometry camera
[0044](../decisions/0044-camera-specified-at-a-granularity-models-follow.md)
forbade. Its occlusion is prose inside the action line, which
[0054](../decisions/0054-one-fact-per-field.md) split out.

So the measurement layer is measuring a prompt shape the pipeline has not
produced since 0044, 0049, 0054, 0059 and 0061. Any conclusion those
scripts reach is about something else.

This is the *silent* version of the failure that prompted this document:
the previous instance (0045 deleting `Beat.cinematography` while the
fixture kept it) at least raised `TypeError`. This one degrades gracefully
instead, which is worse. **CI does not catch it** -- the smoke job runs
`--dry-run`, which parses the fixture but never builds a prompt from it.

Deciding what to do needs care rather than a quick fix. Regenerating the
fixture from a current run destroys the thing it exists to be: a frozen
anchor whose beats were rejected for specific, known reasons. The options
are to re-freeze and accept the loss of that history, to keep it and mark
the affected evals as historical, or to add a second current fixture
alongside it. A smoke assertion that a fixture's beats carry staging would
have caught it either way.

### 2. A workaround the documented discovery grep cannot find

`CLAUDE.md` states that every upstream workaround carries a greppable
`WORKAROUND(<url>):` marker so a later session can list them all with
`grep -rn "WORKAROUND(" src/`. That grep returns exactly one hit.
`stages/previz.py:176` carries a second one, written `TODO(WORKAROUND):`,
which the documented command cannot match -- and its issue was never filed,
so there is no URL to check against either. The workaround itself (reading
reference images as bytes because litellm's Gemini `image_edit` raises on a
bare `Path`) is real and still applied.

### 3. litellm is pinned two minor versions behind the one the docs verify against

`uv.lock` pins litellm 1.98.0. `CLAUDE.md` documents the moderation
workaround as "confirmed still present in litellm 1.100.1 (latest released
as of 2026-09-14)". So the project verified a workaround against a version
it does not run, and finding 2's `Path` workaround was confirmed against
1.98.0's source and never re-checked. The repo's own rule is to look for a
released fix before keeping a workaround; that rule has not been applied to
either of them since the pin.

### 4. `config/models.yaml` pins models for four stages that have no code

`narrative`, `narrative_review`, `shot_list` and `video_prompts` are stages
5-7 and 10-12, which `CLAUDE.md` says are not built. Their pins cannot be
validated by `test_real_project_config_is_valid`, which only asserts that
stages *with* code are present. A pinned model for a stage nobody will
write for months is a pin that quietly goes stale, or names a model that
has been retired by the time it matters.

### 5. The `cli` split promoted module-internal helpers to public names

`review_list_with_unique_ids`, `beat_review_context`, `choose_candidate`,
`resolve_recorded_path` and `record_video_gen_result` lost their leading
underscore during the split but are each called only inside their own
module. The rename was correct for names that cross a module boundary and
was applied too broadly. Cosmetic, but it overstates each module's surface
to the next reader.

### 6. `docs/pipeline.md` still describes the deleted previz reviewer

Stage 8 reads: "Before you ever see a still, it gets one automated
adversarial pass: an independent model reviews the *generated image
itself*." That pass was deleted by
[0055](../decisions/0055-delete-the-automated-previz-reviewer.md). The same
paragraph frames the stage's purpose as catching "anachronistic imagery",
which [0031](../decisions/0031-goal-is-quality-video-not-historical-accuracy.md)
deprioritised. Flagged in this document's first pass and still open.

### 7. `CLAUDE.md` does not describe the `cli/` package

Its Architecture section documents the stage-module layout in detail and
says nothing about the CLI now being six modules with a deliberate import
direction (`app` -> `beats`/`research_flow`/`video_gen` -> `review`/`runlog`
-> `mocks`). A session told to add a CLI feature has no guidance on which
module it belongs in, which is how a 2,491-line `cli.py` happened once.

## Open — still to do

**Prompt rules, tier and order.** 33 bullet rules now sit in the planning
prompt — ADR 0052 added one. Each should be checked against: is it still
true, is it earning its place, and is it at the right tier? The five tiers
are instruction / routed instruction / schema constraint / selection /
capability, with ADR 0048's constraint that only a decidable predicate may
fail a run, and ADR 0049's lesson that *an instruction which already
exists and is losing should move tier rather than be sharpened*.

Three specific suspects were named here. All three were resolved on
2026-09-18 by [ADR 0058](../decisions/0058-delete-rules-by-judgement-not-ablation.md):
the two lit-screen rules and the historical-visitor wardrobe rule are
deleted, and 0052's own rule is deliberately kept, since deleting it
unmeasured would be the same mistake in the other direction. The prompt is
31 rules. The remaining 31 have still not been audited one by one.

Order matters as much as content: in the failure ADR 0049 diagnosed, a
buried conditional clause lost to a more concrete, more emphatic rule
stated elsewhere. Which rule wins is partly a function of how specific and
how prominent it is.

**Does previz honour a composed `camera` field?** ADR 0052 assumes the
planner writing composition into `camera` reaches the image. If previz
treats `camera` less faithfully than a character's placement fields, 0052
bought nothing and the fix belongs downstream. Still unverified for
`camera` specifically — but the placement side is now measured:
`evals/blocking_space.py` found that a character's stated *apparent size*
is obeyed reliably while world-space distance is not obeyed at all
([ADR 0059](../decisions/0059-blocking-and-size-replace-frame-position.md)),
so "does the model act on this field" clearly varies field by field rather
than holding uniformly.

**Every doc claim against its code.** `docs/pipeline.md` still describes
the 12-stage vision, including a previz review whose job is stated as
catching anachronism — worth re-reading against ADR 0031 and against what
`previz_review` actually asks for now. `docs/playbook/failure-taxonomy.md`
has entries logged as open that may have been fixed since.

**Stale scratch directories.** `docs/backup/` holds four
`*-initial-thoughts.md` files from before the project started;
`docs/dry-runs/` holds one historical dry run. Both may be worth keeping
as history — but decide deliberately rather than leaving them ambiguous.

**`previz_review`'s future — closed.** Measured against 78 images the
owner had already ruled on: 56% agreement, against 79% for accepting
everything, and it rejected 31 of the 62 images the owner kept. Deleted by
[ADR 0055](../decisions/0055-delete-the-automated-previz-reviewer.md). The
earlier "exact reverse" claim measured a different task (ranking by
quality) and was overstated; on accept/reject it is weakly positive but
still worse than no gate.
