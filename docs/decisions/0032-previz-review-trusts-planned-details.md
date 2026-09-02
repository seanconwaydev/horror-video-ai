# 32. previz_review trusts scene-plan-approved details, doesn't re-derive them

Date: 2026-09-02

Status: Accepted

## Context

ADR 0030 tried to fix `previz_review` re-flagging a character's modern wardrobe as an unacknowledged anachronism by broadening `acknowledged_fiction`'s text to cover "natural, expected consequences" of the acknowledged premise. A further real run showed this still wasn't enough: the reviewer rejected the same wardrobe again, with a genuinely defensible argument -- *"a time traveler could plausibly have worn era-appropriate Roman dress... modern streetwear is not a natural consequence of the phone/time-travel fiction."* That's logically fair: owning a time-travel phone doesn't strictly entail wearing modern clothes. "Natural consequence" framing was never going to reliably cover a detail that isn't actually a logical consequence of anything -- it's simply a separate, deliberate choice the scene plan already made, independently.

The project owner's own framing cuts to the actual problem: *"if the original prompt specifies that she's wearing modern clothes, that NEEDS to be unquestioned by every model that will check that info."* `previz_review` has been re-deriving historical plausibility from scratch on every single beat, including for details a human already reviewed and approved at scene-plan-review time (docs/decisions/0023) -- wardrobe, distinguishing detail, and the beat's own described action. That's a structurally wrong job for it to be doing: once a detail has been through human review, a later automated pass re-litigating whether that detail is "plausible" in isolation is adversarial toward the human's own already-made decision, not toward the image.

A second, unrelated defect surfaced in the same run: a generated image showed the wrong character (the visiting time-traveler) apparently running the food counter instead of the shop owner -- a plain compositional/fidelity error, not an anachronism, and one `previz_review`'s anachronism-only framing had no way to catch.

## Decision

`run_previz_review_stage` gains optional `character: Character | None` and `beat: Beat | None` parameters. When given, their already-planned, human-reviewed details (wardrobe, distinguishing detail, the beat's own subject/action) are listed explicitly in the review prompt as settled -- not to be flagged as anachronisms on their own terms, no matter how implausible they'd look in isolation, mirroring 0026's "explicit allowlist, not inference" principle but scoped to scene-plan-level decisions rather than only the original premise-conflict text.

`previz_review`'s job description is widened at the same time to a second, independent check: does the image actually depict what was planned -- the right character in the right role doing the right thing -- not just "is nothing anachronistic." A genuinely new problem not covered by the planned details (an unplanned modern object, the wrong character performing an action) is still flagged; only the specific pre-approved details are exempted.

`cli.py`'s beat-generation call site (`_generate_beats_with_choices`, which already has the `character`/`beat` objects in scope) passes them through; the single-scene flow (which predates scene-planning and has no `Character`/`Beat` concept) does not, so its behavior is unchanged.

## Consequences

`previz.py`'s `_REVIEW_PROMPT_TEMPLATE` and `run_previz_review_stage` changed; `cli.py`'s per-beat review call passes `character`/`beat` via `review_kwargs`. No new dataclass fields. This is now the third round on the same underlying problem (0026, 0030, 0032) -- worth naming directly: an independent reviewer re-deriving plausibility from scratch is fundamentally in tension with anything already decided upstream by a human or an earlier stage, and each prior fix only ever covered a narrower slice of "already decided" than the real thing needed. If a fourth case turns up, the more durable fix is likely giving `previz_review` the *entire* reviewed `ScenePlan` as context by default, rather than continuing to add one more named exception.
