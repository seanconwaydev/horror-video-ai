# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An AI pipeline that turns a historical topic into a finished, YouTube-ready video. Different LLMs handle different stages (research, script, shot list, prompts), with a human review gate before every stage that costs real money. See `docs/architecture.md` for the full vision and the stage diagram, and `docs/pipeline.md` for what each of the 12 stages does and reviews.

**Current build is deliberately narrower than that full vision** — see `docs/decisions/0006-narrow-v1-scope-single-image.md`. Implemented so far: stage 2 (research, `stages/research.py`), stage 3 (fact-check, `stages/fact_check.py`), and a scoped-down stage 8 (previz, `stages/previz.py`) that generates one image directly from the fact-checked scene, skipping stages 4–7 for now. `cli.py` wires these three into an interactive run (`uv run historical-video-ai`). Stages 4–7 and 9–12 are not built.

Two docs are worth reading before touching pipeline design: `docs/architecture.md`'s "Design principles" section (cheap-before-expensive stage ordering, every stage produces a reviewable artifact, adversarial review passes, no hardcoded format) and its "Open questions" section (undecided items like the video-gen model — check there before assuming something is settled).

## Commands

This project uses `uv`; `uv.lock` is committed.

```bash
uv sync                                # install dependencies
uv run pytest                          # run the test suite
uv run pytest tests/test_config.py::test_get_stage_model_returns_pinned_model_string  # single test
uv run ruff check .                    # lint
uv run historical-video-ai --mock      # run the pipeline with no API keys / no network calls
uv run historical-video-ai --time "July 1969" --place "Cape Canaveral, Florida" \
    --description "watches a rocket launch from the crowd."
```

Copy `.env.example` to `.env` and fill in real API keys before running anything that calls a model (never commit `.env`; it's gitignored).

## Verification discipline

When a tool exists for a job — anything in Commands above, or any other install/test/lint/build step — always run it and use its real output, rather than approximating what it would say by hand (hand-simulating a test, eyeballing a lint rule, reasoning about whether a dependency would resolve). A hand-rolled substitute is structurally weaker: narrower coverage, more room for a real problem to slip through unnoticed.

If the real tool genuinely can't be run in the current environment, say so plainly and ask before substituting a manual approximation — don't silently decide to improvise and only report the choice after the fact. This matters most for verification-type gaps (can't run the test suite, can't lint, can't confirm a dependency resolves); it's not about trivial, fully-equivalent workarounds (e.g. `mv` instead of a blocked `rm`), which don't need to trigger this.

## Architecture

**Per-stage model configuration (`config/models.yaml` + `src/historical_video_ai/config.py`)**: every pipeline stage's LLM choice is a pinned `<provider>/<model-name>` string (LiteLLM format) in `config/models.yaml`, never hardcoded in stage code and never auto-substituted or routed on failure — see `docs/decisions/0003-model-configuration-via-litellm.md`. Model choices for research/fact-check/previz specifically are explained in `docs/decisions/0007-research-fact-check-previz-models.md`. `load_stage_configs()` fails loud (`ConfigError`) on a missing file, empty file, or a stage missing its `model` key, rather than falling back silently. When adding a new stage's code, add its corresponding block to `config/models.yaml` first — `tests/test_config.py::test_real_project_config_is_valid` asserts the real committed config still defines every stage that has code depending on it, so that test's `expected_stages` set needs updating too.

**LLM calls go through LiteLLM**, not provider SDKs directly — one `completion(model=..., messages=[...])` call works uniformly across providers so stage code doesn't need provider-specific branches (`docs/decisions/0003`). Image generation uses `litellm.image_generation()` the same way (see `stages/previz.py`) — this has not yet been exercised against a live key from this repo; treat the first real run as a test.

**Secrets** load via `config.load_environment()` (wraps `python-dotenv`), called explicitly at a run's entry point — importing `config.py` has no side effects on the environment.

**Stage code**: one module per pipeline stage under `src/historical_video_ai/stages/`, added incrementally as each stage in `docs/pipeline.md` gets implemented (currently: `research.py`, `fact_check.py`, `previz.py`). Established pattern: a frozen-dataclass artifact type for the stage's reviewable output, a stage-specific `<Stage>Error` exception that fails loud on malformed model output (matching `ConfigError`'s convention in `config.py`), and a `run_<stage>_stage(...)` function taking an injectable `completion_fn` or `image_fn` (default `litellm.completion`/`litellm.image_generation`) so tests never need a live API call.

**AWS**: adopted incrementally and only for genuine fit, not proactively (`docs/decisions/0004-aws-incremental-adoption.md`) — SQS is committed for stage 9 (video generation) specifically, as a fan-out-with-retry queue over independent per-scene generation calls; Step Functions is committed for overall pipeline orchestration (matches the sequential-stages-with-human-approval-wait-states shape already). Nothing here is implemented yet, and it isn't needed for the current v1 scope (`docs/decisions/0006`), which uses a plain CLI confirm-loop instead.

**Format**: Shorts-only for now (`docs/decisions/0002-shorts-first-format.md`) — roughly 30–60 seconds. Video generation itself is deferred until the pipeline up to previz is working well (`docs/decisions/0006`).

## Project conventions

- **Architecture decisions are recorded as ADRs** in `docs/decisions/`, one file per decision, numbered sequentially, written once and left alone — a changed decision gets a new ADR that supersedes the old one rather than an edit in place (`docs/decisions/0001-record-architecture-decisions.md`). `docs/architecture.md` stays a short current-state overview; undecided items live in its "Open questions" section until they're resolved, at which point they become an ADR. When you make or are asked to help make an actual architectural decision on this project, write the ADR.
- **`src/` layout**: package code lives under `src/historical_video_ai/`, not flat at repo root (`docs/decisions/0005-project-scaffolding.md`). This is about layout convention, not a rule against a `main.py`-style entry point specifically — the CLI entry point (`cli.py`) lives under `src/historical_video_ai/` for that reason, exposed as the `historical-video-ai` script in `pyproject.toml`.
