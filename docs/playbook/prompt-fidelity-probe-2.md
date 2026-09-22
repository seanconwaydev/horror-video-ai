# Probe 2: prompt-fidelity claim sheet

The re-probe that
[prompt-fidelity-checking-scope.md](./prompt-fidelity-checking-scope.md)
requires before the design can be accepted or rejected. That file fixes
the decision criteria in advance; this one holds the sheet and, once
answered, the verdicts.

**Status: answered and scored, 2026-09-22. Recall 64%, below the 80%
floor the scope doc set in advance -- so the criteria say stop.** See
[Results](#results). The claims below were written from the beat text
alone, before any image was opened, the same discipline probe 1 used.

## What changed since probe 1

Probe 1's 61% precision traced entirely to how its claims were written,
not to the model. Three defects, all repaired here:

- **Compound claims are split.** "a bundle of sheets lifted clear of the
  cart, both hands under it, elbows bent" was three facts sharing one
  answer. Every row below is one fact.
- **Tolerance adverbs are gone.** No "directly", "straight", "about". A
  claim that needs a threshold states one ("between a quarter and a half
  of the image height"), and a claim that only needs a comparison makes
  the comparison instead ("she is larger in the frame than he is").
- **Referents must be resolvable from the image.** Where the beat names
  two objects a viewer could not tell apart (the laundry run's "cart"
  and "folding table"), the claim names only what is distinguishable.

Two more rules, from probe 1's other findings:

- **No inverse-polarity rows.** Probe 1's B1-13 made `y` mean a defect,
  which is a trap for both readers. Every row here reads the same way:
  `y` means the image honours the claim.
- **`†` marks a contact claim** -- touching, grip, weight, body
  boundaries. This is the class the vision model cannot adjudicate (it
  scores position, the owner scores contact), so headline precision and
  recall are reported both with and without these rows.

## How to answer

Verdicts are **y / n / ?**, where `?` is "can't tell" and **counts as a
failure**: the output ships as a vertical short, so a frame a viewer
cannot read at a glance has failed whatever the ground truth is.

Answer at a glance, in order, without re-reading. Then go back and give
a considered second look to the `?` rows only -- an item answered
instantly will not change, and re-answering the whole sheet buys
nothing. Record both answers on any row that moves (`? -> y`).

Owner and model answer independently. Neither sees the other's column
before both are complete.

## The images

Seven images, seven beats, two styles. The laundry run's beats 1 and 3
are deliberately excluded -- they are probe 1, and reusing them would
measure the repair against the material it was derived from.

| sheet | run | beat | image | style |
|---|---|---|---|---|
| B2 | `run_20260922-002146_a-night-porter-loading-a-cart-hears-a` | 2 | `beat_2/beat2_attempt_1_rejected.png` | horror-comic |
| B4 | `run_20260922-002146_...` | 4 | `beat_4/beat4_attempt_1_rejected.png` | horror-comic |
| B5 | `run_20260922-002146_...` | 5 | `beat_5/beat5_attempt_1_rejected.png` | horror-comic |
| L1 | `run_20260921-220038_a-lookout-scanning-the-treeline-sees` | 1 | `beat_1/candidate_1_1.png` | painterly |
| L2 | `run_20260921-220038_...` | 2 | `beat_2/candidate_1_2.png` | painterly |
| L3 | `run_20260921-220038_...` | 3 | `beat_3/candidate_2_2.png` | painterly |
| L4 | `run_20260921-220038_...` | 4 | `beat_4/candidate_2_1.png` | painterly |

Both runs live under the gitignored `outputs/`, so the claims and
verdicts here are the durable record, as in probe 1.

## B2 -- laundry, beat 2 (horror-comic)

| id | claim | field | owner | model |
|---|---|---|---|---|
| B2-1 | the frame is cropped at or above her waist | camera | y `*` | n |
| B2-2 | the camera is level with her face, neither above nor below it | camera | n | n |
| B2-3 | she is seen from a three-quarter angle, not square-on and not in profile | camera | y | y |
| B2-4 | her mouth is open | staging.action | y | y |
| B2-5 | her eyes are turned to one side rather than toward the camera | staging.action | y | y |
| B2-6 | one of her hands is inside a laundry cart | staging.action | y `*` | ? |
| B2-7 `†` | her other hand is closed round the cart's rail | staging.action | y | y |
| B2-8 | a wheeled laundry cart stands beside her at hip height | staging.blocking | y | y |
| B2-9 | the light source is behind her, not in front of her | lighting | y `*` | n |
| B2-10 | she occupies between a quarter and a half of the image | size_in_frame | y `*` | n |

## B4 -- laundry, beat 4 (horror-comic)

| id | claim | field | owner | model |
|---|---|---|---|---|
| B4-1 | the camera is level with their faces | camera | n | n |
| B4-2 | she is visible from the waist up or lower, not cropped to head and shoulders | camera | y | y |
| B4-3 | she is leaning backwards onto a wheeled cart | staging.action | n `*` | y |
| B4-4 | one of her forearms is raised between her face and him | staging.action | n `*` | y |
| B4-5 | her mouth is open | staging.action | y | y |
| B4-6 | he faces her with his teeth showing | staging.action | y | y |
| B4-7 | there is one other person in the frame with her, and no more | staging | y | y |
| B4-8 | she is larger in the frame than he is | size_in_frame | n | n |
| B4-9 | neither figure is hidden or cut off by an object in front of them | occlusion | n | n |
| B4-10 | a single overhead light fixture is the only light source in the frame | lighting | y | y |

## B5 -- laundry, beat 5 (horror-comic)

| id | claim | field | owner | model |
|---|---|---|---|---|
| B5-1 | the camera is below them, looking up | camera | n | n |
| B5-2 | both figures are seen side-on, in profile | camera | y `*` | n |
| B5-3 `†` | his hand is closed round her forearm, touching it | contact | n `*` | y |
| B5-4 | her arm is pulled straight, not bent at the elbow | contact | n `*` | y |
| B5-5 | her eyes are directed at the hand on her arm | staging.action | n | n |
| B5-6 | his teeth are showing | staging.action | y | y |
| B5-7 | he is barefoot | staging.action | y | y |
| B5-8 | his face is darker than her arm | lighting | n | n |
| B5-9 | spilled sheets lie on the floor around them | staging.blocking | y | y |
| B5-10 | neither figure is hidden or cut off by an object in front of them | occlusion | y | y |

## L1 -- lookout, beat 1 (painterly)

| id | claim | field | owner | model |
|---|---|---|---|---|
| L1-1 | we see her from behind -- her back is toward the camera | camera | y | y |
| L1-2 | the camera is level with her head, neither above nor below it | camera | n `*` | ? |
| L1-3 | she is visible from the waist up or lower, not cropped to head and shoulders | camera | y | y |
| L1-4 `†` | both of her hands are on a rail | staging.action | y `*` | n |
| L1-5 | binoculars hang on a strap at her chest | staging.action | n | n |
| L1-6 | the strongest light comes from outside the window ahead of her | lighting | n `*` | y |
| L1-7 | that light is amber, and the light behind her is white | lighting | n | n |
| L1-8 | she is standing at the glass, not across the room from it | staging.blocking | y | y |
| L1-9 | she occupies between a quarter and a half of the image height | size_in_frame | n | n |
| L1-10 | fog is pressed against the outside of the glass | action | y | y |

## L2 -- lookout, beat 2 (painterly)

| id | claim | field | owner | model |
|---|---|---|---|---|
| L2-1 | the camera is below it, looking up | camera | n `*` | y |
| L2-2 | the whole figure and the trees around it are in frame | camera | y `*` | n |
| L2-3 | a lit lamp in its hand is the only light source in the frame | lighting | y `*` | ? |
| L2-4 | tree shadows stretch away from the lamp | lighting | n | n |
| L2-5 | it carries the lamp in one hand | staging.action | y | y |
| L2-6 | its chin is tipped up | staging.action | n `*` | y |
| L2-7 | its teeth are showing | staging.action | n | n |
| L2-8 | its eyes are directed upward | staging.action | n `*` | ? |
| L2-9 | it is walking between two tree trunks | staging.blocking | y | y |
| L2-10 | its head and shoulders are clearer than its legs, which fade into mist | occlusion | y `*` | n |
| L2-11 | it occupies between a quarter and a half of the image height | size_in_frame | y `*` | n |

## L3 -- lookout, beat 3 (painterly)

| id | claim | field | owner | model |
|---|---|---|---|---|
| L3-1 | the camera is below her, looking up | camera | n | n |
| L3-2 | the frame is cropped at or above her waist | camera | y `*` | n |
| L3-3 | one of her forearms is raised across her face | staging.action | y | y |
| L3-4 | her mouth is open | staging.action | y | y |
| L3-5 | her eyes are directed downward and to one side, not at the camera | staging.action | y | y |
| L3-6 `†` | her other palm is flat on a table's edge | staging.action | y | y |
| L3-7 | the light on her face comes from below it | lighting | y `*` | n |
| L3-8 | her eye sockets are in shadow | lighting | y `*` | n |
| L3-9 | a chair lies tipped on its side behind her | intensity | n | n |
| L3-10 | she occupies more than half the image height | size_in_frame | y | y |

## L4 -- lookout, beat 4 (painterly)

| id | claim | field | owner | model |
|---|---|---|---|---|
| L4-1 | the camera is above them, looking down | camera | y | y |
| L4-2 | both figures are in frame in full, with room visible around them | camera | y | y |
| L4-3 | a figure is coming up through an opening in the floor | staging.action | y `*` | n |
| L4-4 `†` | its hand is closed round her wrist, touching it | contact | n `*` | y |
| L4-5 | her arm is pulled straight, not bent at the elbow | contact | n | n |
| L4-6 | she is down on one knee | staging.action | n `*` | y |
| L4-7 | its teeth are showing | staging.action | y | y |
| L4-8 | a lamp standing on the floor is the only light source in the frame | lighting | y `*` | n |
| L4-9 | its body below the shoulders is hidden by the raised hatch lid | occlusion | n | n |
| L4-10 | she occupies less of the image height than it does | size_in_frame | n `*` | y |

## Totals

71 claims: 30 horror-comic, 41 painterly. 5 are contact claims (`†`).
The scope doc's floor is roughly 60, and the margin is deliberate --
probe 1's headline numbers moved by a full point of recall on a single
ambiguous item.

## Results

### The numbers

| | items | agreement | recall on owner's failures | precision |
|---|---|---|---|---|
| **all claims** | 71 | 44 (62%) | **18/28 (64%)** | 18/33 (55%) |
| excluding contact (`†`) | 66 | 42 (64%) | 18/26 (69%) | 18/32 (56%) |
| horror-comic only | 30 | 21 (70%) | 7/11 (64%) | 7/12 (58%) |
| painterly only | 41 | 23 (56%) | 11/17 (65%) | 11/21 (52%) |

Recall is failures found: of the 28 claims the owner marked as not
honoured, the model marked 18. Precision is the share of the model's 33
complaints the owner agreed with. Excluding the contact rows -- the
class the model provably cannot judge -- moves recall by five points and
precision by one.

### Verdict against the criteria fixed in advance

The scope doc's third branch: **recall < 80% -> it is missing real
failures. Stop. The problem is the vision model against this material,
not the prompt.** 64% is not near the line, and the same number on both
styles separately (64% and 65%) says it is not an artifact of one run or
one look.

The second branch -- usable for arm comparison where a consistent bias
cancels -- does not rescue it. That branch is conditioned on recall
>= 90% precisely because a checker that misses a third of the failures
measures a third less of whatever an arm changed.

Note what did **not** happen: probe 1's disagreements ran one way,
owner-yes/model-no, which is what made "the claims are badly written"
the right diagnosis. Repairing the claims removed that asymmetry
(18 one way, 9 the other) without improving agreement -- it fell from
69% to 62%. The bias was real and is fixed; what is left underneath it
is disagreement, which is the thing that cannot be written around.

### Do not run probe 3 by rewriting the claims

Several disagreements below are arguably still claim defects -- L4-8's
"the only light source in the frame" against a cab with grey daylight in
every window, L4-3's "coming up through an opening in the floor" against
a figure standing beside an open hatch. That observation is recorded
because it is true, and acted on **not at all**: a third sheet written
to make the checker agree is the eval-overfitting the scope doc names,
and it would produce a number that measures the claim author rather than
the instrument.

### Integrity check

The scoring is only meaningful if each image was sent with its own
claims. `L4`'s image was opened after both columns were locked and
matches its beat exactly -- cab interior, open floor hatch, lamp on the
grate, a hand closed round her wrist. The driver maps claims to images
by sheet id uniformly, so one correct pairing is strong evidence for all
seven.

### The owner used no `?` answers

Zero of 71, so the first-glance/considered split that probe 1's B3-9
motivated bought nothing here and no row needed a second look. The model
used `?` four times. Worth keeping the verdict set as it is -- one
ambiguous item is what moved probe 1's headline by a point of recall --
but it is not currently earning its keep on the human side.

### Where the owner's failures landed, by field

| field | failed | of |
|---|---|---|
| contact | 4 | 4 |
| staging.action | 8 | 24 |
| camera | 6 | 16 |
| lighting | 4 | 10 |
| size_in_frame | 3 | 6 |
| occlusion | 2 | 4 |
| intensity | 1 | 1 |

**Every contact claim failed.** Five claims is far too few to conclude
from, and it is the same direction as
[0072](../decisions/0072-facing-and-the-threats-own-face.md)'s premise
and probe 1's blind spot: two-body physical facts are both the hardest
thing to render and the hardest thing to check. This is the one number
here worth following up, and following it up means more images, not
more claims per image.

### The 27 disagreements

`*` in the tables above marks each of these rows.

| id | owner | model | claim |
|---|---|---|---|
| B2-1 | y | n | the frame is cropped at or above her waist |
| B2-6 | y | ? | one of her hands is inside a laundry cart |
| B2-9 | y | n | the light source is behind her, not in front of her |
| B2-10 | y | n | she occupies between a quarter and a half of the image |
| B4-3 | n | y | she is leaning backwards onto a wheeled cart |
| B4-4 | n | y | one of her forearms is raised between her face and him |
| B5-2 | y | n | both figures are seen side-on, in profile |
| B5-3 `†` | n | y | his hand is closed round her forearm, touching it |
| B5-4 | n | y | her arm is pulled straight, not bent at the elbow |
| L1-2 | n | ? | the camera is level with her head |
| L1-4 `†` | y | n | both of her hands are on a rail |
| L1-6 | n | y | the strongest light comes from outside the window ahead of her |
| L2-1 | n | y | the camera is below it, looking up |
| L2-2 | y | n | the whole figure and the trees around it are in frame |
| L2-3 | y | ? | a lit lamp in its hand is the only light source in the frame |
| L2-6 | n | y | its chin is tipped up |
| L2-8 | n | ? | its eyes are directed upward |
| L2-10 | y | n | its head and shoulders are clearer than its legs |
| L2-11 | y | n | it occupies between a quarter and a half of the image height |
| L3-2 | y | n | the frame is cropped at or above her waist |
| L3-7 | y | n | the light on her face comes from below it |
| L3-8 | y | n | her eye sockets are in shadow |
| L4-3 | y | n | a figure is coming up through an opening in the floor |
| L4-4 `†` | n | y | its hand is closed round her wrist, touching it |
| L4-6 | n | y | she is down on one knee |
| L4-8 | y | n | a lamp standing on the floor is the only light source in the frame |
| L4-10 | n | y | she occupies less of the image height than it does |

### How it was run

**Model column**, 2026-09-22: all 71 claims answered by
`anthropic/claude-sonnet-5` -- the `previz_review` pin, chosen because
it is vision-capable and is not the model that drew the images. One call
per image, claims only: the model never saw the beat text, the style, or
anything about why the image was generated. Answers were written to the
gitignored `evals/results/probe2_model_answers.json` and not opened
until the owner column existed.

`evals/fidelity_probe.py` is the driver. It parses the claims out of
this file rather than restating them, so the two columns cannot drift,
and its `--dry-run` runs in CI so a change to this sheet's shape cannot
break it silently. The instruction sent with each image is that file's
`INSTRUCTIONS`.

**Owner column**, 2026-09-22: answered at a glance, in order, seven
images one at a time, with the model column sealed.

One incident worth recording, since it bears on any shipped design: the
first model pass died on an SSL error partway through and the retry
succeeded with no other change. Seven calls carrying a 1-2MB image each
is a payload size the rest of this project never sends.
