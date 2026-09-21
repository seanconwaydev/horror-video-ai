# Plan: close the evaluation loop

Started 2026-09-16. A handoff brief for a fresh session — written to be
picked up with no other context. Companion to
[repo-audit-brief.md](./repo-audit-brief.md), which covers documentation
rot; this one covers the AI-engineering side.

## The bar

The project owner's stated goal for this work: get the AI side of the
project to "a 9/10 at least, impressed by the solid practices and
engineering." Learning modern AI-system design by building this project is
one of the reasons the project exists, so the evaluation harness and the
measurement loop are primary deliverables, not scaffolding. If the
evaluation is the worst thing in the repo, it is the top priority.

## The finding this plan exists to fix

**The practices are already here. They are not wired to any decision.**

`evals/` already contains, and this is genuinely good work:

- `scenes.yaml` — a frozen golden dataset of five *different* horror
  sub-types, with "edit only to ADD scenes, so results stay comparable"
  written into the file
- `run_eval.py` — blind A/B with randomised per-scene slot assignment, a
  separate `key.json`, score-first-reveal-after
- automatic refusal counting, because an empty-but-successful response is
  exactly how a silent content block presents itself
- per-cell moderation flagging
- `reviewer_reliability.py` — a judge-reliability study that measured
  `previz_review` and caught it ranking in **exact reverse** of blind human
  judgement while rejecting 88% of images

And yet:

- **15 recorded runs under `evals/results/`. Exactly one file in the whole
  tree contains human scores** (`reviewer_reliability.json`), and that one
  was measuring the reviewer, not the images. Every blind scoring sheet
  `run_eval.py` produced was left unfilled.
- The eval harness was **dead** — `Beat(**beat)` raised `TypeError` on its
  own committed fixture, on a field ADR 0045 deleted. Fixed 2026-09-16.
  Nobody noticed because nobody ran it.
- A gemini vs flux-dev vs flux-schnell image-model bake-off **already ran**
  on 2026-09-15. The images are still sitting in
  `results/20260915-223701/` unscored.

So there are two parallel systems: a rigorous one that generates images and
drops the judgement on the floor, and an ad-hoc one — a human in a terminal
eyeballing candidates — that drives every actual decision. Infrastructure
nobody runs decays silently, exactly like the docs did.

The sequencing insight that orders everything below: **an LLM-as-judge and
any prompt-optimization loop are functions that take human preference data
as an argument.** `previz_review` cannot be fixed, rescoped or honestly
dropped without labelled data to calibrate it against, and nothing in this
repo records what a human actually thinks of an image. Capturing
judgements is not deferring the AI-centric work; it is the only thing that
unblocks it.

## Step 1 — capture judgements as data — DONE

Recorded as [ADR 0053](../decisions/0053-human-judgements-are-recorded-as-data.md).

The gap: `cli.py` recorded `prompt_used` **only on the accepted branch**.
Every *rejected* beat — the most informative label — discarded the exact
prompt that produced it. Since `_build_beat_prompt` changes over time, a
beat's stored fields cannot reconstruct the prompt after the fact, so the
label was unattributable.

Done:

- `_beat_review_context()` and `_choose_candidate(..., context=...)` print
  the beat's camera and per-character staging **at the candidate prompt**.
  Previously that text was last shown at scene-plan review, hundreds of
  lines up the scrollback, so checking whether a render honoured the plan
  meant scrolling back every time — the one judgement the loop exists to
  collect was the one the interface made hardest to make.
- Every attempt records each candidate as
  `{path, prompt_used, kept}`.
- `human_choice` (which candidate, or `"none"`).
- `human_action` (`a`/`r`/`e`/`f`/`g`) and the `feedback` free text, which
  is a human-authored correction naming exactly what the render got wrong
  — the highest-value text in the loop and previously unrecorded.
- Attempts now accumulate **across retry cycles**. They were reassigned per
  cycle, so choosing (e)dit or (f)eedback silently discarded the rejected
  attempt that prompted it. The images survived; the judgements did not.
  `tests/test_cli.py` previously asserted this discard as intended.

- `evals/export_judgements.py` flattens run logs into one labelled JSONL
  dataset, one row per candidate image, carrying the siblings it was shown
  against. Verified end to end against a real `--mock` run.
- The dataset itself is committed at `evals/judgements.jsonl`, written by
  `--update-dataset`, which merges rather than overwrites -- `outputs/` is
  gitignored and gets pruned, so an overwrite would delete every label
  whose images are gone ([ADR 0074](../decisions/0074-judgements-are-committed-and-merged.md)).
- The run log now records `style` too.

Two bugs were caught by running the export against real data rather than
reasoning about it, and both are worth knowing about:

1. Pre-0053 runs store `candidates` as a list of bare path strings. A
   "is the list empty" guard does not catch a wrong-*shaped* list — this is
   the same round-trip failure as the audit brief's finding 4. The export
   now checks the shape and skips those runs.
2. `previz_review` runs **once per attempt, on the kept candidate only**.
   The first version of the export copied its verdict onto every sibling,
   counting images the judge never saw as agreements or disagreements —
   which would have silently poisoned step 2, the one study this dataset
   exists for. Verdicts are now attached only to the scored image.

**The one thing left in step 1: it has produced no real data yet.** The
capture is verified against `--mock`, not against a live interactive run.
One horror run by the owner turns it on.

## Step 2 — the judge: settled, deleted (ADR 0055)

`evals/judge_agreement.py` scored `previz_review` over 78 images the owner
had already ruled on (62 kept, 16 rejected), reusing images and prompts on
disk so nothing was generated.

- agreement with the owner: **56%**
- "always accept" baseline: **79%**
- it rejected **31 of the 62** images the owner kept

So it discriminated slightly (+31% separation, not inverted) but lost to
the trivial baseline by 23 points. Its concerns were also being injected
into the next attempt's prompt as "Fix this: ...", so a signal wrong 44%
of the time was steering regeneration.

Deleted in [ADR 0055](../decisions/0055-delete-the-automated-previz-reviewer.md).
`run_previz_review_stage` survives for `evals/` only. Results kept at
`evals/results/judge-agreement-20260917.json`.

**Caveat that matters for any rebuild:** the 62 positives are least-bad
picks, not endorsements -- the owner rejects nearly everything at present.
A rebuilt judge should be measured on whether its *observations are
factually true of the image*, which needs no quality label, rather than on
whether its verdict predicts a choice.

## Step 3 — swap the image model, judged on the harness

The owner's own read: "previz needs a replacement… a different image model
that better suits our needs, isn't as rigid." Note that previz itself
**cannot be removed** — Wan 2.2 is image-to-video, and
`stages/video_generation.py` hard-fails without an image file — so this is
a model swap, not a stage deletion.

- `run_eval.py` + `scenes.yaml` are built for exactly this and have
  already run three models once. Score the existing images before paying
  for new ones.
- **Missing input:** the owner and a previous session researched Replicate
  image-model options. That research is *not in the repo* — the only
  traces are `architecture.md:79` ("Flux via Replicate, ~$0.03-0.05/image")
  and `:103` ("Kling, Runway, and a real quality bake-off against
  gpt-image-1-mini are all still untried"). Ask the owner to paste it, or
  redo it. Losing it is the audit's own thesis landing on this project.

## Step 4 — the prompt rule sweep

The audit brief's open item (33 rules, tier and order). Deliberately
**after** the model swap: model choice dominates prompt tuning, and tuning
33 rules against a model that is about to be replaced is wasted effort.

## Known open question about ADR 0052

ADR 0052 (composition vocabulary made unconditional) works — a real horror
run on 2026-09-16 produced camera fields carrying the new vocabulary. It
may work *too* literally: the planner quoted the rule's four example
framings nearly verbatim, and "small and low… seen from behind" appeared in
2 of 4 beats. Watch for the menu becoming a house style, which cuts against
the owner's standing preference for stylistic range across runs.

## Separately established, don't re-derive

From the same 2026-09-16 run, the two-characters-ignoring-each-other
failure is **no longer a planning failure** — the plan contained real
cause-and-effect ("leans its whole torso out from behind the concrete
column to keep her in view"). It is lost in `previz._build_beat_prompt`,
for three structural reasons:

1. `ACTION:` restates `beat.action`, which is the focal character's
   physicality again — so the protagonist is described twice and the
   antagonist once, weighting the prompt 2:1 before the model reads a word.
2. The relationship is an *instruction* ("must react to each other"), while
   everything else in the prompt is a *fact*. ADR 0049's own lesson is that
   an instruction which already exists and is losing should move tier
   rather than be sharpened. This one is losing.
3. No relational geometry exists anywhere. Both `frame_position` values are
   absolute; nothing states who is behind whom, how far apart, or where
   each is looking.
   *(Points 1 and 3 are resolved: [ADR 0057](../decisions/0057-drop-the-duplicate-action-line.md)
   removed the duplicate ACTION line, and [ADR 0059](../decisions/0059-blocking-and-size-replace-frame-position.md)
   replaced `frame_position` with `blocking` -- which is relative to the
   camera and the other characters -- plus `size_in_frame`. Gaze was
   deliberately left without a field; see 0059 for why.)*

The owner was asked whether to fix this by prompt restructure alone or by
adding relational data to the schema, and the question was overtaken by the
broader eval discussion. It is still open.

## State of the work

Branch `claude/repo-audit-fixes`, PR #75. **Step 1 is complete and
committed**: the `cli.py` capture, `evals/export_judgements.py`, ADR 0053,
and this file. 478 tests pass, ruff clean.

**Pick up at step 2.** It is blocked on one thing only: a real interactive
run to produce labels, which the owner does by hand. The exact next
actions, in order:

1. Owner does one horror run (any scene; they run these themselves).
2. `uv run python evals/export_judgements.py` — confirm rows appear and
   the summary's agreement line is populated.
3. Build `evals/judge_agreement.py` per step 2 above, and write the ADR
   that decides `previz_review`'s fate on the evidence.

Do not start step 3 or 4 before step 2 lands. The ordering argument is in
each step's own section and it is the whole point of the plan.
