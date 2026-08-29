# Video generation prompting — playbook

Last updated: 2026-08-29

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

**Prefer a dedicated, neutral reference shot over reusing a narrative beat as the anchor.** A real test (the Pompeii influencer scene) conditioned every later beat on an *already-busy* narrative shot (a street scene with background extras, specific lighting mood, a mid-action pose) rather than a clean, purpose-made reference. It worked well enough for face/hair/wardrobe consistency, but best practice is a separate, once-generated "character sheet" shot — neutral pose, even lighting, no narrative content — used purely as the identity anchor, never shown to the audience itself. Not yet tried in this project; worth comparing directly against the reused-narrative-beat approach next time.

## Location consistency needs its own reference, separate from character

**A location needs a canonical reference image too, not just the character.** Real, observed failure: five beats of the Pompeii scene were all conditioned on the *same character* reference (a street shot), and face/hair/wardrobe held rock-solid across all five — but two beats meant to be the same physical room (a thermopolium interior) rendered as two visibly different rooms (different wall art, different counter layout, different architecture), because nothing anchored the *place*. Character conditioning and location conditioning are separate problems with separate fixes.

The fix, consistent across every source checked: generate one canonical, no-character establishing shot of the location first, then condition every beat set there on *that* image (not on the character's reference, and not on an arbitrary earlier beat) — the same "one clean reference, reused deliberately" discipline the character block already gets. A location's reusable block looks structurally different from a shot's 7-part block — no camera field, since a location isn't shot-specific, it's the backdrop shots get composited against:

```
LOCATION: [name/id]
ARCHITECTURE: [physical, concrete structural details -- material, layout, fixed built features]
FIXED PROPS: [specific recurring items that must not change -- that exact fresco, that exact lamp]
AMBIENT LIGHT: [the place's own light quality, distinct from any one shot's lighting direction/mood]
REFERENCE IMAGE: [path, once a canonical establishing shot exists for this location]
```

Describe architecture in physical terms ("an L-shaped masonry counter with 3 embedded terracotta jars"), not aesthetic ones ("a cozy rustic counter") — concrete, checkable details survive being reused across separate generations better than mood language does.

## One image, one moment — not a multi-beat narrative

**A previz prompt describing multiple beats at once produces a collage, not a scene.** Real test: a single previz call given a full multi-beat narrative (a character checking her phone, then entering a building, then greeting someone, then eating) tried to visually satisfy every beat simultaneously — the output showed her holding up a phone *and* a second figure mid-greeting *and* a full plate of food already in the foreground, all in one frame. The fix was mechanical, not a wording tweak: split the narrative into one description per beat, each depicting exactly one instant, before ever calling the image model. This is the still-image version of the same lesson the 7-part structure and timecode ceiling already teach for video — previz has no equivalent "ceiling" guardrail yet because nothing currently stops a multi-beat description from reaching it in one call.

**Explicitly rule out on-screen text and UI chrome if the subject holds a device.** The same collaged attempt also produced garbled fake text on a phone screen, a comic-style speech bubble, and a stray caption stamped in the corner — none of which were asked for. Adding an explicit instruction ("no on-screen text, no speech bubbles, no captions, no comic-style graphics — a clean photographic frame only") eliminated all of it in the next attempt.

## Camera framing and character orientation

**A character facing away from camera, or moving out of frame into darkness, is a normal prompt choice, not a model limitation.** Confirmed by direct comparison in this project: previz images generated with no explicit orientation instruction defaulted to face-toward-camera framing every time, but a shot explicitly requesting "seen from behind, her face not visible, over-the-shoulder following angle" produced exactly that. If a shot isn't turning out to face away from camera, the CAMERA field didn't ask for it — it's not something to work around.

## Composition and negative space

**Describe what negative space actually contains, not just that it should exist.** "Use negative space" as an instruction doesn't reliably work — the model needs to know what fills the empty area ("a lone figure in the lower-right, flat grey sky filling the rest of the frame"), not just that space should be left. The direction of empty space also carries meaning worth using deliberately: space in front of a subject reads as forward motion/possibility, space behind reads as leaving something behind.

**Leave headroom and avoid background clutter if the shot is meant to be animated afterward.** A busy, cluttered background competes with motion once a still becomes video; a small margin around the subject gives camera movement somewhere to go. This is a still-image-time decision — previz's own composition determines whether the resulting video-gen attempt has room to move at all.

## What one image can and can't anchor

One reference image reliably anchors a shot's **starting instant** — its identity, wardrobe, framing. It does **not** reliably guarantee a specific trajectory or ending several seconds later just because the text says so; "guiding the AI to a specific, pre-planned ending state remains a challenge" even from one clean starting image. This is a structural model limitation (limited long-term scene memory, motion magnitude constraints), not a prompting mistake to fix with more adjectives.

**Start + end frame generation is a real, named, documented control method** — two images instead of one, one for the beat's first frame and one for its last, constraining the model to land there. Worth trying specifically when a beat's outcome matters a lot, rather than assuming a better-written ending will get you there from a single starting image.

**Image quality is its own variable**, independent of prompt quality — higher-resolution, cleaner source images measurably improve motion and photorealism.

## Realistic iteration expectations

Running 3–4 generations of the same beat and picking the best is described as **standard professional practice**, not a sign something's broken. Budget for it rather than expecting one clean take.

## Content moderation

Sora 2 and Gemini image generation both enforce provider-side content policies (violence, weapons, self-harm, sexual content, hate speech, dangerous behavior, real-person likeness misuse), and Sora specifically **text-scans the prompt itself before generation starts**, not just the output -- a request can fail with `moderation_blocked` before any frame is even rendered. This scans contextually, not just for a literal blocklist: a real test prompt describing an agent sprinting across a rooftop, leaping a gap, and going through a door -- no weapons, no violence, no injury described -- was blocked once wording like "tactical jacket" and "shoulder-checks it open" was in the mix, then passed cleanly once rewritten with neutral, film-direction language ("black jacket," "passes through the doorway") describing the exact same beats. Nothing about the underlying scene changed, only word choice.

**Practical takeaway:** favor neutral, cinematography-focused verbs and avoid combat/military/forced-entry-coded words even when describing completely non-graphic action content -- "runs and leaps" over "sprints and breaches," a described camera move over an aggressive verb. This isn't about disguising real violent content; it's that ordinary action-genre content can trip a conservative classifier on word choice alone, and rewording it doesn't change what's actually depicted.

**Second real incident: the reference image itself can be the trigger, not the wording.** The same test scene's third beat (reaching a rooftop doorway) failed `moderation_blocked` twice -- once with its original prompt, once with a fully rewritten, deliberately neutral prompt (no aggressive verbs, explicit audio direction, none of the wording flagged above) submitted against the *identical* reference image. Both failed the same way. Since only the text changed between the two attempts, the image was the actual trigger: a dynamic lunging pose, one gloved hand pressed flat against the door, plausibly reading as forced entry into a building even though nothing about it is literally violent. Two other reference images from the same scene (sprinting toward camera, mid-air leap) generated cleanly -- this isn't a blanket "action content" or "gloves" problem, it's specific to that door-entry pose. This is the first entry in `stages/moderation.py`'s `_KNOWN_MODERATION_RISK_PATTERNS` list, which a pre-flight check (docs/decisions/0022) now screens every reference image against before it reaches a paid video-generation call. Also worth noting: OpenAI's own published docs for this API include claims that don't hold up against this project's real runs (e.g. that any reference image containing a human face is rejected -- two of this scene's three successful images show clear faces). Treat this project's own diagnosed incidents as the reliable source, not scraped third-party documentation about the provider's internals.

## How this maps onto this project's pipeline today

- `previz._build_prompt` (stage 8) and `video_generation` (stage 9) currently share the **exact same prompt string**, reused verbatim — a still-image prompt doing double duty as a multi-beat video prompt. That's a known gap, not a design choice: the full pipeline vision's deferred stage 6 (shot list) / stage 7 (per-scene video prompts) exists specifically to give each of these its own dedicated prompt, and this session's real research independently confirmed shot-list-first is what's actually working for other creators, not just internally-consistent architecture.
- `--video-prompt` (CLI flag) is the current stopgap: it lets a hand-written, video-specific prompt be tested against an already-approved previz image without paying for a fresh research/fact-check/previz pass.
- Known bug to fix whenever stage 7 gets built (or sooner): previz's prompt still says "a generic, unnamed person... not a specific named historical figure unless stated," which self-contradicts as soon as the subject is a real, fact-checked named person (e.g. Tang Shizeng). Noted, not yet fixed.

## Real evidence so far (small sample, one comparison)

Same previz image, two prompts, on the Hoh Xil expedition scene: a short generic description let Sora invent an unprompted midday-to-golden-hour lighting arc and an unrelated macro insert shot. A timecoded, 3-beat, 7-part-structured prompt on the identical image produced output that tracked the specified beats instead, with neither the invented lighting arc nor the random insert, while character consistency stayed equally strong in both. One data point, encouraging, not proof at scale yet.

**Pompeii influencer scene (5-beat previz set, `litellm.image_edit` used directly, not through `run_previz_stage` — previz has no reference-image parameter today).** Confirms the multi-beat-collage failure and its fix (above), the location-consistency gap (above), and the camera-orientation finding (above). Two implementation notes worth carrying into any future previz image-conditioning work:

- `litellm.image_edit()`'s Gemini provider has the same `os.PathLike`-handling bug already documented in `video_generation.py` for `input_reference` (advertised as accepted, actually broken — `AttributeError`/`ValueError` on a bare `Path`) — same fix applies: pass raw bytes, not a `Path` object.
- Hit 3 real transient Gemini `InternalServerError`/`ServiceUnavailableError` responses across 5-6 calls in one session — concrete, recent confirmation that `run_previz_stage`'s existing transient-retry logic (docs/decisions/0016) is handling a real, recurring failure rate, not a hypothetical one.
