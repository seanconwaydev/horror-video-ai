# 40. The character reference is an in-world frame, not a turnaround sheet

Date: 2026-09-16

Status: Accepted

Refines [0024](./0024-previz-image-conditioning.md), which introduced reference-image conditioning without specifying what the reference should look like.

## Context

Every beat image is generated as an *edit* of the character reference. Whatever that reference establishes as normal, the beats inherit -- and the reference was specified as the opposite of everything this project wants a beat to be:

```
ACTION:   Standing in a simple, neutral, relaxed pose... calm neutral expression
CAMERA:   Medium-full shot, eye-level, centered
LIGHTING: Soft, even, shadowless studio-quality light
SETTING:  A plain, softly out-of-focus neutral backdrop
```

So every beat asking for a low angle, one hard source, an off-axis camera and visible fear had to fight its own anchor on four separate axes before it could start.

This was measured rather than argued. Two controlled experiments (`evals/reference_anchor.py`), each four or three arms over the same three beats, varying only the character reference, scored blind by forced choice on action, camera and mood:

| arm | adherence | identity held across 3 beats |
|---|---|---|
| in-world sheet, wardrobe pinned | **9/9** | no |
| in-world sheet, wardrobe loose | 5/9 | no |
| no references at all | 3/9 | no |
| location reference only | 1/9 | no |
| face-and-shoulders only | 0/9 | no |
| **neutral turnaround (shipped)** | **0/9** | yes |

What ships today was chosen zero times out of nine, twice. The in-world sheet with a pinned wardrobe was chosen nine times out of nine, and was also the first reference in twelve attempts to render the hardest beat's pose correctly -- a character flat on her back under a duvet with her head turned toward the door, which every other arm had failed.

Two mechanisms, both visible by opening the two reference images side by side. The neutral sheet renders as a costume catalogue page: a grey void, flat light, a straight-on standing figure, no expression. The in-world sheet renders as a frame from the film: deep blacks, one hard pool of light, a real room with depth behind her, fear on her face, weight off-centre.

And the neutral sheet renders **two figures**. Listing both `wardrobe_signature` and `wardrobe_flexible` makes the model produce a turnaround with an alternate outfit alongside, so every beat was conditioned on an image containing two people.

## Decision

`build_character_sheet_prompt` produces an in-world frame:

1. **A real space with depth**, not a backdrop.
2. **One hard, directional source** throwing a defined shadow, not shadowless studio light.
3. **Off-centre, slightly below eye level**, not centred and eye-level.
4. **Caught mid-movement, alert and uneasy**, not standing calmly.
5. **Exactly one person in frame** -- stated explicitly, with "no turnaround, no costume sheet, no second figure, no inset panel".
6. **One wardrobe, stated with explicit negatives.** `wardrobe_flexible` is dropped from this prompt: it is what produced the second figure, and pinning the wardrobe is what took the in-world arm from 5/9 to 9/9.

## Consequences

**A known regression is being accepted deliberately.** The neutral sheet was the only arm that held identity across three beats; the in-world sheet drifts. The trade is 9/9 against 0/9 on composition, versus "holds identity" against "mostly holds identity" -- and the shipped sheet's identity was not perfect either (a distinguishing detail moved between beats). Composition has no other lever available; identity drift has several untried ones. This decision takes the measured win now and treats drift as the next problem, not as a reason to keep a reference that loses every comparison.

**The generalisable lesson, which outlives this prompt**: a conditioning image is a style-and-world exemplar, not an identity token. It teaches the model what "normal" looks like for everything downstream of it. A reference should look like the shot you want, not like a specification of the character.

Deliberately **not** included here, because it is inferred rather than measured: a beat's `SUBJECT` line carries the character *id* (literally "wren"), so the most prominent line in the prompt conveys nothing, and the character's sex is left to be inferred from a physical description that can skew the wrong way -- one beat rendered the character as male. That is a plausible cause with no experiment behind it yet, and it gets its own test rather than riding along with a result that was measured.

Also unresolved, surfaced by the same run: a beat can specify a camera position and a lighting detail that camera cannot see. One beat asked for a low corner camera *and* a thin bar of light under a door whose bottom edge that camera cannot show; the model improvised literal footprint shapes on the floor. That is an internally inconsistent plan, the same class as a beat whose `location_id` contradicts its own action, and it needs its own check.
