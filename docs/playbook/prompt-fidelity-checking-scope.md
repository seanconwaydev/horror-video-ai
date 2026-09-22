# Scope: automated prompt-fidelity checking

Written 2026-09-22. **Not built: the probe it was conditional on came
back at 64% recall against an 80% floor this file set in advance.** The
design below is left as written, because the reason it was rejected is a
measurement and not an argument, and because a different vision model
would be measured against exactly this text. See
[prompt-fidelity-probe-2.md](./prompt-fidelity-probe-2.md) for the
numbers and [Outcome](#outcome) below for what would reopen it.

Same status and purpose as
[judge-calibration-scope.md](./judge-calibration-scope.md), which it
partly replaces as the more useful first move.

## Why this rather than a preference judge

[judge-calibration-scope.md](./judge-calibration-scope.md) proposes a
judge that predicts which candidate the owner would keep. It is blocked
on data -- seven usable preference groups against a few hundred needed --
and it measures taste.

The owner has since stated that taste is not the role they want:

> i'm not so worried about being the taste maker for these generated
> images and videos, i want the prompts to create images and videos that
> are accurate to what the prompts say. then if our prompts are good and
> accurately describe what we want, then the taste should be at least
> somewhat satisfied anyway.

That reframing matters because **fidelity is a grounded question and
taste is not**. "The beat said a trail of wet footprints crosses the
concrete -- is it in the image?" has a checkable answer that two
observers agree on. "Is this image good?" does not. So the data blocker
disappears: fidelity needs a handful of spot-check items, not hundreds of
preference labels.

It also means the deleted reviewer deserves a second look.
[0055](../decisions/0055-delete-the-automated-previz-reviewer.md) killed
`previz_review` for scoring 56% against a 79% always-accept baseline --
but it was asked a plan-fidelity question and scored against keep-or-
reject labels. That ADR's own account of its false rejects is the tell:
"the planned camera framing was a wide shot taken from behind the
counter", "specifies the phone is hanging at her hip" -- **"real
mismatches, trivially unimportant."** Under a fidelity target those are
correct answers. It was not wrong about the images; it was measured
against a different question, gave one binary verdict with no severity,
and -- the genuinely harmful part -- fed its concern into the retry.

## The measurement that exists

One probe, 2026-09-22, on two images from the laundry run
(`run_20260922-002146`, beats 1 and 3, attempt 1 of each). 26 claims were
extracted from the beat text alone, before either image was opened. The
owner and the model answered the same sheet independently, blind.

| | |
|---|---|
| items | 26 |
| agreement | 18/26 (69%) |
| **recall on the owner's failures** | **11/12 (92%)** |
| precision | 11/18 (61%) |

Recall is the number that matters: a checker exists to flag failures, and
it independently found all but one of the owner's. Every complaint in
their prose feedback -- absent footprints, absent dark drum window, eight
drums instead of five, camera not high, camera not behind her in beat 3,
her head not over her shoulder, his head not thrust at her skull, size in
frame wrong -- was agreed unanimously.

Raw data is embedded below so the numbers are re-derivable.

### The false alarms have three causes, all in the claim text

Seven of nine disagreements ran one way: the owner said yes, the model
said no. Not a perception difference -- the model graded every conjunct
of a claim while the owner graded its gist.

1. **Compound claims.** "a bundle of sheets lifted clear of the cart,
   both hands under it, elbows bent" is three claims sharing one answer.
   Split them.
2. **Undefined tolerances.** "*directly* above the folding table",
   "*straight* down beneath her", "*about* a fifth of the image height".
   The claim never says how much slack is allowed, so two readers pick
   different amounts and both are right. Delete the adverb or define it.
3. **Unresolvable referents.** The beat names a "cart" and a "folding
   table" as separate objects; the image contains one object that could
   be either. Harder to fix and possibly not fixable at the claim layer.

The first two are claim-writing defects, not model defects, and both are
repairable before the next probe.

### The blind spot, which is not repairable

Claim B3-10 -- "one hand splayed flat on an open dryer door". The model
scored it present. The owner:

> his hand looks good and is _near_ the door, but to a human it is
> clearly just resting in the middle of a dark void of the open dryer
> door, not physically touching anything.

The model scored *position*; the owner scored *contact*. This is the
AI-artifact class (see also "she melded with the cart" in the same run),
and it is where vision models are weakest -- they describe content, they
do not adjudicate physical plausibility.

Note where that lands. `contact` is a field
[0072](../decisions/0072-facing-and-the-threats-own-face.md) added
specifically because two-body facts could not be stated, and it is the
field an automated checker is least able to verify. **The owner stays the
only detector for this class.** Any claim about touching, weight, or body
boundaries should be marked as owner-only rather than trusted from the
model.

### Three verdicts, not two

Claim B3-9 -- "his eyes are fixed on her, not on the camera". The owner
first answered yes, then reversed:

> honestly it's very hard to tell what he's looking at, one eye is white
> and the other eye looks like a blob of paint almost. i said yes because
> my first glance it looked "good enough", but after looking even more
> than a moment, it does actually look like he's potentially looking at
> the camera.

A binary sheet threw away the most informative answer available. The
verdict set is therefore **yes / no / can't tell**, and *can't tell
counts as a failure rather than as missing data*: the output ships as a
vertical short, so a frame a viewer cannot read in one glance has failed
whatever the ground truth is.

Only the can't-tells get a second look. An item answered instantly will
not change, so re-answering the full sheet buys nothing -- on this probe
it would have meant re-examining exactly one item.

The first-glance/considered split also sorts failures into two buckets
needing opposite repairs, which is the real reason to keep it:

- **no at a glance** -> the image is wrong. Prompt or render problem.
- **can't tell at a glance, yes on inspection** -> the image is *right
  and illegible*. The beat asked for something a still frame at phone
  resolution cannot carry -- the same category as the physical-minutiae
  ban in `_COMPLEXITY_BUDGET_RULE`, which exists because visible breath
  and condensation do not survive into the picture.

Confusing the second for the first is expensive in this project's
characteristic way: someone writes a rule demanding the gaze harder, the
beat goes further over the complexity budget, and the next render drops
something else. That is the beat-1 retry loop from the same run.

## The shape

**One vision call per image, one row per claim, advisory only.**

1. **Extract.** A beat is already a requirements list -- `action`,
   `camera`, `lighting`, and a `staging` entry per character carrying
   blocking, size and occlusion. Turn it into atomic claims
   automatically. The owner never authors a question.
2. **Check.** A vision model answers each claim against the image:
   yes / no / can't tell.
3. **Record.** One row per claim.
4. **Report.** At the review gate: `Beat 1: 8/13 -- missing: wet
   footprints [action], dark drum window [action], size in frame
   [staging]`.

**One row per claim, not per image.** Per-image rows collapse the only
dimension worth having -- which *field* the failure came from. Row shape
follows `evals/judgements.jsonl` (0074: committed, merge-written so
concurrent runs do not clobber): run, beat index, attempt, claim text,
source field, model verdict, owner verdict where spot-checked, image
path, model pin, **and the prompt-rule version**. That last one is not
bookkeeping -- without it old rows cannot be compared to new ones, and
this repo has already shipped a bug of exactly that shape, a `--fixture`
path mislabelling `genre` on every judgement row it exported.

### What consumes it

1. **The run, immediately.** Dropped details are named at the review gate
   instead of hunted for.
2. **Experiments.** `run_eval.py` arms over the frozen `scenes.yaml`:
   mean fidelity per arm and per field. This is what decides whether a
   prompt rule stays or goes.
3. **The accumulating corpus.** Pass rate per field, per model pin, per
   style. This is what would surface "occlusion claims fail 80% of the
   time regardless of wording" -- a hard-ban candidate established by
   counting, the way [0060](../decisions/0060-threat-is-hidden-not-distant.md)
   was (1 success in 22). It also turns
   [0073](../decisions/0073-re-verify-hard-bans-on-a-model-change.md)'s
   re-verification chore into a query.
4. **The premise test.** Fidelity rows join to judgement rows on image
   path, answering: *do high-fidelity images actually get kept?* The
   owner's argument for this whole direction is that faithful renders
   satisfy taste on their own. That is a hypothesis, and the join tests
   it for free, because both datasets exist independently and neither was
   built for it. If the highest-fidelity images are the ones being
   rejected, the premise is wrong and that should surface in a month
   rather than a year.

**Not a consumer, deliberately: the retry loop.** Nothing flows back into
generation automatically. That is what made `previz_review` harmful
rather than merely useless, and the owner reproduced the same failure by
hand on 2026-09-22 -- feedback naming a missing detail appended a
requirement to a beat that had already failed for holding too many, and
the retries came back worse.

## Why a biased checker is still usable

The probe's 61% precision looks disqualifying and is not, because the
main consumer is a comparison between two arms over identical scenes. A
checker with a *consistent* bias still gives a valid comparison -- the
bias lands on both arms and cancels. Consistency is separately
measurable by submitting the same image twice, which is what
`evals/reviewer_reliability.py` was built to do.

So absolute fidelity scores will be somewhat wrong, and differences
between arms will still be real. Accuracy is wanted for the in-run
report; only consistency is needed for the experiments, which are the
part that changes the prompt.

## Decision criteria, written before the experiment

Stated now so the result cannot be rationalised afterwards -- the same
discipline `evals/judge_agreement.py` already applies.

Repair the claim-writing defects above, then re-probe on roughly 60 items
across more beats and both styles. The repaired sheet is
[prompt-fidelity-probe-2.md](./prompt-fidelity-probe-2.md): 71 claims
over seven beats of two runs, one horror-comic and one painterly,
written from beat text with the images unopened.

- **Recall >= 90% and precision >= 80%** -> build it, including the
  in-run report.
- **Recall >= 90%, precision stubbornly low** -> usable for arm
  comparison only, where bias cancels. Do not print it at the review
  gate; a checker that cries wolf at the review gate trains the owner to
  ignore it.
- **Recall < 80%** -> it is missing real failures. Stop. The problem is
  the vision model against this material, not the prompt.
- **Do not sharpen the extraction prompt and re-run until it passes.**
  That is overfitting the eval by hand, the same trap
  judge-calibration-scope.md names.

A held-out split is required once there is enough data to need one.

## Build order, if accepted

Staged so the two steps that need no network land first and are testable
in CI.

1. `stages/fidelity.py` -- claim extraction from a beat. Pure function,
   frozen-dataclass output, `FidelityError` on malformed input, tested
   offline against frozen beats. No API.
2. The check call -- injectable `vision_fn` defaulting to
   `litellm.completion`, matching every other stage's pattern so tests
   never need a live call.
3. `config/models.yaml` gains the stage block **first** (CLAUDE.md), and
   `tests/test_config.py`'s `expected_stages` set with it.
4. The jsonl writer, merge-written per 0074. Incremental, because runs
   are usually abandoned partway.
5. The review-gate report in `cli/beats.py`.
6. Arm comparison in `evals/run_eval.py`.

## What this does not solve

It improves no image on its own -- it is an instrument, and a human still
reads the numbers and decides. It cannot see the contact/artifact class.
And it says only whether a prompt was *obeyed*, never whether it was any
good; that judgement moves upstream to the beat text at the scene-plan
review gate, where the owner already is and where reading five beats is
far cheaper than judging twenty images.

## Appendix: the probe, in full

Images: `beat_1/beat1_attempt_1_rejected.png`,
`beat_3/beat3_attempt_1_rejected.png` of
`outputs/run_20260922-002146_a-night-porter-loading-a-cart-hears-a/`
(gitignored; the claims and verdicts below are the durable record).

`*` marks a disagreement.

| id | claim from beat text | field | owner | model |
|---|---|---|---|---|
| B1-1 | camera is high above, looking down | camera | n | n |
| B1-2 | camera is behind her, we see her back | camera | y | y |
| B1-3 `*` | bundle lifted clear of cart, both hands under it | staging.action | y | n |
| B1-4 | a trail of wet footprints crosses the floor | action | n | n |
| B1-5 | one drum window is dark while the others are lit | action | n | n |
| B1-6 | exactly five lit, tumbling drums | action | n | n |
| B1-7 | a row of dryers runs along the wall beside her | staging.blocking | y | y |
| B1-8 `*` | the cart is at her hip | staging.blocking | y | n |
| B1-9 | she is about a fifth of the image height | size_in_frame | n | n |
| B1-10 | exactly one light fixture, the only light in frame | lighting | y | y |
| B1-11 `*` | that light is directly above the folding table | lighting | y | n |
| B1-12 `*` | her shadow drops straight down beneath her | lighting | y | n |
| B1-13 `*` | (inverse) something prominent the text never mentions | -- | n | y |
| B3-1 | camera is low, looking up | camera | n | n |
| B3-2 | camera is behind her, over her shoulder | camera | n | n |
| B3-3 | her head and near shoulder fill about half the frame | size_in_frame | n | n |
| B3-4 | her head is turned hard over her right shoulder | staging.action | n | n |
| B3-5 | her eyes are wide and her mouth is open | staging.action | y | y |
| B3-6 | the man is behind her, less than one stride away | facing | y | y |
| B3-7 | his head is lowered and thrust at the back of her skull | staging.action | n | n |
| B3-8 | his jaw is slack, teeth bared | staging.action | y | y |
| B3-9 `*` | his eyes are fixed on her, not on the camera | staging.action | y -> can't tell | n |
| B3-10 `*` | one hand splayed flat on an open dryer door | staging.action | n | y |
| B3-11 `*` | her shoulder and ponytail hide his chest and right arm | occlusion | y | n |
| B3-12 `*` | the dominant light is behind him, rimming his neck | lighting | y | n |
| B3-13 | he is barefoot | staging.action | y | y |

B1-13 is an inverse-polarity item and was badly written -- `y` means a
defect, unlike every other row. Do not repeat that shape; the reversal is
a trap for both readers.

The headline numbers above use the owner's *considered* answer on B3-9.
On their first-glance answer, agreement is 17/26 and recall 10/12 -- the
difference one ambiguous item makes at this sample size, and the reason
60 items is the floor for the next probe.

## Outcome

Recorded as [0077](../decisions/0077-no-automated-fidelity-checking.md).

**Rejected on measurement, 2026-09-22**, by the third branch of the
criteria above: recall 64% (69% excluding the contact claims the model
provably cannot judge), against a floor of 80%. Precision was 55%.
Repairing probe 1's claim defects removed its one-way bias -- the 27
disagreements now run 18 one way and 9 the other -- without improving
agreement, which fell from 69% to 62%. What is left is disagreement
rather than bad claim-writing, and that is not something a better sheet
fixes.

Nothing in the build order was started. `evals/fidelity_probe.py` is the
probe driver and is not `stages/fidelity.py`; no stage, no model pin, no
jsonl writer and no review-gate report exist.

Three things would reopen this, and writing a third claim sheet is not
among them -- that is the eval-overfitting this file already forbids:

1. **A different vision model.** The verdict names this model against
   this material, and the sheet is reusable as-is: point
   `evals/fidelity_probe.py` at another pin and rescore the same 71
   claims against the same owner column. That is a cheap experiment, not
   a rebuild.
2. **A narrower question.** Per-field numbers were the surprise: every
   contact claim failed and `staging.action` failed 8 of 24, while the
   overall number was dragged down by camera and lighting claims. A
   checker asked only what it is good at might clear the bar the general
   one missed -- but that is a new scope with its own pre-registered
   criteria, not a re-run of this one.
3. **A materially better model generation.** Same test, later.

What the probe leaves behind is worth more than the rejected design:
71 claims with two independent verdicts each, and the observation that
two-body physical facts (`contact`) failed 4 of 4 in the images and are
simultaneously the class an automated checker cannot see.
