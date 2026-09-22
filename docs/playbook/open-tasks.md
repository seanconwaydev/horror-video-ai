# Open tasks

A resume queue for a fresh session. Each entry is meant to be actionable
without reading the rest of the conversation that produced it. Roughly in
priority order. Neither is decided: 1 is an ADR-sized schema call, and 2
is a diagnosis nobody has run yet. Both come out of the same real run.

Finished entries are deleted rather than ticked off -- git history is the
record. Most recently done: **validating 0054 and 0057 against a real
run** -- occlusion now renders as a physical act (a hand braced on the
pillar being hidden behind) and beat 3 produced the first image the owner
called genuinely acceptable -- plus dropping the duplicate `ACTION:` line
([0057](../decisions/0057-drop-the-duplicate-action-line.md)), deleting
three prompt rules by judgement rather than building the ablation
registry ([0058](../decisions/0058-delete-rules-by-judgement-not-ablation.md)),
broadening the CI trigger to every branch
(which is why five commits had shipped with no CI at all), and splitting
the 2,491-line `cli.py` into `cli/` -- six modules, one seam per commit,
with `app.py` left holding the argument parser and `main()` at 631 lines.
The coverage floor rose from 84 to 86 along the way, and to 94 since.

**Done 2026-09-19.** That split had left 142 of the repo's 198 uncovered
statements in `main()`, measured at 22% while every other module was
above 94%. Rather than combine coverage reports from the smoke job,
`tests/test_cli_app_main.py` now calls `main()` under `--mock` once per
entry shape -- grounded historical, ungrounded genre, fixture replay --
and asserts what each records. app.py is at 81%, the project at 95%, and
the floor moved 86 -> 94.

That was not just a number: the single smoke invocation took one path
through a function that branches three ways before scene planning, which
is how a `--fixture` run came to record `genre: "historical"` no matter
what `--genre` said, mislabelling every judgement row exported from it.

Deeper context lives in [repo-audit-brief.md](./repo-audit-brief.md),
[eval-loop-plan.md](./eval-loop-plan.md) and
[prompt-rule-registry-scope.md](./prompt-rule-registry-scope.md).

---

## 1. Re-run in a scene with room to move

Two rule repairs landed unmeasured in
[0061](../decisions/0061-the-threat-must-act-on-the-person.md): the
non-focal character's own action must now take another character as its
object, and `blocking` states place only, with orientation moved to
`action`. Neither has been seen in an image.

The car-cabin run also established that **scene selection is a lever this
project has never used deliberately**. A sedan cabin permits posture
changes on a bench and nothing else, so a planned escalation had nowhere
to go. The next scene should have physical affordance -- room to close
distance, objects to use, somewhere for one character to move that the
other has to answer.

Run it interactively, `--max-beats 3`, and read the plan at the review
gate before spending: the specific thing to check is whether the threat's
own `action` now reaches for the person rather than bracing on furniture.

## 2. Warn when a beat's camera height cannot exist in its location

Found in the car-cabin run (`--style painterly`, logged in
[failure-taxonomy.md](./failure-taxonomy.md)): a beat asked for
`Medium shot, high above, from behind` **inside a sedan**, whose own
`Location.architecture` names a steel roof and a fabric headliner.

Nothing connects `camera` to what the location can contain, and two rules
drive toward the collision.
[0044](../decisions/0044-camera-specified-at-a-granularity-models-follow.md)
offers four camera heights unconditionally, and the coverage rule requires
consecutive beats at one location not to repeat a combination -- so in an
enclosed interior, where half the vocabulary is unusable, a rule demanding
variety reaches for the impossible half.

This cannot be a hard check: whether a height is possible in a given space
is a judgement about prose, and
[0048](../decisions/0048-heuristic-gates-warn-rather-than-fail.md) reserves
run-failing errors for decidable predicates. The fitting shape already
exists in the codebase -- `identity_field_pose_warnings`, a heuristic
non-blocking warning printed at the scene-plan review gate where a human is
already reading the plan and can edit the field for free. A keyword pass
over `Location.architecture` for enclosure words (roof, ceiling, headliner,
cabin, interior) against camera heights of "high above" or "ground level"
would have caught this instance.

Worth deciding at the same time whether the planning rule should say it
too, or whether the warning alone is enough -- ADR 0058's lesson is that a
32nd bullet is not free.

## 3. Why is the mood under-delivered when the prompt asks for it twice?

The owner on the 2026-09-18 run: "the shadows and mood should probably be
better for horror, though i didn't check how much of the prompt specified
this." It is specified twice and in detail -- the `horror-comic` preset
asks for "heavy inked black shadows... high contrast between lit and
unlit areas", and each beat's own `lighting` field is concrete chiaroscuro
("one hard pool of white light... the far end of the aisle drops into
unlit black").

So this is not a missing instruction, and writing a 32nd rule would be
the exact move ADR 0058 just argued against. Things worth checking before
anything else: whether `LIGHTING` late in the prompt loses to `STYLE`
right after it, and whether the model simply does not do heavy blacks at
this level. The first is testable with the eval harness; the second is
not fixable here.

A third hypothesis was listed here and is already ruled out: "the
character reference sheet every beat is *edited from* is washing out the
contrast." References have been off by default since
[0050](../decisions/0050-no-reference-images-by-default.md) -- a default
run is plain text-to-image and is edited from nothing, so unless the run
passed `--references` there is no sheet to inherit from.

## 4. Retry feedback that adds detail to an over-budget beat

From the 2026-09-22 laundry run, beat 1. The image dropped two named
details -- a dark drum window among five tumbling ones, and a trail of wet
footprints -- while rendering everything else well. The owner retried with
feedback naming exactly those two omissions, and **the retries came back
worse, not better**.

That result is the interesting part, and it generalises past this beat.
When a frame fails by dropout, the cause is that the beat was over the
complexity ceiling `_COMPLEXITY_BUDGET_RULE` exists to hold it under.
Feedback that names the missing thing appends another requirement to a
prompt that already had too many, so the retry is strictly further over
budget than the attempt that failed. The loop is structurally pushing the
wrong direction.

Worth noting the beat was over budget as planned, before any feedback: her
lift, the footprint trail, the one dark drum among five lit ones, a
straight-down shadow, and a wide/high/from-behind camera is five to six
things in a rule that permits about five and says to drop the least
important. So the first question is not "what new rule is missing" but
**why the planner exceeded a budget it was told**, which is a measurement,
not an argument.

The candidate fix, if the diagnosis holds: feedback on a dropout failure
should propose a *removal* or a split, never an addition. Nothing in the
retry path knows the difference between "you missed something" and "you
got something wrong", and those want opposite edits.

## 5. Inserts: spend a frame rather than crowd one

The owner's idea from the same run, offered tentatively and recorded here
rather than implemented. Beat 1's missing machine and footprints could be
a **second image** -- a tighter shot that shows only those -- instead of
extra load on the wide shot that failed to hold them.

This is [0075](../decisions/0075-a-perception-moment-is-two-beats.md)
generalised. That ADR already established the precedent that a moment can
cost two beats, for the specific case of noticing a threat: the look, then
the reverse. The proposal extends the same move to any detail the frame
cannot hold, which in film is an **insert** (or cutaway / detail shot) --
a close frame on an object, cut in between wider ones.

The owner also noticed the second-order benefit unprompted: because the
viewer never sees the whole room at once, fragmenting it across frames
means the room's geometry is never auditable, so an incoherent layout
stops being a defect the viewer can catch. That is genuinely how shot
coverage works on a real set, and it is a reason to prefer inserts beyond
the complexity budget.

The underlying principle is the one worth testing, because it is the most
generalisable lever this project has found: **the model's ceiling is per
frame, so buy detail with more frames rather than more text per frame.**

The cost is 0075's cost and the ADR does not hide it: at four or five
beats a scene, every insert is a story moment not spent. "Not all the
time" was the owner's own framing. An insert also has no character in it,
which no rule currently contemplates -- `subject` and the staging schema
both assume one.

## 6. Non-diegetic marks as a style-level gap-filler

Also from the laundry run, beat 2. The image did not read as "she hears
something", and the owner's feedback -- add a comic-style mark denoting
the sound -- worked. Their read, which is the right one: it may have
worked *because* the style was comic, where drawn sound marks are part of
the visual vocabulary already.

The open question is whether the same move can be pushed into more
realistic styles as a deliberate aesthetic choice, on the grounds that it
covers a real image-model limitation -- a still frame cannot carry sound,
and the model will not invent a way to show it.

Live-action film solves this differently and that alternative should be
weighed first: it shows the *cause* in frame (the dryer door swinging on
its hinge) rather than marking the effect. A painterly style has analogues
that are not literal marks -- a motion streak, disturbed dust, a swinging
object caught mid-arc. The risk of a floating mark in a painterly frame is
that it reads as a rendering artifact rather than as a convention.

## 7. Decide on automated prompt-fidelity checking

Scoped in
[prompt-fidelity-checking-scope.md](./prompt-fidelity-checking-scope.md),
with a 26-item probe attached: 92% recall on the owner's own failures,
61% precision, and all three causes of the false alarms traced to how the
claims were written rather than to the model.

Not decided. The next step is not code -- it is repairing the claim
writing (split compounds, delete tolerance adverbs) and re-probing on
roughly 60 items across more beats and both styles, against the decision
criteria that doc fixes in advance. Build order is listed there if it
passes.

Two things from the probe are worth acting on regardless of whether the
checker is ever built, because both are about how the owner reviews:

- The verdict set is **yes / no / can't tell**, and can't-tell counts as
  a failure. A frame a viewer cannot read in one glance has failed
  whatever its ground truth is.
- Claims about **touching, weight or body boundaries** are owner-only. A
  vision model scores position and misses contact -- it passed a hand
  resting in a void as "splayed flat on the door".
