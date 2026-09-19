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
The coverage floor rose from 84 to 86 along the way.

One thing that split surfaced and did not fix: **142 of the repo's 198
uncovered statements are now `main()`**, and `main()` is not untested --
CI's smoke job runs it end to end offline every push. It is just not
*measured*, because coverage only runs under pytest. Running the smoke
job under `coverage run` and combining the two reports would make the
real number visible; nobody has decided whether that is worth doing.

Deeper context lives in [repo-audit-brief.md](./repo-audit-brief.md),
[eval-loop-plan.md](./eval-loop-plan.md) and
[prompt-rule-registry-scope.md](./prompt-rule-registry-scope.md).

---

## 1. Run a horror scene end to end under 0059 + 0060

Everything measured so far has been measured in pieces. What has not
happened is a full interactive run with all of this session's changes
live: the duplicate `ACTION:` line gone
([0057](../decisions/0057-drop-the-duplicate-action-line.md)), three
prompt rules deleted ([0058](../decisions/0058-delete-rules-by-judgement-not-ablation.md)),
`blocking` + `size_in_frame` ([0059](../decisions/0059-blocking-and-size-replace-frame-position.md)),
and the threat now written close-and-hidden rather than distant
([0060](../decisions/0060-threat-is-hidden-not-distant.md)).

```
uv run historical-video-ai --genre horror --tone dread --style horror-comic \
  --candidates 3 --max-beats 3 --experiment-model deepseek/deepseek-v4-flash \
  --time "present day" --place "an underground car park at night" \
  --description "a woman realises someone has been standing between the pillars watching her"
```

`--max-beats 3`, because the unconstrained plan came back with 8 and three
candidates each is ~24 paid images. Run it interactively so it produces
labels ([0053](../decisions/0053-human-judgements-are-recorded-as-data.md)).

Two specific things to watch, both of which are predictions this session
made and has not tested:

- **Does the threat now arrive close and occluded?** 0060 rewrote the rule
  after a plan-only run put it "far down the aisle beyond her". Read the
  scene plan at the review gate before spending.
- **Does near-field depth ordering hold with a real planner's text?** It
  was 14/14 on prose written by hand for the eval. The planner's own
  `blocking` and `size_in_frame` have never been rendered.

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

## 2. Why is the mood under-delivered when the prompt asks for it twice?

The owner on the 2026-09-18 run: "the shadows and mood should probably be
better for horror, though i didn't check how much of the prompt specified
this." It is specified twice and in detail -- the `horror-comic` preset
asks for "heavy inked black shadows... high contrast between lit and
unlit areas", and each beat's own `lighting` field is concrete chiaroscuro
("one hard pool of white light... the far end of the aisle drops into
unlit black").

So this is not a missing instruction, and writing a 32nd rule would be
the exact move ADR 0058 just argued against. Things worth checking before
anything else: whether the character reference sheet every beat is *edited
from* is washing out the contrast it inherits, whether `LIGHTING` late in
the prompt loses to `STYLE` right after it, and whether the model simply
does not do heavy blacks at this level. The first two are testable with
the eval harness; the third is not fixable here.
