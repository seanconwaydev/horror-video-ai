# 43. One review prompt, asked every time; previz_review informs but no longer decides

Date: 2026-09-16

Status: Accepted

Superseded in part by [0055](./0055-delete-the-automated-previz-reviewer.md):
its "previz_review informs" half is gone, since the reviewer is deleted
outright. The half that matters -- one prompt, asked every time, the human
decides -- stands and is now the only thing deciding.

Supersedes the two-prompt review flow introduced by [0009](./0009-previz-image-review.md) and extended by [0029](./0029-on-rejection-edit-and-retry.md).

## Context

Every generated beat image went through `previz_review`, and its verdict chose which of two different prompts a human then saw:

- **Accepted** → `(a)ccept / (r)eroll / (e)dit this beat? [a/r/e]`
- **Rejected** → `(Enter) keep auto-retrying / (e)dit / (f)eedback / (a)ccept anyway / (g)ive up`

So the reviewer was doing two jobs. It surfaced a concern, and it set the default action. Measurement says it is mixed at the first and actively harmful at the second.

Two controlled experiments this session scored four and then three arms of generated images, blind, by human forced choice. previz_review ranked them **in exact reverse of that judgement** -- it rated highest the arm chosen zero times out of nine, twice. A repeat run confirmed this is not noise: only 2 of 12 images got an inconsistent verdict on identical input, so the disagreement is systematic. It also rejects roughly **88% of everything**, because it compares images against instructions like "wide 24mm from a low position on the floorboards in the far corner beside the radiator" and returns a binary verdict with no notion of severity. On one real run it rejected four beats over a **missing tote bag** while saying nothing about the scene's antagonist being absent entirely.

Letting a component with those properties choose the default cost real money in both directions. On a rejection, the cheapest keystroke -- Enter -- was the one that spent money regenerating. On an acceptance, an image the human might have rerolled was presented as settled.

Two further changes make this the right moment. The project owner has stopped using `--yes` and now runs every pipeline invocation by hand, judging each beat; and has adopted a protocol of driving those prompts as if shipping the video, which makes their accept/reject/give-up choices trustworthy quality data. An automated gate in front of a human who is already looking, which disagrees with that human systematically, is mostly a tax.

## Decision

1. **One prompt after every review**, whatever the verdict: `(a)ccept / (r)etry / (e)dit the beat / (f)eedback then retry / (g)ive up`, prefixed with the attempt number.
2. **The reviewer's verdict becomes a line of text** above it -- "Review: no concerns." or "Review concern: ..." -- and decides nothing on its own.
3. **No default.** Blank input is re-prompted rather than meaning "spend more money". Every attempt past the first is an explicit choice.
4. **`on_rejected` becomes `on_reviewed`**, called after every review with `(concern or None, attempt)`.
5. **A superseded image is archived too.** A human can now retry an image the reviewer accepted, and that image must not be silently overwritten -- archived as `_superseded` rather than `_rejected`, since the distinction is real.
6. **The retry option says what it does.** It reads `(r)etry carrying N review concerns` when there are any, and plain `(r)etry` when there are none. It has always folded every concern so far into the next attempt's prompt, and nothing said so -- which led to the reasonable assumption that the reviewer's wording had to be copy-pasted in by hand via `(f)eedback`.
7. **Concerns survive a cycle restart.** `(e)dit` and `(f)eedback` end the attempt cycle and begin a fresh one, and the reviewer's concerns used to be discarded at that boundary -- so adding a note of your own silently threw away everything the reviewer had said. The caller now carries them across, and `_generate_image_with_review` takes them as `initial_concerns`.
8. **The attempt cap applies only to unattended runs.** `_MAX_PREVIZ_ATTEMPTS` exists to stop a run regenerating forever with nobody watching. Once every attempt is an explicit human choice it stops being a guard and becomes a refusal to do what was just asked: choosing `(r)etry` on the last allowed attempt silently behaved as a give-up. Interactive runs have no ceiling, and the prompt drops the denominator rather than promising a limit that is not there -- the running attempt count is the cost signal instead. `--yes` keeps the cap, because there is no one to ask.
9. **The second prompt is deleted.** Asking accept/reroll/edit again after the human already chose to keep the image was the same question twice.

## Consequences

**`--yes` loses its quality gate in practice.** With no callback the reviewer's verdict is still followed, so unattended runs behave as before -- but that gate is the component measured as anti-correlated, so it is worth little. This is accepted deliberately: `--yes` is now a secondary mode, and the interactive path is where design effort goes.

**Interactive runs need one keystroke per beat that they did not need before**, on beats the reviewer would have accepted. That is the point rather than a cost: those were beats the human never got asked about.

**previz_review's future is still open.** This decision removes its authority without deciding whether to fix, rescope or delete it. The options identified and not chosen: score adherence on a scale so a near-miss is not equal to a total miss; scope it to subject, action and mood and stop policing camera geometry it cannot usefully judge; or drop it from the loop entirely. There is now a cheap way to decide, since the human's choices are trustworthy data -- comparing the reviewer's verdict against them over a few real runs costs nothing extra.

**The retry loop's value is still unmeasured.** It is no longer blind -- [PR #50](./0029-on-rejection-edit-and-retry.md) feeds each concern into the next attempt, and the reviewer is told what to re-check -- but a real run still burned three informed attempts on one beat and got worse. Whether retrying earns its cost at all is worth knowing, and the owner's stated preference is not to rely on "just try it again" as a strategy regardless.
