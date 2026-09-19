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

## 1. One head-to-head, then write the apparent-size ADR

Three blind runs are done, 54 images, written up in
[failure-taxonomy.md](./failure-taxonomy.md). The answer is not the one
this project argued for: the axis is not frame-space versus world-space,
it is whether **apparent size** is stated at all. On "is he between the
camera and her", pooled:

| arm | score |
|---|---|
| `world` -- placement, no size | **0/10** |
| `world_size` -- same placement plus "roughly a third of the image" | **8/8** |
| `frame` -- the incumbent: coordinates plus size | 2/4 |

The focused run alone was 0/6 against 6/6 with no partials. What has not
been run is `world_size` against the **incumbent** at six candidates,
which is the comparison that justifies changing the schema:

```
uv run python evals/blocking_space.py \
  --scenarios confrontation --arms frame,world_size --candidates 6
```

12 images, about $0.47. If `world_size` holds against `frame`, the ADR
splits today's composite `frame_position` into two fields -- where the
character stands relative to the space, the camera and each other, and how
much of the frame they occupy -- which is [0054](../decisions/0054-one-fact-per-field.md)'s
rule applied once more. No floor plan for `Location` is needed.

Settled; do not re-test:

- **Distance is not promptable.** 1 success in 22 images. "He's never more
  than ~10 feet in front of her... a parking garage could have him 50-100+
  feet away easily." Rewrite beats that depend on it.
- **Depth ordering delivers gaze for free.** 12/12 in the focused run,
  because placing him nearer the camera than her forces the turn and the
  turn is what reads as gaze. This may remove the need for a gaze field
  entirely -- decide that inside the ADR above rather than separately.

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
