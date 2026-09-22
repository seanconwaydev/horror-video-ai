# 77. An automated fidelity checker was measured, and is not being built

Date: 2026-09-22

Status: Accepted

Nothing superseded. Extends
[0055](./0055-delete-the-automated-previz-reviewer.md), which deleted
the last automated image reviewer on a measurement, and closes
[playbook/prompt-fidelity-checking-scope.md](../playbook/prompt-fidelity-checking-scope.md)
without building it.

## Context

0055 deleted `previz_review` for agreeing with the owner on 56% of
images against a 79% always-accept baseline. Its own account of the
false rejections -- "the planned camera framing was a wide shot taken
from behind the counter", "specifies the phone is hanging at her hip",
called "real mismatches, trivially unimportant" -- suggested it had been
asked a fidelity question and scored against taste labels. The owner
then stated plainly that taste is not the target:

> i want the prompts to create images and videos that are accurate to
> what the prompts say.

That reframing is what made a second attempt worth considering.
Fidelity is checkable where taste is not: "the beat said a trail of wet
footprints crosses the concrete -- is it in the image?" has an answer
two observers agree on, so it needs a handful of spot-check items rather
than the hundreds of preference labels a taste judge is blocked on.

The scope was written with its decision criteria fixed **before** any
measurement: recall >= 90% and precision >= 80% builds it, recall >= 90%
with low precision restricts it to arm comparison where a consistent
bias cancels, and **recall < 80% stops it**. It also forbade in advance
the obvious escape -- sharpening the claims and re-running until they
pass.

Two probes ran. Both asked the owner and a vision model to answer the
same sheet of claims, extracted from beat text before any image was
opened, independently and blind.

- **Probe 1**, 26 claims over two images: 92% recall, 61% precision.
  Every false alarm traced to how the claims were written -- compound
  claims graded conjunct by conjunct, undefined tolerances ("directly
  above", "about a fifth"), referents the image could not resolve.
- **Probe 2**, 71 claims over seven beats of two runs and two styles,
  with all three defects repaired: **64% recall, 55% precision**, 62%
  agreement. Excluding contact claims, which the model provably cannot
  judge, recall is 69%.

## Decision

Do not build it. Recall 64% is the third branch of the criteria, and the
branch says stop: the checker is missing a third of the real failures,
so the problem is this vision model against this material rather than
the claims put to it.

Nothing in the scope's build order was started -- no `stages/fidelity.py`,
no model pin, no jsonl writer, no review-gate report.
`evals/fidelity_probe.py` exists and is the probe driver, not the stage.

Three things make this a decision rather than a deferral:

- **The repair worked and did not help.** Probe 1's disagreements ran
  one way, which is what made "the claims are badly written" the right
  diagnosis. Repairing them removed that asymmetry -- 18 one way, 9 the
  other -- and agreement *fell*, 69% to 62%. The bias was real and is
  gone; what is underneath it is disagreement, and disagreement is not
  something a better sheet fixes.
- **A third sheet is forbidden and stays forbidden.** Some probe 2
  claims are arguably still imperfect. Rewriting them until the model
  agrees would measure the claim author, not the instrument, which is
  the eval-overfitting the scope named before it could be tempting.
- **The failure is not style-specific.** 64% on horror-comic and 65% on
  painterly, separately.

The probe artifacts are kept rather than deleted: 71 claims with two
independent verdicts each, and a driver that parses the claims out of
the sheet. Pointing it at a different model pin and rescoring the same
sheet against the same owner column is a cheap experiment, and is the
first of the three things the scope's Outcome section records as
reopening this.

## Consequences

**The owner remains the only fidelity detector.** No dropped detail is
named at the review gate; it is still found by looking. That is the
status quo, not a regression -- but it is now a measured status quo
rather than an unexamined one.

**Two review habits survive the rejection**, because they are about how
the owner reads an image rather than about the checker: can't-tell
counts as a failure (a frame a viewer cannot read at a glance has failed
whatever the ground truth is), and claims about touching, weight or body
boundaries are owner-only.

**Every contact claim in probe 2 failed** -- 4 of 4, on top of probe 1's
blind spot, in the class an automated checker is worst at. Five claims
is far too few to conclude from, and it points the same way as
[0072](./0072-facing-and-the-threats-own-face.md): two-body physical
facts are simultaneously the hardest thing to render and the one thing
no automated check can see. Following that up means more images, not
more claims per image.

**The premise this was going to test is still untested.** The scope's
fourth consumer was a free join: do high-fidelity images actually get
kept? That question needed the fidelity rows, so the owner's argument
for the whole direction -- that faithful renders satisfy taste on their
own -- remains an unmeasured hypothesis.

This is the second automated image reviewer this project has measured
and declined to keep. The pattern worth carrying forward is not "model
reviewers do not work" but that both were caught by a measurement that
cost a day, before either could be wired into generation -- which is
where 0055's reviewer did its actual damage.
