# Open tasks

A resume queue for a fresh session. Each entry is meant to be actionable
without reading the rest of the conversation that produced it. Roughly in
priority order. None of the three is decided: 1 and 2 are the owner's
calls, and 3 needs a real run.

Finished entries are deleted rather than ticked off -- git history is the
record. Most recently done: broadening the CI trigger to every branch
(which is why five commits had shipped with no CI at all), and splitting
the 2,491-line `cli.py` into `cli/` -- six modules, one seam per commit,
with `app.py` left holding the argument parser and `main()` at 631 lines.
The coverage floor rose from 84 to 86 along the way.

One thing that split surfaced and did not fix: **142 of the repo's 198
uncovered statements are now `main()`**, and `main()` is not untested --
CI's smoke job runs it end to end offline every push. It is just not
*measured*, because coverage only runs under pytest. Running the smoke
job under `coverage run` and combining the two reports would make the
real number visible; nobody has decided whether that is worth doing.

Deeper context lives in [repo-audit-brief.md](./repo-audit-brief.md),
[eval-loop-plan.md](./eval-loop-plan.md) and
[prompt-rule-registry-scope.md](./prompt-rule-registry-scope.md).

---

## 1. Decide the prompt rule registry

Fully scoped in
[prompt-rule-registry-scope.md](./prompt-rule-registry-scope.md) (also
published at
<https://claude.ai/code/artifact/ba5f97fd-74b5-467b-8892-32135f77cc32>).

Two questions, both the owner's:

- Is rule ablation worth the refactor? If no, the cheaper honest path is
  deleting rules by judgement instead; the audit names two suspects (the
  lit-screen rules, the historical-visitor wardrobe rule).
- The judge is now settled (deleted, ADR 0055), so the "measure it with a
  broken judge" objection is gone — but there is also no automated scorer
  at all now, which changes what ablation would be measured *against*.
  Resolve that before starting.

## 2. Fix `previz.py`'s 2:1 prompt weighting

The owner's longest-standing complaint: the non-focal character is "just
standing there… a permanent issue since extra characters were added."

Known cause, unfixed: `_build_beat_prompt` emits `ACTION: {beat.action}`,
which restates the focal character's physicality — so a two-character
prompt describes the protagonist twice and the antagonist once before the
image model reads a word. ADR 0049 moved per-character physicality into
`staging`, but `beat.action` was left in the prompt alongside it.

Also unaddressed from the same diagnosis: no relational geometry exists
anywhere. Both characters get absolute `frame_position` values and nothing
states who is behind whom, how far apart, or where each is looking.
Deciding between "drop the duplicate `ACTION:` line" and "add a relational
field to `Staging`" is an ADR-sized call.

## 3. Validate ADR 0054 against a real run

[0054](../decisions/0054-one-fact-per-field.md) gave occlusion its own
field and its own `HIDDEN BY:` prompt line, on the evidence that
structured fields are obeyed while prose inside them is not. **Nothing has
been validated against an actual image.** The next horror run is the test:
does a dedicated occlusion field produce a genuinely half-hidden figure?

Run it interactively so it produces labels
([0053](../decisions/0053-human-judgements-are-recorded-as-data.md)); the
persistence fix in [0056](../decisions/0056-persist-work-in-flight.md)
means quitting partway no longer costs them. Compare against the 16
rejections already in `evals/results/` from 2026-09-17.

Watch for one risk 0052 flagged and 0054 inherits: the planner has copied
the composition rule's example phrasings near-verbatim before ("small and
low… from behind" in 2 of 4 beats). If `occlusion` text starts reading the
same way run to run, the menu has become a house style.
