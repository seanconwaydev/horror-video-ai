# Dry run: D-Day / Omaha Beach (manual, no code)

Last updated: 2026-08-12

Status: stages 1–5 completed and reviewed manually (no automation — Claude played each stage's role directly in conversation). Stages 6–7 drafted as illustrative examples of the artifact shape. Stages 8–12 are conceptual only; no image or video model is connected yet, so nothing past this point has actually been generated.

This is exploratory/reference material, not a project decision — see [../architecture.md](../architecture.md) for the current pipeline design and [../decisions/](../decisions) for actual decisions. This file exists so the dry-run work isn't lost once any one conversation ends.

## Stage 1 — Topic

D-Day, June 6 1944, Omaha Beach. Narrative direction: an anonymous soldier's POV, boat through reaching a bunker, ending there — a self-contained arc, not a summary of the whole battle.

## Stage 2 — Research fact sheet

- Operation Overlord: the largest amphibious invasion in military history. Delayed from June 5 to June 6 due to weather.
- ~156,000–160,000 Allied troops landed across five beaches (Utah, Omaha, Gold, Juno, Sword) on June 6; over 7,000 naval vessels including ~4,000 landing craft and ~1,200 warships.
- Omaha Beach: largest of the five zones (6+ miles), defended by the German 352nd Infantry Division from bluffs and 13 fortified strongpoints, mined waters/obstacles. U.S. 1st and 29th Infantry Divisions landed there and faced the heaviest resistance of the day.
- Over 34,000 Americans came ashore at Omaha on June 6. Total Allied casualties that day exceeded 10,300; roughly 2,400 at Omaha alone — the costliest of the five beaches.
- First-hand accounts describe landing craft taking on water/sinking before reaching shore, the sound of gunfire striking the raised ramps, and men left to survive on their own if their craft was disabled.

Sources: [History.com](https://www.history.com/articles/d-day), [Britannica](https://www.britannica.com/place/Omaha-Beach), [Britannica facts](https://www.britannica.com/story/explore-facts-about-omaha-beach-landings-normandy-invasion), [Warfare History Network](https://warfarehistorynetwork.com/ww2-stories-5-compelling-first-hand-accounts-from-d-day/).

## Stage 3 — Fact-check pass

Cross-checked against [The National WWII Museum's official D-Day fact sheet](https://www.nationalww2museum.org/media/press-releases/d-day-fact-sheet-0). Core figures corroborate. Important finding: the Museum itself, quoting historian Stephen Ambrose, cautions that exact D-Day casualty figures are disputed even among primary historians ("No exact figures are possible... for casualties, for D-Day alone") — so script language should hedge numbers ("an estimated 2,400," not "exactly 2,400"). The two named first-hand accounts (Watson, Wagner) came from a single source and weren't independently corroborated, but since the narrative uses an anonymous/composite soldier, they were never used as named characters, sidestepping the risk of misattributing invented dialogue to real named people.

## Stage 4/5 — Final script (post-review)

**"The Ten Feet in Front of Him"** — approx. 60 seconds, no narration (pure visual/ambient piece), restrained violence (implied/distant, no close-up combat), one unexplained recurring detail: the soldier counts under his breath, a private rhythm that breaks and restarts at moments of shock.

1. **The boat** (0:00–0:10): "He doesn't know the men beside him. Doesn't know their names. He counts, under his breath, almost nothing — one, two, three — a rhythm that belongs to no one but him, that means nothing to anyone watching."
2. **The ramp** (0:10–0:15): Ramp drops, light floods in.
3. **The water** (0:15–0:27): "The water takes his legs first. Then his balance. Somewhere to his right a shell lands and the count breaks — loses its place, starts over from one — before a man near him goes down and doesn't get back up."
4. **The beach** (0:27–0:39): "There's no clean line between the sea and the sand. Men fall on either side of him, some to get back up, some not. He doesn't look left or right. He looks at the ground ten feet ahead of him, because that's the only piece of the war he can do anything about."
5. **Taking cover** (0:39–0:49): "He presses into the steel, raises his rifle toward the tree line, fires — not at anyone in particular, just at the noise. His lips are still moving. Counting again. He doesn't seem to notice he's doing it."
6. **The bunker** (0:49–1:00): "Back against the concrete, chest heaving, alive. His mouth is still moving, faint, automatic. Whatever number he's on, it isn't the one he started with." End.

Adversarial review notes (stage 5) that shaped this version: originally 6 beats read as too short for long-form and too generic without a distinguishing character detail — both resolved by (a) the Shorts-first format decision (see [../decisions/0002-shorts-first-format.md](../decisions/0002-shorts-first-format.md)) and (b) adding the unexplained counting habit (see [../playbook/narrative-techniques.md](../playbook/narrative-techniques.md) for that as a reusable technique).

## Stage 6/7 — Illustrative shot list and sample prompts

Same six beats as above with timing attached (see script). Sample per-scene video-generation prompt style (exact phrasing is model-dependent, TBD which model):

> Scene 1: "Interior of a WWII landing craft at dawn, handheld camera, tight on a young soldier's face and hands, other soldiers packed around him out of focus, gray overcast light, tense stillness, realistic historical military uniform detail, no dialogue."

> Scene 6: "A soldier's back against a concrete seawall bunker on a WWII beach, chest heaving, wide eyes, faint tremor in his lips as if murmuring, smoke and distant chaos visible but out of focus behind him, warm late-morning light breaking through haze, close-up, cinematic, restrained not graphic."

A rough (non-photorealistic) storyboard sketch of these six beats was rendered as a visual aid during the conversation this dry run happened in — not saved as a file, since it was illustrative only, not real pipeline output.

## Stages 8–12 — Conceptual only, not yet built

- **Previz:** would render one still per scene for review before any video spend; no image model connected yet.
- **Video generation:** would generate each clip from its approved prompt + reference still; no video model connected yet.
- **Audio:** decided to go narration-free for this particular script, using pure ambient/sound design instead — but audio format is meant to vary video-to-video (see [../pipeline.md](../pipeline.md), stage 10), not fixed project-wide.
- **Assembly:** thumbnail candidate — a still from scene 6 (his face against the bunker). Title candidate: "The Ten Feet in Front of Him."
- **Upload:** would need synthetic-content disclosure toggled on; description should include the "estimated" casualty hedge and a note that this is a dramatized/composite account, not a documented individual's story.

## Open threads from this dry run not yet resolved anywhere

- Cross-scene tic continuity (e.g., a count left at "...2...3..." picked back up at "...30...31..." in the next scene to imply elapsed time) — logged as a rare flavor technique in [../playbook/narrative-techniques.md](../playbook/narrative-techniques.md), not used in this script.
- Long-form pacing/structure requirements (what actually satisfies higher viewer expectations at 8+ minutes, beyond just "more scenes") — flagged as unresolved in [../decisions/0002-shorts-first-format.md](../decisions/0002-shorts-first-format.md), deferred to phase 2.
