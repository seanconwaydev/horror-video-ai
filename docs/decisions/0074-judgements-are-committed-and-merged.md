# 74. The judgement dataset is committed, and written by merge

Date: 2026-09-21

Status: Accepted

## Context

[ADR 0053](./0053-human-judgements-are-recorded-as-data.md) made every
keep-or-reject at the previz gate into a labelled row, and
`evals/export_judgements.py` flattens those rows out of run logs. It
worked, and it has already decided something: the labels it produced are
what `evals/judge_agreement.py` scored `previz_review` against, which is
why [ADR 0055](./0055-delete-the-automated-previz-reviewer.md) deleted it.

But the labels themselves were never stored anywhere durable. Both the run
logs and the export's usual destination are gitignored -- `outputs/` and
`evals/results/` -- so the entire corpus of human preference data this
project has ever produced existed as untracked files on one machine, with
no backup and nothing stopping a cleanup from removing it. The judge study
ran over 78 images; an export a few days later found 41. The difference is
not explained anywhere, which is the point: nothing recorded that it had
been lost.

This is the repository's own documented failure mode arriving at the one
artifact it least affords to lose. Images can be regenerated for money. An
expert human judgement on an image cannot be regenerated at all.

## Decision

`evals/judgements.jsonl` is committed. It is the dataset; the run logs are
a source it is refreshed from, not the record.

`--update-dataset` writes it, and it writes by **merge, never overwrite**.
Rows are unioned on the identity `(run, beat_index, cycle, attempt,
image_path)`, with a freshly exported row winning a collision. A row whose
run no longer exists on disk has no fresh counterpart and survives
untouched.

Overwriting would have been the obvious implementation and is precisely
the bug: run the export after `outputs/` is pruned and every label whose
images are gone disappears, the commit that follows looks deliberate, and
the loss is undetectable afterwards. The merge is the whole decision. The
file is just where it lands.

Two supporting details follow from the file being tracked rather than
scratch:

- Image paths are stored relative to the repository root. A run log holds
  absolute paths, which are machine-specific and, because the path is part
  of a row's identity, would make the same image merge as a second row
  when exported from a clone.
- The file is written with sorted keys in a total row order, so a new run
  appends to the diff instead of reshuffling it, and a corrupt line makes
  `_read_dataset` fail loud. Everywhere else in that script a bad input is
  skipped with a warning, because a truncated run log must not block every
  other run -- but this file is the only copy of its labels, and skipping
  a line here would delete it on the next write.

`tests/test_export_judgements.py` covers the merge directly. CI's smoke
job already runs the export, but a smoke run only proves it exits zero
over whatever is on disk; the failure that matters here is not a crash but
a quiet one.

## Consequences

The labels now survive `outputs/` being cleaned, a fresh clone, and a new
machine. What is in the file at the time of this ADR is 49 labelled images
across 5 runs -- 7 kept, 42 rejected, 8 beats given up on, 8 carrying
written feedback.

Updating it is a deliberate step, not a hook at the end of a run. Most
runs here are abandoned part-way, so an end-of-run write would rarely
fire, and the export is already incremental: running it at any point picks
up every beat the human has finished ruling on.

The dataset is small and heavily negative, and it should be read that way.
A kept image is the least-bad of its candidates rather than an
endorsement, which ADR 0055 already had to caveat once when interpreting
these same labels.

This does not itself improve any image. It makes the input to the things
that would -- an exemplar bank of accepted beats with their exact prompts,
a model bake-off scored against recorded preference, a rebuilt judge --
something that still exists next month.
