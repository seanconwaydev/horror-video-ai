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
