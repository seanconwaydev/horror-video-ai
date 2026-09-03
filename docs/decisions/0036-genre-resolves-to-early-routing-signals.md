# 36. Genre resolves to explicit, early routing signals; rules select by signal, not inline prose

Date: 2026-09-03

Status: Accepted

## Context

A real test run (recreating a user-supplied surreal reference photo via `--genre "surreal photo collage"`) surfaced a genuine architectural conflict, not just a wording problem: `scene_planning.py`'s "staging" rule (clarity, one legible focal point) was actively fighting what the genre needed (asymmetric, chaotic composition). The first fix was an inline prose hedge — "the staging rule still applies to *what* the strange thing is, not whether the scene stays centered" — which worked but is a known anti-pattern: a rule growing exceptions in its own prose as more genres are tested is not a system, it's debt that compounds with every new genre.

The project owner asked for real research (not guesswork) on three questions this raised: where/when should rules apply per-genre systemically; should genre be decided even earlier/more bindingly than today's `--genre` CLI flag; and should the pipeline split by genre entirely. Full research: [playbook/genre-conditioned-pipeline-design.md](../playbook/genre-conditioned-pipeline-design.md).

The project owner's explicit instruction on how to weigh that research against this project's existing genre-related decisions: follow it closely, "even if it requires large changes," because "the current structure feels too limiting" — this ADR is authorized to override prior genre-handling decisions where they conflict with the researched direction, not just add to them. It also supersedes the approach (not the underlying problem) that PR #44's inline-hedge staging-rule fix took — that PR merged before this research was done, using the pattern this ADR now retires. Rather than revert it, the follow-up implementing this ADR replaces its prose-hedge text in place with the mechanism below.

## Decision

Three findings from the research, adopted directly:

**1. Rule selection.** Replace inline prose hedges with named, selected rule groups (the Strategy/Rules-Engine pattern, and how production content-moderation policy engines handle per-category rules: route to a category, then apply that category's rule set, with rules kept structurally separate from the core prompt-building logic). Built **reactively** — one named rule group per rule, only once a real cross-genre conflict is actually observed in a real run, matching this project's existing preference for reactive rather than speculative resilience work. Not a taxonomy of every rule against every possible genre built up front.

**2. Early binding.** `--genre` and `--tone` stay free text — `decisions/0035`'s reasoning (flexibility, discover-what-works-empirically, matches `decisions/0031`) still holds and is not overridden here. What's added is a small, closed-set classification *derived* from that free text, generalizing the pattern `requires_grounding` already uses correctly (`decisions/0034`/`0035`: computed once, early, threaded through explicitly) to cover more than just the grounding axis. Each new axis (grounding was the first; composition/staging is the second, see Consequences) is its own small, independently-resolved signal — not one master "genre enum" — computed once per run and passed explicitly to whatever stage needs it, instead of raw genre/tone text being independently re-interpreted per stage or per rule.

**3. No pipeline split.** The pipeline stays one system. Every relevant precedent found (controllable-generation architecture, mixture-of-experts/mixture-of-prompts, LLM routing, content-moderation policy engines) treats a category signal as routing *within* one system at specific decision points, not a reason to fork the codebase per genre. A full split would replicate every future cross-cutting fix (e.g. `decisions/`-tracked previz_review or transient-retry fixes) once per genre fork, to solve a problem that so far is scoped to specific rules in specific stages.

A game-design counter-perspective was researched and explicitly considered (genre conventions as a creative trap when treated as a priori constraints rather than diagnosed post-hoc) — judged not to apply here: that concern is about genre constraining original invention, whereas this project's problem is genre-blind rules fighting a genre's *already-decided* creative intent. The reactive-only scoping in point 1 already absorbs the legitimate part of that caution (don't speculatively build out a genre taxonomy) without treating genre-conditional rules themselves as suspect.

## Consequences

`scene_planning.py`'s staging rule becomes the first concrete instance of this pattern: a new small, closed, early-resolved signal (`composition_mode`: `"staged"` or `"chaotic"`) replaces the inline "unless genre signals X" hedge merged in PR #44, with the staging rule and its surreal-genre counterpart restructured into named, selected rule groups. Resolved deterministically from the `genre`/`tone` parameters `run_scene_planning_stage` already receives -- no new parameters threaded through `cli.py` were needed for this first instance, since both inputs were already in scope where the signal is used. A future axis that a downstream stage (e.g. `previz_review`) also needs would follow `requires_grounding`'s fuller shape (computed in `cli.py`, passed explicitly) instead -- not required yet, since no such need has been observed.

This does not retroactively redesign `requires_grounding` itself (`decisions/0034`/`0035` stand as-is) — it generalizes the *pattern* they established to a second axis, and establishes that pattern as the standing approach for every future genre-conditional rule conflict this project finds, rather than a one-off.

Resolves the `architecture.md` open question "whether an overall video style/genre preset is worth adding" for the *rule-application* half of that question specifically (the 180-degree-rule-vs-jump-cuts-vs-other-trope-sets idea). Still open, deliberately not addressed here: the fuller structured-brief fields (audience, constraints-as-one-concept, deliverables — tracked separately) and whether per-stage *model* selection (not just prompt rules) should also route on grounding/genre, raised separately by the project owner and tracked as its own open item.
