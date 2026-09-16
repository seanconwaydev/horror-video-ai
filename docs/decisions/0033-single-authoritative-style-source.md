# 33. A single, explicit `--style` source replaces three independent ones

Date: 2026-09-02

Status: Accepted

Its implementation superseded by
[0039](./0039-committed-style-presets-and-single-style-slot.md); the decision
itself stands.

## Context

Two consecutive real runs showed the same style-consistency failure: generated images landed at inconsistent points on the realistic-to-stylized spectrum within a single run -- sometimes a whole beat rendered as stylized 3D/CGI instead of photorealistic, sometimes only the character while the environment stayed photoreal. Root cause, confirmed by inspection: style was specified independently in three separate places with no single source of truth -- `build_character_sheet_prompt`'s hardcoded style line, `build_location_reference_prompt`'s separately hardcoded style line, and every beat's own independently LLM-generated `style` field. Even when each was individually reasonable, nothing forced them to agree with each other.

Real industry vocabulary exists for the actual spectrum -- Realistic / Semi-Realistic ("Pixar sorta-lifelike," a controlled balance between realism and stylization) / Stylized (cel-shaded, exaggerated, cartoon/anime) -- and professional pipelines lock this via a "style bible": a document naming rendering approach, detail level, and explicit "what not to do" examples. See `docs/playbook/failure-taxonomy.md`'s style-consistency entry for the full research trail.

The project owner confirmed both realism levels are legitimate targets -- the requirement is deliberately choosing and holding one, not defaulting to photorealism. They also want the fuller style-bible (per-principle controls: rendering technique, line-work, color grade, and which of the 12 animation principles like squash/stretch/exaggeration apply and how strongly) as the actual eventual goal, but agreed to build the minimal version first and verify it holds on a real run before expanding -- given this session's repeated pattern of a fix looking complete until tested for real.

## Decision

A `--style` CLI flag (`photorealistic` / `semi-realistic` / `stylized`, default `photorealistic` -- preserving prior behavior) becomes the single authoritative realism-level source for a run. `previz.py` gains `_STYLE_INSTRUCTIONS`, a fixed mapping from each level to a concrete instruction with an explicit negative constraint (e.g. photorealistic explicitly says NOT 3D-rendered/CGI/anime) -- a bare positive adjective already proved insufficient to prevent drift in real runs.

`build_character_sheet_prompt` and `build_location_reference_prompt` now take this value and use it in place of their previous hardcoded style lines. `_build_beat_prompt`/`run_beat_image_stage` keep `beat.style` (legitimate per-beat cinematography variety -- lens, grain, framing) but append the authoritative instruction after it as an explicit override, so the realism level itself doesn't compete with whatever a given scene-planning call happened to write.

Explicitly deferred, not abandoned: the fuller style-bible (per-principle intensity controls, rendering technique, line-work, color grade) is the actual target this is a first step toward -- tracked as an open item in the failure-taxonomy doc so it isn't dropped once the minimal flag ships.

## Consequences

`previz.py` (`build_character_sheet_prompt`, `build_location_reference_prompt`, `_build_beat_prompt`, `run_beat_image_stage`) and `cli.py` (new flag, threaded to `_generate_scene_references` and `_generate_beats_with_choices`) changed. No new dataclass fields on `Character`/`Location`/`Beat`. `PrevizError` is raised for an unrecognized style value, matching the project's fail-loud convention.
