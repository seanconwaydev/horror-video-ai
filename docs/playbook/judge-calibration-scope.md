# Scope: a calibrated preference judge

Written 2026-09-21, not yet decided. A design to evaluate, not a plan in
progress. If accepted it becomes an ADR; if rejected, this file records
why so the idea is not re-proposed from scratch. Same status and purpose
as [prompt-rule-registry-scope.md](./prompt-rule-registry-scope.md),
which it partly unblocks.

**Superseded as the first move, 2026-09-22.** The owner has since said
taste is not the role they want -- what they want measured is whether an
image renders what its beat text specified. That is a different and much
cheaper question, and it is scoped in
[prompt-fidelity-checking-scope.md](./prompt-fidelity-checking-scope.md),
which also has a real measurement attached where this document has none.
Nothing here is withdrawn; a preference judge remains the right tool for
"which candidate would they keep", and the label-drift problem below
applies to any calibration against this owner. But the data blocker
stated below is why fidelity goes first.

## The problem, stated plainly

This pipeline has no automated quality signal of any kind. The owner's
eye is the only scorer, applied one image at a time, which means:

- No prompt rule in `scene_planning.py` has ever been measured. All of
  them are arguments.
- [0058](../decisions/0058-delete-rules-by-judgement-not-ablation.md)
  declined the rule registry for exactly this reason: an ablation harness
  whose scorer is a human is just the review loop with machinery in front.
- [0073](../decisions/0073-re-verify-hard-bans-on-a-model-change.md)'s
  re-verification of every hard ban on a model-pin change is a manual
  generate-and-look chore, and will be skipped the first time it is
  inconvenient.

Everything downstream of "is this change better?" is blocked on the same
missing piece.

## What was already tried, and the number it produced

`previz_review` was measured against 78 images the owner had ruled on
(`evals/judge_agreement.py`,
[0055](../decisions/0055-delete-the-automated-previz-reviewer.md)):

| | agreement with the owner |
|---|---|
| `previz_review` | 56% |
| "always accept" | **79%** |
| "always reject" | 21% |

It was deleted. Three causes, all fixable and none of them "LLM judges
don't work":

1. **It answered a different question than it was scored on.** Its job
   was plan fidelity. The labels were keep-or-reject.
2. **Binary, with no severity.** A missing tote bag and an absent
   antagonist were the same event.
3. **Pointwise against a 79% majority-class baseline.** Close to
   unwinnable, and the metric hid that it did discriminate a little
   (+31% between the two groups).

## The proposed shape: pairwise, because the data already is

Every row in `evals/judgements.jsonl` carries `chosen_over` -- the exact
sibling candidates the image was shown against. That is a preference
group, the same structure a reward model trains on.

So the judge's question becomes **"which of these candidates would the
owner keep?"** rather than "is this image acceptable?". Three things
follow:

- It matches the real decision. The CLI shows N candidates and the owner
  picks one; the judge does not need a notion of "good", only of "better
  than its siblings".
- The trivial baseline drops from 79% to 25% (random pick of four), so
  the measurement is informative instead of nearly unwinnable.
- Relative comparison is the more stable mode for a prompted judge.
  Absolute 1--10 scores drift between calls; a preference between two
  concrete images does not.

`evals/judge_agreement.py` already does the harness half of this. What it
scored was the wrong judge asking the wrong question.

## The blocker, with the real number

The corpus as of writing:

| | |
|---|---|
| rows (all interactive, none `--yes`) | 49 |
| across runs | 5 |
| rows carrying siblings | 49 |
| rows the owner kept | 7 |
| **attempts with a winner -- i.e. usable preference groups** | **7** |
| beats abandoned with nothing kept (`g`) | 19 of 49 rows |

**Seven preference groups is the honest number, not forty-nine.** A
pairwise judge needs a winner to compare against, and most attempts here
do not have one. This is nowhere near enough to calibrate anything, and
any agreement figure computed on it now would be noise presented as a
result.

Two things follow. First, **do not build the judge yet** -- bank labels
until there are a few hundred groups. Second, the give-up rate is itself
a signal worth keeping: an attempt where every candidate lost is a strong
negative on all of them, and a judge that only ever sees winner-vs-loser
never learns what "all four are unusable" looks like.

Three ways to get there, cheapest first:

1. **Keep running.** Labels accrue from runs already being done. Since
   [0076](../decisions/0076-rejections-carry-a-reason-code.md) each also
   carries why, which is what turns a preference into a rubric.
2. **Label what is already on disk.** `outputs/` holds generated images
   from runs that were never exported or never judged. Free -- the
   generation is already paid for.
3. **Only then** a deliberate labelling session against `scenes.yaml`.

## The other problem: the labels move

[0055](../decisions/0055-delete-the-automated-previz-reviewer.md) flagged
it and it has not been addressed. The owner's bar has been tightening
over weeks, and a kept image is a *least-bad pick rather than an
endorsement* -- their words: "almost none of the ones i've accepted so
far have truly been 'good enough' by my standards anyway".

A judge calibrated across that learns the average of two different
standards. Mitigations, none free: weight recent labels more heavily,
restrict calibration to a recent window, or re-label the old images under
the current bar. The one thing not to do is compute a number across the
whole corpus and treat it as one distribution.

## What it would be used for, in order of risk

1. **Candidate pre-ranking.** Show the owner the judge's best pick first.
   Gates nothing, rejects nothing; a wrong judge costs a second of
   scrolling. This is the only safe first deployment.
2. **A scorer for prompt changes.** Rule on, rule off, run the eval
   scenes, compare. This is what unblocks
   [the rule registry](./prompt-rule-registry-scope.md) and is the real
   prize.
3. **Regression detection on a model-pin change**, feeding 0073's
   re-verification.

**It must not gate the retry loop.** That is precisely how the last one
did damage: a rejection's concern was folded into the next attempt as
`"Fix this: ..."`, so a signal wrong 44% of the time was steering
regeneration -- injecting "the tote bag is missing" while the absent
antagonist went unmentioned. Advisor until the numbers earn more.

## Decision criteria, written before the experiment

Stated now so the result cannot be rationalised afterwards -- the same
discipline `evals/judge_agreement.py` already applies:

- **Beats 25% random pick by a wide margin on held-out groups** -> real
  signal; deploy as pre-ranking only.
- **Beats random but not by much** -> not useful as a scorer; do not
  deploy, do not sharpen the prompt and re-run until it passes, which is
  just overfitting the eval by hand.
- **Does not beat random** -> the labels or the question are wrong, not
  the model. Re-examine both before trying a bigger model.

A held-out split is required. Calibrating and reporting on the same rows
produces a number that means nothing.

## What this does not solve

It does not improve a single image on its own. It does not replace the
human at the previz gate, and nothing here proposes that it should. It
makes prompt changes measurable, which is a different claim and the only
one worth making.
