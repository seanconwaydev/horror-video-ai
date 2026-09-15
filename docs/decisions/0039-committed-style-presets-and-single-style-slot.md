# 39. Style is a library of committed presets, stated once, and a beat cannot claim one

Date: 2026-09-15

Status: Accepted

Supersedes the implementation of [0033](./0033-single-authoritative-style-source.md), whose decision was right and whose mechanism was not.

## Context

0033 established that a run should have a single authoritative style source. The implementation did not remove the competing source -- it appended a third instruction declaring a winner. Every beat prompt shipped this:

```
STYLE: 35mm, deep focus, fine grain, cold blue-black grade with warm lamp highlights
OVERRIDING STYLE REQUIREMENT (takes priority over anything above): Deliberately
stylized/cartoon illustration, loosely interpreted -- ... is one welcome direction
among several ... softer, rounder, more conventional cartoon/animation looks are
equally valid ... a cute or wholesome character design is a legitimate choice,
not something to avoid. Explicitly NOT photorealistic ...
```

A photographic instruction, then ~100 words that offer several directions, disclaim each, state that consistency is "not required or expected", and invite *cute and wholesome* into a horror scene -- with a note about which wins. The contradiction still reached the model, which had to adjudicate it.

Two contributing causes, both worth naming because both recur elsewhere in this codebase:

- **The hedging was deliberate, and aimed at a real goal.** Stylistic range across outputs is a genuine requirement -- the project owner has been explicit that comic-book art is one reference among several and that different videos should be free to look entirely different. That range was pursued by making one instruction broad enough to cover every option, which produces an instruction that commits to nothing.
- **A prose rule was used where a type was needed.** `scene_planning`'s prompt already told the planner not to make realism claims in a beat's `style` field. A real run emitted "35mm, deep focus, fine grain, cold blue-black grade" into it regardless. An instruction a model can ignore is the weakest available guarantee.

A blind A/B over five horror scenes settled it (harness in `evals/`, scored blind against five named criteria, key withheld until scoring finished). Committed single-source instructions beat the current construction **19-6 of 25**, winning composition, fidelity and mood, and winning **style 5-0**. A sixth scene was discarded as confounded: its committed style was photographic, so it measured a style preference rather than commitment, and re-running it with a stylized preset moved it from 0/5 to 3/5.

The one criterion the old construction won was **motion**, 3-2. That is a real finding and is not addressed here: every preset written so far describes a static graphic artform, while the hedged text drifted toward animation conventions that imply movement. Tracked as follow-up.

## Decision

1. **`_STYLE_INSTRUCTIONS` becomes a library of named, committed presets** -- `photorealistic`, `semi-realistic`, `horror-comic`, `graphic-poster`, `painterly`, `cel-shaded`, `grainy-16mm`. Every entry states one direction plus hard negatives, in 45 words or fewer. A test enforces that shape and rejects hedging vocabulary outright, so the old failure cannot quietly return.
2. **Range comes from choosing between presets, not from vagueness inside one.** Commit within a video, vary between videos. Adding a preset is the supported way to widen the range; loosening one is not.
3. **`STYLE:` appears exactly once in a prompt**, sourced only from the run's chosen preset. The "OVERRIDING STYLE REQUIREMENT" line is deleted.
4. **`Beat.style` is renamed to `Beat.cinematography`** and attached to `CAMERA`, where it cannot compete for the same slot. It is for lens, depth of field, grain and colour grade only.
5. **A realism claim in that field is a parse error**, not an overridden one -- `check_cinematography_is_not_a_style_claim` rejects art-style vocabulary, and is re-run after human edits for the same reason as [0028](./0028-scene-plan-revalidated-after-edits.md). This is the structural half: the claim can no longer be expressed, rather than being discouraged.
6. **The default style is `horror-comic`**, matching the genre committed to in [0037](./0037-horror-motion-comic-shorts-wan-via-replicate.md).
7. **`PHOTOREAL_STYLES` is exported as data**, and `--style`'s help warns about it. A controlled test the same day (`docs/playbook/failure-taxonomy.md`) found `gemini-2.5-flash-image` refused an identical violent scene 3 times in 4 when asked for photorealism and 0 times in 5 when asked for a stylized treatment. Photorealism stays a supported choice; it is no longer an unmarked one.

## Consequences

`--style stylized` no longer exists. It was the hedged value, and every measurement says it was actively harming output.

Beats from an older run log carry `style` rather than `cinematography` and will not load into the current `Beat`. No migration is provided -- run logs are records of what happened, not inputs to be replayed, and the only consumer that reads a beat back (`--video-gen-from`) uses the stored prompt string, not the beat object.

The motion result is unresolved and is the next thing to test: whether a preset can encode movement conventions (motion lines, speed blur, dynamic exaggeration) while staying as committed as these, and whether composing a beat at a mid-action moment rather than a held pose matters more than the style does. Both are A/B-able with the existing harness.

Deliberately not addressed: the character reference sheet is still generated "shadowless, even, studio-quality, calm neutral expression, eye-level, centered" and every beat is an `image_edit` conditioned on it. That is the leading suspect for beats reading as tame regardless of style, and it needs its own experiment rather than being folded into this one.
