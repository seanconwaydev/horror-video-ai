# 58. Delete prompt rules by judgement, not by ablation

Date: 2026-09-18

Status: Accepted

Resolves the open item in
[playbook/repo-audit-brief.md](../playbook/repo-audit-brief.md) and
declines the design in
[playbook/prompt-rule-registry-scope.md](../playbook/prompt-rule-registry-scope.md).

## Context

The scene-planning prompt had grown to 34 bullet rules. Each arrived as a
fix for something a real run got wrong, and none has ever been removed,
so the prompt only ever gets longer. The audit asked the obvious
question -- which of these are still earning their place? -- and a scoped
design exists for answering it properly: a registry that makes each rule
individually switchable so it can be ablated and measured.

The reason not to build it now is that there is nothing to measure
against. [0055](./0055-delete-the-automated-previz-reviewer.md) deleted
the automated reviewer after measuring it: it agreed with the owner's
keep/discard decision on 56% of 78 images against 79% for accepting
everything. The pipeline has no automated quality signal at all. An
ablation harness whose scorer is a human reviewing images one at a time
is not an ablation harness; it is the review loop that already exists,
with extra machinery in front of it.

So the registry is deferred, and the rules it was meant to test get
judged directly.

## Decision

Delete three rules now, on their merits, and leave the registry unbuilt.

- **The historical-visitor wardrobe rule** ("a modern-day visitor, time
  traveler, narrator... describe wardrobe with contemporary clothing
  items"). Written for a pipeline whose subject was historical accuracy.
  [0031](./0031-goal-is-quality-video-not-historical-accuracy.md) settled
  that this project is not that, and the current genre is horror. The
  rule addresses a situation the pipeline no longer sets up.
- **The lit-screen brightness rule** and **the screen-orientation rule**.
  Both are instance patches from one specific failure with a phone, and
  both are addressed to the wrong layer. The orientation rule in
  particular asks the *planner* to write a sentence about what the
  *image model* should not draw. The planner obeyed it -- the run logs
  from 2026-09-17 contain beats specifying the screen turned away from
  camera -- and the image came back with the screen facing the viewer
  anyway. (Those particular observations come from the reviewer 0055
  deleted, so treat them as weak evidence of the mismatch rather than
  proof of it.) That is the shape
  [0054](./0054-one-fact-per-field.md) describes: an instruction that is
  losing needs a field, not a firmer sentence. If screen orientation
  matters again, it should arrive as structure, not as bullet 34.

0052's own composition rule is left in place. The audit flagged that it
should be judged alongside the rest rather than grandfathered in for
being recent, which is fair -- but it has never been observed in a real
run either, and deleting it unmeasured would be the same mistake in the
opposite direction.

## Consequences

The prompt is 31 rules instead of 34. Nothing measures whether that is
better, and this ADR does not pretend otherwise: the claim is that three
rules were addressed to problems this pipeline no longer has, or to a
layer that cannot act on them, not that removing them improves output.

The registry design is not discarded, only unscheduled. It becomes worth
building the day there is a scorer worth ablating against -- which is a
different open question, and a bigger one.

The general lesson is the one the audit stated: a rule that already
exists and is losing should change tier rather than get sharpened. Adding
bullet 35 to fix what bullet 34 failed to fix is how this prompt got
here.
