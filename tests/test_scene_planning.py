import json
from types import SimpleNamespace

import pytest

from historical_video_ai.config import get_stage_model
from historical_video_ai.stages.fact_check import FactCheckResult
from historical_video_ai.stages.research import Claim, FactSheet
from historical_video_ai.stages.scene_planning import (
    ScenePlanningError,
    run_scene_planning_stage,
)


def _fact_check_result() -> FactCheckResult:
    fact_sheet = FactSheet(
        time="79 AD, Pompeii",
        place="a thermopolium in Pompeii",
        description="an influencer visits an eatery and reviews a dish.",
        claims=[Claim(text="Thermopolia served hot prepared food and wine.", source="NPS")],
    )
    return FactCheckResult(fact_sheet=fact_sheet)


def _valid_payload(**overrides) -> dict:
    payload = {
        "characters": [
            {
                "id": "influencer",
                "face_build": "young woman, mid-20s",
                "hair": "light brown wavy",
                "wardrobe_signature": "white crop top, gray leggings",
                "wardrobe_flexible": "accessories may vary",
                "distinguishing_detail": "a glowing phone",
            }
        ],
        "locations": [
            {
                "id": "street",
                "architecture": "stone-paved Pompeii street",
                "fixed_props": "an archway entrance",
                "ambient_light": "bright midday sun",
            }
        ],
        "beats": [
            {
                "location_id": "street",
                "subject": "The influencer",
                "action": "checks her phone",
                "camera": "medium shot",
                "lighting": "bright midday sun",
                "style": "photorealistic",
                "audio": "street ambience",
                "duration_seconds": "3",
            }
        ],
    }
    payload.update(overrides)
    return payload


def _fake_completion(content: str):
    def _completion(**kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )

    return _completion


def test_run_scene_planning_stage_parses_full_plan():
    plan = run_scene_planning_stage(
        _fact_check_result(),
        model="deepseek/deepseek-v4-flash",
        completion_fn=_fake_completion(json.dumps(_valid_payload())),
    )

    assert plan.characters[0].id == "influencer"
    assert plan.locations[0].id == "street"
    assert plan.beats[0].location_id == "street"
    assert plan.beats[0].action == "checks her phone"


def test_run_scene_planning_stage_parses_response_wrapped_in_markdown_fence():
    payload = _valid_payload()
    plan = run_scene_planning_stage(
        _fact_check_result(),
        model="deepseek/deepseek-v4-flash",
        completion_fn=_fake_completion(f"```json\n{json.dumps(payload)}\n```"),
    )

    assert plan.beats[0].location_id == "street"


def test_run_scene_planning_stage_raises_for_invalid_json():
    with pytest.raises(ScenePlanningError, match="not valid JSON"):
        run_scene_planning_stage(
            _fact_check_result(),
            model="deepseek/deepseek-v4-flash",
            completion_fn=_fake_completion("not json"),
        )


def test_run_scene_planning_stage_raises_when_no_beats():
    payload = _valid_payload(beats=[])
    with pytest.raises(ScenePlanningError, match="no beats"):
        run_scene_planning_stage(
            _fact_check_result(),
            model="deepseek/deepseek-v4-flash",
            completion_fn=_fake_completion(json.dumps(payload)),
        )


def test_run_scene_planning_stage_raises_when_beat_references_unknown_location():
    payload = _valid_payload()
    payload["beats"][0]["location_id"] = "nonexistent"
    with pytest.raises(ScenePlanningError, match="doesn't match any defined location"):
        run_scene_planning_stage(
            _fact_check_result(),
            model="deepseek/deepseek-v4-flash",
            completion_fn=_fake_completion(json.dumps(payload)),
        )


def test_run_scene_planning_stage_raises_on_duplicate_character_ids():
    payload = _valid_payload()
    second_character = dict(payload["characters"][0])
    payload["characters"].append(second_character)  # same id as the first
    with pytest.raises(ScenePlanningError, match="Duplicate character id"):
        run_scene_planning_stage(
            _fact_check_result(),
            model="deepseek/deepseek-v4-flash",
            completion_fn=_fake_completion(json.dumps(payload)),
        )


def test_run_scene_planning_stage_raises_on_duplicate_location_ids():
    payload = _valid_payload()
    second_location = dict(payload["locations"][0])
    payload["locations"].append(second_location)  # same id as the first
    with pytest.raises(ScenePlanningError, match="Duplicate location id"):
        run_scene_planning_stage(
            _fact_check_result(),
            model="deepseek/deepseek-v4-flash",
            completion_fn=_fake_completion(json.dumps(payload)),
        )


def test_run_scene_planning_stage_raises_when_character_missing_field():
    payload = _valid_payload()
    del payload["characters"][0]["hair"]
    with pytest.raises(ScenePlanningError, match="missing or has an empty 'hair'"):
        run_scene_planning_stage(
            _fact_check_result(),
            model="deepseek/deepseek-v4-flash",
            completion_fn=_fake_completion(json.dumps(payload)),
        )


def test_run_scene_planning_stage_raises_when_location_field_empty():
    payload = _valid_payload()
    payload["locations"][0]["architecture"] = ""
    with pytest.raises(ScenePlanningError, match="missing or has an empty 'architecture'"):
        run_scene_planning_stage(
            _fact_check_result(),
            model="deepseek/deepseek-v4-flash",
            completion_fn=_fake_completion(json.dumps(payload)),
        )


def test_run_scene_planning_stage_allows_no_characters():
    # Characters are optional -- a scene might have no named/described
    # character at all.
    payload = _valid_payload(characters=[])
    plan = run_scene_planning_stage(
        _fact_check_result(),
        model="deepseek/deepseek-v4-flash",
        completion_fn=_fake_completion(json.dumps(payload)),
    )
    assert plan.characters == []


def test_run_scene_planning_stage_resolves_model_from_config_when_not_passed():
    captured = {}

    def _completion(**kwargs):
        captured["model"] = kwargs["model"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(_valid_payload())))]
        )

    run_scene_planning_stage(_fact_check_result(), completion_fn=_completion)

    assert captured["model"] == get_stage_model("scene_planning")


def test_run_scene_planning_stage_truncates_to_max_beats():
    payload = _valid_payload()
    second_beat = dict(payload["beats"][0])
    second_beat["action"] = "a second thing happens"
    payload["beats"].append(second_beat)

    plan = run_scene_planning_stage(
        _fact_check_result(),
        model="deepseek/deepseek-v4-flash",
        max_beats=1,
        completion_fn=_fake_completion(json.dumps(payload)),
    )

    assert len(plan.beats) == 1
    assert plan.beats[0].action == "checks her phone"


def test_run_scene_planning_stage_leaves_beats_alone_when_under_max_beats():
    plan = run_scene_planning_stage(
        _fact_check_result(),
        model="deepseek/deepseek-v4-flash",
        max_beats=5,
        completion_fn=_fake_completion(json.dumps(_valid_payload())),
    )

    assert len(plan.beats) == 1


def test_run_scene_planning_stage_drops_unused_character_beyond_first_for_max_references():
    # cli.py only ever conditions generation on characters[0] (Beat has no
    # character_id) -- always safe to drop the rest.
    payload = _valid_payload()
    second_character = dict(payload["characters"][0])
    second_character["id"] = "second"
    payload["characters"].append(second_character)

    plan = run_scene_planning_stage(
        _fact_check_result(),
        model="deepseek/deepseek-v4-flash",
        max_references=2,
        completion_fn=_fake_completion(json.dumps(payload)),
    )

    assert len(plan.characters) == 1
    assert plan.characters[0].id == "influencer"
    assert len(plan.locations) == 1


def test_run_scene_planning_stage_drops_unused_location_for_max_references():
    payload = _valid_payload()
    unused_location = dict(payload["locations"][0])
    unused_location["id"] = "unused_place"
    payload["locations"].append(unused_location)
    # payload's one beat only references "street" -- "unused_place" is dead weight.

    plan = run_scene_planning_stage(
        _fact_check_result(),
        model="deepseek/deepseek-v4-flash",
        max_references=2,
        completion_fn=_fake_completion(json.dumps(payload)),
    )

    assert len(plan.locations) == 1
    assert plan.locations[0].id == "street"


def test_run_scene_planning_stage_leaves_used_references_over_budget_when_unsafe_to_drop():
    # Both locations are genuinely referenced by a beat -- dropping either
    # would orphan that beat, so max_references is left unmet rather than
    # corrupting the plan (docs/decisions/0027/0028's same principle).
    payload = _valid_payload()
    second_location = dict(payload["locations"][0])
    second_location["id"] = "interior"
    payload["locations"].append(second_location)
    second_beat = dict(payload["beats"][0])
    second_beat["location_id"] = "interior"
    payload["beats"].append(second_beat)

    plan = run_scene_planning_stage(
        _fact_check_result(),
        model="deepseek/deepseek-v4-flash",
        max_references=2,
        completion_fn=_fake_completion(json.dumps(payload)),
    )

    assert len(plan.characters) == 1
    assert len(plan.locations) == 2  # left over-budget, both are in use


def test_run_scene_planning_stage_includes_max_beats_in_prompt_when_given():
    captured = {}

    def _completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(_valid_payload())))]
        )

    run_scene_planning_stage(
        _fact_check_result(), model="deepseek/deepseek-v4-flash", max_beats=4, completion_fn=_completion
    )

    prompt = captured["messages"][0]["content"]
    assert "at most 4 beat(s)" in prompt


def test_run_scene_planning_stage_omits_max_beats_line_when_not_given():
    captured = {}

    def _completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(_valid_payload())))]
        )

    run_scene_planning_stage(
        _fact_check_result(), model="deepseek/deepseek-v4-flash", completion_fn=_completion
    )

    assert "at most" not in captured["messages"][0]["content"]


def test_run_scene_planning_stage_includes_claims_in_prompt():
    captured = {}

    def _completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(_valid_payload())))]
        )

    run_scene_planning_stage(
        _fact_check_result(), model="deepseek/deepseek-v4-flash", completion_fn=_completion
    )

    prompt = captured["messages"][0]["content"]
    assert "Thermopolia served hot prepared food and wine." in prompt
    assert "79 AD, Pompeii" in prompt


def test_run_scene_planning_stage_uses_creative_framing_when_ungrounded():
    # docs/decisions/0034
    captured = {}

    def _completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(_valid_payload())))]
        )

    run_scene_planning_stage(
        _fact_check_result(),
        model="deepseek/deepseek-v4-flash",
        requires_grounding=False,
        completion_fn=_completion,
    )

    prompt = captured["messages"][0]["content"]
    assert "not meant to be historically or factually accurate" in prompt
    assert "historical video scene" not in prompt
    assert "Verified claims" not in prompt
    assert "Thermopolia served hot prepared food and wine." not in prompt
