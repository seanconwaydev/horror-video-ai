# 5. Project scaffolding: uv, src-layout, YAML config, pytest, ruff

Date: 2026-08-13

Status: Accepted

## Context

Before writing any pipeline stage as real code, the project needed basic scaffolding: a dependency manager, a code layout, a concrete implementation of the per-stage model config described in [0003](./0003-model-configuration-via-litellm.md), a place for API keys, and a testing/linting setup.

## Decision

**`uv`** for dependency management and packaging, over pip+venv or Poetry — it's fast, it's what LiteLLM's own docs recommend for installing it, and it removes the "what's installed where" ambiguity that plain pip/venv is prone to.

**`src/` layout** (`src/historical_video_ai/`) rather than a flat layout — the modern-recommended structure, avoids a class of import-path bugs flat layouts are prone to, and is what a new developer would expect.

**Config: `config/models.yaml`**, one top-level key per pipeline stage, each holding a nested block of that stage's settings (currently just a pinned `model` string). Loaded by `src/historical_video_ai/config.py`, which raises a clear `ConfigError` for a missing file, an empty file, a stage missing its `model` field, or a request for an unconfigured stage — deliberately fails loud rather than silently falling back to anything.

**Secrets: `.env` (gitignored) + `.env.example` (committed, documents required variable names without values)**, loaded via `python-dotenv`, explicitly via a `load_environment()` call rather than as an import side effect.

**Testing: `pytest`**, with real tests from the start (`tests/test_config.py`) covering both the loader's behavior with temporary fixture files and a check that the actual committed `config/models.yaml` is valid.

**Linting: `ruff`.**

Not done yet, deliberately: pre-commit hooks, CI, Docker.

## Consequences

Verification note: the code execution sandbox this was built in has no network access to PyPI, so `uv add` couldn't actually run, and the `pytest`/`ruff` suites couldn't be executed here. Dependencies were added to `pyproject.toml` by hand instead (unpinned -- real versions get resolved and pinned into `uv.lock` on first real `uv sync`). The config-loading logic itself was manually smoke-tested with a direct Python invocation (using pyyaml/python-dotenv, which happened to already be present outside the project's venv) and confirmed working, but the actual test suite has not been run by anyone yet. Running `uv sync && uv run pytest` locally is the next real verification step, not optional follow-up.

The old root-level `main.py` (empty, pre-dates this scaffolding) is now vestigial given the `src/` layout -- left in place rather than deleted without asking.
