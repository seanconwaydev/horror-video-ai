# 55. Delete the automated previz reviewer

Date: 2026-09-17

Status: Accepted

Supersedes [0009](./0009-previz-image-review.md), whose independent image
review this removes, and closes out the open question
[0043](./0043-one-review-prompt-the-human-decides.md) left behind when it
stopped the reviewer from deciding anything on its own.

## Context

`previz_review` was measured against 78 images the project owner had
already ruled on -- 62 kept, 16 rejected -- reusing images and prompts
already on disk, so nothing was generated
(`evals/judge_agreement.py`).

| | agreement with the owner |
|---|---|
| `previz_review` | **56%** |
| "always accept" | **79%** |
| "always reject" | 21% |

It accepted 50% of the images the owner kept and 19% of the ones they
rejected, so it does discriminate a little (+31%) and is not inverted on
this task. But as a predictor it loses to the trivial majority-class
baseline by 23 points, and **it rejected 31 of the 62 images the owner
actually kept.**

Two caveats stated plainly, because they cut in opposite directions and
neither changes the decision. The 62 positives are *least-bad picks*, not
endorsements -- the owner's words: "almost none of the ones i've accepted
so far have truly been 'good enough' by my standards anyway" -- and they
were accepted over weeks under a bar that has been tightening, which
biases against the reviewer looking good. And the earlier
[0043](./0043-one-review-prompt-the-human-decides.md) finding that it
ranked four arms "in exact reverse" measured a different task, ranking
images by quality; on accept/reject it is weakly positive. That claim was
overstated and this ADR replaces it with a number.

The mechanism is visible in the false rejects: "the planned camera framing
was a wide shot taken from behind the counter", "specifies the phone is
hanging at her hip". Real mismatches, trivially unimportant. The reviewer
is asked a plan-fidelity question and answers it as a binary with **no
notion of severity**, so a missing tote bag and an absent antagonist are
the same event. 0043 already recorded it rejecting four beats over a
missing tote bag while saying nothing about the antagonist being absent
entirely.

Worse than the wasted calls: a rejection's `concern` was folded into the
next attempt's prompt as `"Fix this: <concern>"`. A signal wrong 44% of
the time was steering regeneration -- injecting "the tote bag is missing"
while the absent antagonist went unmentioned.

## Decision

Remove the automated review from the pipeline entirely.

- No review call in the attempt loop. `_generate_image_with_review`
  becomes `_generate_image_with_retries`, since that is what it now does.
- `_beat_with_review_corrections` is deleted. Nothing rewrites a beat from
  a machine's opinion.
- Concern accumulation across attempts and cycles is gone, along with the
  `review_model` / `review_kwargs` plumbing and the `previz_review_model`
  run-log field.
- The human is still asked after every attempt -- accept / retry / edit /
  feedback / give up. 0043 established that this prompt was doing the
  actual work, and it is untouched. Human-typed (f)eedback still edits the
  beat; that was never the reviewer's path.
- Under `--yes` the first attempt is accepted. There is nothing left to
  grade an image unattended, and pretending otherwise was the point 0043
  conceded already.
- Archived attempts are all `_rejected` now. The `_superseded` suffix
  existed to distinguish "reviewer was happy, human rerolled" from
  "reviewer objected", and there is no reviewer.
- The pre-spend estimate no longer quotes an "automatic review attempts"
  ceiling, because there are none; it states one attempt per beat and says
  retries cost more.

`run_previz_review_stage` itself survives in `stages/previz.py`, used only
by `evals/` -- including the study that condemned it, and
`evals/reference_anchor.py`. `previz_review` stays in
`config/models.yaml` for those.

## Consequences

The pipeline has no automated quality signal at all now. That is an honest
description of the situation rather than a regression: it had one, it was
measured, and it was worse than nothing.

An LLM-as-judge earns its place when there is a quality bar that can be
articulated and outputs landing near it. Neither is true yet -- the owner
currently rejects nearly everything. Rebuilding one is deliberately
deferred until image quality is materially better and the engineering
practices are solid, and it should be rebuilt from scratch rather than
revived: a binary plan-fidelity verdict is the wrong shape, and severity
is the thing it needs.

The `evals/judge_agreement.py` result is kept at
`evals/results/judge-agreement-20260917.json` so a future attempt starts
from evidence rather than re-running this argument.

Not addressed: whether the reviewer's *observations* are factually true of
the images, as distinct from whether its verdicts predict the owner's
choice. That is a better-posed question, needs no quality label, and stays
valid while generation quality is poor -- but it is a question about a
component that no longer runs, so it waits for the rebuild.
