# 35. `--genre` and `--tone` replace the binary `--creative` flag

Date: 2026-09-03

Status: Accepted

Supersedes: [decisions/0034](./0034-creative-flag-skips-historical-grounding.md)

## Context

The project owner asked for real research (not guesswork) on what shape a video-generation pipeline's entry point should actually take, given this project's own was still three free-text strings plus an ad hoc `--creative` boolean. The research (`docs/playbook/human-input-and-tools.md`) converged on a consistent answer across sources: production AI-content systems structure input as a **creative brief** -- objective, audience, tone, constraints, deliverables -- not a freeform prompt, and **genre specifically** is a real, evidenced field (a book-generation case study showed genre alone measurably affects output success rate), not an invented one.

ADR 0034's `--creative` flag was a first, deliberately scoped-down step in this direction, but it encoded genre as a bare boolean (real vs. not-real) rather than as the actual descriptive field the research points to. That's a real gap: a "meme" scene and a "vlog" scene both skip historical grounding for the same reason, but they don't want the same staging conventions, and a boolean can't carry that distinction. Tone (near-universal in every creative-brief source found, and previously absent from this project's input entirely) was also a real, named gap, not a speculative one.

The project owner's explicit instruction on scope: "you can completely change whatever needs changing, use this newest research as the guiding light, not previous vibes" -- a mandate to implement the researched shape directly rather than bolt genre onto the existing boolean.

## Decision

`--creative` (boolean) is replaced by `--genre` (free text, default `"historical"`) and a new `--tone` (free text, optional). Free text, not a fixed enum -- the whole point of genre flexibility is not hardcoding a closed list (matches the project's broader "stay genre-agnostic, discover what works empirically" stance, ADR 0031).

Grounding requirement is now derived from genre rather than being its own separate flag: `requires_grounding = (genre.strip().lower() == "historical")`. Every other genre value skips research/fact-check and uses the ungrounded scene-planning/previz_review framing, exactly as `--creative` did -- the mechanism from ADR 0034 (`_GROUNDED_PREAMBLE`/`_CREATIVE_PREAMBLE`, the ungrounded review template) is unchanged, just now selected by a genre value instead of a boolean.

`genre` (when not "historical") and `tone` (always, when given) are woven into scene-planning's prompt, with an explicit instruction that they must actually shape staging/expression/wardrobe choices, not just be echoed back as prose -- matching this project's established "explicit allowlist, not inference" principle (ADR 0026) applied to a new kind of context, not just anachronism exceptions.

A `--fixture` replay always implies grounding (`requires_grounding = True`, `genre = "historical"`) unconditionally -- a fixture is, by construction, a replay of a previously completed real research/fact-check run, from before this flag existed.

## Consequences

`cli.py` (flag definitions, `requires_grounding` computed once and threaded through both `run_scene_planning_stage` and `_generate_beats_with_choices` calls) and `scene_planning.py` (`genre`/`tone` parameters, `{genre_tone_line}` woven into both preambles, a new planning rule instructing the model to actually use them) changed. No changes to `previz.py` -- it only ever needed the already-existing `requires_grounding` boolean, not the genre string itself.

Explicitly not done here, and deliberately deferred: genre-specific *convention* sets (the 180-degree-rule-vs-jump-cuts-vs-other-trope-sets idea from `architecture.md`'s open questions) and a fuller structured brief (audience, constraints-as-one-concept, deliverables). This is the field existing, not yet a taxonomy of what each field's value should do beyond the grounding/staging hooks added here.
