"""main() end to end under --mock, once per entry shape.

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


def test_a_grounded_historical_run_records_its_stages(run_in):
    log = run_in(
        [*_BASE, "--time", "1969", "--place", "Florida", "--description", "she watches"]
    )

    assert log["genre"] == "historical"
    assert log["requires_grounding"] is True
    # Research and fact-check really ran (mocked), rather than the
    # ungrounded branch being taken by accident.
    assert log["research_claims"]
    assert "fact_check_flags" in log
    assert log["research_model"] and log["fact_check_model"]
    assert log["scene_plan"]["beats"]
    assert log["previz_beats"]


def test_an_ungrounded_genre_skips_research_and_says_so_in_the_log(run_in):
    """docs/decisions/0034/0035: a scene never claiming to be real gets no
    value from historical-accuracy machinery."""
    log = run_in(
        [
            *_BASE,
            "--genre",
            "meme",
            "--time",
            "now",
            "--place",
            "a kitchen",
            "--description",
            "a cat knocks a glass over",
        ]
    )

    assert log["genre"] == "meme"
    assert log["requires_grounding"] is False
    assert log["research_claims"] == []
    # Neither stage ran, so neither model is recorded. The run log is the
    # judgement dataset (docs/decisions/0053): a field naming what
    # produced a row is worse than absent if it names something that
    # never ran.
    assert "research_model" not in log
    assert "fact_check_model" not in log
    assert log["scene_plan"]["beats"]


def test_a_fixture_run_records_the_genre_it_actually_used(run_in, tmp_path):
    """The genre routes composition mode and threat mode whether or not
    the run is grounded, so `--fixture X --genre horror` really does plan
    a horror scene. Recording a hardcoded "historical" made the run log
    disagree with the run -- and evals/export_judgements.py stamps every
    judgement row with this field so that rows made under different
    conditions are never compared."""
    source = run_in(
        [*_BASE, "--time", "1969", "--place", "Florida", "--description", "she watches"]
    )
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(json.dumps(source))

    log = run_in([*_BASE, "--genre", "horror", "--fixture", str(fixture_path)])

    assert log["genre"] == "horror"
    # Still grounded: a fixture's fact sheet was verified for real and
    # --genre cannot un-ground it.
    assert log["requires_grounding"] is True
    assert log["fixture"] == str(fixture_path)
    assert log["scene_plan"]["beats"]
