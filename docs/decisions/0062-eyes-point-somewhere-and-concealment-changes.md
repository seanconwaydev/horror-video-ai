# 62. The eyes point at something, and the threat's concealment changes when it is noticed

Date: 2026-09-19

Status: Accepted

Extends two rules already in `scene_planning.py` rather than adding
bullets: the facial-expression rule, and the threat-presence rule
[0060](./0060-threat-is-hidden-not-distant.md) last rewrote. Nothing is
superseded.

## Context

The car-cabin run's images were unusable, and
[0061](./0061-the-threat-must-act-on-the-person.md) covers why. But the
project owner's account of the same images named two near-misses -- beats
that would have worked with one thing changed -- and those are a different
kind of evidence from a failure. In his words, deliberately offered as
positive signal: "i'm trying to share more 'what DOES work', 'what almost
works', because we need some positive signals here."

**On beat 2:** "she looks scared but is just looking randomly... if she was
'trying to look behind herself to the right' where humans will move their
eyeballs as far right as they can when they sense something is behind them
and they're slowly turning to see it... this could be an effective beat."

The expression rule already requires a named emotion, with "her jaw
tightens, eyes wide with fear" as its worked example. It says nothing about
where the eyes are *pointed*. An expression is not a direction, and a
frightened face aimed at nothing reads as distraction.

This also refines an earlier finding. Across two evals it looked settled
that gaze could not be specified usefully, because a horror figure's eyes
render as featureless white or black and gaze had to be read off posture.
That holds for the *threat*. It does not hold for the human character,
whose eyes are rendered normally -- and hers were unspecified, so they
pointed nowhere.

**On beat 3:** "it's better, image 2 is almost quite good. if the monster
looked more sinister and like he was 'ok she sees me, i'm going to stop
sort of hiding and go all out!', it'd be pretty cool."

That is a story beat the schema can express and no rule asks for. 0060
established that the threat should be hidden. Nothing says its hiddenness
should ever *change*, so a plan can hide it equally in every beat and
produce, in the owner's phrase, three poses rather than a scene. The
escalation rule is adjacent -- "if a character gets closer, more
threatening, or more exposed... that change must show in the BODY" -- but
it governs how a change is written, not whether the threat's relationship
to being seen is one of the things that changes.

## Decision

**The expression rule gains a direction.** A beat's `action` must state
where the eyes are pointed as well as what the face is doing, aimed at
something named in the beat, with the sensed-from-behind case spelled out:
eyes cut hard to one side, whites showing on the far side, the head only
starting to follow.

**The threat rule gains an arc.** The threat's concealment must change
across the scene, hinged on the moment it is noticed: hidden while unseen,
then committing once seen. The beat where the protagonist registers it gets
a visibly smaller `occlusion` than the beat before and an `action` that
comes out from behind whatever covered it.

Both are extensions to rules that already exist, not new bullets.
[0058](./0058-delete-rules-by-judgement-not-ablation.md) is the reason:
this prompt got to 34 rules by adding one whenever something failed, and a
33rd bullet restating a 12th is how that happens.

## Consequences

Unmeasured, like 0060 and 0061. Three prompt-rule changes now sit unproven
on top of one another, which is exactly the accumulation 0058 warned about
-- with the difference that each came from a specific observed failure with
the owner's own words attached, rather than from reasoning. If the next run
does not move, the rules are not the lever and the honest next step is to
stop adding them.

The concealment arc has a cost worth naming: it pushes every horror scene
toward the same three-act shape -- hidden, noticed, committed. That is a
strong and common horror structure, and it is also a house style. The
project has been deliberate about not locking to one look; locking to one
*story shape* is the same risk in a place nobody is watching for it.
