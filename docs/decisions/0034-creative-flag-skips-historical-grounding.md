# 34. `--creative` skips historical grounding, not just fact-check

Date: 2026-09-03

Status: Accepted

Superseded by [0035](./0035-genre-and-tone-replace-binary-creative-flag.md).

## Context

The project owner identified a real inconsistency in how this project was being reasoned about, not just a missing feature: "you say we need to be flexible but then push back when i want to forego fact checking in certain ways." Fact-checking's mandatory status traces to ADR 0008, written before "research best practices first" became a standing habit on this project -- an early, reasonable-guess decision, not one backed by the research this session has since done. Meanwhile the project's stated goal (ADR 0031) is videos worth watching across whatever genres turn out to work, not historical accuracy for its own sake.

Making fact-checking skippable isn't just "skip an API call," though. The historical-accuracy framing is baked into the actual prompt text of two other stages: `scene_planning.py`'s template opens with *"a shot-list planner for a short **historical** video scene"*, and `previz_review`'s entire job description is *"reviewing a generated image against a **historically accurate** scene description... does it depict anything that could not have existed or happened at this time and place?"* For a scene that was never claiming to be real -- a meme, an abstract idea -- that framing isn't neutral overhead to skip, it's actively wrong: "could not have existed" is the point of the scene, not a defect to flag.

## Decision

A `--creative` CLI flag, when set:

- Skips `run_research_stage`/`run_fact_check_stage` entirely. `main()` constructs a minimal `FactSheet`/`FactCheckResult` directly from the given time/place/description, with no claims, no premise conflict, no acknowledged-fiction machinery -- there's nothing to fact-check or excuse in the first place.
- `run_scene_planning_stage` gains `requires_grounding: bool = True`, selecting between two preambles (`_GROUNDED_PREAMBLE`, unchanged, vs. a new `_CREATIVE_PREAMBLE` that explicitly tells the model not to treat anything as needing real-world grounding). The shared planning rules (coverage, staging, screen orientation, furniture contact, etc.) apply to both -- those are genuinely genre-agnostic craft advice, not historical-accuracy-specific.
- `run_previz_review_stage` gains the same parameter, selecting between the existing anachronism-plus-fidelity template and a new fidelity-only template that drops the anachronism check entirely rather than trying to soften it.

Explicitly scoped down, per the project owner's own call, matching the pattern that worked for `--style`: a binary flag now, not a fuller genre-taxonomy system, to be verified on a real contrasting pair of runs (a meme scene against the existing Pompeii scene) before any further design. A proper genre/structured-input schema at the pipeline's entry point is real, separate, tracked future work -- deliberately not conflated with this scoped-down first step.

## Consequences

`cli.py` (new flag, stub fact-sheet construction, threading `requires_grounding` through scene-planning and every previz_review call), `scene_planning.py` (`_GROUNDED_PREAMBLE`/`_CREATIVE_PREAMBLE` split), and `previz.py` (`_UNGROUNDED_REVIEW_PROMPT_TEMPLATE`) changed. No new dataclass fields. `_generate_previz_with_review` (the pre-scene-planning single-scene flow) is not reachable from `main()`'s actual runtime path anymore and was left untouched -- out of scope here.
