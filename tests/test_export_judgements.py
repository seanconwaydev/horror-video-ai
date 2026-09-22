"""The merge behind the committed judgement dataset.

Every human keep-or-reject this project has ever recorded lives in one
tracked file, and `outputs/` -- the only other copy -- is gitignored and
gets pruned. So the failure that matters here is not a crash but a quiet
one: a merge that drops a row deletes a label permanently, and the next
commit makes it look intentional. CI's smoke job runs the export, but a
smoke run only proves it exits zero over whatever happens to be on disk.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evals"))

from export_judgements import _merge, _read_dataset, _row_identity, _write_dataset


def row(**overrides):
    base = {
        "run": "20260920-120000",
        "beat_index": 1,
        "cycle": 1,
        "attempt": 1,
        "image_path": "outputs/20260920-120000/beat_1/attempt_1_candidate_1.png",
        "prompt_used": "a prompt",
        "kept": False,
    }
    return {**base, **overrides}


def test_merge_keeps_rows_whose_run_is_gone():
    # The whole point: outputs/ was pruned, so the old run exports nothing.
    old = row(run="20260901-000000", kept=True)
    merged = _merge([old], [row()])

    assert old in merged
    assert len(merged) == 2


def test_merge_never_shrinks_when_the_export_is_empty():
    existing = [row(beat_index=i) for i in range(3)]

    assert _merge(existing, []) == sorted(existing, key=lambda r: r["beat_index"])


def test_fresh_row_wins_over_a_stale_one():
    # A beat the human had not ruled on yet exports no row; once they do,
    # the run log is the better source for that same candidate.
    merged = _merge([row(kept=False, human_action=None)], [row(kept=True, human_action="a")])

    assert len(merged) == 1
    assert merged[0]["kept"] is True
    assert merged[0]["human_action"] == "a"


def test_candidates_of_one_attempt_are_separate_rows():
    # The unit of judgement is the image, not the beat (docs/decisions/0053),
    # so siblings must not collapse into each other.
    merged = _merge([], [row(image_path="a.png"), row(image_path="b.png")])

    assert len(merged) == 2


def test_same_filename_in_a_different_run_is_a_different_row():
    # Candidate filenames restart every run, so the path alone is not an identity.
    assert _row_identity(row(run="a")) != _row_identity(row(run="b"))


def test_rows_sort_numerically_not_lexicographically():
    # A file that reorders itself on every write buries the new labels in
    # a diff nobody can read.
    merged = _merge([], [row(beat_index=10), row(beat_index=2)])

    assert [r["beat_index"] for r in merged] == [2, 10]


def test_round_trips_through_the_file(tmp_path):
    path = tmp_path / "judgements.jsonl"
    rows = [row(beat_index=1), row(beat_index=2)]
    _write_dataset(path, rows)

    assert _read_dataset(path) == rows


def test_writing_twice_is_byte_identical(tmp_path):
    first, second = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    rows = _merge([], [row(beat_index=2), row(beat_index=1)])
    _write_dataset(first, rows)
    _write_dataset(second, _merge(_read_dataset(first), []))

    assert first.read_text() == second.read_text()


def test_missing_dataset_is_no_rows_not_an_error(tmp_path):
    assert _read_dataset(tmp_path / "nothing.jsonl") == []


def test_a_corrupt_line_fails_loud(tmp_path):
    # Skipping it with a warning, as the run-log reader does, would delete
    # the line on the next write -- the run logs are disposable, this is not.
    path = tmp_path / "judgements.jsonl"
    path.write_text(json.dumps(row()) + "\nnot json\n")

    with pytest.raises(SystemExit, match="corrupt dataset line"):
        _read_dataset(path)
