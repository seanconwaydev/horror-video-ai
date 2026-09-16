import json
import random
from types import SimpleNamespace

import pytest

from historical_video_ai.config import get_stage_model
from historical_video_ai.stages.fact_check import FactCheckResult
from historical_video_ai.stages.research import Claim, FactSheet
from historical_video_ai.stages.scene_planning import (
    Beat,
    Character,
    ScenePlanningError,
    _random_character_trait_hint,
    _resolve_composition_mode,
    _resolve_threat_mode,
    check_beat_character_references,
    check_cinematography_is_not_a_style_claim,
    check_identity_fields_describe_appearance,
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
                "cinematography": "35mm, shallow depth of field",
                "audio": "street ambience",
                "duration_seconds": "3",
            }
        ],
    }
    payload.update(overrides)
    return payload


def _beat(**overrides) -> Beat:
    fields = {
        "location_id": "street",
        "subject": "The influencer",
        "action": "checks her phone",
        "camera": "medium shot",
        "lighting": "bright midday sun",
        "cinematography": "35mm, shallow depth of field",
        "audio": "street ambience",
        "duration_seconds": "3",
    }
    fields.update(overrides)
    return Beat(**fields)


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


def test_run_scene_planning_stage_includes_genre_and_tone_when_ungrounded():
    # docs/decisions/0035
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
        _fact_check_result(), model="deepseek/deepseek-v4-flash", completion_fn=_completion
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
        _fact_check_result(), model="deepseek/deepseek-v4-flash", completion_fn=_completion
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
        _fact_check_result(), model="deepseek/deepseek-v4-flash", completion_fn=_completion
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
        _fact_check_result(),
        model="deepseek/deepseek-v4-flash",
        completion_fn=_completion,
        rng=random.Random(42),
    )

    prompt = captured["messages"][0]["content"]
    expected_hint = _random_character_trait_hint(random.Random(42))
    assert "Vary each Character's physical appearance meaningfully" in prompt
    assert expected_hint in prompt


def test_run_scene_planning_stage_omits_genre_when_grounded():
    # "historical" is always the genre when grounded -- redundant with the
    # preamble's own framing, so it's not echoed.
    captured = {}

    def _completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(_valid_payload())))]
        )

    run_scene_planning_stage(
        _fact_check_result(),
        model="deepseek/deepseek-v4-flash",
        requires_grounding=True,
        genre="historical",
        tone="sincere",
        completion_fn=_completion,
    )

    prompt = captured["messages"][0]["content"]
    assert "Genre:" not in prompt
    assert "Tone: sincere." in prompt


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
        _fact_check_result(),
        model="deepseek/deepseek-v4-flash",
        requires_grounding=False,
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
        _fact_check_result(),
        model="deepseek/deepseek-v4-flash",
        requires_grounding=False,
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
        _fact_check_result(),
        model="deepseek/deepseek-v4-flash",
        requires_grounding=False,
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
        _fact_check_result(),
        model="deepseek/deepseek-v4-flash",
        requires_grounding=True,
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
        _fact_check_result(),
        model="deepseek/deepseek-v4-flash",
        requires_grounding=True,
        genre="historical",
        completion_fn=_completion,
    )

    prompt = captured["messages"][0]["content"]
    assert 'the animation principle of "staging"' in prompt
    assert "Commit fully to a strange, asymmetric, or chaotic composition" not in prompt


# --- cinematography must not claim an art style (docs/decisions/0039) ---


@pytest.mark.parametrize(
    "text",
    [
        "photorealistic, 35mm",
        "shot like a CARTOON",
        "cel-shaded look, shallow depth of field",
        "35mm, deep focus, fine grain, photograph-like grade",
    ],
)
def test_check_cinematography_rejects_art_style_claims(text):
    """The planning prompt already forbids this and a real run did it
    anyway, which is why it's a parse failure now rather than an
    instruction (docs/decisions/0039)."""
    beat = _beat(cinematography=text)
    with pytest.raises(ScenePlanningError, match="art-style claim"):
        check_cinematography_is_not_a_style_claim([beat])


@pytest.mark.parametrize(
    "text",
    [
        "35mm, shallow depth of field",
        "wide lens, heavy grain, cold blue grade",
        "long lens, compressed background, warm highlights",
    ],
)
def test_check_cinematography_allows_genuine_lens_and_grade_notes(text):
    check_cinematography_is_not_a_style_claim([_beat(cinematography=text)])


def test_parse_scene_plan_rejects_a_style_claim_in_cinematography():
    payload = _valid_payload()
    payload["beats"][0]["cinematography"] = "photorealistic, 35mm"

    def _completion(**kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
        )

    with pytest.raises(ScenePlanningError, match="art-style claim"):
        run_scene_planning_stage(_fact_check_result(), completion_fn=_completion)


# --- beats must be able to name more than one character (ADR 0041) ---


def test_beat_renders_every_named_character_and_says_all_are_present():
    from historical_video_ai.stages.previz import _build_beat_prompt

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
    beat = _beat(subject="w1", character_ids=["w1", "fig1"])

    prompt = _build_beat_prompt(beat, characters=[woman, figure], location=None)

    assert "CHARACTER w1:" in prompt
    assert "CHARACTER fig1:" in prompt
    assert "ALL OF THESE CHARACTERS ARE IN THIS SHOT: w1, fig1" in prompt


def test_check_beat_character_references_rejects_an_unknown_id():
    known = [Character(id="w1", face_build="x", hair="x", wardrobe_signature="x",
                       wardrobe_flexible="x", distinguishing_detail="x")]
    beat = _beat(subject="w1", character_ids=["w1", "ghost"])
    with pytest.raises(ScenePlanningError, match="don't match any defined character"):
        check_beat_character_references([beat], known)


def test_a_beat_without_character_ids_falls_back_to_the_first_character():
    """A planning model that ignores the new field still produces a usable
    single-character beat -- which is what every beat was before ADR 0041."""
    payload = _valid_payload()
    payload["beats"][0].pop("character_ids", None)

    def _completion(**kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
        )

    plan = run_scene_planning_stage(_fact_check_result(), completion_fn=_completion)
    assert plan.beats[0].character_ids == [plan.characters[0].id]


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
        _fact_check_result(), genre="horror", tone="dread", completion_fn=_completion
    )
    prompt = captured["messages"][0]["content"]
    assert "LIST ITS ID in `character_ids`" in prompt
    assert "EVERY character visible in that shot" in prompt


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
def test_pose_in_an_identity_field_is_rejected(overrides):
    with pytest.raises(ScenePlanningError, match="pose or behaviour"):
        check_identity_fields_describe_appearance([_char(**overrides)])


@pytest.mark.parametrize(
    "overrides",
    [
        {"distinguishing_detail": "a thin white scar through the right eyebrow"},
        {"face_build": "softly rounded face with freckles across the nose"},
        # "standing collar" is a garment, not a pose -- the leading-verb
        # check is anchored to the start of the field for this reason.
        {"wardrobe_signature": "a wool coat with a standing collar"},
        {"hair": "buzzed very short, sitting close to the scalp"},
    ],
)
def test_genuine_appearance_descriptions_are_allowed(overrides):
    check_identity_fields_describe_appearance([_char(**overrides)])


def test_planning_prompt_tells_the_planner_identity_fields_are_appearance_only():
    captured = {}

    def _completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(_valid_payload())))]
        )

    run_scene_planning_stage(_fact_check_result(), completion_fn=_completion)
    prompt = captured["messages"][0]["content"]
    assert "never what they are doing" in prompt
    assert "an instruction the character can never escape" in prompt
