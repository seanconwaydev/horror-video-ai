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

## 1. Run `blocking_space.py`'s third arm, then decide

The first run is done (`results/blocking-20260918-224824`, written up in
[failure-taxonomy.md](./failure-taxonomy.md)). **World-space blocking
lost** -- every image the owner favoured was a frame-coordinate one. It
also showed that *distance failed in both arms*, so the projection problem
is real and world-space authoring does not fix it.

What is left is one uncontrolled variable. The frame arm states an
explicit apparent size ("roughly a twentieth of the image") because that
is how `frame_position` is written; the world arm stated none; and
apparent size is the strongest depth cue an image has. The run's only two
depth successes were in the arm holding it. A third arm, `world_size` --
world placement plus the same size figures -- is written and unrun:

```
uv run python evals/blocking_space.py
```

18 images now, about $0.70, scored blind the same way. If `world_size`
matches `frame`, the lever is apparent size and not frame coordinates, and
`frame_position` can become world placement plus a size -- a far smaller
schema change than giving `Location` a floor plan. If it matches `world`,
frame coordinates stay and the ADR is short.

Two separate findings from the first run that need their own decisions
either way:

- **Gaze may not be expressible as gaze.** It failed in every cell, and is
  often not even scoreable -- the model renders a horror figure's eyes as
  featureless white or black, so where they look cannot be read off the
  image. The one time the owner could tell, he credited body position and
  clothing. A gaze field probably has to be written as body orientation.
- **Shadow is doing work nothing controls.** The owner repeatedly credited
  shadow for rescuing an occlusion the pillar did not achieve. No field
  asks for it. That makes it a confound in the result above and, on its
  own, a hint that occlusion-by-shadow may be cheaper and more reliable
  than occlusion-by-object.

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
