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

## Step 1 — capture judgements as data

**Status: code done, not yet committed as of this writing. See "State of
the work" below.**

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

Remaining:

- `evals/export_judgements.py` — walk `outputs/*/run_log.json` into one
  flat labelled dataset (JSONL): one row per candidate image with its
  prompt, beat, run metadata (model, style, genre, tone), whether the human
  kept it, and what `previz_review` said. This is the artifact that makes
  the capture usable; without it the data is just sitting in run logs.
- ADR 0053 recording the decision.
- Doc updates: `CLAUDE.md`, `docs/architecture.md`, and this file.

## Step 2 — fix the judge. This is the actual priority

`previz_review` is the AI-centric component the project already has, and it
is the single most broken thing in the pipeline: measured ranking four arms
in exact reverse of blind human judgement, rejecting 88% of images, and
**still gating the retry loop**. A judge that anti-correlates will, if used
for optimization, confidently drive the system toward images the owner
rejects.

- Build `evals/judge_agreement.py`: score `previz_review` against the
  human labels Step 1 now captures. Measure agreement, not just reversal —
  reuse `reviewer_reliability.py`'s approach, which already does repeated
  verdicts per image.
- Then decide its fate **with data**: rescope it to the one thing it may
  be good at, grade on a scale instead of accept/reject, or drop it. Write
  the ADR either way. The audit brief already lists this as open; this plan
  supplies the evidence it was missing.

Needs one real interactive run first, to produce labels. Any horror run
works; the owner runs these by hand.

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

The owner was asked whether to fix this by prompt restructure alone or by
adding relational data to the schema, and the question was overtaken by the
broader eval discussion. It is still open.

## State of the work

Branch `claude/repo-audit-fixes`, PR #75. Step 1's `cli.py` changes and
test updates are committed there; `export_judgements.py`, ADR 0053 and the
doc updates may not be — check `git log` on that branch and the checklist
above against what is actually present before assuming either way.
