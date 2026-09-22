# 26. previz_review is told about acknowledged intentional fiction

Date: 2026-09-02

Status: Accepted


Voided by [0069](./0069-delete-historical-grounding.md): the allowlist it built told a reviewer
not to flag acknowledged fiction, and there is no longer either one.
## Context

A real run of the Pompeii scene, after 0025 landed, hit a severe, costly
regression: 10 of 12 beats were rejected by `previz_review`, each burning
all 3 automatic retry attempts (30 wasted image generations total) --
every single rejection was for depicting the smartphone the human had
already explicitly chosen to keep as intentional fiction at the
premise-conflict gate. The two beats that did pass only did because the
image model happened not to render the phone in those particular shots,
not because the reviewer became lenient about it.

Root cause: 0025's "keep as intentional fiction" choice clears
`fact_check_result.premise_conflict` to `None` so `run_previz_stage`'s own
hard-refuse check is satisfied, but `run_previz_review_stage` -- a fully
separate, independent adversarial check run per beat -- receives that same
`fact_check_result` and has no way to know the smartphone was ever
acknowledged as deliberate. It is doing exactly its job (docs/decisions
/0009: flag anything that couldn't have existed at this time and place)
correctly, by its own narrow mandate, with no visibility into a decision
made upstream.

This is corroborated by real research checked before designing the fix,
not just reasoned from this one incident:

- Content-moderation best practice uses a tiered review with an explicit
  escalation hierarchy where a human with authority can grant an
  exception -- and that exception is expected to persist and be respected
  going forward, not be silently dropped and re-litigated on every
  subsequent automated pass.
- LLM-as-judge research specifically found that "off-the-shelf LLMs have
  high refusal rates when faced with exceptions to stated policies, often
  refusing to grant exceptions significantly more than human
  decision-makers" -- confirmed directly in this run: one rejection's own
  reasoning noted the research claim calling the phone "a deliberate
  anachronism," and still didn't consistently extend that leniency on
  other beats. An LLM reviewer will not reliably infer permission from
  ambient context; it needs to be told explicitly.

## Decision

`FactCheckResult` gains a new field, `acknowledged_fiction: str | None =
None`. When "keep as intentional fiction" is chosen (0025),
`_resolve_premise_conflict` sets it to the conflict's `explanation` instead
of discarding that text entirely.

`run_previz_review_stage`'s prompt gains a new, conditional section: when
`acknowledged_fiction` is set, the reviewer is told explicitly that this
specific thing has already been acknowledged as intentional and must not
be flagged -- only genuinely new or different problems should be reported.
Since every beat's review call already receives the same
`fact_check_result` object passed down from `main()`, this fixes the whole
scene, not one image -- no per-beat threading needed beyond what already
exists.

Deliberately a single optional string, not a list: the current mechanism
only ever resolves one premise conflict per scene (0008/0025), so a
single field matches what's actually produced today. Worth revisiting if
a scene later needs multiple independently-acknowledged fictional
elements -- not solved here, per this project's practice of building for
observed need rather than speculative generality.

## Consequences

`fact_check.py`'s `FactCheckResult` and `previz.py`'s
`_REVIEW_PROMPT_TEMPLATE`/`run_previz_review_stage` change; no config or
CLI surface changes. Every call site that already threads
`fact_check_result` through (the original single-scene flow and the
scene-plan beat flow) gets this fix automatically once `acknowledged_fiction`
is set at the one place it's produced.

This does not change previz_review's core job -- it still independently
catches genuinely unintended anachronisms, which is the entire reason it
exists. It only stops it from re-flagging the one specific thing a human
already, explicitly signed off on.
