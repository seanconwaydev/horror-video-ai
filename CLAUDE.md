# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An AI pipeline that turns a historical topic into a finished, YouTube-ready video. Different LLMs handle different stages (research, script, shot list, prompts), with a human review gate before every stage that costs real money. See `docs/architecture.md` for the full vision and the stage diagram, and `docs/pipeline.md` for what each of the 12 stages does and reviews.

**Current build is deliberately narrower than that full vision** — see `docs/decisions/0006-narrow-v1-scope-single-image.md`. Implemented so far: stage 2 (research, `stages/research.py`), stage 3 (fact-check, `stages/fact_check.py`), a scoped-down stage 8 (previz, `stages/previz.py`) that generates one image directly from the fact-checked scene, skipping stages 4–7 for now, and stage 9 (video generation, `stages/video_generation.py`, `docs/decisions/0010`). `cli.py` wires research/fact-check/previz into one interactive run (`uv run historical-video-ai`); video generation is a deliberately separate, standalone invocation (`--video-gen-from`), not yet part of that same run — see `docs/decisions/0010`'s reasoning (previz is the spend gate; video generation should always be a distinct, deliberate step). Stages 4–7 and 10–12 are not built.

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

**LLM calls go through LiteLLM**, not provider SDKs directly — one `completion(model=..., messages=[...])` call works uniformly across providers so stage code doesn't need provider-specific branches (`docs/decisions/0003`). Image generation uses `litellm.image_generation()` the same way (`stages/previz.py`), and video generation uses `litellm.video_generation()`/`video_status()`/`video_content()` (`stages/video_generation.py`, `docs/decisions/0010`) — both confirmed working end to end against real keys, including a full paid video generation run.

**Secrets** load via `config.load_environment()` (wraps `python-dotenv`), called explicitly at a run's entry point — importing `config.py` has no side effects on the environment.

**Stage code**: one module per pipeline stage under `src/historical_video_ai/stages/`, added incrementally as each stage in `docs/pipeline.md` gets implemented (currently: `research.py`, `fact_check.py`, `previz.py`, `video_generation.py`). Established pattern: a frozen-dataclass artifact type for the stage's reviewable output, a stage-specific `<Stage>Error` exception that fails loud on malformed model output (matching `ConfigError`'s convention in `config.py`), and a `run_<stage>_stage(...)` function taking an injectable `completion_fn`/`image_fn`/`video_fn` (default `litellm.completion`/`litellm.image_generation`/`litellm.video_generation`) so tests never need a live API call.

**AWS**: adopted incrementally and only for genuine fit, not proactively (`docs/decisions/0004-aws-incremental-adoption.md`) — SQS is committed for stage 9 (video generation) specifically, as a fan-out-with-retry queue over independent per-scene generation calls; Step Functions is committed for overall pipeline orchestration (matches the sequential-stages-with-human-approval-wait-states shape already). Nothing here is implemented yet, and it isn't needed for the current v1 scope (`docs/decisions/0006`), which uses a plain CLI confirm-loop instead.

**Format**: Shorts-only for now (`docs/decisions/0002-shorts-first-format.md`) — roughly 30–60 seconds. Video generation itself is deferred until the pipeline up to previz is working well (`docs/decisions/0006`).

## Known upstream workarounds

Sometimes a third-party dependency has a real bug with no released fix, and the only way forward is a workaround in this project's own code rather than waiting indefinitely. When that happens: check whether a newer **released** version (stable or an official pre-release build actually published to the package index) fixes it first — never install from an unmerged PR or issue-thread patch as a substitute for a real release, even if it looks relevant, since those can be incomplete or simply wrong (see the litellm example below, where two open PRs claiming to fix the exact error don't actually fix it). Only once a released fix genuinely doesn't exist does a workaround belong in the codebase.

Every such workaround must be tagged with a greppable `WORKAROUND(<issue-or-PR-URL>):` marker at the patch site, so a later session can find every currently-applied one (`grep -rn "WORKAROUND(" src/`) and check whether it's now safe to delete because upstream shipped a real fix.

None currently active. The last two (`src/historical_video_ai/_litellm_workarounds.py`, covering litellm's `Message`/`ModelResponse` construction failing on Python 3.10/3.11 per [litellm#36384](https://github.com/BerriAI/litellm/issues/36384), and a separate undocumented leak of litellm's own internal params into the `video_generation()` request body) were both deleted once the project moved to Python 3.11 + litellm 1.98.0 confirmed both fixed for real — see [docs/decisions/0013](./docs/decisions/0013-python-3.11-upgrade.md).

## Project conventions

- **Architecture decisions are recorded as ADRs** in `docs/decisions/`, one file per decision, numbered sequentially, written once and left alone — a changed decision gets a new ADR that supersedes the old one rather than an edit in place (`docs/decisions/0001-record-architecture-decisions.md`). `docs/architecture.md` stays a short current-state overview; undecided items live in its "Open questions" section until they're resolved, at which point they become an ADR. When you make or are asked to help make an actual architectural decision on this project, write the ADR.
- **`src/` layout**: package code lives under `src/historical_video_ai/`, not flat at repo root (`docs/decisions/0005-project-scaffolding.md`). This is about layout convention, not a rule against a `main.py`-style entry point specifically — the CLI entry point (`cli.py`) lives under `src/historical_video_ai/` for that reason, exposed as the `historical-video-ai` script in `pyproject.toml`.
- **Type annotations are required** on every function's parameters and return type in `src/` — enforced by ruff's `ANN001`/`ANN201`/`ANN202` rules (`pyproject.toml`), not just convention. `tests/` is exempt (pytest fixtures like `tmp_path`/`monkeypatch` are conventionally left unannotated, and every test returns `None`).
- **Keep docstrings/comments tight, not narrative.** State the current behavior and the specific non-obvious "why," then point to the relevant ADR for the full reasoning — don't re-derive an ADR's argument inline, and don't describe what a past version used to do (that's what git history and the ADR are for). This became a real problem once: several module/function docstrings grew into multi-paragraph essays over the course of a session, restating ADR content and narrating the debugging history that led to the current code. Long inline docs on empirical/API-behavior findings (the kind this project has a lot of — verified quirks of third-party providers) are the exception worth keeping, since a type signature can't carry that information at all; a doc that's just re-explaining a decision already recorded in `docs/decisions/` is the one to trim.
