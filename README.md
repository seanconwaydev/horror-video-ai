# Horror Video AI

A Python pipeline that turns a one-line scene idea into a short vertical horror video, stage by stage, with a human review gate before every step that costs money.

You give it three strings: a time, a place and what happens ("present day", "an underground car park at night", "a woman notices someone standing between the pillars"). It plans the scene, renders a storyboard, and generates video only after you approve what it is about to pay for.

> **Status:** personal project, in active development since August 2026. What runs today is scene planning → previz → video generation. Audio, assembly and upload are designed but not built.

## Demo

Shorts made with the pipeline (Kling v3), posted by hand:

- [Short 1 on TikTok](https://www.tiktok.com/@whowhereamai/video/7689589918753951006)
- [Short 2 on TikTok](https://www.tiktok.com/@whowhereamai/video/7689594934193573150)

## How it works

| Stage | What it produces | Model (pinned in `config/models.yaml`) | Review gate |
|---|---|---|---|
| Scene planning | Characters, locations and beats, each beat with action, camera, lighting and per-character staging | DeepSeek V4 Flash | Plan is validated before any image is made |
| Previz | Several candidate stills per beat | Gemini 3.1 Flash-Lite Image | You keep, retry or reject each beat; rejections carry a reason code |
| Video generation | One image-to-video clip per approved still | Wan 2.2 (fast) on Replicate | A separate command, so crossing the spend gate is always deliberate |
| Moderation check | Advisory YouTube-policy signal on every video prompt | OpenAI omni-moderation | Reports, never blocks |

A second path, the **short flow**, skips per-beat stills: Claude Sonnet 5 rewrites the plan as shots that move, writes them to `shots.json` and stops. You edit that file, then a second command generates the whole short. Direct-to-vendor backends for Veo 3.1, Kling v3 and Wan 2.7 are written behind one interface but have not yet been run against the live APIs.

Models are reached through [LiteLLM](https://github.com/BerriAI/litellm) where it supports them and through small REST clients where it does not (Replicate, Kling). Every stage's model is pinned by hand: no fallbacks and no routers, so a run is reproducible and a model change is a reviewed diff.

## Evaluation

Prompt changes are measured, not eyeballed. `evals/` generates the same scenes under two prompt variants, hides which is which, and asks for a forced A-or-B choice on five criteria (composition, style, fidelity, mood, motion). The answer key stays sealed until scoring is done.

Two rounds so far, one rater, five scenes × five criteria:

- Committing to one style per scene, instead of a hedged style instruction, won **19 of 25** comparisons but lost on motion, 2–3 ([ADR 0039](docs/decisions/0039-committed-style-presets-and-single-style-slot.md)).
- Adding a motion-composition clause to the winner won **16 of 25** and won motion **4–1**.

The same approach removed a component. An automated vision reviewer sat in front of the human gate until it was measured against 78 images already ruled on: 56% agreement, against 79% for simply accepting everything, and it rejected 31 of the 62 images that were kept. It was deleted ([ADR 0055](docs/decisions/0055-delete-the-automated-previz-reviewer.md)).

## Design decisions

Every significant choice is an Architecture Decision Record in [`docs/decisions/`](docs/decisions/) (79 so far). Good starting points:

- [0003](docs/decisions/0003-model-configuration-via-litellm.md): per-stage model pins through LiteLLM
- [0010](docs/decisions/0010-video-generation-model-and-standalone-stage.md): previz is the spend gate, and video generation is its own command
- [0037](docs/decisions/0037-horror-motion-comic-shorts-wan-via-replicate.md): moving video generation off Sora to Wan 2.2, after Sora's moderation proved a structural misfit for horror
- [0053](docs/decisions/0053-human-judgements-are-recorded-as-data.md): every human keep/reject is recorded as data
- [0069](docs/decisions/0069-delete-historical-grounding.md) and [0070](docs/decisions/0070-rename-to-horror-video-ai.md): why this started as a historical-video pipeline and stopped being one

[`docs/architecture.md`](docs/architecture.md) has the full design, including the stages not built yet and a per-model cost comparison.

## Running it

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run horror-video-ai --mock        # full pipeline offline: no API keys, no network calls
```

For real runs, copy `.env.example` to `.env` and fill in the keys for the stages you use.

```bash
# Plan a scene and review previz stills
uv run horror-video-ai --time "present day" --place "an underground car park at night" \
    --description "a woman notices someone standing between the pillars."

# Generate video from an approved run (the spend gate)
uv run horror-video-ai --video-gen-from outputs/<run>

# Short flow: write shots, edit them, then generate
uv run horror-video-ai --short --time "..." --place "..." --description "..."
uv run horror-video-ai --shots outputs/<run>/shots.json --backend veo
```

## Development

```bash
uv run pytest            # tests
uv run ruff check .      # lint
uv run mypy              # types: src/, evals/ and tests/ must be clean
uv run pytest --cov      # coverage, with a 94% floor
```

CI runs all four, plus an offline smoke job that drives the pipeline and the short flow end to end in mock mode and checks the eval scripts still parse their fixtures.

Built with [Claude Code](https://claude.com/claude-code) as a pair programmer. `CLAUDE.md` holds the project instructions it works from, and the ADRs are where its proposals were accepted, changed or rejected.
