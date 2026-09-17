# Scope: a prompt rule registry

Written 2026-09-17, not yet decided. A design to evaluate, not a plan in
progress. If accepted it becomes an ADR; if rejected, this file records why
so the idea is not re-proposed from scratch.

Also published as a formatted page:
<https://claude.ai/code/artifact/ba5f97fd-74b5-467b-8892-32135f77cc32>
(same content; this file is the canonical text).

## The problem, measured

`scene_planning.py` assembles its planning prompt from one 23-bullet
f-string plus five module-level chunks, three of which are routed by
genre/tone. Counting what those 23 bullets actually address:

| | |
|---|---|
| bullets in `_PLANNING_RULES_AND_SHAPE` | 23 |
| that name no field at all | **10** |
| that name more than one field | **7** |
| that touch camera or framing | **11** |
| that touch per-character action | **11** |
| that say "vary this between beats" | **4** (rules 7, 9, 10, 11) |

No rule has an id, a declared field, or an owning ADR. The consequence is
that nothing can answer three questions that now come up constantly:

- Does a rule for this concept already exist?
- Which ADR put this rule here, and is that ADR still current?
- Is this rule earning its place?

## Why this is the mechanical cause of the rediscovery loop

Every "oops, we already found this" in this project has the same shape: a
failure is observed, a rule is written for it, and a rule for the same
concept already existed somewhere the author did not look.

Three real instances:

- **ADR 0052 vs ADR 0044.** 0044 states `camera` carries shot size, height
  and orientation "and nothing else". 0052 instructed the planner to write
  a compositional choice into `camera`. Both rules define what one field
  contains. Every camera failure in the 2026-09-17 run traced to 0052's
  examples, and 0052 was written during the session whose stated purpose
  was finding contradictions between decisions.
- **Occlusion.** ADR 0049's threat rule already asked for "what
  specifically occludes it", inside `frame_position`. It lost in 4 of 4
  beats for a year before ADR 0054 moved it to its own field. Nobody knew
  the instruction was already there and already losing.
- **"Unless stillness is the point."** An escape hatch that licensed
  precisely the T-posing ADR 0049 was written to stop, sitting one rule
  above it.

None of these are findable by grep. All three are findable by a uniqueness
check over declared metadata.

## Proposed shape

Each rule becomes a record rather than a line in a string:

```python
Rule(
    id="frame-position-and-occlusion",
    defines="occlusion",          # this rule says what the field contains
    concept=Concept.FRAME_PLACEMENT,
    adr="0054",
    tier=Tier.SCHEMA_CONSTRAINT,
    applies_when=None,            # or a routing predicate
    text="- Give EVERY character a `frame_position` AND an `occlusion` ...",
)
```

Prompt assembly becomes: filter by `applies_when`, order, render. The
default output must be **byte-identical** to today's prompt — that is the
migration's safety property and it is testable.

## What becomes mechanically checkable

Honest about which of these a test can enforce and which only become
visible:

| Invariant | Enforceable? | Real defect it catches |
|---|---|---|
| At most one rule may `define` a given field | **Yes, a test** | ADR 0052 vs 0044 — both defined `camera` |
| Every rule names an ADR, and that ADR file exists | **Yes, a test** | orphan rules with no recorded reasoning |
| Every rule's ADR is not marked superseded | **Yes, a test** | a rule outliving the decision that created it |
| At most one rule per `Concept` | **Yes, a test** | the four separate "vary between beats" rules |
| Rule ids unique; every rule reachable | **Yes, a test** | dead rules behind a routing predicate nothing selects |
| Two rules asking one field to carry different kinds of fact | **No — only visible** | the occlusion case; needs a human reading a grouped view |

The last row matters: a registry does not detect semantic contradiction.
What it does is make "show me every rule that touches `frame_position`"
a one-line query instead of a careful read of 700 lines.

## What it enables that is impossible today

1. **Rule ablation in evals.** Turn one rule off by id and measure the
   difference against `scenes.yaml`. This is the only way to answer "is
   this rule earning its place", which the audit lists as open and which
   cannot currently be answered at all. It is also the strongest argument
   for the registry: it converts 28 untested assertions into 28 testable
   ones.
2. **Attribution in a failure.** When a beat renders wrong, the rules
   governing that field are enumerable, with their ADRs.
3. **Tier discipline as data.** ADR 0048's constraint (only a decidable
   predicate may fail a run) and ADR 0049's lesson (a losing instruction
   moves tier rather than being sharpened) become fields on a record
   rather than conventions someone has to remember.

## Cost and risk

- **Mechanical refactor of a ~700-line prompt.** The risk is silently
  changing prompt text, which would invalidate comparison against every
  recorded run. Mitigated by a golden-file test asserting the assembled
  default prompt is byte-identical before and after; the refactor is not
  done until that passes.
- **The `Concept` taxonomy is a judgement call and can itself rot.**
  Mitigated by keeping it a small closed enum, and by the one-rule-per-
  concept test forcing the question at the point a rule is added.
- **It is machinery.** A registry for 28 rules is defensible; for 8 it
  would not be. The justification is ablation, not tidiness.

## What this does not solve

It does not improve a single image. It does not detect semantic
contradiction. It does not decide whether any current rule is right — it
makes that decidable by experiment, which is a different thing.

It also does not touch `previz.py`'s prompt construction, which has its
own known unfixed defect: `ACTION:` restates the focal character, so a
two-character prompt describes the protagonist twice and the antagonist
once.

## Migration sequence

A real sequence, so numbered:

1. Add `Rule`, `Concept`, `Tier` and the registry alongside the existing
   string. Nothing uses it yet.
2. Golden-file test: capture today's assembled prompt for several
   genre/tone combinations.
3. Move rules into the registry in batches, re-running the golden test
   after each until the registry produces byte-identical output.
4. Delete the f-string. Add the invariant tests above.
5. Add `--without-rule <id>` to the eval harness. This is the payoff and
   should not be deferred — a registry that never ablates anything is
   bureaucracy.

Steps 1-4 are worthless without step 5, which is the argument for doing
all five or none.

## Open decisions

- **Is ablation worth the refactor?** If the answer is no, the honest
  alternative is to delete rules by judgement instead — cheaper, and the
  audit's open item already lists two suspects (the lit-screen rules, the
  historical-visitor wardrobe rule).
- **Does this come before or after the judge?** `previz_review`
  anti-correlates with human judgement, and ablation measured by a broken
  judge is worse than no measurement. Argument for doing the judge first;
  16 real labels now exist.
