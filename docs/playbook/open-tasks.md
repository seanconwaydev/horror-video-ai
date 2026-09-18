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

## 1. Run `evals/blocking_space.py` and decide the authoring space

The largest open design question (`architecture.md`): where a character
appears in the frame is a *projection* of where they stand and where the
camera is, and the pipeline authors all three legs independently. Two
coherent architectures exist and the current one is neither -- frame-space
authoring (`frame_position` authoritative, world prose derived or dropped)
or world-space blocking (author the room and the marks, let the camera
imply the frame).

`evals/blocking_space.py` decides it on images rather than argument. Three
scenarios, taken from `run_20260918-221017`'s own beats including the one
that produced the floating figure, each authored both ways with everything
else held constant. 12 images, about $0.50, scored blind:

```
uv run python evals/blocking_space.py
```

Read `prompts/` afterwards before trusting the result -- the validity risk
is that the world arm says something the frame arm does not and wins for
being more specific rather than for being world-space.

Whichever way it comes out, an ADR follows, and it is a large one. If
world blocking wins, `Location` needs a geometry it does not have -- it is
`architecture`, `fixed_props` and `ambient_light`, all prose, so there is
no floor plan to place anyone against. Gaze has no field either way
(`run_20260918-221017` had the antagonist staring at camera mid-lunge, and
his staging describes weight, torso and arm but not his eyes).

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
