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

## 1. Confirm whether apparent size is the depth lever

Two blind runs are done (30 images, written up in
[failure-taxonomy.md](./failure-taxonomy.md)). They did **not** settle
frame-space versus world-space authoring, and the reason is worth stating
plainly: at two candidates per cell the noise is larger than the effect --
the same arm on an identical prompt scored 2/2 then 0/2 on the same
question between runs. No ADR can be written on that.

One thread survived both runs. `world` scored **0/4** on "is he between
the camera and her"; `world_size` -- the same world placement with an
apparent-size figure added -- scored **2/2**. If that holds, the
instruction doing the work is *how much of the image someone occupies*,
not the frame coordinates, and `frame_position` becomes "where they stand"
plus "how much of the frame they fill". Still n=2.

The focused confirmation, with candidates spent where they can separate
something rather than spread across a scenario the owner judged unfit:

```
uv run python evals/blocking_space.py \
  --scenarios distant_figure,confrontation --arms world,world_size --candidates 6
```

24 images, about $0.95. Score the same way, blind.

Settled and not worth re-testing:

- **Distance is not promptable.** 1 success in 10 images across every arm
  and every phrasing. Beats that depend on a figure reading as genuinely
  far away should be rewritten rather than re-prompted.
- **Gaze has to be written as body orientation.** Observed across both
  runs: the model renders a horror figure's eyes as featureless white or
  black, so gaze is frequently not recoverable from the image at all, and
  every time the owner could read it he read it off posture.

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
