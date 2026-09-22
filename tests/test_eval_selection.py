"""The shared option-resolver behind every eval script's list flags.

CLAUDE.md notes that `testpaths` is ["tests"] and nothing here imports
anything under evals/, which is why the whole measurement layer once sat
broken for a month. The CI smoke job covers the scripts' `--dry-run`s,
but a `--dry-run` only ever passes valid flags, so the failure path this
module exists for -- what happens when you typo one -- is exactly what a
smoke run cannot reach.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evals"))

from selection import require_known, select

MAPPING = {"flux-dev": {"n": 1}, "flux-schnell": {"n": 2}}


@pytest.fixture
def parser():
    # exit_on_error is irrelevant here: parser.error() always raises
    # SystemExit, which is the behaviour under test.
    return argparse.ArgumentParser(prog="eval")


def test_select_resolves_keys_in_the_order_given(parser):
    assert list(select(parser, MAPPING, "flux-schnell,flux-dev", flag="models")) == [
        "flux-schnell",
        "flux-dev",
    ]


def test_select_tolerates_whitespace_around_keys(parser):
    assert list(select(parser, MAPPING, " flux-dev , flux-schnell ", flag="models")) == [
        "flux-dev",
        "flux-schnell",
    ]


def test_select_names_the_unknown_value_and_the_valid_ones(parser, capsys):
    """A bare `KeyError: 'sonnet'` names the thing that failed and nothing
    about what would have worked -- the complaint config.py already
    answers for stage names."""
    with pytest.raises(SystemExit):
        select(parser, MAPPING, "flux-dev,sonnet", flag="models")

    err = capsys.readouterr().err
    assert "'sonnet'" in err
    assert "flux-dev" in err and "flux-schnell" in err


def test_select_rejects_an_empty_value(parser):
    with pytest.raises(SystemExit):
        select(parser, MAPPING, ",, ,", flag="models")


def test_require_known_rejects_an_id_that_matches_nothing(parser, capsys):
    """run_eval's --scenes filters a list rather than indexing a mapping,
    so an unknown id used to select nothing and run happily against zero
    scenes -- a silent no-op, worse than a crash."""
    with pytest.raises(SystemExit):
        require_known(parser, ["outdoor_chase", "visible_entity"], "nope", flag="scenes")

    assert "'nope'" in capsys.readouterr().err


def test_require_known_returns_the_requested_ids(parser):
    assert require_known(
        parser, ["outdoor_chase", "visible_entity"], "visible_entity", flag="scenes"
    ) == {"visible_entity"}
