import json
import random
from types import SimpleNamespace

import pytest

from horror_video_ai.config import get_stage_model
from horror_video_ai.stages.scene_planning import (
    Beat,
    Character,
    Scene,
    ScenePlanningError,
    Staging,
    _parse_scene_plan,
    _random_character_trait_hint,
    _resolve_composition_mode,
    _resolve_threat_mode,
    beat_visibility_warnings,
    check_beat_character_references,
    identity_field_pose_warnings,
    load_scene_plan,
    run_scene_planning_stage,
)


def _scene() -> Scene:
    return Scene(
        time="79 AD, Pompeii",
        place="a thermopolium in Pompeii",
        description="an influencer visits an eatery and reviews a dish.",
    )


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
                "staging": [
                    {
                        "character_id": "influencer",
                        "action": "thumbs the screen awake and angles it away from the sun",
                        "blocking": "right third, filling half the frame height",
                        "size_in_frame": "roughly a third of the image",
                    }
                ],
                "contact": "",
                "intensity": "still -- nothing moving but her thumb on the screen",
                "camera": "medium shot",
                "lighting": "bright midday sun",
                "audio": "street ambience",
                "duration_seconds": "3",
            }
        ],
    }
    payload.update(overrides)
    return payload


def _staging(cid, action="reaches for the door handle", blocking="left third"):
    return Staging(character_id=cid, action=action, blocking=blocking)


def _beat(**overrides) -> Beat:
    fields: dict[str, object] = {
        "location_id": "street",
        "subject": "The influencer",
        "action": "checks her phone",
        "camera": "medium shot",
        "lighting": "bright midday sun",
        "audio": "street ambience",
        "duration_seconds": "3",
    }
    fields.update(overrides)
    # Splatting a fixture dict into a typed dataclass is not checkable;
    # overrides legitimately carry a staging list among the strings.
    return Beat(**fields)  # type: ignore[arg-type]


def _fake_completion(content: str):
    def _completion(**kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )

    return _completion


def test_run_scene_planning_stage_parses_full_plan():
    plan = run_scene_planning_stage(
        _scene(),
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
        _scene(),
        model="deepseek/deepseek-v4-flash",
        completion_fn=_fake_completion(f"```json\n{json.dumps(payload)}\n```"),
    )

    assert plan.beats[0].location_id == "street"


def test_run_scene_planning_stage_raises_for_invalid_json():
    with pytest.raises(ScenePlanningError, match="not valid JSON"):
        run_scene_planning_stage(
            _scene(),
            model="deepseek/deepseek-v4-flash",
            completion_fn=_fake_completion("not json"),
        )


def test_run_scene_planning_stage_raises_when_no_beats():
    payload = _valid_payload(beats=[])
    with pytest.raises(ScenePlanningError, match="no beats"):
        run_scene_planning_stage(
            _scene(),
            model="deepseek/deepseek-v4-flash",
            completion_fn=_fake_completion(json.dumps(payload)),
        )


def test_run_scene_planning_stage_raises_when_beat_references_unknown_location():
    payload = _valid_payload()
    payload["beats"][0]["location_id"] = "nonexistent"
    with pytest.raises(ScenePlanningError, match="doesn't match any defined location"):
        run_scene_planning_stage(
            _scene(),
            model="deepseek/deepseek-v4-flash",
            completion_fn=_fake_completion(json.dumps(payload)),
        )


def test_run_scene_planning_stage_raises_on_duplicate_character_ids():
    payload = _valid_payload()
    second_character = dict(payload["characters"][0])
    payload["characters"].append(second_character)  # same id as the first
    with pytest.raises(ScenePlanningError, match="Duplicate character id"):
        run_scene_planning_stage(
            _scene(),
            model="deepseek/deepseek-v4-flash",
            completion_fn=_fake_completion(json.dumps(payload)),
        )


def test_run_scene_planning_stage_raises_on_duplicate_location_ids():
    payload = _valid_payload()
    second_location = dict(payload["locations"][0])
    payload["locations"].append(second_location)  # same id as the first
    with pytest.raises(ScenePlanningError, match="Duplicate location id"):
        run_scene_planning_stage(
            _scene(),
            model="deepseek/deepseek-v4-flash",
            completion_fn=_fake_completion(json.dumps(payload)),
        )


def test_run_scene_planning_stage_raises_when_character_missing_field():
    payload = _valid_payload()
    del payload["characters"][0]["hair"]
    with pytest.raises(ScenePlanningError, match="missing or has an empty 'hair'"):
        run_scene_planning_stage(
            _scene(),
            model="deepseek/deepseek-v4-flash",
            completion_fn=_fake_completion(json.dumps(payload)),
        )


def test_run_scene_planning_stage_raises_when_location_field_empty():
    payload = _valid_payload()
    payload["locations"][0]["architecture"] = ""
    with pytest.raises(ScenePlanningError, match="missing or has an empty 'architecture'"):
        run_scene_planning_stage(
            _scene(),
            model="deepseek/deepseek-v4-flash",
            completion_fn=_fake_completion(json.dumps(payload)),
        )


def test_run_scene_planning_stage_allows_no_characters():
    # Characters are optional -- a scene might have no named/described
    # character at all.
    payload = _valid_payload(characters=[])
    plan = run_scene_planning_stage(
        _scene(),
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

    run_scene_planning_stage(_scene(), completion_fn=_completion)

    assert captured["model"] == get_stage_model("scene_planning")


def test_run_scene_planning_stage_truncates_to_max_beats():
    payload = _valid_payload()
    second_beat = dict(payload["beats"][0])
    second_beat["action"] = "a second thing happens"
    payload["beats"].append(second_beat)

    plan = run_scene_planning_stage(
        _scene(),
        model="deepseek/deepseek-v4-flash",
        max_beats=1,
        completion_fn=_fake_completion(json.dumps(payload)),
    )

    assert len(plan.beats) == 1
    assert plan.beats[0].action == "checks her phone"


def test_run_scene_planning_stage_leaves_beats_alone_when_under_max_beats():
    plan = run_scene_planning_stage(
        _scene(),
        model="deepseek/deepseek-v4-flash",
        max_beats=5,
        completion_fn=_fake_completion(json.dumps(_valid_payload())),
    )

    assert len(plan.beats) == 1


def test_run_scene_planning_stage_includes_max_beats_in_prompt_when_given():
    captured = {}

    def _completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(_valid_payload())))]
        )

    run_scene_planning_stage(
        _scene(), model="deepseek/deepseek-v4-flash", max_beats=4, completion_fn=_completion
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
        _scene(), model="deepseek/deepseek-v4-flash", completion_fn=_completion
    )

    assert "at most" not in captured["messages"][0]["content"]


def test_run_scene_planning_stage_includes_genre_and_tone():
    # docs/decisions/0035
    captured = {}

    def _completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(_valid_payload())))]
        )

    run_scene_planning_stage(
        _scene(),
        model="deepseek/deepseek-v4-flash",
        genre="meme",
        tone="comedic",
        completion_fn=_completion,
    )

    prompt = captured["messages"][0]["content"]
    assert "Genre: meme." in prompt
    assert "Tone: comedic." in prompt


def test_run_scene_planning_stage_includes_location_physical_consistency_rule():
    # Real run (2026-09-15): scene planning assigned a "lying in bed, near
    # the headboard/nightstand" beat to a Location whose own architecture
    # was a hallway/landing with no bed at all -- previz then rendered the
    # location it was actually given (a landing) with a bed awkwardly
    # implied into it, not the contradiction-free scene the beat's own
    # text described. This rule is always included (not genre-gated).
    captured = {}

    def _completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(_valid_payload())))]
        )

    run_scene_planning_stage(
        _scene(), model="deepseek/deepseek-v4-flash", completion_fn=_completion
    )

    prompt = captured["messages"][0]["content"]
    assert "must be physically possible in the Location it's assigned to" in prompt


def test_run_scene_planning_stage_includes_within_location_position_rule():
    # Real report (2026-09-15): two beats sharing a staircase location
    # came out basically identical images -- the existing "coverage" rule
    # covered camera position and pose, but nothing required the
    # character's own physical position within the space (e.g. top vs.
    # bottom of the stairs) to actually differ.
    captured = {}

    def _completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(_valid_payload())))]
        )

    run_scene_planning_stage(
        _scene(), model="deepseek/deepseek-v4-flash", completion_fn=_completion
    )

    prompt = captured["messages"][0]["content"]
    assert "genuinely different physical position *within* that location's own space" in prompt


def test_run_scene_planning_stage_includes_facial_expression_rule():
    # Real report (2026-09-15): generated beats consistently showed a
    # flat, deadpan expression -- image models render neutral unless a
    # specific emotion is named outright, the same "vague adjective
    # doesn't work" pattern behind several other rules in this file.
    # Always included, not genre-gated -- every genre benefits from an
    # explicit facial expression, not just horror.
    captured = {}

    def _completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(_valid_payload())))]
        )

    run_scene_planning_stage(
        _scene(), model="deepseek/deepseek-v4-flash", completion_fn=_completion
    )

    prompt = captured["messages"][0]["content"]
    assert "must state the character's facial expression/emotion explicitly" in prompt
    assert "give every beat its own distinct, specifically-named point along that arc" in prompt


def test_random_character_trait_hint_is_deterministic_for_a_seeded_rng():
    hint_a = _random_character_trait_hint(random.Random(42))
    hint_b = _random_character_trait_hint(random.Random(42))
    assert hint_a == hint_b


def test_run_scene_planning_stage_includes_character_variety_rule_with_trait_hint():
    # Real report (2026-09-15): the same character recurred nearly
    # identically across separate runs of an identical prompt, since
    # nothing forced the planning model to vary physical traits when the
    # scene's own description didn't specify any. A seeded `rng` makes
    # the injected hint's exact wording deterministic and checkable here.
    captured = {}

    def _completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(_valid_payload())))]
        )

    run_scene_planning_stage(
        _scene(),
        model="deepseek/deepseek-v4-flash",
        completion_fn=_completion,
        rng=random.Random(42),
    )

    prompt = captured["messages"][0]["content"]
    expected_hint = _random_character_trait_hint(random.Random(42))
    assert "Vary each Character's physical appearance meaningfully" in prompt
    assert expected_hint in prompt


# docs/decisions/0036: composition_mode is an early-resolved, closed-set
# routing signal (a second axis alongside requires_grounding) selecting
# which composition rule group scene_planning uses -- replaces the inline
# "unless genre signals X" prose hedge PR #44 added to the staging rule.


@pytest.mark.parametrize(
    "genre,tone",
    [
        ("surreal photo collage", "deadpan"),
        ("absurdist comedy", ""),
        ("historical", "chaotic and unhinged"),  # keyword can come from tone alone
        ("SURREAL meme", ""),  # case-insensitive
        ("bizarre vaporwave dreamscape", None),
    ],
)
def test_resolve_composition_mode_returns_chaotic_for_surreal_signals(genre, tone):
    assert _resolve_composition_mode(genre, tone) == "chaotic"


@pytest.mark.parametrize(
    "genre,tone",
    [
        ("historical", "sincere"),
        ("meme", None),  # "meme" alone doesn't imply chaotic composition
        (None, None),
        ("vlog", "upbeat"),
    ],
)
def test_resolve_composition_mode_defaults_to_staged(genre, tone):
    assert _resolve_composition_mode(genre, tone) == "staged"


def test_run_scene_planning_stage_uses_chaotic_composition_rule_for_surreal_genre():
    captured = {}

    def _completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(_valid_payload())))]
        )

    run_scene_planning_stage(
        _scene(),
        model="deepseek/deepseek-v4-flash",
        genre="surreal photo collage",
        tone="deadpan",
        completion_fn=_completion,
    )

    prompt = captured["messages"][0]["content"]
    assert "Commit fully to a strange, asymmetric, or chaotic composition" in prompt
    assert 'the animation principle of "staging"' not in prompt


# threat_mode: a third early-resolved, closed-set routing signal alongside
# composition_mode (0036), added after a real horror test run showed the
# threat mentioned in only 2 of 9 beats' text -- see
# docs/research/short-form-format-selection.md.


@pytest.mark.parametrize(
    "genre,tone",
    [
        ("horror", ""),
        ("psychological thriller", None),
        ("historical", "creepy and dread-filled"),  # keyword can come from tone alone
        ("HORROR comedy", ""),  # case-insensitive
        ("supernatural mystery", None),
    ],
)
def test_resolve_threat_mode_returns_present_for_horror_signals(genre, tone):
    assert _resolve_threat_mode(genre, tone) == "present"


@pytest.mark.parametrize(
    "genre,tone",
    [
        ("historical", "sincere"),
        ("meme", None),
        (None, None),
        ("vlog", "upbeat"),
    ],
)
def test_resolve_threat_mode_defaults_to_none(genre, tone):
    assert _resolve_threat_mode(genre, tone) == "none"


def test_run_scene_planning_stage_includes_fear_driven_motivation_rule_for_horror_genre():
    # Real report (2026-09-15): beats read as emotionally wrong for a
    # horror scene -- the character's motivation came across as neutral
    # curiosity, not fear, even though nothing forced the description
    # text itself to say "she is afraid" (genre/tone are the mechanism
    # meant to carry that without needing to restate it every time).
    captured = {}

    def _completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(_valid_payload())))]
        )

    run_scene_planning_stage(
        _scene(),
        model="deepseek/deepseek-v4-flash",
        genre="horror",
        completion_fn=_completion,
    )

    prompt = captured["messages"][0]["content"]
    assert "must read as fear/apprehension/dread-driven in every beat" in prompt


def test_run_scene_planning_stage_includes_threat_presence_rule_for_horror_genre():
    captured = {}

    def _completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(_valid_payload())))]
        )

    run_scene_planning_stage(
        _scene(),
        model="deepseek/deepseek-v4-flash",
        genre="horror",
        tone="dread-filled",
        completion_fn=_completion,
    )

    prompt = captured["messages"][0]["content"]
    assert "the central threat must read as present across a clear majority of beats" in prompt
    assert "give EVERY beat its own explicit, distinct point along that progression" in prompt
    assert "one single, hard-edged, dominant light source explicitly" in prompt


def test_run_scene_planning_stage_omits_threat_presence_rule_by_default():
    captured = {}

    def _completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(_valid_payload())))]
        )

    run_scene_planning_stage(
        _scene(),
        model="deepseek/deepseek-v4-flash",
        genre="historical",
        completion_fn=_completion,
    )

    prompt = captured["messages"][0]["content"]
    assert "central threat must read as present" not in prompt


def test_run_scene_planning_stage_uses_staged_composition_rule_by_default():
    captured = {}

    def _completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(_valid_payload())))]
        )

    run_scene_planning_stage(
        _scene(),
        model="deepseek/deepseek-v4-flash",
        genre="historical",
        completion_fn=_completion,
    )

    prompt = captured["messages"][0]["content"]
    assert 'the animation principle of "staging"' in prompt
    assert "Commit fully to a strange, asymmetric, or chaotic composition" not in prompt


# docs/decisions/0052: the framing vocabulary used to live only in the
# chaotic rule, so horror -- which matches no chaotic keyword -- could
# never reach it. It is unconditional now, so both modes must carry it.
@pytest.mark.parametrize(
    ("genre", "tone"),
    [
        ("horror", "dread"),  # the gap 0052 was written for
        ("historical", None),  # staged, the default
        ("surreal photo collage", "deadpan"),  # chaotic
    ],
)
def test_run_scene_planning_stage_always_includes_base_composition_rule(genre, tone):
    captured = {}

    def _completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(_valid_payload())))]
        )

    run_scene_planning_stage(
        _scene(),
        model="deepseek/deepseek-v4-flash",
        genre=genre,
        tone=tone,
        completion_fn=_completion,
    )

    prompt = captured["messages"][0]["content"]
    assert "one deliberate compositional choice" in prompt
    assert "a subject well off-centre" in prompt
    # docs/decisions/0054: the rule used to ask for this as prose in
    # `camera`, contradicting 0044's "three terms and nothing else" and
    # duplicating blocking. Each part now names its own field.
    assert "never as extra prose in `camera`" in prompt


# docs/decisions/0049 diagnosed a buried conditional losing to a concrete
# rule elsewhere. Two rules still ended with an "unless X is the point"
# hatch -- the stillness one licensed exactly the T-posing 0049 exists to
# stop (docs/playbook/repo-audit-brief.md, finding 1).
# docs/decisions/0054: occlusion moved out of blocking's prose into
# its own field. These assert the move actually happened rather than being
# described -- a second statement of the same rule is the failure mode
# this ADR exists to stop.
def test_staging_parses_occlusion_and_defaults_it_for_older_plans():
    from horror_video_ai.stages.scene_planning import load_scene_plan

    payload = _valid_payload()
    payload["beats"][0]["staging"] = [
        {
            "character_id": payload["characters"][0]["id"],
            "action": "presses a palm flat to the wall",
            "blocking": "right third, a quarter of the frame",
            "occlusion": "the pillar covers all but one shoulder",
        }
    ]
    plan = load_scene_plan(payload)
    assert plan.beats[0].staging[0].occlusion == "the pillar covers all but one shoulder"

    # A plan captured before the field still loads, same allowance
    # `staging` itself carries (docs/decisions/0049).
    del payload["beats"][0]["staging"][0]["occlusion"]
    assert load_scene_plan(payload).beats[0].staging[0].occlusion == ""


# docs/decisions/0059: `frame_position` became `blocking` + `size_in_frame`.
# Archived runs are replayed by --fixture and --video-gen-from, so a plan
# saved before the split has to keep loading rather than becoming
# unreadable.
def test_staging_reads_a_pre_0059_frame_position_into_blocking():
    from horror_video_ai.stages.scene_planning import load_scene_plan

    payload = _valid_payload()
    payload["beats"][0]["staging"] = [
        {
            "character_id": payload["characters"][0]["id"],
            "action": "presses a palm flat to the wall",
            "frame_position": "right third, a quarter of the frame",
            "occlusion": "the pillar covers all but one shoulder",
        }
    ]

    staged = load_scene_plan(payload).beats[0].staging[0]

    assert staged.blocking == "right third, a quarter of the frame"
    # The old field carried both facts in one string, and nothing can
    # separate them after the fact -- so size is empty rather than guessed.
    assert staged.size_in_frame == ""
    assert staged.occlusion == "the pillar covers all but one shoulder"


def test_staging_parses_size_in_frame_and_defaults_it_for_older_plans():
    from horror_video_ai.stages.scene_planning import load_scene_plan

    payload = _valid_payload()
    payload["beats"][0]["staging"] = [
        {
            "character_id": payload["characters"][0]["id"],
            "action": "presses a palm flat to the wall",
            "blocking": "directly between her and the camera, near enough to touch her",
            "size_in_frame": "roughly a third of the image",
        }
    ]

    staged = load_scene_plan(payload).beats[0].staging[0]
    assert staged.size_in_frame == "roughly a third of the image"

    del payload["beats"][0]["staging"][0]["size_in_frame"]
    assert load_scene_plan(payload).beats[0].staging[0].size_in_frame == ""


# docs/decisions/0060: the threat rule used to offer "a shape at the edge
# of vision", and a plan-only run took it -- putting the figure "far down
# the aisle beyond her", the shot that scored 1 in 22 measured images.
def test_threat_rule_asks_for_occlusion_rather_than_distance():
    captured = {}

    def _completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(_valid_payload())))]
        )

    run_scene_planning_stage(
        _scene(),
        model="deepseek/deepseek-v4-flash",
        genre="horror",
        tone="dread",
        completion_fn=_completion,
    )

    prompt = captured["messages"][0]["content"]
    assert "made ominous by OCCLUSION, not by distance" in prompt
    assert "Put it CLOSE and HIDDEN instead" in prompt
    # and the option that produced the unrenderable shot is gone rather
    # than merely counterbalanced by the new rule
    assert "a shape at the edge of vision" not in prompt


# docs/decisions/0061: the interaction rule used to be satisfied by the
# VICTIM reacting, which left the threat free to act on scenery -- a real
# run gave it three beats of hands on upholstery and read as two people
# sitting in a car together.
# docs/decisions/0062: the owner named both of these as the difference
# between a near-miss beat and an effective one.
def test_threat_rule_requires_concealment_to_change_when_noticed():
    captured = {}

    def _completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(_valid_payload())))]
        )

    run_scene_planning_stage(
        _scene(),
        model="deepseek/deepseek-v4-flash",
        genre="horror",
        tone="dread",
        completion_fn=_completion,
    )

    prompt = captured["messages"][0]["content"]
    assert "the threat's CONCEALMENT must change" in prompt
    assert "the moment \\\nit is noticed is the hinge" in prompt or "is the hinge" in prompt
    assert "visibly smaller `occlusion` than the one before" in prompt


def test_interaction_rule_binds_the_non_focal_character_not_just_any_entry():
    captured = {}

    def _completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(_valid_payload())))]
        )

    run_scene_planning_stage(
        _scene(),
        model="deepseek/deepseek-v4-flash",
        genre="horror",
        tone="dread",
        completion_fn=_completion,
    )

    prompt = captured["messages"][0]["content"]
    assert "NON-FOCAL character's own `action` must take another character as its OBJECT" in prompt
    assert "An action performed on scenery is not enough" in prompt
    # the victim's reaction is still required, but explicitly does not
    # discharge the rule on its own
    assert "that reaction ALONE does not satisfy the rule above" in prompt


def test_blocking_rule_forbids_stating_which_way_a_character_faces():
    captured = {}

    def _completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(_valid_payload())))]
        )

    run_scene_planning_stage(
        _scene(),
        model="deepseek/deepseek-v4-flash",
        genre="horror",
        tone="dread",
        completion_fn=_completion,
    )

    prompt = captured["messages"][0]["content"]
    assert "Do NOT state which way they FACE here" in prompt
    assert "belongs in `action`" in prompt


def test_planning_prompt_routes_each_compositional_part_to_its_own_field():
    captured = {}

    def _completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(_valid_payload())))]
        )

    run_scene_planning_stage(
        _scene(),
        model="deepseek/deepseek-v4-flash",
        genre="horror",
        tone="dread",
        completion_fn=_completion,
    )

    prompt = captured["messages"][0]["content"]
    # occlusion is asked for as its own field, in the schema and the rules
    assert '"occlusion"' in prompt
    assert "`blocking` is WHERE THEY" in prompt
    assert "`size_in_frame` is HOW BIG THEY READ" in prompt
    assert "`occlusion` is WHAT HIDES" in prompt
    # the frozen-instant rule, which process verbs kept defeating
    assert "the frozen instant, not the movement through it" in prompt
    # and the old instruction is gone rather than duplicated: nothing may
    # still tell the planner to put occlusion inside blocking
    assert "In `blocking` state concretely" not in prompt


def test_planning_rules_carry_no_unless_its_the_point_escape_hatches():
    captured = {}

    def _completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(_valid_payload())))]
        )

    run_scene_planning_stage(
        _scene(),
        model="deepseek/deepseek-v4-flash",
        genre="horror",
        tone="dread",
        completion_fn=_completion,
    )

    prompt = captured["messages"][0]["content"]
    assert "unless stillness is specifically the point" not in prompt
    assert "unless centring them is the point" not in prompt


def test_beat_renders_every_named_character_and_says_all_are_present():
    from horror_video_ai.stages.previz import _build_beat_prompt

    woman = Character(
        id="w1", face_build="mid-forties, slender", hair="ash-blonde shag",
        wardrobe_signature="grey car coat", wardrobe_flexible="coat open",
        distinguishing_detail="scar through right eyebrow",
    )
    figure = Character(
        id="fig1", face_build="late sixties, heavy-set", hair="grey stubble under a cap",
        wardrobe_signature="olive work jacket", wardrobe_flexible="collar turned up",
        distinguishing_detail="brass keyring",
    )
    beat = _beat(subject="w1", staging=[_staging("w1"), _staging("fig1")])

    prompt = _build_beat_prompt(beat, characters=[woman, figure], location=None)

    assert "CHARACTER w1:" in prompt
    assert "CHARACTER fig1:" in prompt
    assert "ALL OF THESE CHARACTERS ARE IN THIS SHOT: w1, fig1" in prompt


def test_check_beat_character_references_rejects_an_unknown_id():
    known = [Character(id="w1", face_build="x", hair="x", wardrobe_signature="x",
                       wardrobe_flexible="x", distinguishing_detail="x")]
    beat = _beat(subject="w1", staging=[_staging("w1"), _staging("ghost")])
    with pytest.raises(ScenePlanningError, match="don't match any defined character"):
        check_beat_character_references([beat], known)


def test_an_archived_beat_without_staging_falls_back_to_the_first_character():
    """Reading a plan off disk stays lenient: a pre-ADR-0041 beat still
    produces a usable single-character beat, which is what --fixture,
    --video-gen-from and the eval harness replay (docs/decisions/0065)."""
    from horror_video_ai.stages.scene_planning import load_scene_plan

    payload = _valid_payload()
    payload["beats"][0].pop("staging", None)

    plan = load_scene_plan(payload)

    assert [s.character_id for s in plan.beats[0].staging] == [plan.characters[0].id]


def test_a_live_beat_without_staging_is_refused_rather_than_silently_downgraded():
    """The same input from a *model* is a planner that ignored the prompt,
    not an old file. Accepting it spent a paid image on a beat whose prompt
    had silently lost its STANDS:/SIZE IN FRAME: lines, with nothing said
    (docs/decisions/0065)."""
    payload = _valid_payload()
    payload["beats"][0].pop("staging", None)

    def _completion(**kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
        )

    with pytest.raises(ScenePlanningError, match="no 'staging' entries"):
        run_scene_planning_stage(_scene(), completion_fn=_completion)


def test_a_live_staging_entry_without_size_in_frame_is_refused():
    """docs/decisions/0059: world placement without size_in_frame never
    once rendered the right depth ordering (0/10), with it never failed
    (14/14). An empty one drops the SIZE IN FRAME: line entirely."""
    payload = _valid_payload()
    del payload["beats"][0]["staging"][0]["size_in_frame"]

    def _completion(**kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
        )

    with pytest.raises(ScenePlanningError, match="no 'size_in_frame'"):
        run_scene_planning_stage(_scene(), completion_fn=_completion)


def test_an_archived_staging_entry_without_size_in_frame_still_loads():
    from horror_video_ai.stages.scene_planning import load_scene_plan

    payload = _valid_payload()
    del payload["beats"][0]["staging"][0]["size_in_frame"]

    assert load_scene_plan(payload).beats[0].staging[0].size_in_frame == ""


def test_planning_prompt_tells_the_planner_to_list_an_embodied_threat():
    """A real run defined a stalking figure, generated its reference image,
    mentioned it once in a lighting field, and produced four beats with no
    antagonist in any of them."""
    captured = {}

    def _completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(_valid_payload())))]
        )

    run_scene_planning_stage(
        _scene(), genre="horror", tone="dread", completion_fn=_completion
    )
    prompt = captured["messages"][0]["content"]
    assert "GIVE IT ITS OWN `staging` ENTRY" in prompt
    assert "EVERY character visible in" in prompt


# --- identity fields describe appearance, never behaviour (ADR 0042) ---


def _char(**overrides) -> Character:
    fields_ = {
        "id": "fig", "face_build": "gaunt, elongated face", "hair": "no visible hair",
        "wardrobe_signature": "charcoal overcoat", "wardrobe_flexible": "collar up or flat",
        "distinguishing_detail": "a thin white scar through one eyebrow",
    }
    fields_.update(overrides)
    return Character(**fields_)


@pytest.mark.parametrize(
    "overrides",
    [
        # The real failure: a stalking figure's pose written into its
        # identity, then emitted into all four beat prompts.
        {"distinguishing_detail": "Stands perfectly still with both arms straight at its "
                                  "sides and its head tilted slightly to one shoulder."},
        {"face_build": "Sits hunched over whenever indoors"},
        {"hair": "Holds a lantern that lights it from below"},
    ],
)
def test_pose_in_an_identity_field_warns(overrides):
    assert identity_field_pose_warnings([_char(**overrides)])


@pytest.mark.parametrize(
    "overrides",
    [
        {"distinguishing_detail": "a thin white scar through the right eyebrow"},
        {"face_build": "softly rounded face with freckles across the nose"},
        {"wardrobe_signature": "a wool coat with a standing collar"},
        {"hair": "buzzed very short, sitting close to the scalp"},
    ],
)
def test_genuine_appearance_descriptions_are_allowed(overrides):
    assert identity_field_pose_warnings([_char(**overrides)]) == []


@pytest.mark.parametrize(
    "detail",
    [
        "Stands perfectly still with both arms straight at its sides.",
        # The exact string from the real run that this ADR is about: a
        # description of height the heuristic reads as a posture verb.
        (
            "stands a full head taller than an ordinary adult, with wrists so "
            "thin the glove leather hangs loose and bunched at the cuff"
        ),
    ],
)
def test_a_posed_identity_field_does_not_fail_the_parse(detail):
    """The check warns; it must never kill a run after a paid planning
    call and before the human can edit anything (docs/decisions/0048)."""
    payload = _valid_payload()
    payload["characters"][0]["distinguishing_detail"] = detail
    plan = _parse_scene_plan(json.dumps(payload))
    assert plan.characters[0].distinguishing_detail == detail


def test_planning_prompt_tells_the_planner_identity_fields_are_appearance_only():
    captured = {}

    def _completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(_valid_payload())))]
        )

    run_scene_planning_stage(_scene(), completion_fn=_completion)
    prompt = captured["messages"][0]["content"]
    assert "never what they are doing" in prompt
    assert "an instruction the character can never escape" in prompt


# --- camera specified at a granularity image models act on (ADR 0044) ---


def test_planning_prompt_asks_for_camera_in_model_actionable_terms():
    """Real run: the planner specified "camera beside the boot of the
    neighbouring parked car in bay 15" and "a ceiling corner at the west
    end", and the image model produced eye-level shots three attempts
    running. The CAMERA field already said the right thing; the model does
    not place a virtual camera in a floor plan."""
    captured = {}

    def _completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(_valid_payload())))]
        )

    run_scene_planning_stage(_scene(), completion_fn=_completion)
    prompt = captured["messages"][0]["content"]

    assert "SHOT SIZE" in prompt
    assert "CAMERA HEIGHT" in prompt
    assert "SUBJECT ORIENTATION" in prompt
    assert "Do NOT specify where the camera stands in the world" in prompt
    # The old coverage rule demanded exactly what the model ignores.
    assert "move the camera to a different part of the room" not in prompt


def test_planning_prompt_asks_for_screen_direction_not_camera_side():
    """The 180-degree rule's enforceable half is which way the subject
    faces in frame; which side of an imaginary line the camera sits on is
    not something an image model can honour."""
    captured = {}

    def _completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(_valid_payload())))]
        )

    run_scene_planning_stage(_scene(), completion_fn=_completion)
    prompt = captured["messages"][0]["content"]

    assert "SCREEN DIRECTION" in prompt
    assert "which side of an imaginary line the camera sits on is not" in prompt


# --- docs/decisions/0049: per-character staging -----------------------------


def test_each_characters_action_sits_in_that_characters_own_prompt_block():
    """A single shared ACTION paragraph gave the focal character the verb
    and left everyone else a static pose. Binding the verb to the person
    is the whole point of the schema change (docs/decisions/0049)."""
    from horror_video_ai.stages.previz import _build_beat_prompt

    woman = Character(id="w1", face_build="early twenties", hair="blonde bun",
                      wardrobe_signature="green puffer", wardrobe_flexible="hood up",
                      distinguishing_detail="birthmark on the jaw")
    figure = Character(id="fig1", face_build="very tall, gaunt", hair="shaved scalp",
                       wardrobe_signature="black rain jacket", wardrobe_flexible="hood up",
                       distinguishing_detail="scar down the throat")
    beat = _beat(
        subject="w1",
        staging=[
            _staging("w1", action="jams the key at the lock", blocking="right of frame"),
            _staging("fig1", action="reaches over the car roof toward her",
                     blocking="far left edge, a quarter of the frame"),
        ],
    )

    prompt = _build_beat_prompt(beat, characters=[woman, figure], location=None)

    w_block = prompt.split("CHARACTER fig1:")[0]
    f_block = "CHARACTER fig1:" + prompt.split("CHARACTER fig1:")[1]
    assert "jams the key at the lock" in w_block
    assert "jams the key at the lock" not in f_block
    assert "reaches over the car roof toward her" in f_block
    assert "far left edge, a quarter of the frame" in f_block


def test_a_multi_character_beat_demands_the_characters_react_to_each_other():
    """The failure this addresses: "two independently-posed figures that
    happen to share a frame" in all four beats of a real run."""
    from horror_video_ai.stages.previz import _build_beat_prompt

    chars = [
        Character(id=cid, face_build="x", hair="x", wardrobe_signature="x",
                  wardrobe_flexible="x", distinguishing_detail="x")
        for cid in ("w1", "fig1")
    ]
    two = _build_beat_prompt(
        _beat(staging=[_staging("w1"), _staging("fig1")]), characters=chars, location=None
    )
    one = _build_beat_prompt(
        _beat(staging=[_staging("w1")]), characters=chars[:1], location=None
    )

    assert "must react to each other" in two
    assert "must react to each other" not in one


def test_staging_the_same_character_twice_is_rejected():
    known = [Character(id="w1", face_build="x", hair="x", wardrobe_signature="x",
                       wardrobe_flexible="x", distinguishing_detail="x")]
    beat = _beat(staging=[_staging("w1"), _staging("w1", action="turns away")])
    with pytest.raises(ScenePlanningError, match="stages the same character twice"):
        check_beat_character_references([beat], known)


def test_a_staging_entry_missing_its_action_is_rejected():
    payload = _valid_payload()
    payload["beats"][0]["staging"][0].pop("action")
    with pytest.raises(ScenePlanningError, match="A staging entry"):
        _parse_scene_plan(json.dumps(payload))


@pytest.mark.parametrize(
    "phrase",
    [
        # Each rule the run's failures map onto, asserted so a prompt edit
        # can't quietly drop one (docs/decisions/0049).
        "are states, not actions",
        "must take another character as its OBJECT",
        "State WHERE THE EYES ARE POINTED",

        "must show in the BODY",
        "Never encode",
        "the field that makes depth render",
    ],
)
def test_planning_prompt_carries_the_staging_rules(phrase):
    captured = {}

    def _completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(_valid_payload())))]
        )

    run_scene_planning_stage(_scene(), completion_fn=_completion)
    assert phrase in captured["messages"][0]["content"]


# --- docs/decisions/0071: contact, visibility, intensity, complexity ---


def test_a_live_beat_without_intensity_is_refused():
    """Strict parsing of a model response, same reasoning as size_in_frame
    (docs/decisions/0065): a beat with no intensity silently loses its
    INTENSITY line and the render comes back static, after the human has
    already paid for it."""
    payload = _valid_payload()
    payload["beats"][0].pop("intensity")
    with pytest.raises(ScenePlanningError, match="no 'intensity'"):
        _parse_scene_plan(json.dumps(payload))


def test_an_archived_plan_without_intensity_still_loads():
    """--fixture and --video-gen-from replay plans written before the
    field existed; they must keep loading (docs/decisions/0065)."""
    payload = _valid_payload()
    payload["beats"][0].pop("intensity")
    plan = load_scene_plan(payload)
    assert plan.beats[0].intensity == ""


def test_contact_is_optional_and_round_trips():
    payload = _valid_payload()
    payload["beats"][0]["contact"] = "its hand closes round her forearm at frame centre"
    plan = _parse_scene_plan(json.dumps(payload))
    assert plan.beats[0].contact == "its hand closes round her forearm at frame centre"

    payload["beats"][0].pop("contact")
    assert _parse_scene_plan(json.dumps(payload)).beats[0].contact == ""


def test_facing_is_optional_and_round_trips():
    """Optional both ways: a one-character beat has no pair to aim, and an
    archived plan predates the field (docs/decisions/0072)."""
    payload = _valid_payload()
    payload["beats"][0]["facing"] = "he is turned three quarters toward her across the hatch"
    plan = _parse_scene_plan(json.dumps(payload))
    assert plan.beats[0].facing == "he is turned three quarters toward her across the hatch"

    payload["beats"][0].pop("facing")
    assert _parse_scene_plan(json.dumps(payload)).beats[0].facing == ""
    assert load_scene_plan(payload).beats[0].facing == ""


def test_a_reflection_written_into_facing_is_warned_about():
    """`facing` is free text describing two bodies, so it can smuggle in a
    reflected person exactly as `contact` can."""
    from horror_video_ai.stages.scene_planning import beat_visibility_warnings

    payload = _valid_payload()
    payload["beats"][0]["facing"] = "she is square to his reflection in the window glass"
    warnings = beat_visibility_warnings(_parse_scene_plan(json.dumps(payload)).beats)
    assert any("reflection" in w for w in warnings)


def test_staging_a_character_the_camera_cannot_see_is_refused():
    """The beat-2 failure in docs/decisions/0071: a threat placed behind a
    total occluder and still given a share of the frame. The image model
    settles the contradiction by drawing it somewhere arbitrary, and no
    human correction can then move it, because the plan never named a
    place for it."""
    payload = _valid_payload()
    payload["beats"][0]["staging"][0]["occlusion"] = (
        "the catwalk's floor grating covers it completely, not visible from here"
    )
    with pytest.raises(ScenePlanningError, match="cannot see"):
        _parse_scene_plan(json.dumps(payload))


def test_partial_occlusion_naming_what_survives_is_still_allowed():
    """Threat presence in this project runs entirely on partial occlusion,
    so the check must not catch it."""
    payload = _valid_payload()
    payload["beats"][0]["staging"][0]["occlusion"] = (
        "the pillar's near face covers everything but one shoulder and half her head"
    )
    plan = _parse_scene_plan(json.dumps(payload))
    assert plan.beats[0].staging[0].occlusion.startswith("the pillar")


def test_a_reflected_character_is_warned_about():
    beat = _beat(
        staging=[_staging("influencer")],
        lighting="her reflection stares back out of the black glass",
    )
    warnings = beat_visibility_warnings([beat])
    assert any("reflect" in w.lower() for w in warnings)
    assert any("second copy" in w for w in warnings)


def test_a_character_hidden_behind_a_solid_surface_is_warned_about():
    beat = _beat(
        staging=[
            Staging(
                character_id="bearer",
                action="lifts the lantern toward her",
                blocking="a flight below the catwalk",
                occlusion="the catwalk's floor grating hides all but the lantern",
            )
        ]
    )
    warnings = beat_visibility_warnings([beat])
    assert any("different space" in w for w in warnings)


def test_a_clean_beat_produces_no_visibility_warnings():
    assert beat_visibility_warnings([_beat(staging=[_staging("influencer")])]) == []


@pytest.mark.parametrize(
    "phrase",
    [
        # docs/decisions/0071, one per failure the rules were written for.
        "that beat's `contact` field",
        "as ONE shape seen from the camera",
        "Only stage characters the camera can actually SEE",
        "Every beat needs an `intensity`",
        "must CHANGE across the scene",
        "Budget each beat's complexity",
        "One beat is ONE SPACE",
        "Never put a CHARACTER'S REFLECTION",
        "One dominant light source per beat",
        # docs/decisions/0072's unconditional rules, one per failure each
        # was written for. The two that live in the threat rule are
        # checked separately, below, since that block is genre-gated.
        "fill in that beat's `facing` field",
        "Do this in EVERY `staging` entry too",
        "An occluder does not have to be solid",
        "Let the LOCATION escalate too",
    ],
)
def test_planning_prompt_carries_the_0071_rules(phrase):
    captured = {}

    def _completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(_valid_payload())))]
        )

    run_scene_planning_stage(_scene(), completion_fn=_completion)
    assert phrase in captured["messages"][0]["content"]


def test_planning_prompt_asks_for_contact_and_intensity_in_its_json_shape():
    """A rule the response shape has no slot for is a rule the planner
    cannot obey."""
    captured = {}

    def _completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(_valid_payload())))]
        )

    run_scene_planning_stage(_scene(), completion_fn=_completion)
    prompt = captured["messages"][0]["content"]
    assert '"contact":' in prompt
    assert '"facing":' in prompt
    assert '"intensity":' in prompt


# docs/decisions/0072: the owner's review of a real four-beat run found
# the threat rendering as puzzled rather than hunting, and the protagonist
# merely concerned while a monster stood a pace away in open view. Both
# rules belong to the genre-gated threat block.
@pytest.mark.parametrize(
    "phrase",
    [
        "Give the threat a FACE as well",
        "an embodied threat routinely gets pure mechanics and no face",
        "TOP of her fear arc",
        "written as panic rather than concern",
        # the threat's own occluder list is no longer solid-only
        "the fog, smoke or unlit dark the location already has",
    ],
)
def test_threat_rule_gives_the_threat_a_face_and_the_victim_a_ceiling(phrase):
    captured = {}

    def _completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(_valid_payload())))]
        )

    run_scene_planning_stage(
        _scene(),
        model="deepseek/deepseek-v4-flash",
        genre="horror",
        tone="dread",
        completion_fn=_completion,
    )

    assert phrase in captured["messages"][0]["content"]
