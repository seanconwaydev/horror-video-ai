# Repo audit brief — documentation and instruction rot

Started 2026-09-16. A working brief for a fresh session, not a finished
audit: the findings below were established by inspection and are ready to
act on; the sections marked **open** still need doing.

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

## Findings ready to act on

### 1. Two planning rules contradict each other

`scene_planning.py`'s rule "Also vary the character's body position..."
ends with **"unless stillness is specifically the point of that beat."**
ADR 0049's new rule states that `"Stands"`, `"waits"` and `"watches"` are
states, not actions, and must never be a staging `action`.

For a horror stalker, "stillness is the point" is the most natural reading
a planner could make — so the escape hatch licenses exactly the T-posing
0049 exists to stop. The hatch predates 0049 and should have been removed
by it. **Fix: delete the clause**, or narrow it to the focal character
only.

### 2. A rule is stated twice

"Every beat must give a `staging` entry to EVERY character visible in that
shot" and "EVERY character in a beat gets a `staging` entry" are both in
the prompt, from different edits. Duplication costs attention and makes it
unclear which one a planner is obeying. Merge them.

### 3. Horror can never reach the anti-centering vocabulary

`_resolve_composition_mode` routes on `_CHAOTIC_COMPOSITION_KEYWORDS`
(surreal, absurd, dreamlike, ...). `horror` matches none of them, so a
horror run always gets `_STAGED_COMPOSITION_RULE` — "clarity beats
complexity" — which says nothing about framing. The only text in the whole
prompt mentioning off-center or asymmetric composition sits in
`_CHAOTIC_COMPOSITION_RULE`, permanently unreachable for this project's
actual genre.

This maps directly onto a real complaint: "composition, the girl just
simply being center-stage, lame framing." ADR 0049's `frame_position`
rule partly covers it, but the compositional vocabulary itself is still
gated away. Decide whether horror should get a third composition mode
rather than falling through to the default.

### 4. The eval harness is broken against saved plans, one way silently

`evals/reference_anchor.py:161` and `evals/reviewer_reliability.py:50`
rebuild beats with `Beat(**beat)` straight from a plan's JSON. After 0049:

- an **archived** plan raises `TypeError: unexpected keyword argument
  'character_ids'`
- a **current** plan constructs fine but leaves `staging` as a list of
  plain dicts, so the first `s.character_id` access raises
  `AttributeError` — it looks like it worked

The silent case is the dangerous one. These scripts need the same
`_parse_staging` treatment the real parser has. This is the
"context must round-trip every path" lesson again: the schema changed in
the stage and the parser, and the third consumer was missed.

### 5. Four configured stages have no code

`config/models.yaml` defines `narrative`, `narrative_review`, `shot_list`
and `video_prompts`. Zero code references each. They are pinned model
choices for stages 4–7, which are not built. Harmless, but they make the
config look like a description of the system when it is partly a wish
list. Either annotate them as unbuilt or remove them.

### 6. ADR supersession is only recorded forwards

A superseding ADR names the one it replaces; the replaced ADR says
nothing. So opening ADR 0024 — or grepping for "reference conditioning" —
returns a decision that reads as current and is not. This is a plausible
mechanical cause of the rot pattern above, and the cheapest fix in the
list: a one-line `Superseded by 00NN` under the old ADR's Status. It does
not violate ADR 0001's write-once rule, which is about not rewriting the
*reasoning*.

Known supersessions currently unmarked: 0006 and 0009 (by 0051), 0024 (by
0050, on the default), 0041 (by 0049), 0042 (amended by 0048), 0008 (its
refusal was deleted by 0051).

### 7. Doc links are unchecked

Five broken internal links existed; four were filename typos in recent
ADRs and are fixed. Nothing checks these, so they accumulate silently. A
link check is about fifteen lines of Python and could run in the test
suite.

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

**Prompt rules, tier and order.** 32 bullet rules now sit in the planning
prompt. Beyond the three findings above, each should be checked against:
is it still true, is it earning its place, and is it at the right tier?
The five tiers are instruction / routed instruction / schema constraint /
selection / capability, with ADR 0048's constraint that only a decidable
predicate may fail a run, and ADR 0049's lesson that *an instruction which
already exists and is losing should move tier rather than be sharpened*.

Two specific suspects: the lit-screen rules (a phone's brightness, hiding
a screen face from camera) read as instance patches from a specific
failure, and it is unclear they earn their place in horror. The
"character who doesn't belong to the historical setting (a modern-day
visitor, time traveler)" wardrobe rule is written for a historical
pipeline this project no longer is.

Order matters as much as content: in the failure ADR 0049 diagnosed, a
buried conditional clause lost to a more concrete, more emphatic rule
stated elsewhere. Which rule wins is partly a function of how specific and
how prominent it is.

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
