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

## 1. Give `Staging` the facts it is missing: ground, depth, gaze

Now measured against a real run rather than reasoned about
(`run_20260918-221017`, logged in
[failure-taxonomy.md](./failure-taxonomy.md)). ADR 0057 worked -- the
antagonist acts instead of standing there, and beat 3 produced the first
image the owner called genuinely acceptable. Three facts have no field,
and each produced a visible defect in the same run:

- **Where someone stands in the space.** `frame_position` is a 2D fact.
  Beat 1 said "far background, upper-left of frame" under a `wide, low,
  from behind` camera, which in that shot is the ceiling -- so the model
  put a standing man in the air and invented a roof slab to hide him
  behind. The planner was not wrong on its own terms; it had nowhere to
  write "forty metres down the aisle, on the floor".
- **Who is where relative to whom.** Still nothing states who is behind
  whom or how far apart they are. The planner currently smuggles this
  into `action` prose ("keeping the concrete between himself and her
  sightline"), which is exactly where 0049 and 0054 found it losing.
- **Where each is looking.** One beat-3 candidate had the antagonist
  staring at camera mid-lunge. His staging describes weight, torso and
  arm, and says nothing about his eyes. The prompt's multi-character line
  asks that "gazes, distances and body angles have to agree" -- three
  facts, no fields, which is the pattern ADR 0054 exists to stop.

ADR-sized: new fields on `Staging`, the planner prompt that fills them,
the parser, the eval fixtures. Worth deciding whether these are three
fields or one, and 0054's evidence argues for separate ones.

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
