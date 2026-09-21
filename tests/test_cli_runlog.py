"""Where a run's files go, and how a finished run is read back
(cli/runlog.py).

Split out of test_cli.py alongside the module itself. The monkeypatching
here targets `horror_video_ai.cli.runlog.project_root`: patching the
old `cli.app` binding would leave these tests green while the code under
test went on using the real filesystem.
"""

import json
import os
import re
from pathlib import Path

import pytest

from horror_video_ai.cli.runlog import (
    new_run_dir,
    project_root,
    read_log,
    safe_path_component,
    slugify,
    write_log,
)


def _write_fixture(tmp_path, **overrides):
    payload = {
        "time": "December 1903",
        "place": "Kitty Hawk, North Carolina",
        "description": "watches a flying machine lift off from the dunes.",
        "research_claims": [
            {
                "text": "The dunes at Kitty Hawk were largely undeveloped in 1903.",
                "source": "NPS",
                "date": None,
            }
        ],
        "fact_check_flags": [],
        **overrides,
    }
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(payload))
    return path


def test_slugify_lowercases_and_hyphenates():
    assert slugify("A Young Dockworker Wades!") == "a-young-dockworker-wades"


def test_slugify_truncates_at_a_word_boundary():
    text = ("a" * 20) + " " + ("b" * 20)  # 41 chars once hyphenated
    result = slugify(text, max_length=25)
    assert len(result) <= 25
    assert result == "a" * 20  # cut back to the hyphen boundary, not mid-word


def test_slugify_returns_empty_for_content_free_input():
    assert slugify("   ...   ") == ""


def test_project_root_raises_when_no_pyproject_toml_found(monkeypatch):
    # Regression test: the old fallback silently guessed a fixed parents[2]
    # offset instead of failing loud when no ancestor has a pyproject.toml.
    monkeypatch.setattr(Path, "exists", lambda self: False)

    with pytest.raises(RuntimeError, match="Could not find pyproject.toml"):
        project_root()


def test_run_dir_includes_slug_in_directory_name(tmp_path, monkeypatch):
    monkeypatch.setattr("horror_video_ai.cli.runlog.project_root", lambda: tmp_path)

    d = new_run_dir("a-flood-rescue-scene")

    assert d.parent == tmp_path / "outputs"
    assert re.match(r"^run_\d{8}-\d{6}_a-flood-rescue-scene$", d.name)
    assert d.exists()


def test_run_dir_omits_slug_when_not_given(tmp_path, monkeypatch):
    monkeypatch.setattr("horror_video_ai.cli.runlog.project_root", lambda: tmp_path)

    d = new_run_dir()

    assert re.match(r"^run_\d{8}-\d{6}$", d.name)


def test_run_dir_never_reuses_an_existing_directory(tmp_path, monkeypatch):
    """Second precision alone is not unique. Re-running the same command
    right after a failed attempt lands in the same second with the same
    slug, and `exist_ok=True` let the second run write straight over the
    first one's images and log."""
    monkeypatch.setattr("horror_video_ai.cli.runlog.project_root", lambda: tmp_path)

    first = new_run_dir("same-scene")
    (first / "previz.png").write_bytes(b"first run's image")
    second = new_run_dir("same-scene")

    assert second != first, "a second run in the same second reused the first run's directory"
    assert (first / "previz.png").read_bytes() == b"first run's image"


@pytest.mark.parametrize(
    ("raw_id", "expected"),
    [("hallway", "hallway"), ("a/../../evil", "a-..-..-evil"), ("../x", "x"), ("///", "unnamed")],
)
def test_ids_used_as_directory_names_cannot_escape_the_run_folder(raw_id, expected):
    """Ids come from a planning model and can be edited by hand, so they
    are not guaranteed to be single path components. "a/../../evil"
    resolved outside the run directory entirely."""
    safe = safe_path_component(raw_id)
    assert safe == expected
    assert "/" not in safe and os.sep not in safe


# --- one review prompt, asked every time (ADR 0043) ---


def test_a_failed_write_leaves_the_previous_run_log_intact(tmp_path, monkeypatch):
    """The whole point of writing through a temp file. Before this,
    `write_text` truncated run_log.json first, so an interruption part-way
    destroyed every earlier stage's record -- and docs/decisions/0056
    makes these writes frequent precisely because runs get abandoned
    part-way."""
    write_log(tmp_path, {"time": "1969", "research_claims": ["kept"]})

    # Interrupt *during* the write, after truncation -- not before it.
    # A fake that raises before any bytes are written passes against the
    # old truncate-in-place implementation too, and so proves nothing.
    real_write_text = Path.write_text

    def half_then_interrupt(self, data, *args, **kwargs):
        real_write_text(self, data[: len(data) // 2], *args, **kwargs)
        raise KeyboardInterrupt

    monkeypatch.setattr(Path, "write_text", half_then_interrupt)
    with pytest.raises(KeyboardInterrupt):
        write_log(tmp_path, {"time": "1969", "research_claims": ["lost"]})
    monkeypatch.undo()

    assert read_log(tmp_path) == {"time": "1969", "research_claims": ["kept"]}


def test_write_log_round_trips_and_leaves_no_temp_file_behind(tmp_path):
    write_log(tmp_path, {"beats": [{"id": "b1"}]})

    assert read_log(tmp_path) == {"beats": [{"id": "b1"}]}
    assert [p.name for p in tmp_path.iterdir()] == ["run_log.json"]
