# 37. Format decided: short, stylized horror motion-comics; video generation moves off Sora to Wan 2.2 via Replicate

Date: 2026-09-14

Status: Accepted

## Context

This project's v1 scope (decisions/0006) never settled what *kind* of video it should actually produce beyond "shorts-first" (decisions/0002) and "historical settings are what's been tested, not what the project is required to specialize in" (decisions/0031). The project owner asked to close that gap: find a short-form format that's genuinely popular, actually uses generated video (not a still image with music, already explicitly ruled out), and fits what this pipeline can realistically produce -- full research trail in [research/short-form-format-selection.md](../research/short-form-format-selection.md).

That research converged on a **motion-comic** treatment (one previz-generated panel per beat, each getting a short, restrained video-generation pass, not a full continuous scene) as the right shape: cheap, sidesteps the multi-shot "coverage" problem that's the most-logged unresolved issue in `failure-taxonomy.md`, and doesn't need the previz→video "extend/chaining" capability this project doesn't have.

Genre was chosen deliberately independent of this project's historical-genre-heavy implementation history, per the owner's explicit instruction not to let that history steer the choice. Real 2026 trend research found **horror** to be the strongest fit: a proven, currently-viral, highly-engaging category, and one where this pipeline's own characteristics (uncanny-valley AI weirdness reads as a genre *asset*, not a defect to hide; incoherent or even unintentionally-funny outcomes are explicitly acceptable per the owner) work in its favor rather than against it -- see `failure-taxonomy.md`'s "What counts as a successful outcome for horror specifically" entry.

Real testing on 2026-09-14 (two full horror scene-planning + previz runs) validated the mechanics: a new genre-routed threat-presence rule (extending the ADR 0036 routing pattern) got the story's threat referenced across most beats with literal, checkable staging language instead of vague adjectives; multi-location scenes read as one coherent house without any dedicated cross-location consistency mechanism; `--style stylized` produced a clean, appealing comic/animated look with zero style drift.

That same testing found `openai/sora-2` (the pinned video-generation model, decisions/0010) to be a structurally bad fit for horror specifically, not just an inconvenience:

- Sora's own real content moderation is independently documented (OpenAI's developer community, real user reports) as unusually aggressive and false-positive-prone, with OpenAI's own stated philosophy being "false positives are preferable to potential harm."
- This project's own second-layer moderation heuristic (`stages/moderation.py`'s `run_moderation_risk_review`, decisions/0022) compounded that: primed with one real past incident as a reference pattern, it over-generalized to skip two more, much milder beats before any real Sora API call was even attempted.
- Sora's API is being removed by OpenAI on 2026-09-24 regardless, forcing a model change independent of any of the above.
- Broader comparative research found all major hosted commercial video APIs (Sora, Veo, Kling, Runway, Pika) enforce similar horror/violence-adjacent vendor moderation policy, with the industry trend tightening over time, not loosening -- ruling out a like-for-like swap to a different mainstream provider as a real fix.

Real, live testing of **Wan 2.2** (Alibaba's open-weight video model, which has no vendor-baked safety alignment at all) hosted via **Replicate's API** (no self-hosted GPU infrastructure needed) confirmed it as the actual fix: three real beats tested, zero moderation friction on any of them, including a beat showing an actual visible monster-shaped shadow figure in frame -- content Sora's own heuristic had guessed would be risky for a much milder version of. It also came in at roughly $0.05/clip against Sora's ~$0.40, and showed measurably more real per-clip motion in this small sample.

The one real technical gap: litellm has no support for Replicate's (or fal.ai's) video-generation endpoints as of the latest released version (1.100.1, confirmed by reading its source directly) -- only OpenAI, Azure, Gemini, Vertex AI, and RunwayML are wired up for video. The project owner explicitly authorized breaking from decisions/0003's "everything through litellm" convention for this one stage rather than waiting: *"I'm not worried at all about 'everything through litellm' ... it's fine to try new things and change shape as needed, because the previous direction and restrictiveness was not working."*

After this testing, the project owner confirmed the format and genre as final: *"I think I'm happy with this direction being the final choice for this project, making short, stylized videos about little bespoke horror ideas."*

## Decision

1. **Format**: short (roughly 20-60s) Shorts, motion-comic style -- one previz-generated panel per beat, each getting a short, restrained video-generation pass, stitched together (docs/pipeline.md's still-unbuilt Assembly stage, tracked separately, not part of this decision).
2. **Genre**: horror, as this project's actual creative focus going forward -- not a default extension of its historical-genre-heavy build history. Individual scenes are small, bespoke, standalone ideas; internal narrative coherence and a tidy resolution are explicitly not required.
3. **Video generation moves off `openai/sora-2` to Wan 2.2**, called directly against Replicate's REST API rather than through litellm -- a deliberate, scoped exception to decisions/0003 for this one stage, justified by litellm's current lack of Replicate/fal.ai video support and the project owner's explicit sign-off above.
4. `stages/moderation.py`'s existing pre-flight (decisions/0022) needs re-scoping as follow-up work: it was built specifically to guess at Sora's own moderation behavior, and that framing doesn't transfer to a model with no vendor-baked safety alignment. `_KNOWN_MODERATION_RISK_PATTERNS` in particular is premised on the wrong vendor's behavior and should not simply be carried forward as-is.

## Consequences

Resolves `architecture.md`'s long-standing "video generation model" open question, at least for now -- Wan 2.2 via Replicate is the new pinned choice, chosen specifically because of the moderation-restrictiveness research, not a coherence/quality bake-off against Veo/Kling/Runway (which remain untried on quality grounds and were deprioritized here on policy-fit grounds instead).

Introduces this project's first real, intentional exception to decisions/0003's "always through litellm" convention. If litellm adds real Replicate or fal.ai video support later, revisiting whether to move this stage back onto litellm is a natural follow-up, not required.

Real gaps, not solved by this decision, tracked as follow-up implementation work:
- `config/models.yaml`'s `video_generation` entry and `stages/video_generation.py` need real code changes to call Replicate directly -- not done as part of this ADR, which records the decision, not the implementation.
- Wan generates no native audio, unlike Sora -- a real regression needing its own future solution (a separate sound-design step), not addressed here.
- `stages/moderation.py`'s re-scoping (point 4 above) is a real, separate piece of follow-up work.

Deliberately not resolved here, tracked instead as its own open question in `architecture.md`: whether horror sub-genres beyond the domestic-interior-haunting scenes tested so far (an outdoor chase, body horror, a slasher scenario) will need their own routed rule variants, the way `composition_mode` already routes staged-vs-chaotic composition (decisions/0036).
