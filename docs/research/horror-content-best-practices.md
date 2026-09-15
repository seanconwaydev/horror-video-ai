# Horror content best practices — research

Last updated: 2026-09-14

Follow-up research after [decisions/0037](../decisions/0037-horror-motion-comic-shorts-wan-via-replicate.md) committed this project to horror as its genre. [research/short-form-format-selection.md](./short-form-format-selection.md) established *that* horror was the right genre choice; this doc goes a level deeper into what actually works *within* horror content specifically, now that it's the real direction, not a hypothesis being weighed.

## Real channels and formats, not just the genre in the abstract

Solo creators are already producing horror content entirely with AI, no camera/crew/studio (Black Lake AI Studio's Halloween promos, cited by name). Two named formats worth studying directly:

- **"Laundry Day 2026"** — an AI horror short series using community-led storytelling, where viewers' comments shape the next installment. Relevant less as a format to copy than as evidence that audiences will follow a *series* of small, standalone AI horror scenes over time, not just one-off videos.
- **Midnight Lab's "Mr. Puzzles"** — AI horror shorts built from **one-sentence stories**. This is close to exactly this project's own committed shape (small, bespoke, standalone horror ideas, ADR 0037) validated as a real, named, working format, not just this project's own invention.

**Content-multiplication pattern, worth knowing even if not adopted directly**: some creators build one larger interactive horror premise, then cut 15–20 short clips out of it (jump scares, plot twists, choice moments), each with its own hook ("POV: you made the wrong choice," "would you survive?"). Doesn't fit this pipeline's per-scene generation shape today, but is a candidate answer if volume/cadence ever becomes the bottleneck rather than per-scene quality.

## Hooks, captions, and on-screen text

The hook lives in two places that should rhyme, not repeat verbatim: on-screen text overlay and the caption. For horror specifically, the hook needs to stop the scroll in the first second or two — an unsettling sound, a strange visual, or a provocative line of text, not a slow build. Documented real caption conventions: *"This isn't just a story… it's a warning,"* *"Some things are better left unexplained,"* *"Whatever you do, don't turn around."* "POV:" framing (now more a storytelling-prompt convention than literal first-person camera, confirmed earlier this session) remains a strong, recognizable hook shape specifically for horror.

**Practical gap for this pipeline**: none of this exists yet. Captions/on-screen text are not part of any current stage — previz produces clean frames with explicit "no on-screen text/UI/logos" instructions (correct for the image itself), and there's no separate caption/hook-authoring step. This is squarely inside the still-unbuilt Assembly stage's scope, not something to retrofit into previz.

## Narrative structure that actually works short

Tropes (haunted house, creepy child, isolated location) are genuinely useful in short form specifically *because* they establish atmosphere and threat with near-zero exposition — a real narrative-economy argument, not just genre laziness, for leaning on recognizable horror shorthand rather than inventing new mythology every scene. The strongest documented ending shape for short horror: a "horrible realization that the threat isn't actually vanquished" — an unresolved, ongoing-dread ending, not a tidy defeat of the monster. This lines up exactly with the project owner's own stated preference (no resolution required, ambiguity is a feature) rather than being a new constraint.

## Analog horror / liminal spaces — a proven, different flavor of horror worth trying deliberately

A specific, massive, real trend distinct from every domestic-interior scene tested so far: **analog horror** (horror with a deliberately degraded, nostalgic technological quality — VHS artifacts, CCTV framing, broadcast-signal glitches) and **liminal spaces** (empty, transitional, familiar-but-wrong locations — empty malls, motel hallways, pool corridors). Real scale: the "analog horror" TikTok category alone has 2.3 billion views; "liminal spaces" has 4.9 billion. The dread mechanism is explicitly spatial, not creature-based: "the fear of being trapped inside a system, a space, or a loop with no visible exit" — the *place itself* is the threat, not a monster in it. Mainstream legitimacy: Kane Parsons's Backrooms found-footage series (originated as exactly this kind of online horror) was adapted into an A24 feature in 2026.

This is directly relevant to `architecture.md`'s open question on whether horror sub-genres need their own rule routing: analog horror/liminal spaces is a genuinely different scenario type from every domestic-haunting scene tested tonight (no character-shadow escalation, no closet-door reveal — the setting itself, degraded and empty, carries the whole effect), and it's popular enough to be worth a real test in its own right rather than staying a hypothetical "other horror type" in the abstract.

## Monetization economics specific to horror

Two concrete numbers worth carrying forward: YouTube horror channels are cited among the **highest CPM categories, $8–$25** — notably higher than generic content. But shorts are explicitly a **top-of-funnel mechanism** for most successful creators in this space — the real monetization multiplier (15–60x) happens on long-form content that shorts funnel viewers toward, not on the shorts themselves. Worth flagging honestly against this project's current shorts-only scope (`decisions/0002`): the format decided on is good for *reach*, but the research suggests the real money in this genre specifically sits in long-form, which is out of scope for now, not a gap to solve today.

## Practical implications for this pipeline, prioritized

1. **Try an analog-horror/liminal-space scene as a real test** — the clearest concrete next step this research points to, since it's a structurally different scenario type from everything tested so far and independently proven popular.
2. **Caption/hook authoring is a real, currently-missing piece** — not urgent before Assembly exists, but worth remembering it's not just "add text," it's its own genre-literate authoring task (the on-screen/caption rhyme-not-repeat convention, specific proven phrasings).
3. **The shorts-are-a-funnel-not-the-destination finding** is worth keeping in view as this project's scope potentially widens later, not acted on now.

Sources: [Best AI Horror Video Generators 2026](https://scarystories.live/blog/best-ai-horror-video-generators-2026) · [The short-form scare: writing horror for TikTok and YouTube Shorts](https://thelittlehouseofhorrors.com/the-short-form-scare-a-guide-for-students-for-writing-horror-for-tiktok-and-youtube-shorts/) · [Analog uncanny: how this weird and experimental side of TikTok is forging the future of horror](https://theconversation.com/analog-uncanny-how-this-weird-and-experimental-side-of-tiktok-is-forging-the-future-of-horror-222882) · [Liminal space aesthetic — EBSCO Research Starters](https://www.ebsco.com/research-starters/religion-and-philosophy/liminal-space-aesthetic) · [Why we love to wander the empty halls of the internet's creepiest aesthetic — YouTube Blog](https://blog.youtube/culture-and-trends/liminal-space/) · [Analog Horror Is Entertainment's Next Big Trend — ComicBook.com](https://comicbook.com/movies/feature/analog-horror-is-entertainments-next-big-trend-but-will-big-budgets-get-these-viral-sensations-right/)
