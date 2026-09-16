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

**This is now a convention with no enforcement.** A new ADR that
supersedes another still has to be written to update both ends by hand.

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

## Open — still to do

**Prompt rules, tier and order.** 33 bullet rules now sit in the planning
prompt — ADR 0052 added one. Each should be checked against: is it still
true, is it earning its place, and is it at the right tier? The five tiers
are instruction / routed instruction / schema constraint / selection /
capability, with ADR 0048's constraint that only a decidable predicate may
fail a run, and ADR 0049's lesson that *an instruction which already
exists and is losing should move tier rather than be sharpened*.

Three specific suspects: the lit-screen rules (a phone's brightness,
hiding a screen face from camera) read as instance patches from a specific
failure, and it is unclear they earn their place in horror; the "character
who doesn't belong to the historical setting (a modern-day visitor, time
traveler)" wardrobe rule is written for a historical pipeline this project
no longer is; and 0052's own new rule should be judged alongside the rest
rather than grandfathered in because it is recent.

Order matters as much as content: in the failure ADR 0049 diagnosed, a
buried conditional clause lost to a more concrete, more emphatic rule
stated elsewhere. Which rule wins is partly a function of how specific and
how prominent it is.

**Does previz honour a composed `camera` field?** ADR 0052 assumes the
planner writing composition into `camera` reaches the image. If previz
treats `camera` less faithfully than a character's `frame_position`, 0052
bought nothing and the fix belongs downstream. Unverified — it needs a
real run, and it is the fastest way to find out whether 0052 worked.

**Every doc claim against its code.** `docs/pipeline.md` still describes
the 12-stage vision, including a previz review whose job is stated as
catching anachronism — worth re-reading against ADR 0031 and against what
`previz_review` actually asks for now. `docs/playbook/failure-taxonomy.md`
has entries logged as open that may have been fixed since.

**Stale scratch directories.** `docs/backup/` holds four
`*-initial-thoughts.md` files from before the project started;
`docs/dry-runs/` holds one historical dry run. Both may be worth keeping
as history — but decide deliberately rather than leaving them ambiguous.

**`previz_review`'s future.** Measured as anti-correlated with human
judgement, and it still gates the retry loop. Rescope it, grade on a
scale, or drop it. This is a decision, not an audit item, but the audit
should not silently pass over it.
