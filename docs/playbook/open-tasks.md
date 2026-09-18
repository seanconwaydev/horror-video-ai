# Open tasks

A resume queue for a fresh session. Each entry is meant to be actionable
without reading the rest of the conversation that produced it. Roughly in
priority order. None of the four is fully decided: 1 needs scoping before
any code moves, 2 and 3 are the owner's calls, and 4 needs a real run.

Finished entries are deleted rather than ticked off -- git history is the
record. Most recently done: broadening the CI trigger to every branch,
which is what let five commits ship with no CI at all.

Deeper context lives in [repo-audit-brief.md](./repo-audit-brief.md),
[eval-loop-plan.md](./eval-loop-plan.md) and
[prompt-rule-registry-scope.md](./prompt-rule-registry-scope.md).

---

## 1. Finish splitting `cli.py`

It is now a package, `src/historical_video_ai/cli/`, being taken apart one
seam per commit so each step is reviewable and revertible. Every stage
module sits at 95-100% coverage; `cli/app.py` is at 75% and holds
effectively all of the uncovered code in the repo.

Be clear about what the split does and does not buy: moving code changes
no coverage number at all. The floor rises because a module small enough
to test on its own gets tested — which is what happened when `mocks.py`
came out (0% to 100%, floor 84 to 85).

| Seam | Lands in | Status |
|---|---|---|
| the `--mock` fakes | `cli/mocks.py` | done |
| run dirs, slugs, run-log read/write, fixtures | `cli/runlog.py` | done |
| review widgets (`_confirm`, `_review_*`, `_edit_item_fields`) | `cli/review.py` | next |
| `--video-gen-from` | `cli/video_gen.py` | after review.py, which it uses |
| research + fact-check + premise conflict | `cli/research_flow.py` | to do |
| the beat generation loop | `cli/beats.py` | to do |
| flags, arg parser, `main` | stays in `cli/app.py` | — |

Order is set by import direction, not by size: `video_gen.py` calls the
run-log helpers and the confirm prompt, so those seams come out first or
the two modules import each other.

One hazard to keep handling: `tests/test_cli.py` imports private names
from the module directly and monkeypatches them by string
(`"historical_video_ai.cli.app._project_root"` in three places). The test
file has to be split alongside each move rather than papered over with
re-exports from `__init__` — and that is the reason why. `monkeypatch.setattr`
on a string target raises when the attribute is absent, so a moved
function fails loudly; but a re-export keeps the old name alive, the patch
lands on a binding nothing calls, and the test passes while testing
nothing.

Two things to get right when renaming during a move, both of which went
wrong once and were caught by the test run: rename whole identifiers only
(a plain search-and-replace of `_load_fixture` rewrites
`test_load_fixture_reconstructs_...` into `testload_fixture_...`, which
pytest still collects), and remember that a module which imports a name
holds its own binding — patching the source module does not reach it.

## 2. Decide the prompt rule registry

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

## 3. Fix `previz.py`'s 2:1 prompt weighting

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

## 4. Validate ADR 0054 against a real run

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
