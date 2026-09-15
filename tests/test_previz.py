import dataclasses
import json
from types import SimpleNamespace

import litellm
import pytest

from historical_video_ai.config import get_stage_model
from historical_video_ai.stages.fact_check import ClaimFlag, FactCheckResult, PremiseConflict
from historical_video_ai.stages.previz import (
    PrevizError,
    build_character_sheet_prompt,
    build_location_reference_prompt,
    run_beat_image_stage,
    run_previz_review_stage,
    run_previz_stage,
    run_reference_image_stage,
)
from historical_video_ai.stages.research import Claim, FactSheet
from historical_video_ai.stages.scene_planning import Beat, Character, Location

# A tiny valid 1x1 PNG, base64-encoded, so tests never touch a real API or
# write anything that isn't a real (if trivial) image file.
_TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _fact_check_result(flags=None) -> FactCheckResult:
    fact_sheet = FactSheet(
        time="December 1903",
        place="Kitty Hawk, North Carolina",
        description="watches a flying machine lift off from the dunes.",
        claims=[
            Claim(text="The dunes at Kitty Hawk were largely undeveloped in 1903.", source="NPS"),
            Claim(text="This claim will be contradicted.", source="somewhere"),
        ],
    )
    return FactCheckResult(fact_sheet=fact_sheet, flags=flags or [])


def _fake_image_fn(b64_json: str):
    def _image_fn(**kwargs):
        return SimpleNamespace(data=[SimpleNamespace(b64_json=b64_json)])

    return _image_fn


def test_run_previz_stage_writes_image_and_returns_prompt(tmp_path):
    result = run_previz_stage(
        _fact_check_result(),
        model="gemini/gemini-2.5-flash-image",
        image_fn=_fake_image_fn(_TINY_PNG_B64),
        output_dir=tmp_path,
    )

    assert result.image_path.exists()
    assert result.image_path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic bytes
    assert "Kitty Hawk" in result.prompt_used


def test_run_previz_stage_requests_a_video_aspect_ratio_hint(tmp_path):
    # See docs/decisions/0011: requests an aspect ratio close to Sora-2's
    # target size so video_generation only needs a barely-perceptible
    # resize, not a large content-losing crop.
    captured = {}

    def _image_fn(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(data=[SimpleNamespace(b64_json=_TINY_PNG_B64)])

    run_previz_stage(
        _fact_check_result(),
        model="gemini/gemini-2.5-flash-image",
        image_fn=_image_fn,
        output_dir=tmp_path,
    )

    assert captured["size"] == "720x1280"


def test_run_previz_stage_includes_all_fact_sheet_claims_unfiltered(tmp_path):
    # previz trusts fact_sheet.claims as already resolved -- flags no
    # longer cause any auto-exclusion here (see cli.py's _resolve_flags,
    # which is where a human now decides to accept/cut/soften a flagged
    # claim before it ever reaches this stage).
    flags = [
        ClaimFlag(
            claim_text="This claim will be contradicted.",
            concern="Doesn't hold up.",
            severity="contradicted",
        )
    ]

    result = run_previz_stage(
        _fact_check_result(flags),
        model="gemini/gemini-2.5-flash-image",
        image_fn=_fake_image_fn(_TINY_PNG_B64),
        output_dir=tmp_path,
    )

    assert "This claim will be contradicted." in result.prompt_used
    assert "undeveloped in 1903" in result.prompt_used


def test_run_previz_stage_prompt_warns_against_claims_from_other_eras(tmp_path):
    # Regression test: a real run depicting Giza in 1991-1993 included a
    # true, correctly-cited research claim about a *recent* LED lighting
    # upgrade at the pyramids -- with no signal that it didn't apply to the
    # depicted moment, the image model rendered modern wall lamps into the
    # scene three times in a row (all three real reviews rejected it for
    # exactly this anachronism). The prompt must now tell the model claims
    # can describe other eras and only the stated Time should be depicted.
    result = run_previz_stage(
        _fact_check_result(),
        model="gemini/gemini-2.5-flash-image",
        image_fn=_fake_image_fn(_TINY_PNG_B64),
        output_dir=tmp_path,
    )

    assert "December 1903" in result.prompt_used
    assert "other times" in result.prompt_used


def test_run_previz_stage_refuses_unresolved_premise_conflict(tmp_path):
    result_with_conflict = FactCheckResult(
        fact_sheet=_fact_check_result().fact_sheet,
        premise_conflict=PremiseConflict(
            explanation="Nothing like this existed at this time and place.",
            suggested_alternative=None,
        ),
    )

    with pytest.raises(PrevizError, match="historically impossible"):
        run_previz_stage(
            result_with_conflict,
            model="gemini/gemini-2.5-flash-image",
            image_fn=_fake_image_fn(_TINY_PNG_B64),
            output_dir=tmp_path,
        )


def test_run_previz_stage_raises_when_no_image_data(tmp_path):
    def _empty_image_fn(**kwargs):
        return SimpleNamespace(data=[])

    with pytest.raises(PrevizError, match="no image data"):
        run_previz_stage(
            _fact_check_result(),
            model="gemini/gemini-2.5-flash-image",
            image_fn=_empty_image_fn,
            output_dir=tmp_path,
        )


def test_run_previz_stage_hints_at_moderation_for_empty_data_list(tmp_path):
    # A present-but-empty `data` list (a successful call, zero images) is
    # distinct from a malformed response object -- worth a specific,
    # actionable hint rather than a bare "no image data" message, since a
    # real run hit this for a religious-imagery-adjacent prompt with no
    # other error detail available.
    def _empty_image_fn(**kwargs):
        return SimpleNamespace(data=[])

    with pytest.raises(PrevizError, match="silently refused"):
        run_previz_stage(
            _fact_check_result(),
            model="gemini/gemini-2.5-flash-image",
            image_fn=_empty_image_fn,
            output_dir=tmp_path,
        )


def test_run_previz_stage_resolves_model_from_config_when_not_passed(tmp_path):
    captured = {}

    def _image_fn(**kwargs):
        captured["model"] = kwargs["model"]
        return SimpleNamespace(data=[SimpleNamespace(b64_json=_TINY_PNG_B64)])

    run_previz_stage(_fact_check_result(), image_fn=_image_fn, output_dir=tmp_path)

    assert captured["model"] == get_stage_model("previz")


def test_run_previz_stage_retries_on_transient_error_then_succeeds(tmp_path):
    calls = {"n": 0}

    def _flaky_image_fn(**kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise litellm.exceptions.ServiceUnavailableError(
                message="simulated 503", llm_provider="gemini", model="gemini-2.5-flash-image"
            )
        return SimpleNamespace(data=[SimpleNamespace(b64_json=_TINY_PNG_B64)])

    retries_seen = []
    result = run_previz_stage(
        _fact_check_result(),
        image_fn=_flaky_image_fn,
        output_dir=tmp_path,
        sleep_fn=lambda _seconds: None,
        on_transient_retry=lambda n, exc: retries_seen.append((n, type(exc).__name__)),
    )

    assert result.image_path.exists()
    assert calls["n"] == 3
    assert retries_seen == [(1, "ServiceUnavailableError"), (2, "ServiceUnavailableError")]


def test_run_previz_stage_raises_after_exhausting_transient_retries(tmp_path):
    def _always_503(**kwargs):
        raise litellm.exceptions.ServiceUnavailableError(
            message="simulated 503", llm_provider="gemini", model="gemini-2.5-flash-image"
        )

    with pytest.raises(litellm.exceptions.ServiceUnavailableError):
        run_previz_stage(
            _fact_check_result(),
            image_fn=_always_503,
            output_dir=tmp_path,
            sleep_fn=lambda _seconds: None,
        )


def test_run_previz_stage_does_not_retry_non_transient_errors(tmp_path):
    # A real content rejection or bad request will fail the identical way
    # on a retry -- only errors judged transient get retried.
    calls = {"n": 0}

    def _auth_error(**kwargs):
        calls["n"] += 1
        raise litellm.exceptions.AuthenticationError(
            message="bad key", llm_provider="gemini", model="gemini-2.5-flash-image"
        )

    with pytest.raises(litellm.exceptions.AuthenticationError):
        run_previz_stage(
            _fact_check_result(),
            image_fn=_auth_error,
            output_dir=tmp_path,
            sleep_fn=lambda _seconds: None,
        )

    assert calls["n"] == 1


def _write_reference_png(tmp_path, name="reference.png"):
    import base64

    path = tmp_path / name
    path.write_bytes(base64.b64decode(_TINY_PNG_B64))
    return path


def test_run_previz_stage_uses_edit_fn_when_character_reference_given(tmp_path):
    character_ref = _write_reference_png(tmp_path, "character.png")
    captured = {}

    def _edit_fn(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(data=[SimpleNamespace(b64_json=_TINY_PNG_B64)])

    def _exploding_image_fn(**kwargs):
        raise AssertionError("plain image_fn should not be called when a reference is given")

    result = run_previz_stage(
        _fact_check_result(),
        image_fn=_exploding_image_fn,
        edit_fn=_edit_fn,
        character_reference=character_ref,
        output_dir=tmp_path,
    )

    assert result.image_path.exists()
    assert captured["image"] == character_ref.read_bytes()
    assert isinstance(captured["image"], bytes)  # raw bytes, not a Path (litellm's real bug)


def test_run_previz_stage_sends_both_references_as_a_list_when_both_given(tmp_path):
    character_ref = _write_reference_png(tmp_path, "character.png")
    location_ref = _write_reference_png(tmp_path, "location.png")
    captured = {}

    def _edit_fn(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(data=[SimpleNamespace(b64_json=_TINY_PNG_B64)])

    run_previz_stage(
        _fact_check_result(),
        edit_fn=_edit_fn,
        character_reference=character_ref,
        location_reference=location_ref,
        output_dir=tmp_path,
    )

    assert captured["image"] == [character_ref.read_bytes(), location_ref.read_bytes()]


def test_run_previz_stage_retries_edit_fn_on_transient_error_then_succeeds(tmp_path):
    character_ref = _write_reference_png(tmp_path, "character.png")
    calls = {"n": 0}

    def _flaky_edit_fn(**kwargs):
        calls["n"] += 1
        if calls["n"] < 2:
            raise litellm.exceptions.ServiceUnavailableError(
                message="simulated 503", llm_provider="gemini", model="gemini-2.5-flash-image"
            )
        return SimpleNamespace(data=[SimpleNamespace(b64_json=_TINY_PNG_B64)])

    result = run_previz_stage(
        _fact_check_result(),
        edit_fn=_flaky_edit_fn,
        character_reference=character_ref,
        output_dir=tmp_path,
        sleep_fn=lambda _seconds: None,
    )

    assert result.image_path.exists()
    assert calls["n"] == 2


def test_run_reference_image_stage_writes_image_and_returns_prompt(tmp_path):
    result = run_reference_image_stage(
        "A neutral character reference shot.",
        model="gemini/gemini-2.5-flash-image",
        image_fn=_fake_image_fn(_TINY_PNG_B64),
        output_dir=tmp_path,
    )

    assert result.image_path.exists()
    assert result.image_path.name == "reference.png"
    assert result.prompt_used == "A neutral character reference shot."


def test_run_reference_image_stage_raises_when_no_image_data(tmp_path):
    def _empty_image_fn(**kwargs):
        return SimpleNamespace(data=[])

    with pytest.raises(PrevizError, match="no image data"):
        run_reference_image_stage(
            "A neutral character reference shot.",
            image_fn=_empty_image_fn,
            output_dir=tmp_path,
        )


def test_run_reference_image_stage_retries_on_transient_error_then_succeeds(tmp_path):
    calls = {"n": 0}

    def _flaky_image_fn(**kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise litellm.exceptions.ServiceUnavailableError(
                message="simulated 503", llm_provider="gemini", model="gemini-2.5-flash-image"
            )
        return SimpleNamespace(data=[SimpleNamespace(b64_json=_TINY_PNG_B64)])

    result = run_reference_image_stage(
        "A neutral location reference shot.",
        image_fn=_flaky_image_fn,
        output_dir=tmp_path,
        sleep_fn=lambda _seconds: None,
    )

    assert result.image_path.exists()
    assert calls["n"] == 3


def test_run_reference_image_stage_resolves_model_from_config_when_not_passed(tmp_path):
    captured = {}

    def _image_fn(**kwargs):
        captured["model"] = kwargs["model"]
        return SimpleNamespace(data=[SimpleNamespace(b64_json=_TINY_PNG_B64)])

    run_reference_image_stage("A neutral reference shot.", image_fn=_image_fn, output_dir=tmp_path)

    assert captured["model"] == get_stage_model("previz")


def _character() -> Character:
    return Character(
        id="influencer",
        face_build="young woman, mid-20s",
        hair="light brown wavy",
        wardrobe_signature="white crop top, gray leggings",
        wardrobe_flexible="accessories may vary",
        distinguishing_detail="a glowing phone",
    )


def _location() -> Location:
    return Location(
        id="street",
        architecture="stone-paved Pompeii street",
        fixed_props="an archway entrance",
        ambient_light="bright midday sun",
    )


def _beat() -> Beat:
    return Beat(
        location_id="street",
        subject="The influencer",
        action="checks her phone, puzzled",
        camera="medium shot, three-quarter angle",
        lighting="bright midday sun",
        style="photorealistic",
        audio="street ambience",
        duration_seconds="3",
    )


def test_build_character_sheet_prompt_includes_all_character_fields():
    prompt = build_character_sheet_prompt(_character())
    assert "light brown wavy" in prompt
    assert "white crop top, gray leggings" in prompt
    assert "a glowing phone" in prompt
    assert "reference sheet, not a story moment" in prompt


def test_build_location_reference_prompt_includes_all_location_fields():
    prompt = build_location_reference_prompt(_location())
    assert "stone-paved Pompeii street" in prompt
    assert "an archway entrance" in prompt
    assert "location reference, not a character shot" in prompt


def test_build_character_sheet_prompt_defaults_to_photorealistic():
    # docs/decisions/0033: single authoritative style source.
    prompt = build_character_sheet_prompt(_character())
    assert "Photorealistic" in prompt
    assert "NOT 3D-rendered" in prompt


def test_build_character_sheet_prompt_honors_stylized_style():
    prompt = build_character_sheet_prompt(_character(), style="stylized")
    assert "stylized/cartoon" in prompt
    assert "Explicitly NOT photorealistic" in prompt


def test_build_character_sheet_prompt_honors_semi_realistic_style():
    prompt = build_character_sheet_prompt(_character(), style="semi-realistic")
    assert "Pixar/Disney" in prompt


def test_build_location_reference_prompt_honors_style():
    prompt = build_location_reference_prompt(_location(), style="stylized")
    assert "stylized/cartoon" in prompt


def test_build_character_sheet_prompt_raises_on_unknown_style():
    with pytest.raises(PrevizError, match="Unknown style"):
        build_character_sheet_prompt(_character(), style="watercolor")


def test_run_beat_image_stage_writes_image_and_prompt_includes_beat_fields(tmp_path):
    result = run_beat_image_stage(
        _beat(),
        character=_character(),
        location=_location(),
        model="gemini/gemini-2.5-flash-image",
        image_fn=_fake_image_fn(_TINY_PNG_B64),
        output_dir=tmp_path,
    )

    assert result.image_path.exists()
    assert "checks her phone, puzzled" in result.prompt_used
    assert "stone-paved Pompeii street" in result.prompt_used
    assert "light brown wavy" in result.prompt_used


def test_run_beat_image_stage_uses_style_as_overriding_requirement(tmp_path):
    # docs/decisions/0033: beat.style is kept (cinematography notes), but
    # the run's authoritative style always appears too, as an override.
    result = run_beat_image_stage(
        _beat(),
        character=_character(),
        location=_location(),
        style="stylized",
        image_fn=_fake_image_fn(_TINY_PNG_B64),
        output_dir=tmp_path,
    )

    assert "photorealistic" in result.prompt_used  # beat.style's own text, unchanged
    assert "OVERRIDING STYLE REQUIREMENT" in result.prompt_used
    assert "stylized/cartoon" in result.prompt_used


def test_run_beat_image_stage_omits_character_block_when_none_given(tmp_path):
    result = run_beat_image_stage(
        _beat(),
        character=None,
        location=_location(),
        image_fn=_fake_image_fn(_TINY_PNG_B64),
        output_dir=tmp_path,
    )

    assert "CHARACTER:" not in result.prompt_used


def test_run_beat_image_stage_uses_edit_fn_when_references_given(tmp_path):
    character_ref = _write_reference_png(tmp_path, "character.png")
    location_ref = _write_reference_png(tmp_path, "location.png")
    captured = {}

    def _edit_fn(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(data=[SimpleNamespace(b64_json=_TINY_PNG_B64)])

    run_beat_image_stage(
        _beat(),
        character_reference=character_ref,
        location_reference=location_ref,
        edit_fn=_edit_fn,
        output_dir=tmp_path,
    )

    assert captured["image"] == [character_ref.read_bytes(), location_ref.read_bytes()]


def _write_tiny_png(tmp_path):
    import base64

    path = tmp_path / "previz.png"
    path.write_bytes(base64.b64decode(_TINY_PNG_B64))
    return path


def _fake_review_completion(content: str):
    def _completion(**kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )

    return _completion


def test_run_previz_review_stage_accepts(tmp_path):
    image_path = _write_tiny_png(tmp_path)
    payload = {"accepted": True, "concern": None}

    review = run_previz_review_stage(
        image_path,
        _fact_check_result(),
        model="anthropic/claude-sonnet-5",
        completion_fn=_fake_review_completion(json.dumps(payload)),
    )

    assert review.accepted is True
    assert review.concern is None


def test_run_previz_review_stage_parses_response_wrapped_in_markdown_fence(tmp_path):
    # Regression test: this is the exact failure observed for real against
    # a live claude-sonnet-5 call reviewing a real Gemini-generated previz
    # image -- the same prompt returned raw JSON on one call and a
    # ```json-fenced response on the next. See historical_video_ai.json_utils.
    image_path = _write_tiny_png(tmp_path)
    payload = {"accepted": True, "concern": None}

    review = run_previz_review_stage(
        image_path,
        _fact_check_result(),
        model="anthropic/claude-sonnet-5",
        completion_fn=_fake_review_completion(f"```json\n{json.dumps(payload)}\n```"),
    )

    assert review.accepted is True


def test_run_previz_review_stage_rejects_with_concern(tmp_path):
    image_path = _write_tiny_png(tmp_path)
    payload = {"accepted": False, "concern": "Depicts a car that didn't exist yet."}

    review = run_previz_review_stage(
        image_path,
        _fact_check_result(),
        model="anthropic/claude-sonnet-5",
        completion_fn=_fake_review_completion(json.dumps(payload)),
    )

    assert review.accepted is False
    assert review.concern == "Depicts a car that didn't exist yet."


def test_run_previz_review_stage_raises_when_rejected_without_concern(tmp_path):
    image_path = _write_tiny_png(tmp_path)
    payload = {"accepted": False}

    with pytest.raises(PrevizError, match="missing 'concern'"):
        run_previz_review_stage(
            image_path,
            _fact_check_result(),
            model="anthropic/claude-sonnet-5",
            completion_fn=_fake_review_completion(json.dumps(payload)),
        )


def test_run_previz_review_stage_raises_for_invalid_json(tmp_path):
    image_path = _write_tiny_png(tmp_path)

    with pytest.raises(PrevizError, match="not valid JSON"):
        run_previz_review_stage(
            image_path,
            _fact_check_result(),
            model="anthropic/claude-sonnet-5",
            completion_fn=_fake_review_completion("not json"),
        )


def test_run_previz_review_stage_raises_for_non_bool_accepted(tmp_path):
    image_path = _write_tiny_png(tmp_path)
    payload = {"accepted": "yes"}

    with pytest.raises(PrevizError, match="must be true or false"):
        run_previz_review_stage(
            image_path,
            _fact_check_result(),
            model="anthropic/claude-sonnet-5",
            completion_fn=_fake_review_completion(json.dumps(payload)),
        )


def test_run_previz_review_stage_sends_image_as_base64(tmp_path):
    image_path = _write_tiny_png(tmp_path)
    captured = {}

    def _completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps({"accepted": True}))
                )
            ]
        )

    run_previz_review_stage(
        image_path, _fact_check_result(), model="anthropic/claude-sonnet-5", completion_fn=_completion
    )

    content = captured["messages"][0]["content"]
    image_part = next(part for part in content if part["type"] == "image_url")
    assert image_part["image_url"]["url"].startswith("data:image/png;base64,")


def test_run_previz_review_stage_includes_acknowledged_fiction_when_set(tmp_path):
    # docs/decisions/0026: an explicit allowlist for a human-acknowledged
    # intentional fictional element, so the reviewer doesn't re-flag it.
    image_path = _write_tiny_png(tmp_path)
    fact_check_result = dataclasses.replace(
        _fact_check_result(),
        acknowledged_fiction="A smartphone with a time-travel app did not exist in 79 AD.",
    )
    captured = {}

    def _completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"accepted": True})))]
        )

    run_previz_review_stage(
        image_path, fact_check_result, model="anthropic/claude-sonnet-5", completion_fn=_completion
    )

    prompt_text = next(
        part["text"] for part in captured["messages"][0]["content"] if part["type"] == "text"
    )
    assert "already been explicitly acknowledged as" in prompt_text
    assert "A smartphone with a time-travel app did not exist in 79 AD." in prompt_text


def test_run_previz_review_stage_omits_acknowledged_fiction_block_when_not_set(tmp_path):
    image_path = _write_tiny_png(tmp_path)
    captured = {}

    def _completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"accepted": True})))]
        )

    run_previz_review_stage(
        image_path, _fact_check_result(), model="anthropic/claude-sonnet-5", completion_fn=_completion
    )

    prompt_text = next(
        part["text"] for part in captured["messages"][0]["content"] if part["type"] == "text"
    )
    assert "already been explicitly acknowledged as" not in prompt_text


def test_run_previz_review_stage_includes_planned_details_when_character_and_beat_given(tmp_path):
    # docs/decisions/0032: a scene-plan-approved character/beat detail must
    # not be re-flagged as an anachronism on its own terms.
    image_path = _write_tiny_png(tmp_path)
    captured = {}

    def _completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"accepted": True})))]
        )

    run_previz_review_stage(
        image_path,
        _fact_check_result(),
        character=_character(),
        beat=_beat(),
        model="anthropic/claude-sonnet-5",
        completion_fn=_completion,
    )

    prompt_text = next(
        part["text"] for part in captured["messages"][0]["content"] if part["type"] == "text"
    )
    assert "already deliberately planned and human-reviewed" in prompt_text
    assert "white crop top, gray leggings" in prompt_text
    assert "checks her phone, puzzled" in prompt_text
    # Real report (2026-09-15): the reviewer was rejecting otherwise-correct
    # images for not showing a distinguishing detail (a chipped tooth, a
    # forearm scar) that the beat's own described pose/camera couldn't
    # have shown in the first place -- this carve-out stops that.
    assert "only needs to be visible when the beat's own described pose" in prompt_text


def test_run_previz_review_stage_omits_planned_details_block_when_not_given(tmp_path):
    image_path = _write_tiny_png(tmp_path)
    captured = {}

    def _completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"accepted": True})))]
        )

    run_previz_review_stage(
        image_path, _fact_check_result(), model="anthropic/claude-sonnet-5", completion_fn=_completion
    )

    prompt_text = next(
        part["text"] for part in captured["messages"][0]["content"] if part["type"] == "text"
    )
    assert "already deliberately planned and human-reviewed" not in prompt_text


def test_run_previz_review_stage_includes_previous_concerns_when_given(tmp_path):
    # A retry review with no memory of a prior rejection could wave through
    # the same unresolved flaw on the next attempt -- observed for real
    # (fisheye distortion flagged missing once, then a second attempt with
    # the same flaw was accepted). Prior concerns must reach the prompt so
    # the reviewer is told to specifically re-check them.
    image_path = _write_tiny_png(tmp_path)
    captured = {}

    def _completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"accepted": True})))]
        )

    run_previz_review_stage(
        image_path,
        _fact_check_result(),
        previous_concerns=["Shot lacks the described extreme fisheye-from-below perspective."],
        model="anthropic/claude-sonnet-5",
        completion_fn=_completion,
    )

    prompt_text = next(
        part["text"] for part in captured["messages"][0]["content"] if part["type"] == "text"
    )
    assert "This is a retry" in prompt_text
    assert "Shot lacks the described extreme fisheye-from-below perspective." in prompt_text


def test_run_previz_review_stage_omits_previous_concerns_block_when_not_given(tmp_path):
    image_path = _write_tiny_png(tmp_path)
    captured = {}

    def _completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"accepted": True})))]
        )

    run_previz_review_stage(
        image_path, _fact_check_result(), model="anthropic/claude-sonnet-5", completion_fn=_completion
    )

    prompt_text = next(
        part["text"] for part in captured["messages"][0]["content"] if part["type"] == "text"
    )
    assert "This is a retry" not in prompt_text


def test_run_previz_review_stage_includes_previous_concerns_when_ungrounded(tmp_path):
    # The ungrounded template (docs/decisions/0034) has its own separate
    # {previous_concerns_block} substitution -- must format correctly too.
    image_path = _write_tiny_png(tmp_path)
    captured = {}

    def _completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"accepted": True})))]
        )

    run_previz_review_stage(
        image_path,
        _fact_check_result(),
        requires_grounding=False,
        previous_concerns=["The vinyl record element is missing from the frame."],
        model="anthropic/claude-sonnet-5",
        completion_fn=_completion,
    )

    prompt_text = next(
        part["text"] for part in captured["messages"][0]["content"] if part["type"] == "text"
    )
    assert "This is a retry" in prompt_text
    assert "The vinyl record element is missing from the frame." in prompt_text


def test_run_previz_review_stage_drops_anachronism_check_when_ungrounded(tmp_path):
    # docs/decisions/0034
    image_path = _write_tiny_png(tmp_path)
    captured = {}

    def _completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"accepted": True})))]
        )

    run_previz_review_stage(
        image_path,
        _fact_check_result(),
        requires_grounding=False,
        model="anthropic/claude-sonnet-5",
        completion_fn=_completion,
    )

    prompt_text = next(
        part["text"] for part in captured["messages"][0]["content"] if part["type"] == "text"
    )
    assert "not meant to be historically or factually accurate" in prompt_text
    assert "historically accurate scene description" not in prompt_text
    assert "Claims the image should be consistent with" not in prompt_text


def test_run_previz_review_stage_resolves_model_from_config_when_not_passed(tmp_path):
    image_path = _write_tiny_png(tmp_path)
    captured = {}

    def _completion(**kwargs):
        captured["model"] = kwargs["model"]
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps({"accepted": True}))
                )
            ]
        )

    run_previz_review_stage(image_path, _fact_check_result(), completion_fn=_completion)

    assert captured["model"] == get_stage_model("previz_review")
