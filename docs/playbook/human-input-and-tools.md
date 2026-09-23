# Human input design and the tool landscape — playbook

Last updated: 2026-09-03

Two questions the project owner asked to have properly researched and written down, not decided by guessing: how much human input this pipeline should expect (and how the CLI should guide it toward being good), and what tools established AI-video practitioners actually use, per stage. Sourced from real 2026 research, not invented — same sourcing discipline as this playbook's other docs.

## Human input: how much, where, why

**Substantial, multi-gate human review is the documented norm in real production AI content systems, not something to minimize.** A concrete case study (ContentMonk): a human sets constraints *before* generation (tone, audience, brand guidelines), reviews and approves the AI-generated brief before a draft gets made, then reviews the draft again before publishing — roughly 70-80% automated, with human review at every meaningful checkpoint. This is the same shape as this project's existing review gates (scene plan, references, each beat), not overhead to trim down.

**Almost none of that input should be freeform text, and this is backed by more than intuition**: structured inputs (explicit fields, not a single prompt blob) measurably reduce hallucinations and improve reliability by 30-40% in production AI content workflows. The recurring named pattern across sources is a **creative brief**: five core fields — objective, audience, insight, deliverables, constraints — with tone, format, and genre/category as further commonly-named fields. "AI cannot interpret ambiguity, infer intent, or apply brand judgment without explicit rules, while a human can fill gaps and apply experience" — the brief exists specifically to remove the ambiguity a freeform prompt leaves in.

**CLI-specific conventions** (from CLI design guidelines like [clig.dev](https://clig.dev/) and production CLI-UX writeups):
- Prompt for missing required info rather than erroring immediately — but **never require** an interactive prompt; every value must be settable via a flag too, for automation. This project's `--yes` + `_prompt_if_missing` pattern already follows this.
- Validate input early and fail with a specific, actionable message, not a late failure deep in the pipeline.
- Provide sensible defaults instead of asking for everything every time.
- Flags, not positional arguments — labels give context and remove the need to memorize order. Already this project's convention throughout.
- An interactive mode's real value is "guardrails" — constraining choices to prevent mistakes and showing the user what's actually possible, not just collecting free text.

**Risk-tiered review** is the documented pattern for when volume grows past what exhaustive review can sustain: categorize generated content by risk level, full review for the top tier, calibrated spot-checks for the rest. Not relevant at this project's current scale (every beat still gets full review), but the lever to reach for once producing much higher volume than today.

### What this means for this project's current input shape

Structured input already exists in some places (Character/Location/Beat fields, per-field edit in scene-plan review) but the true entry point — `--time`/`--place`/`--description`, three free-text strings — is still the "freeform prompt" shape the research says to move away from. This is exactly the gap the tracked task (design a real genre/structured-input schema at the pipeline's entry point) exists to close — not designed yet, deliberately, pending real evidence from testing multiple genres first (see `failure-taxonomy.md`).

## Tool landscape, by stage

No tool exists specifically for "historical-accuracy AI video generation" — this project's own niche has to be built, not bought (already established in `failure-taxonomy.md`). But real, specialized tools exist for every *general* stage a video pipeline needs, and knowing the landscape is useful both for informing this project's own architecture and as literal candidates for the still-open model-choice decisions (previz image model, video-generation model).

| Stage | This project's current pinned choice | Real-world alternatives found in research | Notes |
|---|---|---|---|
| Research / fact-check | `perplexity/sonar-deep-research`, `gemini/*` (per `config/models.yaml`) | General LLMs with search grounding | No dedicated "AI video research" tool found — this is a general LLM task with retrieval, same shape this project already uses. |
| Scene/shot planning | `deepseek/deepseek-v4-flash` | Same — general LLM task | Real workflows increasingly automate this step too: "autonomous agents analyze text scripts, automatically storyboard scenes, select optimal models for specific shots" — the *pattern* this project's scene-planning stage already follows. |
| Image generation (previz) | `gemini/gemini-3.1-flash-lite-image` | Seedance 2.0 (strongest prompt adherence, 12 reference inputs, native audio), gpt-image-1-mini | Still an open, untried comparison per `architecture.md`. |
| Video generation | `openai/sora-2` (deprecated 2026-09-24) | **Veo 3.1** — best motion/physics, closest to real cinematography; **Kling 3.0** — strongest for stylized storytelling, human motion, multi-shot sequences up to 4K; **Runway Gen-4/4.5** — native prompt-driven camera control, reference-image-based character consistency; **Seedance 2.0** — commercial/brand-consistency focus, native audio | Real use-case split, not "one is just better": Veo for realism, Kling for stylized/human-motion work, Runway when camera control specifically matters (directly relevant to this project's coverage/same-location problem, see `failure-taxonomy.md`). |
| Voice / dubbing | Not yet implemented (`beat.audio` is currently prompt text only, hoping the video model generates it natively) | ElevenLabs, HeyGen | Real professional workflows often generate silent video and layer audio in post rather than relying on native video-model audio — a pattern worth remembering whenever this project's audio approach gets real attention. |
| Avatar-based characters | Not applicable to this project's current approach (per-scene generated characters, not one fixed reusable avatar) | Synthesia | Relevant if this project ever adopts a fixed recurring "brand" character (see `architecture.md`'s open question on that). |
| Assembly / editing | Not yet implemented (a deferred pipeline stage) | Opus Clip (auto-shorts), Descript (transcript-based editing), Twelve Labs (video search/indexing) | |

**The real, named workflow pattern across multiple sources — "script-to-screen automation"**: analyze the script → storyboard scenes → select the best model *per shot* based on what that shot needs (a face close-up vs. a wide establishing shot might go to different models) → generate B-roll → assemble a rough cut. This is finer-grained than this project's current per-*stage* (not per-shot) static model pinning (`config/models.yaml`) — a real, documented next level of sophistication, not something to build now, but useful to know the ceiling exists.

**Build-vs-buy heuristic, stated directly in the research**: "most platforms end up hybrid: buy the generative hero models, build the commodity transcription and composition stages." This validates this project's actual shape — the generative "hero" calls (research LLM, image model, eventually video model) are all bought via API through `litellm`, while the orchestration/glue (stage sequencing, review gates, scene-plan structuring) is this project's own custom code. Not a deviation from real practice; the standard shape of it.

Sources: [Command Line Interface Guidelines](https://clig.dev/) · [How to Design a CLI Tool That Developers Actually Love Using](https://hackernoon.com/how-to-design-a-cli-tool-that-developers-actually-love-using) · [Human-in-the-Loop AI Content Workflows](https://growthx.ai/learn/human-in-the-loop-ai-content-workflows) · [How to Create a Content Brief for AI Writing](https://searchatlas.com/blog/how-to-create-a-content-brief-for-ai-writing/) · [Best AI Video Generators in 2026](https://higgsfield.ai/blog/best-ai-video-generators-2026) · [Best AI Video Editing Tools in 2026](https://www.forasoft.com/blog/article/ai-powered-video-editing-solutions)
