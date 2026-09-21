# 69. Delete research, fact-check, and everything that grounded a scene in the real world

Date: 2026-09-19

Status: Accepted

Completes [0031](./0031-goal-is-quality-video-not-historical-accuracy.md),
which reset the project's goal but left the machinery in place. Voids the
grounding halves of [0034](./0034-creative-flag-skips-historical-grounding.md)
and [0035](./0035-genre-and-tone-replace-binary-creative-flag.md), and the
decisions that exist only to serve grounding:
[0008](./0008-refuse-impossible-premises.md),
[0014](./0014-fact-check-claims-by-number.md),
[0015](./0015-persist-research-before-fact-check.md),
[0018](./0018-fact-check-model-retired.md),
[0019](./0019-yes-flag-refuses-contradicted-flags.md),
[0025](./0025-keep-premise-conflict-as-intentional-fiction.md),
[0026](./0026-previz-review-knows-acknowledged-fiction.md),
[0027](./0027-fact-check-result-round-trips-through-fixture.md) and
[0030](./0030-acknowledged-fiction-covers-knock-on-consequences.md). The
research/fact-check halves of [0003](./0003-model-configuration-via-litellm.md)'s
config and [0007](./0007-research-fact-check-previz-models.md)'s model
choices go with them.


Completed by [0070](./0070-rename-to-horror-video-ai.md), which does the
rename this ADR's final paragraph defers.
## Context

[0031](./0031-goal-is-quality-video-not-historical-accuracy.md) settled
that this project makes videos worth watching, not accurate ones, and
that fantastical and impossible elements are welcome. That was a year of
decisions ago in repo time, and the machinery built on the old premise
was never removed. It was still the default path.

`--genre` defaulted to `"historical"`, so a bare `historical-video-ai`
run called `perplexity/sonar-deep-research` — the most expensive text
call in the pipeline — to gather sourced claims about a real time and
place, ran a second model to fact-check them, asked the human to resolve
each flag, and then handed the planner a preamble beginning *"You are a
shot-list planner for a short historical video scene"* with a block of
*"Verified claims about this place (use these to ground locations and
beats in real detail)"*.

For a horror short set in an underground car park, all of that is
overhead at best. The owner's framing, applied to the whole subsystem:
everything history-related should be gone, including any concerns about
fiction.

Three things made this safe to do in one pass rather than incrementally.

**The destination already existed and worked.** `--genre meme` skipped
research and fact-check entirely, built a stub result with no claims, and
went straight to scene planning. That path had been exercised for weeks.
Deleting is a collapse onto it, not a new design.

**Most of the fiction machinery was already disconnected.**
`acknowledged_fiction` — the string a human produces by saying "yes, the
time-travel smartphone is deliberate" — was read only by
`run_previz_review_stage`, which [0055](./0055-delete-the-automated-previz-reviewer.md)
removed from the pipeline. So the human was being asked a question whose
answer reached nothing that ran.

**The audit had just finished.** Three passes over this repo established
that its characteristic failure is a decision outliving its premise while
looking alive. This is the largest instance of exactly that, and the one
0031 predicted.

## Decision

Deleted outright: `stages/research.py`, `stages/fact_check.py`,
`cli/research_flow.py`, their three test modules, `tests/fixtures/`, the
`research` and `fact_check` model pins, and the `--fixture` and
`--experiment-model` flags. `--fixture` replayed a captured research +
fact-check result to avoid re-paying for it; there is nothing expensive
left to replay, since a scene is now three strings on the command line.
`--experiment-model` only ever overrode those two stages' models.

`run_scene_planning_stage` takes a new `Scene` (time, place, description)
instead of a `FactCheckResult`. `time` and `place` stay: *"present day"*
and *"an underground car park at night"* are a setting, not a claim about
the world.

One preamble instead of two. The second existed only to *undo* the
first's framing — it spent a paragraph telling the planner not to treat
anything as needing real-world grounding. With nothing asserting
grounding, nothing needs to disclaim it.

`previz_review`'s anachronism-detection half is gone too, leaving the
plan-fidelity check [0032](./0032-previz-review-trusts-planned-details.md)
defined. That reviewer is still out of the pipeline (0055) and still
exists for evals/.

`--genre` now defaults to `horror`, the genre this project actually
makes ([0037](./0037-horror-motion-comic-shorts-wan-via-replicate.md)).
No value is special any more; `historical` is just another genre.

## Consequences

**The planner now sees the genre on a default run, and did not before.**
Genre was passed to the prompt only when a run was *un*grounded, on the
reasoning that a grounded run's genre was always the literal string
"historical" and the preamble said so already. Both halves of that are
gone, so a default run gains a real input it was previously denied. This
is a behaviour change to the live prompt, not just a deletion, and it is
the one thing here worth watching in the next run's output.

A run is cheaper and shorter: one fewer paid model call, one fewer
review gate, and no flag-resolution prompts between the command and the
scene plan.

Nothing verifies claims about the world any more, and that is the point
rather than a regression to mitigate. A scene that wants a real place
gets it from the description the human wrote.

Old run logs keep their `research_claims` and `fact_check_flags` keys.
Nothing reads them, and `evals/export_judgements.py` stamps rows from a
fixed field list that never included them. The `--fixture` path that
consumed them is gone, so they are inert history rather than a
compatibility burden.

The package is still called `historical_video_ai` and the command is
still `historical-video-ai`. That rename is deliberately a separate
change: it touches every import, the CI workflow, every doc and the
command the owner types, and mixing it into a behavioural deletion would
make both harder to review and to revert.
