"""Shot writing: parsing, duration fitting, and the platform-safety gate."""

import json
from types import SimpleNamespace

import pytest

from horror_video_ai.stages.scene_planning import Beat, Character, Location, ScenePlan
from horror_video_ai.stages.shot_writing import (
    Shot,
    ShotList,
    ShotWritingError,
    check_platform_safety,
    fit_durations,
    format_plan,
    run_shot_writing_stage,
)

LOOK = "IR night-vision security cam, locked off high in a corner. Camera static."


def _plan():
    return ScenePlan(
        characters=[
            Character(
                id="watcher",
                face_build="tall and gaunt",
                hair="none",
                wardrobe_signature="a long grey coat",
                wardrobe_flexible="scuffed boots",
                distinguishing_detail="a matte black ear cuff",
            )
        ],
        locations=[
            Location(
                id="bedroom",
                architecture="a small room with one door",
                fixed_props="a single bed",
                ambient_light="infrared illuminator only",
            )
        ],
        beats=[
            Beat(
                location_id="bedroom",
                subject="the watcher",
                action="stands in the doorway, motionless",
                camera="wide, high corner",
                lighting="infrared",
                audio="hiss",
                duration_seconds="4",
            )
        ],
    )


def _completion(shots):
    def fake(**kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(shots)))]
        )

    return fake


def test_run_shot_writing_stage_parses_and_fits_durations():
    shots = [
        {"prompt": "A door creeps open. Audio: hiss.", "duration_seconds": 4},
        {"prompt": "It is mid-floor now. Audio: a creak.", "duration_seconds": 4},
    ]
    result = run_shot_writing_stage(
        _plan(),
        look=LOOK,
        total_seconds=15,
        model="test/model",
        completion_fn=_completion(shots),
    )
    assert result.total_seconds == 15
    assert len(result.shots) == 2
    assert result.look == LOOK
    assert result.negative_prompt


def test_code_fenced_json_is_accepted():
    def fake(**kwargs):
        body = '```json\n[{"prompt": "A door creeps open.", "duration_seconds": 5}]\n```'
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=body))])

    result = run_shot_writing_stage(
        _plan(), look=LOOK, total_seconds=8, model="test/model", completion_fn=fake
    )
    assert result.total_seconds == 8


def test_non_json_output_fails_loud():
    def fake(**kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="here are your shots!"))]
        )

    with pytest.raises(ShotWritingError, match="did not return JSON"):
        run_shot_writing_stage(
            _plan(), look=LOOK, model="test/model", completion_fn=fake
        )


def test_empty_response_fails_loud():
    def fake(**kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=""))])

    with pytest.raises(ShotWritingError, match="empty response"):
        run_shot_writing_stage(_plan(), look=LOOK, model="test/model", completion_fn=fake)


def test_too_many_shots_is_refused():
    shots = [{"prompt": f"Shot {i}.", "duration_seconds": 1} for i in range(8)]
    with pytest.raises(ShotWritingError, match="shots"):
        run_shot_writing_stage(
            _plan(),
            look=LOOK,
            total_seconds=15,
            max_shots=6,
            model="test/model",
            completion_fn=_completion(shots),
        )


# The whole point of the safety gate: a real generation produced ambiguous
# anatomy from exactly this kind of description, and the resulting video
# could not be published.
@pytest.mark.parametrize(
    "prompt",
    [
        "A tall figure with long bare legs stands in the doorway.",
        "The figure is naked beneath the hanging hem.",
        "It stands in underwear at the foot of the bed.",
        "The light falls on its crotch.",
        "Something hangs between its legs.",
        "Its wet clothing clings to it.",
    ],
)
def test_platform_safety_rejects_anatomy_risks(prompt):
    assert check_platform_safety(prompt)
    with pytest.raises(ShotWritingError, match="platform-safety"):
        run_shot_writing_stage(
            _plan(),
            look=LOOK,
            total_seconds=4,
            model="test/model",
            completion_fn=_completion([{"prompt": prompt, "duration_seconds": 4}]),
        )


def test_platform_safety_allows_a_clothed_figure():
    prompt = "A tall figure in a long grey coat stands in the doorway. Audio: hiss."
    assert check_platform_safety(prompt) == []


def test_fit_durations_absorbs_drift_into_the_last_shot():
    shots = [Shot("a", 4), Shot("b", 4), Shot("c", 4)]
    assert [s.duration_seconds for s in fit_durations(shots, 15)] == [4, 4, 7]


def test_fit_durations_drops_shots_that_cannot_fit():
    shots = [Shot("a", 8), Shot("b", 8), Shot("c", 8)]
    fitted = fit_durations(shots, 10)
    assert sum(s.duration_seconds for s in fitted) == 10
    assert len(fitted) < 3


def test_shot_list_round_trips_through_json():
    original = ShotList(
        shots=[Shot("a door creeps open", 4), Shot("it is closer", 4)],
        look=LOOK,
        negative_prompt="nude, naked",
    )
    assert ShotList.from_json(original.to_json()) == original


def test_shot_list_from_json_fails_loud_on_a_missing_field():
    with pytest.raises(ShotWritingError, match="Unusable shot list"):
        ShotList.from_json('{"shots": [{"prompt": "x"}], "look": "l", "negative_prompt": "n"}')


def test_format_plan_includes_every_layer_the_writer_needs():
    text = format_plan(_plan())
    assert "CHARACTER watcher" in text
    assert "LOCATION bedroom" in text
    assert "BEAT 1" in text
    assert "a long grey coat" in text
