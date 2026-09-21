"""The --mock fakes had no tests while they lived inside cli.py, so a
change to a stage's expected output shape could break every offline run
-- including CI's smoke job, the only automated cover the cross-stage
wiring has -- with nothing to catch it locally.

These tests feed each fake's output into the real parser that consumes it
in a --mock run, rather than asserting on the fake's literal strings. A
fake that no longer satisfies its stage is the failure worth catching.
"""

import base64
import io
import json

import pytest
from PIL import Image

from historical_video_ai.cli.mocks import (
    MOCK_PNG_B64,
    mock_download,
    mock_image,
    mock_image_edit,
    mock_moderation_policy_check,
    mock_prediction,
    mock_scene_planning_completion,
)
from historical_video_ai.stages.scene_planning import _parse_scene_plan


def _content(response):
    return json.loads(response.choices[0].message.content)


@pytest.mark.parametrize("fake", [mock_image, mock_image_edit])
def test_mock_image_fakes_return_a_decodable_png(fake):
    b64 = fake().data[0].b64_json
    image = Image.open(io.BytesIO(base64.b64decode(b64)))
    assert image.format == "PNG"
    # 9:16, the only format this project generates (docs/decisions/0002).
    assert image.width / image.height == pytest.approx(9 / 16, abs=0.01)


def test_mock_scene_plan_parses_through_the_real_stage_parser():
    # _parse_scene_plan is what run_scene_planning_stage feeds model
    # output to, validators included -- so this fails the day a required
    # field is added to Character, Location, Staging or Beat and the fake
    # is not updated with it.
    raw = mock_scene_planning_completion().choices[0].message.content
    plan = _parse_scene_plan(raw)

    assert [c.id for c in plan.characters] == ["mock-character"]
    assert [loc.id for loc in plan.locations] == ["mock-location"]
    assert len(plan.beats) == 1
    beat = plan.beats[0]
    assert beat.location_id == "mock-location"
    assert [s.character_id for s in beat.staging] == ["mock-character"]


def test_mock_prediction_is_already_succeeded():
    prediction = mock_prediction()
    assert prediction["status"] == "succeeded"
    assert prediction["error"] is None
    assert prediction["output"].endswith(".mp4")


def test_mock_download_returns_bytes():
    assert isinstance(mock_download(), bytes)


def test_mock_moderation_comes_back_clean():
    result = mock_moderation_policy_check()
    assert result.results[0].flagged is False


def test_mock_png_is_a_real_png():
    assert base64.b64decode(MOCK_PNG_B64).startswith(b"\x89PNG")
