# 61. The threat must act on the person, and `blocking` states place only

Date: 2026-09-19

Status: Accepted

Repairs two rules rather than replacing a decision. The interaction rule
comes from [0049](./0049-per-character-staging-in-beats.md); the `blocking`
field is [0059](./0059-blocking-and-size-replace-frame-position.md)'s, and
this narrows what may be written in it.

## Context

The first run in a scenario deliberately unlike the car park every rule had
been tuned on -- a sedan cabin at night, `--style painterly` -- produced
images the project owner could not use. His description is the diagnosis:
"it mostly reads as the two characters just hanging out in the car
together, and there's no escalation... the girl tends to look off into
'somewhere' in the distance while the figure is kinda just posing and
chilling."

Both halves of that are visible in the prompts the model was sent.

**The threat never acted on the woman.** Its `action` across all three
beats: "braces its shoulders low into the rear bench cushion, one crooked
hand flattened on the seat fabric beside its hip"; "both hands planted flat
on the seat cushion ahead of its knees"; "both long pale hands closed on
the top edge of the seat back". Three beats, three actions performed on
upholstery. Nothing it does involves her.

0049's interaction rule was supposed to prevent exactly this, and has a
hole. It asked that "at least one `staging` entry must name what that
character does BECAUSE OF another character", and its three worked examples
-- "a flinch away from them, a step that puts a pillar between them, a hand
that stops halfway to a pocket" -- are all *victim* behaviours. So the
cheapest way to satisfy it is the protagonist reacting, which the plan duly
did ("her torso rotated a few inches off the seat back because of the shape
behind her"), leaving the antagonist free to do nothing to anyone. A rule
asking for *a* relationship gets the cheapest one available.

**Orientation was stated twice, and the two statements disagreed.** Beat 1
sent `DOING: her torso rotated a few inches off the seat back because of
the shape behind her` and `STANDS: ... facing the windscreen with the
figure on the rear bench directly behind her headrest`. The image model
obeyed the `blocking`: she looks out of the windscreen at nothing while the
threat sits behind her unremarked. Beat 2 repeats the pattern. Only beat 3
turns her toward it in both fields.

This one is 0059's own doing. That ADR let `blocking` carry orientation and
cited it as the reason not to add a gaze field -- "facing back along the
aisle toward her" was read as evidence that gaze arrives free. It does,
when the two fields agree, which they did in the eval prompts because the
same hand wrote both. Given a real planner they can contradict each other,
and then a fact stated in two places is adjudicated by the model. That is
the failure [0057](./0057-drop-the-duplicate-action-line.md) removed from
the beat prompt, reintroduced in a field created after it.

## Decision

**The non-focal character's own `action` must take another character as its
object.** Reaching for her, closing a hand on her arm, putting its face at
hers, blocking the door she is moving toward. An action performed on
scenery does not satisfy it, however menacing the scenery is. The rule now
says so with the upholstery example attached, because the abstract version
was already there and lost.

The focal character's reaction is still required, and is now explicitly
stated not to discharge the rule on its own.

**`blocking` states place and nothing else.** Which way a character faces
moves to `action`, with the rest of what the body is doing. The rule
carries the windscreen failure as its reason, so a later session does not
helpfully reinstate orientation as a clarification.

No new field. Orientation could have had one -- that is what
[0054](./0054-one-fact-per-field.md)'s rule would suggest -- but the body
turn is already physical description, which is what `action` is for, and a
fifth staging field on the same day as the fourth is churn ahead of
evidence.

## Consequences

Both changes are unmeasured. This ADR records a diagnosis and a repair, not
a result; the next run in a scenario with room to move is the test. The
first of the two is the one expected to matter, since the difference
between a figure posing and a figure attacking is most of what a horror
beat is.

A scenario lesson is worth recording alongside them, in the owner's words:
"there isn't too much to 'do' with such a confined space." A sedan cabin
permits almost no action beyond posture changes on a bench, so the planned
escalation -- lying, then kneeling up, then leaning over the seat back --
had nowhere to go. That is not a prompt failure and no rule here fixes it.
Scene selection is a lever on image quality in its own right, and this
project has not treated it as one.
