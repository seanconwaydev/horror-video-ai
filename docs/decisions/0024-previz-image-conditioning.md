# 24. Previz gains image-conditioning: character and location references

Date: 2026-09-01

Status: Accepted

## Context

`run_previz_stage` (`stages/previz.py`) only ever does plain text-to-image
(`litellm.image_generation()`) -- it has no reference-image parameter at
all. Every real test of image-conditioning this project has actually run
(the Agent Voss beats, the two full Pompeii experiments) happened entirely
outside this codebase, in throwaway scripts calling `litellm.image_edit()`
directly. That's the gap this ADR closes -- it takes what those scripts
proved works and makes it a real previz capability, consuming
[decisions/0023](./0023-scene-planning-stage.md)'s `Location` and
`Character` output instead of hand-written prompt text.

The Pompeii redo (`docs/playbook/video-generation-prompting.md`) confirmed
two specific things worth building around: a **dedicated, neutral,
non-narrative reference image** works better as a character anchor than
reusing a busy narrative beat, and a **canonical, no-character location
reference**, reused across every beat set there, is what actually fixes
cross-beat setting drift -- text description alone, even good text
description, already failed at this once. Both are real generation inputs,
not prompt-wording choices, so previz needs an actual parameter for each.

A real, reproducible bug was also found and worked around directly:
`litellm.image_edit()`'s Gemini provider advertises `os.PathLike` as an
accepted `image` type but actually raises `ValueError: Unsupported image
type for Gemini image edit.` on a bare `Path` -- the same category of bug
`video_generation.py` already documents for `input_reference`, just in a
different litellm code path. Also hit repeatedly: real transient Gemini
`InternalServerError`/`ServiceUnavailableError` responses on `image_edit`
calls, at a similar rate to what `run_previz_stage`'s existing
`_TRANSIENT_IMAGE_ERRORS` retry logic (0016) was built to handle for plain
generation.

## Decision

`run_previz_stage` gains two new optional parameters: `character_reference:
Path | None` and `location_reference: Path | None`. When either is given,
the stage calls `litellm.image_edit()` instead of `litellm.image_generation()`,
passing the reference image(s) as raw bytes rather than a bare `Path`
(`WORKAROUND(<litellm issue URL -- to be filed/found before implementing,
per this project's convention of checking for a released fix first>)`).
The existing transient-retry loop wraps whichever call is actually made
(generation or edit), not just generation, since both now have real,
observed transient-failure evidence.

A new, simpler function, `run_reference_image_stage(prompt: str, *, model=None,
image_fn=litellm.image_generation, output_dir) -> PrevizResult`, generates
the character-sheet and location-reference images themselves -- plain
text-to-image, no `FactCheckResult` input (a reference image isn't tied to
a specific historical scene the way a beat's final image is), reusing
`PrevizResult` as its return type since the shape (an image path + the
prompt that produced it) is identical.

**Orchestration (`cli.py`), once a `ScenePlan` (0023) is approved:**
generate the character reference once per `Character`; generate one
location reference per `Location`; then for each `Beat`, call
`run_previz_stage(..., character_reference=<that beat's character's ref>,
location_reference=<that beat's location's ref>)`. `previz_review` still
runs per beat exactly as today -- image-conditioning changes what
generates the image, not whether the result gets independently checked.

## Consequences

No new `config/models.yaml` entry -- reference generation and
conditioned generation both use previz's existing pinned model, just a
different call shape. `tests/test_previz.py` gains cases for the new
parameters (fake `image_fn`/`edit_fn`, asserting the right one is called
and that reference bytes -- not a `Path` -- are what's actually sent).

Not addressed here, explicitly future work: multi-reference conditioning
beyond one character + one location (some platforms support up to 7
simultaneous references, per the research behind the playbook's findings);
axis-of-action/screen-direction consistency across a scene's beats
(`docs/architecture.md`'s open questions); and the two real prompt-level
misses from the Pompeii redo (a gesture-direction instruction not fully
realized, a simulated phone-selfie POV producing a confused double-subject
result) -- both prompting problems to solve empirically, not something
this ADR's plumbing change fixes by itself.
