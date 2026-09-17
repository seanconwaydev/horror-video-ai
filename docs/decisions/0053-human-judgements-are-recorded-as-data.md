# 53. Human judgements at the previz gate are recorded as data

Date: 2026-09-16

Status: Accepted

## Context

The project owner drives every previz review by hand. A four-beat run with
four candidates per beat puts sixteen images in front of them, and each
keep-or-reject is an expert judgement on a generated image — the most
expensive kind of label to obtain and the one this pipeline most needs.

None of it was kept. `cli.py` recorded `prompt_used` only on the accepted
branch, so a rejected beat discarded the exact prompt that produced it.
Because `_build_beat_prompt` changes over time, a beat's stored fields
cannot reconstruct the prompt after the fact, which makes the label
unattributable even where the image survived on disk. Attempts were also
reassigned per retry cycle, so choosing (e)dit or (f)eedback silently
dropped the rejected attempt that prompted the edit; `tests/test_cli.py`
asserted that discard as intended behaviour.

The consequence is not just lost data. `previz_review` — this project's
LLM-as-judge — was measured ranking four arms in exact reverse of blind
human judgement while rejecting 88% of images, and it still gates the
retry loop. It cannot be honestly rescoped, recalibrated or dropped
without labelled data to measure it against, and no such data existed.
The same is true of any future prompt-optimization loop: a judge and an
optimizer are both functions that take human preference data as an
argument. Capturing judgements is what unblocks the automated side, not a
detour away from it.

`evals/` already had the harder half of this built — a frozen golden
dataset, blind A/B with randomised slots, refusal counting, a judge
reliability study. Across fifteen recorded runs, exactly one file
contained human scores, and that one was measuring the reviewer rather
than the images. The practices existed; nothing connected them to a
decision.

## Decision

Every attempt records each candidate as `{path, prompt_used, kept}`,
alongside which candidate the human chose (`human_choice`), which action
they took (`human_action`: accept/retry/edit/feedback/give-up) and any
free-text `feedback` — a human-authored correction naming exactly what the
render got wrong. Attempts accumulate across retry cycles rather than
being replaced. The run log also records `style`, since a judgement is
only comparable to another made under the same preset.

The unit of the record is the candidate image, not the beat: rejecting
three of four candidates is three negatives and one positive, and
collapsing it to "the beat was accepted" discards most of the signal.

`evals/export_judgements.py` flattens run logs into one labelled dataset,
one row per candidate image, carrying the sibling candidates it was shown
against — a rejection is only meaningful relative to what it lost to.

`previz_review`'s verdict is attached **only to the candidate it actually
scored**. It runs once per attempt, on the kept image; copying its verdict
onto siblings it never saw would manufacture agreement and disagreement
out of nothing, in precisely the study this dataset exists to support.

Separately, the candidate prompt now prints the beat's camera and
per-character staging. That text was last shown at scene-plan review,
hundreds of lines up the scrollback, so checking whether a render honoured
the plan required scrolling back every time — the one judgement the loop
exists to collect was the one the interface made hardest to make. A
judgement the interface discourages is a judgement that does not get made
carefully.

## Consequences

Runs recorded before this ADR cannot be exported. They stored `candidates`
as a list of bare path strings with no prompt attached, so the images
exist but are not usable labels. The export detects that shape and skips
it rather than emitting rows with a missing prompt.

What this enables, in order: measuring `previz_review`'s agreement with
human judgement and deciding its fate with evidence; scoring an image-model
bake-off against recorded preferences rather than by eye; and an exemplar
bank of accepted beats with the exact prompts that produced them, which is
the cheapest mechanism available here for the system to learn from its own
history.

This does not itself improve any image. It is deliberately the
unglamorous half — logging, not modelling — and everything in
[playbook/eval-loop-plan.md](../playbook/eval-loop-plan.md) after step 1
depends on it existing first.

The dataset is only as good as the interactive path's honesty. The owner
has stopped using `--yes`, and under `--yes` the first candidate is taken
with no human in the loop; such rows carry `human_choice: null` and are
not preference data. Any study over this dataset has to exclude them.
