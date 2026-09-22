# Probe 2: prompt-fidelity claim sheet

The re-probe that
[prompt-fidelity-checking-scope.md](./prompt-fidelity-checking-scope.md)
requires before the design can be accepted or rejected. That file fixes
the decision criteria in advance; this one holds the sheet and, once
answered, the verdicts.

**Status: unanswered.** Nobody has opened these images yet -- the claims
below were written from the beat text alone, the same discipline probe 1
used.

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
| B2-1 | the frame is cropped at or above her waist | camera | | |
| B2-2 | the camera is level with her face, neither above nor below it | camera | | |
| B2-3 | she is seen from a three-quarter angle, not square-on and not in profile | camera | | |
| B2-4 | her mouth is open | staging.action | | |
| B2-5 | her eyes are turned to one side rather than toward the camera | staging.action | | |
| B2-6 | one of her hands is inside a laundry cart | staging.action | | |
| B2-7 `†` | her other hand is closed round the cart's rail | staging.action | | |
| B2-8 | a wheeled laundry cart stands beside her at hip height | staging.blocking | | |
| B2-9 | the light source is behind her, not in front of her | lighting | | |
| B2-10 | she occupies between a quarter and a half of the image | size_in_frame | | |

## B4 -- laundry, beat 4 (horror-comic)

| id | claim | field | owner | model |
|---|---|---|---|---|
| B4-1 | the camera is level with their faces | camera | | |
| B4-2 | she is visible from the waist up or lower, not cropped to head and shoulders | camera | | |
| B4-3 | she is leaning backwards onto a wheeled cart | staging.action | | |
| B4-4 | one of her forearms is raised between her face and him | staging.action | | |
| B4-5 | her mouth is open | staging.action | | |
| B4-6 | he faces her with his teeth showing | staging.action | | |
| B4-7 | there is one other person in the frame with her, and no more | staging | | |
| B4-8 | she is larger in the frame than he is | size_in_frame | | |
| B4-9 | neither figure is hidden or cut off by an object in front of them | occlusion | | |
| B4-10 | a single overhead light fixture is the only light source in the frame | lighting | | |

## B5 -- laundry, beat 5 (horror-comic)

| id | claim | field | owner | model |
|---|---|---|---|---|
| B5-1 | the camera is below them, looking up | camera | | |
| B5-2 | both figures are seen side-on, in profile | camera | | |
| B5-3 `†` | his hand is closed round her forearm, touching it | contact | | |
| B5-4 | her arm is pulled straight, not bent at the elbow | contact | | |
| B5-5 | her eyes are directed at the hand on her arm | staging.action | | |
| B5-6 | his teeth are showing | staging.action | | |
| B5-7 | he is barefoot | staging.action | | |
| B5-8 | his face is darker than her arm | lighting | | |
| B5-9 | spilled sheets lie on the floor around them | staging.blocking | | |
| B5-10 | neither figure is hidden or cut off by an object in front of them | occlusion | | |

## L1 -- lookout, beat 1 (painterly)

| id | claim | field | owner | model |
|---|---|---|---|---|
| L1-1 | we see her from behind -- her back is toward the camera | camera | | |
| L1-2 | the camera is level with her head, neither above nor below it | camera | | |
| L1-3 | she is visible from the waist up or lower, not cropped to head and shoulders | camera | | |
| L1-4 `†` | both of her hands are on a rail | staging.action | | |
| L1-5 | binoculars hang on a strap at her chest | staging.action | | |
| L1-6 | the strongest light comes from outside the window ahead of her | lighting | | |
| L1-7 | that light is amber, and the light behind her is white | lighting | | |
| L1-8 | she is standing at the glass, not across the room from it | staging.blocking | | |
| L1-9 | she occupies between a quarter and a half of the image height | size_in_frame | | |
| L1-10 | fog is pressed against the outside of the glass | action | | |

## L2 -- lookout, beat 2 (painterly)

| id | claim | field | owner | model |
|---|---|---|---|---|
| L2-1 | the camera is below it, looking up | camera | | |
| L2-2 | the whole figure and the trees around it are in frame | camera | | |
| L2-3 | a lit lamp in its hand is the only light source in the frame | lighting | | |
| L2-4 | tree shadows stretch away from the lamp | lighting | | |
| L2-5 | it carries the lamp in one hand | staging.action | | |
| L2-6 | its chin is tipped up | staging.action | | |
| L2-7 | its teeth are showing | staging.action | | |
| L2-8 | its eyes are directed upward | staging.action | | |
| L2-9 | it is walking between two tree trunks | staging.blocking | | |
| L2-10 | its head and shoulders are clearer than its legs, which fade into mist | occlusion | | |
| L2-11 | it occupies between a quarter and a half of the image height | size_in_frame | | |

## L3 -- lookout, beat 3 (painterly)

| id | claim | field | owner | model |
|---|---|---|---|---|
| L3-1 | the camera is below her, looking up | camera | | |
| L3-2 | the frame is cropped at or above her waist | camera | | |
| L3-3 | one of her forearms is raised across her face | staging.action | | |
| L3-4 | her mouth is open | staging.action | | |
| L3-5 | her eyes are directed downward and to one side, not at the camera | staging.action | | |
| L3-6 `†` | her other palm is flat on a table's edge | staging.action | | |
| L3-7 | the light on her face comes from below it | lighting | | |
| L3-8 | her eye sockets are in shadow | lighting | | |
| L3-9 | a chair lies tipped on its side behind her | intensity | | |
| L3-10 | she occupies more than half the image height | size_in_frame | | |

## L4 -- lookout, beat 4 (painterly)

| id | claim | field | owner | model |
|---|---|---|---|---|
| L4-1 | the camera is above them, looking down | camera | | |
| L4-2 | both figures are in frame in full, with room visible around them | camera | | |
| L4-3 | a figure is coming up through an opening in the floor | staging.action | | |
| L4-4 `†` | its hand is closed round her wrist, touching it | contact | | |
| L4-5 | her arm is pulled straight, not bent at the elbow | contact | | |
| L4-6 | she is down on one knee | staging.action | | |
| L4-7 | its teeth are showing | staging.action | | |
| L4-8 | a lamp standing on the floor is the only light source in the frame | lighting | | |
| L4-9 | its body below the shoulders is hidden by the raised hatch lid | occlusion | | |
| L4-10 | she occupies less of the image height than it does | size_in_frame | | |

## Totals

71 claims: 30 horror-comic, 41 painterly. 5 are contact claims (`†`).
The scope doc's floor is roughly 60, and the margin is deliberate --
probe 1's headline numbers moved by a full point of recall on a single
ambiguous item.

## Results

Not yet run.
