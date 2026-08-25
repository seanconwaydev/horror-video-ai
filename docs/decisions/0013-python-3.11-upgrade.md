# 13. Upgrade to Python 3.11, delete both litellm workarounds

Date: 2026-08-25

Status: Accepted

## Context

By the time the video-generation stage was working end to end, this
project was carrying two undocumented-to-outright-bugged litellm
behaviors patched locally in `_litellm_workarounds.py`:

1. `litellm.types.utils.Message`/`ModelResponse` failing to construct at
   all on Python 3.10/3.11 ([litellm#36384](https://github.com/BerriAI/litellm/issues/36384)),
   breaking `litellm.completion()` for every provider.
2. `video_generation()`'s own internal implementation details
   (`local_vars`, `_is_async`) leaking into the actual HTTP request body,
   breaking every Sora-2 call outright.

Both were checked against real released litellm versions before either
workaround was written, per this project's own "prefer an upgrade over a
workaround" convention (`CLAUDE.md`'s "Known upstream workarounds"). Both
turned out to already be fixed in the real, released `1.98.0` -- verified
by direct reproduction against litellm's real code in an isolated venv,
not assumed from a changelog. But `1.98.0` (and the newest available
pre-release, `1.99.0rc1`) unconditionally `from typing import
NotRequired`, which doesn't exist before Python 3.11, so litellm failed to
even *import* on this project's then-current Python 3.10
(`.python-version`). No usable released fix existed for this project's
actual environment, which is what justified writing the workarounds in
the first place rather than just upgrading immediately.

Sean asked for the Python 3.11 upgrade specifically to remove that
blocker and delete the workarounds once confirmed unnecessary -- not to
bundle it into whichever feature happened to be in flight when the
litellm bug was found, so any regression from the version bump would be
easy to isolate from unrelated feature work.

## Decision

**Moved to Python 3.11** (`.python-version`, `pyproject.toml`'s
`requires-python`) and **upgraded litellm to the real released `1.98.0`**
(`uv lock --upgrade-package litellm`). Both workarounds were then
re-verified against the *actual* upgraded environment -- not just
carried over as "should be fine" from the earlier isolated-venv checks --
before being deleted:

- `litellm.types.utils.Message(...)` constructs fine directly, with no
  workaround imported.
- A full `litellm.completion(..., mock_response=...)` call (the same real
  code path every stage module actually uses) succeeds with no workaround
  imported.
- `litellm.video_generation()`'s real request-building path (reproduced
  end-to-end by intercepting the HTTP layer, the same technique used to
  originally find the bug) produces a clean request body with no
  `local_vars`/`_is_async` leak, no workaround imported.

Worth noting for future maintenance: the video-generation workaround's
own self-deactivation probe (which fed a synthetic `{"local_vars": ...}`
dict directly into `get_requested_video_generation_optional_param()`) was
testing the wrong layer -- that function will always pass through a key
you hand it directly, regardless of whether the real bug is fixed. The
actual fix landed further upstream, in what `video_generation()` itself
constructs before calling that function. The probe would have kept
reporting "still broken" indefinitely. This was only caught because the
workaround was verified against the *real* call path before deletion,
rather than trusting the probe's own verdict -- the same "verify directly,
don't infer from a proxy signal" discipline this project already applies
to live API calls.

`_litellm_workarounds.py` is deleted in full (both of its workarounds were
everything it contained), along with the `from historical_video_ai import
_litellm_workarounds # noqa: F401` import in every stage module that had
one (`research.py`, `fact_check.py`, `previz.py`, `video_generation.py`).
`CLAUDE.md`'s "Known upstream workarounds" section is updated to reflect
none currently active.

## Consequences

`ruff` flagged one new opportunity once the project's Python floor moved
to 3.11 (`UP017`: `datetime.timezone.utc` -> `datetime.UTC`, added in
3.11) -- applied via `ruff check --fix`.

Fixed a separate, pre-existing gap surfaced while smoke-testing this
upgrade, unrelated to Python/litellm: `cli.py`'s `--mock` previz fake
returned a bare 1x1 pixel PNG, which `video_generation`'s aspect-ratio
guard ([0011](./0011-previz-image-model-for-video-aspect-ratio-fit.md))
correctly rejects on contact -- `--mock --video-gen-from` was silently
broken (raising a real `VideoGenerationError` instead of exercising the
mock path) any time after that guard was added. Replaced the mock's fixed
image with a real 90x160 PNG (Sora's exact 9:16 target ratio, tiny for
speed).

Full test suite (89 tests) and `ruff check` both pass on the upgraded
environment; a full mock pipeline run (research through video generation,
including `--video-seconds`) was exercised end to end as a smoke test.
Not yet re-verified: a full real, paid run through every stage on the
upgraded environment -- the individual real-call paths this ADR cared
about (Message construction, a real `completion()` call, and
`video_generation()`'s request-building) were each verified directly, but
that's not the same as re-running the whole paid pipeline once more just
to prove the upgrade didn't regress anything, which hasn't been done.
