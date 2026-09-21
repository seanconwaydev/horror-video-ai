"""main() end to end under --mock.

cli/app.py sat at 22% coverage with main() never called by the suite,
while every other module was above 94%. Its only automated exercise was
the CI smoke job's single `--mock` invocation, which takes one path
through a function that branches three ways before it reaches scene
planning. That is how a fixture run came to record `genre: "historical"`
no matter what --genre said: the branch that did it had no test and no
smoke run.

These are slower than a unit test because they really do run every stage
(mocked) and write a real run directory into tmp_path. That is the point
-- the seams between stages are what nothing else covers.
"""

from __future__ import annotations

import json
import sys

import pytest

from historical_video_ai.cli.app import main


@pytest.fixture
def run_in(tmp_path, monkeypatch):
    """Point outputs/ at tmp_path. Patches runlog's own binding, not
    app's: patching the importing module would leave these tests green
    while the code under test used the real filesystem."""
    (tmp_path / "pyproject.toml").write_text("")
    monkeypatch.setattr(
        "historical_video_ai.cli.runlog.project_root", lambda: tmp_path
    )

    def _run(argv: list[str]) -> dict:
        monkeypatch.setattr(sys, "argv", ["historical-video-ai", *argv])
        main()
        run_dirs = sorted((tmp_path / "outputs").glob("run_*"))
        assert run_dirs, "main() produced no run directory"
        return json.loads((run_dirs[-1] / "run_log.json").read_text())

    return _run


_BASE = [
    "--mock",
    "--yes",
    "--candidates",
    "1",
    "--max-beats",
    "1",
]


def test_a_run_plans_a_scene_and_produces_beat_images(run_in):
    log = run_in(
        [
            *_BASE,
            "--genre",
            "horror",
            "--tone",
            "dread",
            "--time",
            "present day",
            "--place",
            "an underground car park",
            "--description",
            "a woman notices someone between the pillars",
        ]
    )

    assert log["genre"] == "horror"
    assert log["tone"] == "dread"
    assert log["time"] == "present day"
    assert log["scene_plan"]["beats"]
    assert log["previz_beats"]


def test_a_run_records_nothing_about_research_or_fact_check(run_in):
    """docs/decisions/0069 deleted both stages. The run log is the
    judgement dataset (docs/decisions/0053), so a leftover key here would
    be a column of nulls in every exported row."""
    log = run_in(
        [*_BASE, "--time", "now", "--place", "a kitchen", "--description", "a cat jumps"]
    )

    for gone in (
        "research_model",
        "fact_check_model",
        "research_claims",
        "fact_check_flags",
        "premise_conflict",
        "acknowledged_fiction",
        "requires_grounding",
        "fixture",
    ):
        assert gone not in log, f"{gone!r} is still being written to the run log"


def test_genre_defaults_to_horror_and_reaches_the_plan(run_in):
    """`historical` was the default, and on that default the genre was
    never shown to the planner at all -- it was only passed through when
    a run was *un*grounded. Both halves of that are gone."""
    log = run_in(
        [*_BASE, "--time", "now", "--place", "a stairwell", "--description", "she looks up"]
    )

    assert log["genre"] == "horror"
