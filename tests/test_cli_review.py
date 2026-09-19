"""The interactive review widgets (cli/review.py): confirm, prompt, show,
edit, accept.

Split out of test_cli.py alongside the module itself.
"""

import dataclasses

import pytest
from factories import a_beat, a_character, a_location

from historical_video_ai.cli.review import (
    confirm,
    edit_item_fields,
    print_item_fields,
    prompt_if_missing,
    review_scene_plan,
)
from historical_video_ai.stages.scene_planning import Beat, Location, ScenePlan, Staging


def test_confirm_auto_yes_returns_true_without_calling_input(monkeypatch):
    def _explode(_prompt):
        raise AssertionError("input() should not be called under auto_yes")

    monkeypatch.setattr("builtins.input", _explode)

    assert confirm("Proceed?", auto_yes=True) is True


def test_prompt_if_missing_auto_yes_raises_on_empty_value():
    with pytest.raises(ValueError, match="Time is required"):
        prompt_if_missing(None, "Time", auto_yes=True)


def test_prompt_if_missing_auto_yes_passes_through_a_given_value():
    # auto_yes only matters when the value is missing -- an already-given
    # value (e.g. from a CLI flag) is returned as-is.
    assert prompt_if_missing("July 1969", "Time", auto_yes=True) == "July 1969"


def test_review_scene_plan_accepts_everything_under_auto_yes():
    plan = ScenePlan(characters=[a_character()], locations=[a_location()], beats=[a_beat()])

    reviewed = review_scene_plan(plan, auto_yes=True)

    assert reviewed == plan


def test_review_scene_plan_recatches_a_beat_edited_to_an_unknown_location(monkeypatch):
    # docs/decisions/0028: editing a beat's location_id to something that
    # doesn't match any reviewed location must not silently drop all
    # location grounding -- it should re-prompt for that beat specifically.
    # Each failed round re-enters review_item from the top (a)ccept/(e)dit
    # choice, so recovering means editing *again* with a valid id, not
    # just re-accepting the still-broken beat.
    plan = ScenePlan(characters=[], locations=[a_location()], beats=[a_beat()])
    responses = iter(
        ["a"]  # location: accept
        + ["e", "nonexistent-typo", "", "", "", "", "", "", ""]  # beat round 1: bad location_id
        + ["e", "street", "", "", "", "", "", "", ""]  # beat round 2: fixed
    )
    monkeypatch.setattr("builtins.input", lambda _: next(responses))

    reviewed = review_scene_plan(plan, auto_yes=False)

    assert reviewed.beats[0].location_id == "street"


def test_review_scene_plan_recatches_duplicate_location_ids_after_edit(monkeypatch):
    # docs/decisions/0028: editing a second location's id to collide with
    # the first must not silently corrupt character_refs/location_refs.
    plan = ScenePlan(
        characters=[],
        locations=[a_location(), Location(id="other", architecture="x", fixed_props="y", ambient_light="z")],
        beats=[a_beat()],
    )
    # Location 1: accept. Location 2: edit id to collide with location 1,
    # blank the rest -- caught, re-reviewed: accept location 1, then edit
    # location 2's id back to something unique.
    responses = iter(
        [
            "a",  # location 1: accept
            "e", "street", "", "", "",  # location 2: edit id to collide ("street")
            "a",  # re-review location 1: accept
            "e", "other-fixed", "", "", "",  # re-review location 2: fix id
            "a",  # beat: accept
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _: next(responses))

    reviewed = review_scene_plan(plan, auto_yes=False)

    ids = [loc.id for loc in reviewed.locations]
    assert len(ids) == len(set(ids))
    assert "other-fixed" in ids


def test_editing_a_beat_walks_into_each_staging_entry(monkeypatch):
    """staging is a list of dataclasses; the editor must prompt per
    character rather than asking for a repr back (docs/decisions/0049)."""
    beat = Beat(
        location_id="carpark", subject="w1", action="she reaches the car",
        camera="medium", lighting="one hard strip light", audio="hum",
        duration_seconds="4",
        staging=[
            Staging(character_id="w1", action="stands", blocking="centre"),
            Staging(character_id="fig1", action="stands", blocking="left"),
        ],
    )
    prompts = []

    def _fake_input(prompt):
        prompts.append(prompt)
        # Rewrite only the antagonist's action; keep everything else.
        return "leans around the pillar toward her" if "fig1 action" in prompt else ""

    monkeypatch.setattr("builtins.input", _fake_input)
    edited = edit_item_fields(beat, fields=("staging",))

    assert any("w1 action" in p for p in prompts)
    assert any("fig1 stands" in p for p in prompts)
    assert edited.staging[0].action == "stands"
    assert edited.staging[1].action == "leans around the pillar toward her"
    assert edited.staging[1].blocking == "left"


def test_confirm_reprompts_until_the_answer_is_recognisable(monkeypatch, capsys):
    answers = iter(["maybe", "", "Y"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    assert confirm("Continue?") is True
    assert capsys.readouterr().out.count("Please answer y or n.") == 2


def test_confirm_accepts_a_no(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "no")

    assert confirm("Continue?") is False


def test_prompt_if_missing_reprompts_until_something_is_typed(monkeypatch, capsys):
    answers = iter(["", "   ", "Kitty Hawk"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    assert prompt_if_missing(None, "Place") == "Kitty Hawk"
    assert capsys.readouterr().out.count("Place is required") == 3


def test_printing_a_beat_spells_out_its_staging(capsys):
    # A Staging repr in a review prompt is unreadable, and staging is the
    # field a human most needs to read (docs/decisions/0049).
    beat = dataclasses.replace(
        a_beat(),
        staging=(
            Staging(
                character_id="influencer",
                action="checks her phone",
                blocking="left third, mid-ground",
                occlusion="a market stall",
            ),
        ),
    )

    print_item_fields(beat)

    out = capsys.readouterr().out
    assert "- influencer: checks her phone" in out
    assert "stands: left third, mid-ground" in out
    assert "hidden by: a market stall" in out


def test_printing_a_beat_omits_the_occlusion_line_when_there_is_none(capsys):
    beat = dataclasses.replace(
        a_beat(),
        staging=(
            Staging(
                character_id="influencer",
                action="checks her phone",
                blocking="left third, mid-ground",
                occlusion="",
            ),
        ),
    )

    print_item_fields(beat)

    assert "hidden by" not in capsys.readouterr().out
