# 9. Independently review previz's generated image, not just its prompt

Date: 2026-08-24

Status: Accepted

Superseded by [0043](./0043-one-review-prompt-the-human-decides.md) on the review
flow, by [0051](./0051-remove-the-single-image-previz-flow.md) on the
single-image flow it reviewed, and finally by
[0055](./0055-delete-the-automated-previz-reviewer.md), which deletes the
automated review outright -- measured agreeing with the owner on 56% of 78
images against 79% for accepting everything.

## Context

A real run (`1920 New York` / "a group of people see godzilla in the
distance", corrected via [decisions/0008](./0008-refuse-impossible-premises.md)
to "a group of people... joke that a distant shape resembles a prehistoric
beast from Arthur Conan Doyle's The Lost World") produced an image showing
an unambiguous, literally-present dinosaur -- not an indistinct shape people
are reacting to, an actual creature. The text sent to previz was accurate
and appropriately hedged; the image wasn't. Text-to-image models are known
to be unreliable at exactly this: hedged, subjective, or negated language
("resembles", "believed to be", "not X") tends to collapse into the
concrete noun getting rendered as literally real. Nothing checked the
*image* against the scene it was supposed to depict -- only the response's
validity as an image file (`run_previz_stage`'s existing `PrevizError`
checks). Every other stage in this pipeline follows a generate-then-review
pattern (`docs/architecture.md`'s design principles; `fact_check` doing
exactly this to `research`'s output). previz never got the second half of
that pattern.

## Decision

`run_previz_review_stage` (`stages/previz.py`) sends the *generated image*,
not just the prompt, to an independent vision-capable model, asking whether
it depicts anything that couldn't have existed or happened at this time and
place -- returning a `PrevizReview` (`accepted: bool`, `concern: str |
None`). Pinned to `anthropic/claude-sonnet-5` in `config/models.yaml` as
`previz_review` -- vision-capable, a different provider than previz's own
OpenAI image model, same "not the same model checking its own work"
reasoning as `fact_check` vs. `research` ([0007](./0007-research-fact-check-previz-models.md)).
Like previz's own model choice, this is picked to unblock building the
stage, not a rigorously compared decision.

`cli.py`'s `_generate_previz_with_review` orchestrates: generate, review,
and on rejection, regenerate -- capped at `_MAX_PREVIZ_ATTEMPTS = 3`. This
was a deliberate choice against building prompt-engineering safeguards
(detecting hedged language, injecting explicit "depict as ambiguous, not
literal" instructions): that path adds real complexity for a payoff that
isn't guaranteed to work, since the underlying unreliability is in the
image model's handling of language, not in this pipeline's prompt-building
logic -- and it would make previz's output meaningfully less deterministic
by making its prompt depend on retry history. A hard retry cap with blind
regeneration (same prompt, relying on generation's own inherent
stochasticity to maybe produce a better result) is simpler and keeps
behavior predictable: at most 3 real attempts, then stop. If every attempt
is rejected, no image is produced -- refusing rather than handing over
something known to be wrong, the same principle [0008](./0008-refuse-impossible-premises.md)
established for an unresolved premise conflict. A rejected attempt's image
is archived as `previz_attempt_<n>_rejected.png` rather than silently
overwritten, so the reason it was rejected has something to point at.

## Consequences

`config/models.yaml` gains a `previz_review` entry;
`tests/test_config.py`'s `expected_stages` updated to match.
`ANTHROPIC_API_KEY` moves from "deferred stages" to genuinely required in
`.env.example`, alongside the other three v1 keys -- a run can now make up
to 4 real API calls per scene (research, fact-check, and up to 3
generate+review previz round trips) instead of 3.

As of this writing, `run_previz_review_stage` has **not** been exercised
against a live key from this repo -- `ANTHROPIC_API_KEY` was never set
during development, so the vision-input call shape (litellm.completion()
with a text block + an image_url block) is unverified. Confirmed working
during development: `run_previz_stage` (real OpenAI image generation) and
the premise-conflict flow (real DeepSeek research + fact-check, including
the automatic re-verification pass). Treat the first real
`run_previz_review_stage` call as a test, not a known-working thing.

Explicitly out of scope: this only checks the image for depicting something
*impossible*, not general image quality, composition, or whether it's a
good match for the mood/tone of the scene -- those stay entirely a human
judgment call at the existing review gate (you looking at the final image).
Also out of scope, raised but not resolved here: whether a "how far are we
pushing plausibility" score (rather than a flat accept/reject) would be
worth adding later -- the flat threshold was chosen for now as the simpler
option.
