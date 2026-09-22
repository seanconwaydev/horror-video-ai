# 72. A pair has a facing, and the threat has a face

Date: 2026-09-21

Status: Accepted

## Context

A four-beat horror run (`a lookout scanning the treeline sees her own
tower's light moving through the trees below her`) was reviewed beat by
beat by the project owner. Checking each judgement against the plan text
that produced it splits the complaints cleanly in two: some the plan
stated correctly and the image ignored, and some the plan never stated at
all. Only the second kind is actionable here.

The plan was right and the render was not on: a lanyard worn backwards, a
pair of legs that do not resolve, and a protagonist further from the
window than the staging entry that said she "presses her fingertips flat
against the pane". Those are render lottery and no rule addresses them.
(Note on the first: a real person can wear a lanyard backwards, but the
viewer has no way to read it as a choice, so it lands as a generation
error. Plausible is not the bar.)

Five things the plan never said:

1. **The pair had no shared axis.** Beat 3 put the threat rising out of a
   floor hatch and the protagonist backed away from it. Its staging entry
   said "its eyes fixed up onto her face"; hers said "her eyes locked
   down on the hatch". Both correct, both independent, and the image came
   back with the threat staring into the camera. This is exactly the
   failure [0071](./0071-beats-describe-one-camera-view.md) diagnosed for
   physical contact — `staging` describes one character at a time, so a
   two-body fact written there is two unrelated sentences — and `contact`
   fixed it only for bodies that touch. Beat 4, which had a `contact`,
   was the beat whose entanglement the owner singled out as working.
   `_build_beat_prompt` did carry a generic fallback line ("their gazes,
   distances and body angles have to agree"); it fired on beat 3 and lost.

2. **The threat had no face.** Every facial-expression rule in the
   planner is written for the protagonist, and the threat block says so
   outright ("the *protagonist's* own motivation and emotional
   register"). Beat 3's antagonist was pure mechanics — clamps, hauls,
   eyes up — and rendered "a little confused, more than like he's trying
   to hunt someone". Beat 4's was "its face lowered to hers", with no
   expression, and its body language read as "holding her, saving her
   from danger".

3. **Eye direction was required of `beat.action` but not of each
   `staging.action`.** Beat 4's `action` read "she stares past her own
   pinned arm at the thing crouched over her"; her staging entry named no
   eyes at all. That beat is where the owner reported her staring off
   into the distance in three of four candidates.

4. **Concealment was only ever a solid object.** Every occlusion rule and
   example names a pillar, a door frame, a parked car, a trunk. The run
   was set in a fogged-in forest; beat 2's threat was hidden behind a
   pine trunk and otherwise fully lit, and the owner's note was that fog
   covering him partially or completely was the obvious move and was not
   taken. The fog rendered everywhere except on the one figure it should
   have been hiding.

5. **Fear had an arc requirement but no ceiling, and the location did not
   escalate at all.** `intensity` must change and reach a peak, but that
   field is about physical force; the emotional-arc rule only asks for a
   distinct point per beat. A protagonist a pace from a monster in open
   view, looking mildly concerned, satisfies every existing rule. Separately,
   beat 4's overturned chair — the planner's own instinct, written into
   `intensity` — did more to sell the struggle than the description of the
   struggle, and nothing in the prompt asks for that.

## Decision

**`Beat.facing`** — the single line between two characters who are *not*
touching, written once from the camera's point of view: which way each is
turned relative to the other and how much space is between them. Optional;
empty for a one-character beat and for one where `contact` already
describes the shape the two of them make. It leads the image prompt
alongside `contact` and `intensity`, ahead of the per-character blocks,
and it replaces the generic "must react to each other" line, which stays
only as the fallback for a multi-character beat that states neither.

`facing` also joins `BEAT_QUICK_EDIT_FIELDS` and the text shown at the
candidate-review prompt, for 0071's reason: whether two characters are
aimed at each other rather than at the lens is one of the fastest things
a human can check and one of the things these images fail most often.

Four prompt rules, three of them folded into the existing bullet that
already owns the concept rather than appended as new ones — the prompt is
past thirty-five bullets and
[0058](./0058-delete-rules-by-judgement-not-ablation.md) left it with no
mechanism for shedding any:

- The eye-direction bullet now applies to every `staging` entry, not only
  to the beat's own `action`.
- The `occlusion` bullet now admits atmospheric occluders — fog, smoke,
  rain, spray, unlit darkness — held to the same standard as a solid one,
  naming what survives them. What fails to render is a vague adjective,
  not a soft occluder. The threat block's own example list gains the
  same.
- The threat block gains a rule giving the threat a predatory face in its
  own staging entry, and a rule making the beat where the protagonist
  first sees it in the open the top of her fear arc, written as panic.
- A new unconditional rule makes the location carry escalation: later
  beats sharing a `location_id` must show physical evidence of what has
  already happened there, and must never reset a space to undisturbed.

## Consequences

`facing` is the second field to exist because `staging`'s per-character
decomposition cannot express a fact about a pair. That is now a pattern
rather than a one-off, and the next such fact should get its own field on
`Beat` instead of being written twice into two entries.

The complexity budget rule counts `facing` among the fields whose
contents share a beat's five-thing ceiling, so a beat that fills it is
spending budget it must take from somewhere else. That is intended: on
the evidence of beats 3 and 4, where the two characters are aimed is
worth more than a fifth detail.

The threat's face and the fear ceiling are both genre-gated, living in
the block that only assembles when genre or tone signals a threat. A
non-horror scene with an antagonist gets neither. That matches how every
other threat rule here is scoped and is not worth changing until a real
run needs it.

Whether any of this works is a question for the next run's judgements.
None of these rules has evidence behind it yet beyond one run's review —
which is the same standing on which most of the existing rules were
written, and the same reason 0058 wants them judged rather than accumulated.
