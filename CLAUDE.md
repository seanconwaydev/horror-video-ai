# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An AI pipeline that turns a historical topic into a finished, YouTube-ready video. Different LLMs handle different stages (research, script, shot list, prompts), with a human review gate before every stage that costs real money. See `docs/architecture.md` for the full vision and the stage diagram, and `docs/pipeline.md` for what each of the 12 stages does and reviews. The project is in early scaffolding — only stage config-loading exists as code so far; `src/historical_video_ai/stages/` is empty and stage 2 (research) is the next piece of work.

Two docs are worth reading before touching pipeline design: `docs/architecture.md`'s "Design principles" section (cheap-before-expensive stage ordering, every stage produces a reviewable artifact, adversarial review passes, no hardcoded format) and its "Open questions" section (undecided items like the video-gen model and control-flow mechanism — check there before assuming something is settled).

## Commands

This project uses `uv`. There is no `uv.lock` committed yet (dependencies were hand-added to `pyproject.toml` because the environment they were scaffolded in had no PyPI access — `uv sync` has not actually been run against this repo yet, so treat first-run friction here as expected, not a regression).

```bash
uv sync                    # install dependencies
uv run pytest              # run the test suite
uv run pytest tests/test_config.py::test_get_stage_model_returns_pinned_model_string  # single test
uv run ruff check .        # lint
```

Copy `.env.example` to `.env` and fill in real API keys before running anything that calls a model (never commit `.env`; it's gitignored).

## Architecture

**Per-stage model configuration (`config/models.yaml` + `src/historical_video_ai/config.py`)**: every pipeline stage's LLM choice is a pinned `<provider>/<model-name>` string (LiteLLM format) in `config/models.yaml`, never hardcoded in stage code and never auto-substituted or routed on failure — see `docs/decisions/0003-model-configuration-via-litellm.md`. `load_stage_configs()` fails loud (`ConfigError`) on a missing file, empty file, or a stage missing its `model` key, rather than falling back silently. When adding a new stage's code, add its corresponding block to `config/models.yaml` first — `tests/test_config.py::test_real_project_config_is_valid` asserts the real committed config still defines every stage that has code depending on it, so that test's `expected_stages` set needs updating too.

**LLM calls go through LiteLLM**, not provider SDKs directly — one `completion(model=..., messages=[...])` call works uniformly across providers so stage code doesn't need provider-specific branches (`docs/decisions/0003`).

**Secrets** load via `config.load_environment()` (wraps `python-dotenv`), called explicitly at a run's entry point — importing `config.py` has no side effects on the environment.

**Stage code**: one module per pipeline stage under `src/historical_video_ai/stages/`, added incrementally as each stage in `docs/pipeline.md` gets implemented.

**AWS**: adopted incrementally and only for genuine fit, not proactively (`docs/decisions/0004-aws-incremental-adoption.md`) — SQS is committed for stage 9 (video generation) specifically, as a fan-out-with-retry queue over independent per-scene generation calls; Step Functions is committed for overall pipeline orchestration (matches the sequential-stages-with-human-approval-wait-states shape already). S3, Secrets Manager/Parameter Store, and DynamoDB/RDS are identified as natural fits but deliberately not yet adopted — each gets its own ADR if and when it's actually needed. Nothing here is implemented yet.

**Format**: Shorts-only for now (`docs/decisions/0002-shorts-first-format.md`) — roughly 30–60 seconds. Long-form is an explicit later phase with its own unresolved design questions (pacing/act-structure expectations that don't just come from writing a longer script), not a natural extension of the Shorts pipeline.

## Project conventions

- **Architecture decisions are recorded as ADRs** in `docs/decisions/`, one file per decision, numbered sequentially, written once and left alone — a changed decision gets a new ADR that supersedes the old one rather than an edit in place (`docs/decisions/0001-record-architecture-decisions.md`). `docs/architecture.md` stays a short current-state overview; undecided items live in its "Open questions" section until they're resolved, at which point they become an ADR. When you make or are asked to help make an actual architectural decision on this project, write the ADR.
- **`src/` layout**: package code lives under `src/historical_video_ai/`, not flat at repo root (`docs/decisions/0005-project-scaffolding.md`).
- Root-level `main.py` was removed as vestigial pre-scaffolding cruft (still shown as deleted in git status) — don't recreate it; entry points belong under `src/historical_video_ai/`.
