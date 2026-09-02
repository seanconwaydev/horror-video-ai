# Image/video generation failure taxonomy — playbook

Last updated: 2026-09-02

A running log of real, observed oddities in generated previz images/video, and what (if anything) was done about each one. This is the raw material for eventually building a genuinely sustainable answer to "AI generation keeps producing small, specific oddities" — see the Methodology section for why a log, not just a growing pile of one-off prompt tweaks, is the point.

## Methodology

Sourced from Hamel Husain & Shreya Shankar's error-analysis process for evaluating LLM/generative systems ([LLM Evals: Everything You Need to Know](https://hamel.dev/blog/posts/evals-faq/)), the same methodology reportedly used inside teams at Anthropic and OpenAI — not invented for this project:

1. **Open coding** (where this doc lives right now): a human looks at a real output and writes a free-form note on what's wrong. This step can't be handed to an LLM — it requires actually knowing what a correct result looks like for this specific project. Every entry below is one open-coding note.
2. **Axial coding** (future, once there's enough volume): group the accumulated notes into a small taxonomy of ~5-10 recurring failure categories, rather than treating every note as its own permanent, isolated case. Husain's own guidance is to wait for **30-50 real traces** before this step is worth doing — clustering 6 entries would just be guessing at categories that don't have enough evidence yet.
3. **Golden eval set** (further out): once real categories exist, build a small fixed set of test scenes that get run whenever a prompt template changes, scored automatically (an LLM-as-judge — which `previz_review` already structurally is), to catch a regression before it costs a real image-generation run to discover.

Practically: **keep adding entries below as they're found, in the field's natural free-form-note style — don't force a rigid category onto the `tentative category` field either. It'll be revisited for real once there's enough here to cluster.**

### Per-genre rules — the plan, not yet the practice

Different kinds of scenes (a modern-day narrator, a pure historical reconstruction, something openly fantastical) plausibly need different rule sets — a phone-orientation rule is dead weight on a scene with no handheld device. The `genre` field below exists so that tagging happens from day one and doesn't need retrofitting later, but actually splitting rules by genre is real design work that needs real volume within each genre first — not attempted yet.

### Public benchmarks/guides — what's genuinely borrowable, and what isn't

There's no dataset, from Anthropic, OpenAI, or anyone else, of "historical-accuracy anachronism failures in AI video" — that's this project's own niche, and it has to be built from the entries below, not imported. What *does* exist publicly and is worth knowing about:

- **General text-to-image failure-mode benchmarks** — [T2I-CompBench](https://ar5iv.labs.arxiv.org/html/2307.06350) (6,000 prompts across attribute binding, spatial relationships, and complex compositions), [DrawBench](https://www.emergentmind.com/topics/t2i-compbench) (200 prompts testing counting/composition/conflicting/writing), [PartiPrompts](https://www.emergentmind.com/topics/t2i-compbench) (1,600 prompts), and [GenEval](https://www.emergentmind.com/topics/t2i-compbench) (object/attribute/position alignment). These are useful for the *vocabulary* of failure categories — e.g. T2I-CompBench's own "spatial relationships" category is literally the same class of bug as the phone-screen-orientation entry below — not for the historical-domain content itself.
- **Video-specific**: the [VBench](https://www.researchgate.net/publication/397699220_VBench_Comprehensive_and_Versatile_Benchmark_Suite_for_Video_Generative_Models) family evaluates dimensions including subject identity consistency, motion smoothness, temporal flickering, spatial relationship, physics, and commonsense — directly relevant vocabulary once video-generation-specific (not just previz-image) oddities start getting logged here.
- **OpenAI's own Sora 2 Prompting Guide** is already this project's primary sourced reference for prompt *structure* (see `docs/playbook/video-generation-prompting.md`) — first-party, genuinely reputable, and already informing this project's beat structure (subject/action/camera/lighting/style/audio).

None of the above have been applied to this project yet beyond the existing video-generation-prompting.md citations — noted here so they don't need re-discovering later, not because anything's been copied in.

## Log

Each entry: date, which run surfaced it, a tentative category (not yet a settled taxonomy — see Methodology), a genre tag, what was actually observed, and what (if anything) was done about it.

---

**2026-09-02** · Pompeii influencer run · *tentative category: retry-loop blindness to a structural (not random) rejection cause* · genre: modern-visitor-in-historical-setting
A Character's `face_build` field was hand-edited during scene-plan review to include "purple hair" (a scene_planning.py bug found separately: the field text is baked into every beat's prompt, ADR 0029's motivating case). previz_review correctly rejected it every time, but the automatic retry loop burned all 3 attempts blind before giving up, with no way to intervene mid-loop.
→ Addressed: [ADR 0029](../decisions/0029-on-rejection-edit-and-retry.md) (on-rejection edit/give-up hook, plus a same-concern-twice heuristic for `--yes` runs).

**2026-09-02** · Pompeii influencer run · *tentative category: staticness / insufficient motion across beats* · genre: modern-visitor-in-historical-setting
Across a full 12-beat run, the character stayed in the same standing position, orientation, and pose in nearly every beat — the only real variation was zoom level. The existing "vary camera framing" prompt rule wasn't enough on its own; framing changed, blocking didn't.
→ Addressed: scene_planning.py prompt rule requiring explicit body-position/pose variety per beat, not just camera framing (PR #23).

**2026-09-02** · Pompeii influencer run · *tentative category: attribute vagueness* · genre: modern-visitor-in-historical-setting
The character was meant to read as a modern-day visitor but came across ambiguous/not-clearly-modern — traced to vague wardrobe field text ("casual clothes" style phrasing) rather than concrete, specific clothing items.
→ Addressed: scene_planning.py prompt rule requiring specific, concrete, contemporary clothing items for out-of-era characters (PR #23).

**2026-09-02** · Pompeii influencer run · *tentative category: prop lighting realism* · genre: modern-visitor-in-historical-setting
A held smartphone rendered as an unrealistically bright, star-like light source. Traced to escalating "glow" language across beats' own `action`/`lighting` text ("a glowing smartphone" → "cool electric glow" → "phone-screen light"), not the Character's own description — nothing told the model to keep it subtle relative to the scene's real light source.
→ Addressed: scene_planning.py prompt rule requiring lit screens to be described as clearly weaker than the beat's main light source (PR #24).

**2026-09-02** · Pompeii influencer run · *tentative category: prop spatial/orientation consistency* (matches T2I-CompBench's own "spatial relationships" category) · genre: modern-visitor-in-historical-setting
A held phone's screen rendered facing the camera in a shot where the described geometry (over-the-shoulder from behind her) should have shown its back instead. Image models default to rendering a phone's iconic "screen-facing-viewer" view regardless of described camera geometry unless told the opposite outright.
→ Addressed: scene_planning.py prompt rule requiring an explicit "screen not visible to camera" statement whenever the described camera angle would naturally hide it (PR #24).

**2026-09-02** · Pompeii influencer run · *tentative category: review-scope / acknowledged-exception coverage* · genre: modern-visitor-in-historical-setting
A human acknowledged one specific anachronism (a time-travel smartphone) as intentional fiction. previz_review correctly followed that literal acknowledgment, but then separately rejected the character's modern *clothing* as an unacknowledged anachronism the moment a wider beat framing actually showed it clearly — even though "keep as intentional fiction" for a time-traveling visitor obviously implies her whole modern appearance, not just her phone.
→ Addressed: [ADR 0030](../decisions/0030-acknowledged-fiction-covers-knock-on-consequences.md) (acknowledged_fiction broadened to cover natural knock-on consequences of the same acknowledged premise, not just its literal text).
