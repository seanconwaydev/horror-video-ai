import json
from types import SimpleNamespace

import pytest
from PIL import Image

from historical_video_ai.cli import (
    _generate_previz_with_review,
    _load_fixture,
    _load_previz_output,
    _resolve_flags,
    _resolve_premise_conflict,
    _run_video_generation_only,
)
from historical_video_ai.stages.fact_check import ClaimFlag, FactCheckResult, PremiseConflict
from historical_video_ai.stages.research import Claim, FactSheet

_TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _write_fixture(tmp_path, **overrides):
    payload = {
        "time": "December 1903",
        "place": "Kitty Hawk, North Carolina",
        "description": "watches a flying machine lift off from the dunes.",
        "research_claims": [
            {
                "text": "The dunes at Kitty Hawk were largely undeveloped in 1903.",
                "source": "NPS",
                "date": None,
                "names": [],
            }
        ],
        "fact_check_flags": [],
        **overrides,
    }
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(payload))
    return path


def test_load_fixture_reconstructs_fact_check_result(tmp_path):
    path = _write_fixture(tmp_path)

    result = _load_fixture(path)

    assert result == FactCheckResult(
        fact_sheet=FactSheet(
            time="December 1903",
            place="Kitty Hawk, North Carolina",
            description="watches a flying machine lift off from the dunes.",
            claims=[
                Claim(
                    text="The dunes at Kitty Hawk were largely undeveloped in 1903.",
                    source="NPS",
                )
            ],
        ),
        flags=[],
    )


def test_load_fixture_reconstructs_flags(tmp_path):
    path = _write_fixture(
        tmp_path,
        fact_check_flags=[
            {
                "claim_text": "The dunes at Kitty Hawk were largely undeveloped in 1903.",
                "concern": "Source doesn't specifically support 'largely'.",
                "severity": "uncertain",
            }
        ],
    )

    result = _load_fixture(path)

    assert result.flags == [
        ClaimFlag(
            claim_text="The dunes at Kitty Hawk were largely undeveloped in 1903.",
            concern="Source doesn't specifically support 'largely'.",
            severity="uncertain",
        )
    ]


@pytest.mark.parametrize("missing_field", ["time", "place", "description"])
def test_load_fixture_raises_for_empty_required_field(tmp_path, missing_field):
    path = _write_fixture(tmp_path, **{missing_field: ""})

    with pytest.raises(ValueError, match=missing_field):
        _load_fixture(path)


def test_load_fixture_reconstructs_premise_conflict(tmp_path):
    path = _write_fixture(
        tmp_path,
        premise_conflict={
            "explanation": "Nothing like this existed yet.",
            "suggested_alternative": "A close, true version.",
        },
    )

    result = _load_fixture(path)

    assert result.premise_conflict == PremiseConflict(
        explanation="Nothing like this existed yet.",
        suggested_alternative="A close, true version.",
    )


def test_load_fixture_defaults_premise_conflict_to_none_when_absent(tmp_path):
    path = _write_fixture(tmp_path)

    result = _load_fixture(path)

    assert result.premise_conflict is None


def test_load_fixture_raises_when_flag_claim_text_does_not_match(tmp_path):
    path = _write_fixture(
        tmp_path,
        fact_check_flags=[
            {
                "claim_text": "The dunes at Kitty Hawk were largely undeveloped in 1903. "
                "(date: null) [source: NPS]",
                "concern": "Paraphrased instead of copied verbatim.",
                "severity": "uncertain",
            }
        ],
    )

    with pytest.raises(ValueError, match="doesn't exactly match any research claim"):
        _load_fixture(path)


def _fact_sheet_with_two_claims() -> FactSheet:
    return FactSheet(
        time="December 1903",
        place="Kitty Hawk, North Carolina",
        description="watches a flying machine lift off from the dunes.",
        claims=[
            Claim(text="Claim A", source="Source A"),
            Claim(text="Claim B", source="Source B"),
        ],
    )


def test_resolve_flags_returns_same_fact_sheet_when_no_flags():
    fact_sheet = _fact_sheet_with_two_claims()

    resolved = _resolve_flags(fact_sheet, [])

    assert resolved is fact_sheet


def test_resolve_flags_accept_keeps_claim_unchanged(monkeypatch):
    fact_sheet = _fact_sheet_with_two_claims()
    flags = [ClaimFlag(claim_text="Claim A", concern="Might be off.", severity="uncertain")]
    monkeypatch.setattr("builtins.input", lambda _: "a")

    resolved = _resolve_flags(fact_sheet, flags)

    assert resolved.claims == fact_sheet.claims


def test_resolve_flags_cut_removes_the_claim(monkeypatch):
    fact_sheet = _fact_sheet_with_two_claims()
    flags = [ClaimFlag(claim_text="Claim A", concern="Wrong.", severity="contradicted")]
    monkeypatch.setattr("builtins.input", lambda _: "c")

    resolved = _resolve_flags(fact_sheet, flags)

    assert [c.text for c in resolved.claims] == ["Claim B"]


def test_resolve_flags_soften_replaces_claim_text_only(monkeypatch):
    fact_sheet = _fact_sheet_with_two_claims()
    flags = [ClaimFlag(claim_text="Claim A", concern="Too strong.", severity="uncertain")]
    responses = iter(["s", "A softened version of claim A"])
    monkeypatch.setattr("builtins.input", lambda _: next(responses))

    resolved = _resolve_flags(fact_sheet, flags)

    resolved_a = next(c for c in resolved.claims if c is not resolved.claims[1])
    assert resolved_a.text == "A softened version of claim A"
    assert resolved_a.source == "Source A"  # only text changes, not the rest of the claim
    assert resolved.claims[1].text == "Claim B"


def test_resolve_flags_reprompts_on_invalid_action(monkeypatch):
    fact_sheet = _fact_sheet_with_two_claims()
    flags = [ClaimFlag(claim_text="Claim A", concern="Wrong.", severity="contradicted")]
    responses = iter(["x", "c"])  # invalid choice, then a valid one
    monkeypatch.setattr("builtins.input", lambda _: next(responses))

    resolved = _resolve_flags(fact_sheet, flags)

    assert [c.text for c in resolved.claims] == ["Claim B"]


def _fake_reverify_completion(fact_check_payload=None):
    """Stand-in for a real research + fact-check re-verification pass: the
    research call returns one clean claim, the fact-check call returns
    fact_check_payload (defaulting to clean -- no flags, no conflict)."""

    def _completion(**kwargs):
        prompt = kwargs["messages"][0]["content"]
        if "Claims to check" in prompt:
            content = json.dumps(fact_check_payload or {"flags": [], "premise_conflict": None})
        else:
            content = json.dumps(
                {
                    "claims": [
                        {
                            "text": "A newly researched claim for the corrected scene.",
                            "source": "Some source",
                            "date": None,
                            "names": [],
                        }
                    ]
                }
            )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )

    return _completion


def _premise_conflict_fact_check_result(suggested_alternative) -> FactCheckResult:
    return FactCheckResult(
        fact_sheet=_fact_sheet_with_two_claims(),
        premise_conflict=PremiseConflict(
            explanation="This depicts something that didn't exist yet.",
            suggested_alternative=suggested_alternative,
        ),
    )


def _resolve_premise_conflict_kwargs(completion_fn):
    return {
        "time": "December 1903",
        "place": "Kitty Hawk, North Carolina",
        "research_model": "anthropic/claude-sonnet-5",
        "fact_check_model": "anthropic/claude-sonnet-5",
        "completion_kwargs": {"completion_fn": completion_fn},
    }


def test_resolve_premise_conflict_returns_unchanged_when_no_conflict():
    fact_sheet = _fact_sheet_with_two_claims()
    fact_check_result = FactCheckResult(fact_sheet=fact_sheet)

    result = _resolve_premise_conflict(
        fact_sheet, fact_check_result, **_resolve_premise_conflict_kwargs(None)
    )

    assert result == (fact_sheet, fact_check_result)


def test_resolve_premise_conflict_accepts_suggested_alternative_and_reverifies(monkeypatch):
    fact_check_result = _premise_conflict_fact_check_result("A close, true version of the scene.")
    responses = iter(["y", "y"])  # use suggested alternative; proceed to fact-check on reverify
    monkeypatch.setattr("builtins.input", lambda _: next(responses))

    result = _resolve_premise_conflict(
        fact_check_result.fact_sheet,
        fact_check_result,
        **_resolve_premise_conflict_kwargs(_fake_reverify_completion()),
    )

    assert result is not None
    new_fact_sheet, new_fact_check_result = result
    assert new_fact_sheet.description == "A close, true version of the scene."
    assert new_fact_check_result.premise_conflict is None


def test_resolve_premise_conflict_declines_alternative_and_provides_own(monkeypatch):
    fact_check_result = _premise_conflict_fact_check_result("A suggested version.")
    responses = iter(["n", "y", "my own corrected description", "y"])
    monkeypatch.setattr("builtins.input", lambda _: next(responses))

    result = _resolve_premise_conflict(
        fact_check_result.fact_sheet,
        fact_check_result,
        **_resolve_premise_conflict_kwargs(_fake_reverify_completion()),
    )

    assert result is not None
    new_fact_sheet, _ = result
    assert new_fact_sheet.description == "my own corrected description"


def test_resolve_premise_conflict_no_alternative_provides_own(monkeypatch):
    fact_check_result = _premise_conflict_fact_check_result(None)
    responses = iter(["y", "my own corrected description", "y"])
    monkeypatch.setattr("builtins.input", lambda _: next(responses))

    result = _resolve_premise_conflict(
        fact_check_result.fact_sheet,
        fact_check_result,
        **_resolve_premise_conflict_kwargs(_fake_reverify_completion()),
    )

    assert result is not None
    new_fact_sheet, _ = result
    assert new_fact_sheet.description == "my own corrected description"


def test_resolve_premise_conflict_declining_everything_stops(monkeypatch):
    fact_check_result = _premise_conflict_fact_check_result("A suggested version.")
    responses = iter(["n", "n"])  # decline alternative, decline providing own
    monkeypatch.setattr("builtins.input", lambda _: next(responses))

    result = _resolve_premise_conflict(
        fact_check_result.fact_sheet,
        fact_check_result,
        **_resolve_premise_conflict_kwargs(None),
    )

    assert result is None


def test_resolve_premise_conflict_stops_if_reverify_still_conflicted(monkeypatch):
    fact_check_result = _premise_conflict_fact_check_result("A suggested version.")
    responses = iter(["y", "y"])  # use alternative; proceed to fact-check on reverify
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    still_conflicted_payload = {
        "flags": [],
        "premise_conflict": {
            "explanation": "Still impossible even with the corrected description.",
            "suggested_alternative": None,
        },
    }

    result = _resolve_premise_conflict(
        fact_check_result.fact_sheet,
        fact_check_result,
        **_resolve_premise_conflict_kwargs(_fake_reverify_completion(still_conflicted_payload)),
    )

    assert result is None


def _fact_check_result_for_previz() -> FactCheckResult:
    return FactCheckResult(fact_sheet=_fact_sheet_with_two_claims())


def _fake_image_fn(**kwargs):
    return SimpleNamespace(data=[SimpleNamespace(b64_json=_TINY_PNG_B64)])


def _fake_review_completion(verdicts):
    """verdicts: list of (accepted, concern) tuples, one per call, in order."""
    responses = iter(verdicts)

    def _completion(**kwargs):
        accepted, concern = next(responses)
        content = json.dumps({"accepted": accepted, "concern": concern})
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )

    return _completion


def _generate_previz_with_review_kwargs(review_completion_fn, out_dir):
    return {
        "previz_model": "openai/gpt-image-1-mini",
        "review_model": "anthropic/claude-sonnet-5",
        "image_kwargs": {"image_fn": _fake_image_fn},
        "review_kwargs": {"completion_fn": review_completion_fn},
        "out_dir": out_dir,
    }


def test_generate_previz_with_review_accepts_on_first_attempt(tmp_path):
    result, attempts = _generate_previz_with_review(
        _fact_check_result_for_previz(),
        **_generate_previz_with_review_kwargs(_fake_review_completion([(True, None)]), tmp_path),
    )

    assert result is not None
    assert result.image_path == tmp_path / "previz.png"
    assert attempts == [{"attempt": 1, "accepted": True, "concern": None}]


def test_generate_previz_with_review_retries_then_accepts(tmp_path):
    verdicts = [(False, "Depicts something anachronistic."), (True, None)]

    result, attempts = _generate_previz_with_review(
        _fact_check_result_for_previz(),
        **_generate_previz_with_review_kwargs(_fake_review_completion(verdicts), tmp_path),
    )

    assert result is not None
    assert result.image_path == tmp_path / "previz.png"
    # the rejected first attempt was archived, not left at previz.png or lost
    assert (tmp_path / "previz_attempt_1_rejected.png").exists()
    assert [a["accepted"] for a in attempts] == [False, True]


def test_generate_previz_with_review_gives_up_after_max_attempts(tmp_path):
    verdicts = [(False, "Wrong.")] * 3

    result, attempts = _generate_previz_with_review(
        _fact_check_result_for_previz(),
        **_generate_previz_with_review_kwargs(_fake_review_completion(verdicts), tmp_path),
    )

    assert result is None
    assert len(attempts) == 3
    assert all(not a["accepted"] for a in attempts)
    # every rejected attempt archived, no final previz.png left behind
    for n in (1, 2, 3):
        assert (tmp_path / f"previz_attempt_{n}_rejected.png").exists()
    assert not (tmp_path / "previz.png").exists()


def _write_previz_run_log(run_dir, *, image_path=None, prompt="A prompt from previz."):
    run_dir.mkdir(parents=True, exist_ok=True)
    if image_path is None:
        image_path = run_dir / "previz.png"
        # A real PNG already at Sora's target size -- video_generation
        # genuinely opens and resizes this with Pillow now, so arbitrary
        # bytes no longer work here.
        Image.new("RGB", (720, 1280), color="blue").save(image_path, format="PNG")
    log = {"previz_image_path": str(image_path), "previz_prompt_used": prompt}
    (run_dir / "run_log.json").write_text(json.dumps(log))
    return image_path


def test_load_previz_output_returns_image_path_and_prompt(tmp_path):
    run_dir = tmp_path / "run_1"
    image_path = _write_previz_run_log(run_dir, prompt="Scene one's prompt.")

    result_image_path, prompt = _load_previz_output(run_dir)

    assert result_image_path == image_path
    assert prompt == "Scene one's prompt."


def test_load_previz_output_raises_when_no_run_log(tmp_path):
    run_dir = tmp_path / "run_missing"
    run_dir.mkdir()

    with pytest.raises(FileNotFoundError, match="No run_log.json"):
        _load_previz_output(run_dir)


def test_load_previz_output_raises_when_previz_incomplete(tmp_path):
    run_dir = tmp_path / "run_incomplete"
    run_dir.mkdir()
    (run_dir / "run_log.json").write_text(json.dumps({"time": "1969"}))

    with pytest.raises(ValueError, match="no completed previz result"):
        _load_previz_output(run_dir)


def test_load_previz_output_raises_when_image_file_missing(tmp_path):
    run_dir = tmp_path / "run_stale"
    run_dir.mkdir()
    missing_image = run_dir / "previz.png"
    log = {"previz_image_path": str(missing_image), "previz_prompt_used": "A prompt."}
    (run_dir / "run_log.json").write_text(json.dumps(log))

    with pytest.raises(FileNotFoundError, match="no longer exists"):
        _load_previz_output(run_dir)


def test_run_video_generation_only_generates_one_clip_per_run_dir(tmp_path):
    source_a = tmp_path / "source_run_a"
    source_b = tmp_path / "source_run_b"
    _write_previz_run_log(source_a, prompt="Scene A's prompt.")
    _write_previz_run_log(source_b, prompt="Scene B's prompt.")
    out_dir = tmp_path / "video_run"
    out_dir.mkdir()

    _run_video_generation_only(
        [source_a, source_b], mock=True, out_dir=out_dir, video_model="openai/sora-2"
    )

    assert (out_dir / "video_scene_1.mp4").exists()
    assert (out_dir / "video_scene_2.mp4").exists()
    log = json.loads((out_dir / "run_log.json").read_text())
    assert log["mode"] == "video_generation_only"
    assert [s["prompt_used"] for s in log["scenes"]] == [
        "Scene A's prompt.",
        "Scene B's prompt.",
    ]


def test_generate_previz_with_review_calls_on_image_generated_before_review(tmp_path):
    calls = []

    result, _ = _generate_previz_with_review(
        _fact_check_result_for_previz(),
        **_generate_previz_with_review_kwargs(_fake_review_completion([(True, None)]), tmp_path),
        on_image_generated=calls.append,
    )

    assert len(calls) == 1
    assert calls[0] == result


def test_generate_previz_with_review_on_image_generated_survives_a_review_crash(tmp_path):
    # Regression test: a real run hit exactly this -- previz generated a
    # real image, but previz_review raised (missing ANTHROPIC_API_KEY)
    # before returning a verdict at all. on_image_generated must still have
    # fired for that image, so a caller logging progress (main()'s
    # run_log.json) doesn't lose track of an already-generated, already
    # paid-for image just because the next stage blew up.
    calls = []

    def _crashing_review(**kwargs):
        raise RuntimeError("simulated previz_review crash (e.g. missing API key)")

    with pytest.raises(RuntimeError, match="simulated previz_review crash"):
        _generate_previz_with_review(
            _fact_check_result_for_previz(),
            **_generate_previz_with_review_kwargs(_crashing_review, tmp_path),
            on_image_generated=calls.append,
        )

    assert len(calls) == 1
    assert calls[0].image_path == tmp_path / "previz.png"


def test_resolve_premise_conflict_stops_if_reverify_research_declined(monkeypatch):
    fact_check_result = _premise_conflict_fact_check_result("A suggested version.")
    responses = iter(["y", "n"])  # use alternative; decline "proceed to fact-check" on reverify
    monkeypatch.setattr("builtins.input", lambda _: next(responses))

    result = _resolve_premise_conflict(
        fact_check_result.fact_sheet,
        fact_check_result,
        **_resolve_premise_conflict_kwargs(_fake_reverify_completion()),
    )

    assert result is None
