# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An AI pipeline that turns a scene idea into a finished, YouTube-ready video. Different LLMs handle different stages (planning, prompts), with a human review gate before every stage that costs real money. See `docs/architecture.md` for the full vision and the stage diagram, and `docs/pipeline.md` for what each of the 12 stages does and reviews.

**Nothing here is grounded in the real world.** `docs/decisions/0031` reset the goal to videos worth watching rather than accurate ones, and `docs/decisions/0069` finished the job: research, fact-check, premise conflicts, acknowledged fiction and the whole historical framing are deleted. A scene is three strings — time, place, description — and impossible things are welcome. Don't reintroduce a verification step because a scene mentions a real place.

This was `historical_video_ai` until `docs/decisions/0070` renamed it. **Every ADR numbered below 0070 refers to the package as `historical_video_ai` and the command as `historical-video-ai`** — those are write-once records (`docs/decisions/0001`) and were left alone, so read the old names as today's.

**Current build is deliberately narrower than that full vision** — see `docs/decisions/0006-narrow-v1-scope-single-image.md` for the original scoping, though not for the current state. Implemented: scene planning (`stages/scene_planning.py`, `docs/decisions/0023`), which takes a `Scene` and breaks it into beats with characters and locations; stage 8 (previz, `stages/previz.py`), which renders one image per beat; and stage 9 (video generation, `stages/video_generation.py`, `docs/decisions/0010`, `0037`). `cli/` wires scene-planning and previz into one interactive run (`uv run horror-video-ai`); video generation is a deliberately separate, standalone invocation (`--video-gen-from`) — see `docs/decisions/0010` (previz is the spend gate; crossing it should be a distinct, deliberate step). Stages 2–3 were built and then deleted (`docs/decisions/0069`); stages 5–7 and 10–12 were never built.

The single-image previz flow that `docs/decisions/0006` originally scoped — one image straight from the scene — was deleted once scene planning made it unreachable (`docs/decisions/0051`). Every image now comes from a beat. Archived runs in that old shape are still *readable* by `--video-gen-from`; only the generation path is gone.

Two docs are worth reading before touching pipeline design: `docs/architecture.md`'s "Design principles" section (cheap-before-expensive stage ordering, every stage produces a reviewable artifact, adversarial review passes, no hardcoded format) and its "Open questions" section (undecided items like the video-gen model — check there before assuming something is settled).

## Commands

This project uses `uv`; `uv.lock` is committed.

```bash
uv sync                                # install dependencies
uv run pytest                          # run the test suite
uv run pytest tests/test_config.py::test_get_stage_model_returns_pinned_model_string  # single test
uv run ruff check .                    # lint
uv run mypy                            # type check src/, evals/, tests/ -- must be clean
uv run pytest --cov                    # tests + coverage floor (94%)
uv run horror-video-ai --mock      # run the pipeline with no API keys / no network calls
uv run horror-video-ai --time "present day" --place "an underground car park at night" \
    --description "a woman notices someone standing between the pillars."
```

Copy `.env.example` to `.env` and fill in real API keys before running anything that calls a model (never commit `.env`; it's gitignored).

One **external, non-Python dependency**: `evals/motion_test.py` shells out to `ffmpeg` to measure frame-to-frame motion. `uv sync` cannot install it and nothing else in the repo needs it (macOS: `brew install ffmpeg`). That script checks for it up front, because the measurement runs after generation and a missing `ffmpeg` otherwise surfaced only once a clip had already been paid for.

## Verification discipline

**CI runs `ruff`, `pytest` and `mypy` on every push and PR, plus an
offline smoke job** (`.github/workflows/ci.yml`) — the eval scripts'
`--dry-run`s, the judgement export, and one end-to-end `--mock` pipeline
run. All of it is keyless and spends nothing. The smoke job exists because
`testpaths` is `["tests"]` and nothing under `tests/` imports anything
under `evals/`, so the whole measurement layer had no automated coverage
and sat broken for a month without anyone noticing.

Both type checking and the smoke job are **blocking, not advisory**. The
tree is at zero mypy errors, so there is no backlog to grandfather in, and
this repo's documented failure mode is precisely "the guard existed and
nobody ran it".

Three traps that CI caught and that a local run will not:

- `evals/results/` and `outputs/` are gitignored, so anything reading them
  passes on a developer machine and fails in a clean checkout. To
  reproduce CI's conditions, move `evals/results`, `outputs` and `.env`
  aside before running.
- **A stale `.ruff_cache` can give a false pass.** A misordered import that
  ruff flags from a cold cache was reported clean locally by the same
  pinned ruff version. `rm -rf .ruff_cache .mypy_cache` before treating a
  local lint or type result as authoritative, and treat CI -- which always
  starts cold in a clean checkout -- as the authority over a local run.
- **Never redirect a checker's output** (`ruff check . >/dev/null`). It
  reduces the check to an exit code nobody reads and makes a suspiciously
  silent run indistinguishable from a passing one. Read what the tool
  actually said; that is the whole point of the Verification discipline
  above.


When a tool exists for a job — anything in Commands above, or any other install/test/lint/build step — always run it and use its real output, rather than approximating what it would say by hand (hand-simulating a test, eyeballing a lint rule, reasoning about whether a dependency would resolve). A hand-rolled substitute is structurally weaker: narrower coverage, more room for a real problem to slip through unnoticed.

If the real tool genuinely can't be run in the current environment, say so plainly and ask before substituting a manual approximation — don't silently decide to improvise and only report the choice after the fact. This matters most for verification-type gaps (can't run the test suite, can't lint, can't confirm a dependency resolves); it's not about trivial, fully-equivalent workarounds (e.g. `mv` instead of a blocked `rm`), which don't need to trigger this.

## Architecture

**Per-stage model configuration (`config/models.yaml` + `src/horror_video_ai/config.py`)**: every pipeline stage's LLM choice is a pinned `<provider>/<model-name>` string (LiteLLM format) in `config/models.yaml`, never hardcoded in stage code and never auto-substituted or routed on failure — see `docs/decisions/0003-model-configuration-via-litellm.md`. Model choices for research/fact-check/previz specifically are explained in `docs/decisions/0007-research-fact-check-previz-models.md`. `load_stage_configs()` fails loud (`ConfigError`) on a missing file, empty file, or a stage missing its `model` key, rather than falling back silently. When adding a new stage's code, add its corresponding block to `config/models.yaml` first — `tests/test_config.py::test_real_project_config_is_valid` asserts the real committed config still defines every stage that has code depending on it, so that test's `expected_stages` set needs updating too.

**LLM calls go through LiteLLM**, not provider SDKs directly — one `completion(model=..., messages=[...])` call works uniformly across providers so stage code doesn't need provider-specific branches (`docs/decisions/0003`). Image generation uses `litellm.image_generation()`/`image_edit()` the same way (`stages/previz.py`). Video generation is the one deliberate exception: it calls Replicate's REST API directly via `replicate_client.py`, because litellm has no video support for Wan (`docs/decisions/0037`). Both paths are confirmed working end to end against real keys, including a full paid video generation run.

**Secrets** load via `config.load_environment()` (wraps `python-dotenv`), called explicitly at a run's entry point — importing `config.py` has no side effects on the environment.

**Stage code**: one module per pipeline stage under `src/horror_video_ai/stages/`, added incrementally as each stage in `docs/pipeline.md` gets implemented (currently: `scene_planning.py`, `previz.py`, `moderation.py`, `video_generation.py`). Established pattern: a frozen-dataclass artifact type for the stage's reviewable output, a stage-specific `<Stage>Error` exception that fails loud on malformed model output (matching `ConfigError`'s convention in `config.py`), and a `run_<stage>_stage(...)` function taking an injectable `completion_fn`/`image_fn`/`video_fn` (default `litellm.completion`/`litellm.image_generation`/`litellm.video_generation`) so tests never need a live API call.

**CLI code** (`src/horror_video_ai/cli/`): six modules, not one file — a 2,491-line `cli.py` is what this replaced. Which module a new CLI feature belongs in follows from a deliberate one-way import direction, and adding an import that points back up it is how the single file grows again:

- `app.py` — argument parser and `main()`; the only module that knows the whole run's shape. Imports every other module.
- `beats.py` / `video_gen.py` — one per stage-facing flow: beat images + their review loop, and the standalone `--video-gen-from` path.
- `review.py` / `runlog.py` — shared primitives the flows sit on: interactive confirm/edit prompts, and reading/writing a run's `run_log.json`.
- `mocks.py` — the `--mock` fixtures, imported by `app.py` and `video_gen.py` only.

Helpers stay `_`-prefixed unless another module actually calls them; a name without the underscore is a claim that it crosses a module boundary.

**AWS**: adopted incrementally and only for genuine fit, not proactively (`docs/decisions/0004-aws-incremental-adoption.md`) — SQS is committed for stage 9 (video generation) specifically, as a fan-out-with-retry queue over independent per-scene generation calls; Step Functions is committed for overall pipeline orchestration (matches the sequential-stages-with-human-approval-wait-states shape already). Nothing here is implemented yet, and it isn't needed for the current v1 scope (`docs/decisions/0006`), which uses a plain CLI confirm-loop instead.

**Format**: Shorts-only for now (`docs/decisions/0002-shorts-first-format.md`) — roughly 30–60 seconds, vertical 9:16. Genre is horror in a motion-comic style (`docs/decisions/0037`); video generation runs on Wan via Replicate.

## Known upstream workarounds

Sometimes a third-party dependency has a real bug with no released fix, and the only way forward is a workaround in this project's own code rather than waiting indefinitely. When that happens: check whether a newer **released** version (stable or an official pre-release build actually published to the package index) fixes it first — never install from an unmerged PR or issue-thread patch as a substitute for a real release, even if it looks relevant, since those can be incomplete or simply wrong (see the litellm example below, where two open PRs claiming to fix the exact error don't actually fix it). Only once a released fix genuinely doesn't exist does a workaround belong in the codebase.

Every such workaround must be tagged with a greppable `WORKAROUND(...):` marker at the patch site, so a later session can find every currently-applied one (`grep -rn "WORKAROUND(" src/`) and check whether it's now safe to delete because upstream shipped a real fix. Put the issue or PR URL in the parens when one exists. When no upstream issue tracks the bug, write `WORKAROUND(unfiled -- <one-line description>):` — this project does not file bug reports upstream, so an unfiled workaround is a normal steady state, not a TODO. It still has to be re-checkable: an unfiled marker must say how to re-test the bug directly against the installed version, since there is no URL to watch. Do not invent a variant spelling — `TODO(WORKAROUND):` was used once and the documented grep could not find it.

One currently active: `stages/moderation.py`'s `run_moderation_policy_check` strips a leading `"openai/"` from the model string before calling litellm's synchronous `moderation()`, which passes `model` straight through to `openai_client.moderations.create()` with no provider-prefix stripping at all (unlike `completion()`/`image_generation()`) — confirmed still present in litellm 1.101.0 — the version this project runs and the latest released as of 2026-09-18 — by calling `litellm.moderation` against the installed package, not just reading its source; [litellm#6020](https://github.com/BerriAI/litellm/issues/6020) documents the same bug and is closed "not planned," so no upstream fix is coming.

A second one lives in `stages/previz.py`: reference images are passed to litellm's Gemini `image_edit` as raw `bytes`, because its `_read_all_bytes` accepts only `bytes`/`BytesIO`/`BufferedReader` and raises `ValueError` on the `os.PathLike` its own type hint advertises — also re-confirmed against the installed 1.101.0.

**Keep the pinned version and the verified version the same.** These two were verified against 1.100.1 while `uv.lock` pinned 1.98.0, so the project had checked a version it did not run. When you re-check a workaround, upgrade the lock to the version you checked.

The previous two (`src/horror_video_ai/_litellm_workarounds.py`, covering litellm's `Message`/`ModelResponse` construction failing on Python 3.10/3.11 per [litellm#36384](https://github.com/BerriAI/litellm/issues/36384), and a separate undocumented leak of litellm's own internal params into the `video_generation()` request body) were both deleted once the project moved to Python 3.11 + litellm 1.98.0 confirmed both fixed for real — see [docs/decisions/0013](./docs/decisions/0013-python-3.11-upgrade.md).

## Hard bans expire with the model

Some prompt rules forbid something because one image model rendered it
badly -- no character reflections, no distant threat, no process verbs,
one space per beat. These are different from every other rule here: a rule
that *asks* for something shows up (or doesn't) in the next batch of
images, but a ban suppresses the only evidence that would retire it, so it
can be wrong silently and forever. Each is tagged with a greppable
`MODEL-BAN(<model it was measured on> -- <how to re-test it>):` comment,
so `grep -rn "MODEL-BAN(" src/` lists every ban in force. **When
`config/models.yaml`'s `previz` or `video_generation` pin moves to a
different model family or major version, re-verify them all before
shipping the pin** -- by generating the forbidden thing against the new
model and looking at it, never by reasoning from the model's docs -- and
update each surviving ban's marker to the model it was just checked on.
See `docs/decisions/0073`.

## Project conventions

- **Architecture decisions are recorded as ADRs** in `docs/decisions/`, one file per decision, numbered sequentially, written once and left alone — a changed decision gets a new ADR that supersedes the old one rather than an edit in place (`docs/decisions/0001-record-architecture-decisions.md`). `docs/architecture.md` stays a short current-state overview; undecided items live in its "Open questions" section until they're resolved, at which point they become an ADR. When you make or are asked to help make an actual architectural decision on this project, write the ADR.
- **`src/` layout**: package code lives under `src/horror_video_ai/`, not flat at repo root (`docs/decisions/0005-project-scaffolding.md`). This is about layout convention, not a rule against a `main.py`-style entry point specifically — the CLI entry point (`cli/`) lives under `src/horror_video_ai/` for that reason, exposed as the `horror-video-ai` script in `pyproject.toml`.
- **Type annotations are required** on every function's parameters and return type in `src/` — enforced by ruff's `ANN001`/`ANN201`/`ANN202` rules (`pyproject.toml`), not just convention. `tests/` is exempt (pytest fixtures like `tmp_path`/`monkeypatch` are conventionally left unannotated, and every test returns `None`).
- **Keep docstrings/comments tight, not narrative.** State the current behavior and the specific non-obvious "why," then point to the relevant ADR for the full reasoning — don't re-derive an ADR's argument inline, and don't describe what a past version used to do (that's what git history and the ADR are for). This became a real problem once: several module/function docstrings grew into multi-paragraph essays over the course of a session, restating ADR content and narrating the debugging history that led to the current code. Long inline docs on empirical/API-behavior findings (the kind this project has a lot of — verified quirks of third-party providers) are the exception worth keeping, since a type signature can't carry that information at all; a doc that's just re-explaining a decision already recorded in `docs/decisions/` is the one to trim.
