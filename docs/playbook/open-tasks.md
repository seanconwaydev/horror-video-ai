# Open tasks

A resume queue for a fresh session. Each entry is meant to be actionable
without reading the rest of the conversation that produced it. Roughly in
priority order. Neither is decided: 1 is an ADR-sized schema call, and 2
needs a real run.

Finished entries are deleted rather than ticked off -- git history is the
record. Most recently done: dropping the duplicate `ACTION:` line
([0057](../decisions/0057-drop-the-duplicate-action-line.md)), deleting
three prompt rules by judgement rather than building the ablation
registry ([0058](../decisions/0058-delete-rules-by-judgement-not-ablation.md)),
broadening the CI trigger to every branch
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

## 1. Add relational geometry to `Staging`

Half of the 2:1 weighting fix is done
([0057](../decisions/0057-drop-the-duplicate-action-line.md) dropped the
duplicate `ACTION:` line). The other half of the owner's "just standing
there" complaint is a schema gap: both characters get an absolute
`frame_position` and **nothing anywhere states who is behind whom, how
far apart they are, or where each is looking.**

The failure taxonomy already names this shape as the clearest instance of
this project's worst pattern -- a prose rule instructing a model to do
something the data model cannot express. The composition rule asks for
characters who react to each other; `Staging` has no field in which a
planner could say so.

Bigger than 0057: a new field on `Staging`, the planner prompt that fills
it, the parser, and the eval fixtures. ADR-sized.

## 2. Validate ADR 0054 and 0057 against a real run

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
