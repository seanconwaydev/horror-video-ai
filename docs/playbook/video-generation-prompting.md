# Video generation prompting — playbook

Last updated: 2026-08-27

Practical findings for prompting previz (stage 8) and video generation (stage 9) — see [pipeline.md](../pipeline.md). Sourced from real 2026 prompting guides (including OpenAI's own official Sora 2 Prompting Guide) and from real generations run against this project's own scenes, not guessed at. This is a pool of grounded technique, not a locked spec — expect it to grow as more scenes get tested.

## The 7-part shot structure

Every single beat/shot, whether it's the whole prompt or one timecoded segment of a longer one, should specify: **subject, action, setting, camera, lighting, style, audio**. Naming actual cinematography language (a push-in, a static wide, a whip-pan) gets more reliable results than describing the same move in plain English — Sora 2 specifically has strong cinematography literacy. Audio is easy to forget: Sora 2 generates it natively and expects to be told what to hear, not left to guess.

## Timecode notation for multi-beat prompts

OpenAI's own Sora 2 Prompting Guide documents this format directly:

```
(0–3s): [Shot 1 — subject, action, camera, ...]
(3–6s): [Shot 2 — what changes, new action/angle, ...]
(6–10s): [Shot 3 — resolution/final beat, ...]
```

**Ceiling: 2–3 sequential beats per single generation call**, not more. Actions read best as concrete counted beats ("takes four steps, pauses half a second, extends arm"), not abstract description.

**Counterintuitive finding worth designing around:** stitching two separately-generated shorter clips can outperform one longer single generation covering the same ground (the guide's own example: two 4s clips beat one 8s clip). Practical rule of thumb: up to ~2–3 beats, one call; past that, generate each beat as its own shorter clip and stitch, rather than pushing one call to cover more ground.

## Character consistency

A locked character block, reused **verbatim** in every beat/prompt that character appears in:

```
CHARACTER: [name/id]
ROLE: main | secondary | background
FACE/BUILD: [age range, build, face shape, skin tone]
HAIR: [cut, color]
WARDROBE (signature — must not change): [1–2 unmistakable pieces]
WARDROBE (flexible): [things that can plausibly vary]
DISTINGUISHING DETAIL: [one memorable anchor — a scar, glasses, an accessory]
REFERENCE IMAGE: [path, once one exists for this character]
```

**Text has a hard ceiling.** Current models reconstruct a character from scratch on every generation rather than maintaining a fixed identity — so even a great text block will drift given enough separate shots. The actual highest-leverage lever for a character who needs to stay consistent *across separate scenes/videos* is a small reference-image set (2–6 images per character: a headshot, a full-body shot, ideally a multi-angle turnaround), reused as input across generations — not more adjectives. Bump to 3–4 combined references when a scene has two named characters.

**Known, current, industry-wide limits** (not something to expect this project to solve): some drift is normal even doing everything right; two characters interacting in one shot still causes identity blur on every platform as of mid-2026; identity preservation holds up to roughly 4 subjects + 1 scene reference before it degrades.

**Change one variable per attempt.** Applies to iterating on a single beat (camera OR subject motion, not both at once, if a shot isn't landing) and to isolating what's causing drift between shots (new setting/same angle, or new angle/same lighting — never both at once).

## What one image can and can't anchor

One reference image reliably anchors a shot's **starting instant** — its identity, wardrobe, framing. It does **not** reliably guarantee a specific trajectory or ending several seconds later just because the text says so; "guiding the AI to a specific, pre-planned ending state remains a challenge" even from one clean starting image. This is a structural model limitation (limited long-term scene memory, motion magnitude constraints), not a prompting mistake to fix with more adjectives.

**Start + end frame generation is a real, named, documented control method** — two images instead of one, one for the beat's first frame and one for its last, constraining the model to land there. Worth trying specifically when a beat's outcome matters a lot, rather than assuming a better-written ending will get you there from a single starting image.

**Image quality is its own variable**, independent of prompt quality — higher-resolution, cleaner source images measurably improve motion and photorealism.

## Realistic iteration expectations

Running 3–4 generations of the same beat and picking the best is described as **standard professional practice**, not a sign something's broken. Budget for it rather than expecting one clean take.

## Content moderation

Sora 2 and Gemini image generation both enforce provider-side content policies (violence, weapons, self-harm, sexual content, hate speech, dangerous behavior, real-person likeness misuse), and Sora specifically **text-scans the prompt itself before generation starts**, not just the output -- a request can fail with `moderation_blocked` before any frame is even rendered. This scans contextually, not just for a literal blocklist: a real test prompt describing an agent sprinting across a rooftop, leaping a gap, and going through a door -- no weapons, no violence, no injury described -- was blocked once wording like "tactical jacket" and "shoulder-checks it open" was in the mix, then passed cleanly once rewritten with neutral, film-direction language ("black jacket," "passes through the doorway") describing the exact same beats. Nothing about the underlying scene changed, only word choice.

**Practical takeaway:** favor neutral, cinematography-focused verbs and avoid combat/military/forced-entry-coded words even when describing completely non-graphic action content -- "runs and leaps" over "sprints and breaches," a described camera move over an aggressive verb. This isn't about disguising real violent content; it's that ordinary action-genre content can trip a conservative classifier on word choice alone, and rewording it doesn't change what's actually depicted.

## How this maps onto this project's pipeline today

- `previz._build_prompt` (stage 8) and `video_generation` (stage 9) currently share the **exact same prompt string**, reused verbatim — a still-image prompt doing double duty as a multi-beat video prompt. That's a known gap, not a design choice: the full pipeline vision's deferred stage 6 (shot list) / stage 7 (per-scene video prompts) exists specifically to give each of these its own dedicated prompt, and this session's real research independently confirmed shot-list-first is what's actually working for other creators, not just internally-consistent architecture.
- `--video-prompt` (CLI flag) is the current stopgap: it lets a hand-written, video-specific prompt be tested against an already-approved previz image without paying for a fresh research/fact-check/previz pass.
- Known bug to fix whenever stage 7 gets built (or sooner): previz's prompt still says "a generic, unnamed person... not a specific named historical figure unless stated," which self-contradicts as soon as the subject is a real, fact-checked named person (e.g. Tang Shizeng). Noted, not yet fixed.

## Real evidence so far (small sample, one comparison)

Same previz image, two prompts, on the Hoh Xil expedition scene: a short generic description let Sora invent an unprompted midday-to-golden-hour lighting arc and an unrelated macro insert shot. A timecoded, 3-beat, 7-part-structured prompt on the identical image produced output that tracked the specified beats instead, with neither the invented lighting arc nor the random insert, while character consistency stayed equally strong in both. One data point, encouraging, not proof at scale yet.
