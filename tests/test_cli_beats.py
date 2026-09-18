"""Generating a scene plan's beats into images (cli/beats.py).

The last piece of test_cli.py to be split; it was the bulk of it. The
generate_fn / image_fn / edit_fn seams these tests drive are the reason
none of this needs a live API call.
"""

import base64
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from factories import TINY_PNG_B64, a_beat, a_character, a_location

from historical_video_ai.cli.beats import (
    beat_gallery_dir,
    generate_beats_with_choices,
    generate_image_with_retries,
    generate_scene_references,
    link_beat_into_gallery,
)
from historical_video_ai.stages.previz import PrevizResult
from historical_video_ai.stages.scene_planning import Character, ScenePlan


def _fake_image_fn(**kwargs):
    return SimpleNamespace(data=[SimpleNamespace(b64_json=TINY_PNG_B64)])


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


def _retry_loop_kwargs(out_dir):
    """Kwargs for generate_image_with_retries, the attempt loop itself.

    The loop runs no automated review any more (docs/decisions/0055), so
    what remains to exercise is attempt counting, archiving, and the human
    choice callback.
    """
    return {"out_dir": out_dir}


def _previz_generate_fn(out_dir):
    """A generate_fn writing one candidate to out_dir/previz.png."""

    def _generate():
        path = out_dir / "previz.png"
        path.write_bytes(base64.b64decode(TINY_PNG_B64))
        return [PrevizResult(image_path=path, prompt_used="a prompt")]

    return _generate


def test_image_review_loop_accepts_on_first_attempt(tmp_path):
    result, attempts = generate_image_with_retries(
        _previz_generate_fn(tmp_path),
        **_retry_loop_kwargs(tmp_path),
    )

    assert result is not None
    assert result.image_path == tmp_path / "previz.png"
    assert attempts == [
        {
            "attempt": 1,
            "accepted": True,
            "concern": None,
            # Single-candidate attempts have no choice to record.
            "human_choice": None,
            "unattended": False,
            # The exact prompt is the label's input: _build_beat_prompt
            # changes over time, so a beat's fields can't reconstruct it
            # after the fact (docs/decisions/0053).
            "candidates": [
                {
                    "path": str(tmp_path / "previz.png"),
                    "prompt_used": "a prompt",
                    "kept": True,
                }
            ],
        }
    ]


def test_image_review_loop_retries_then_accepts(tmp_path):
    decisions = iter(["continue", "accept"])

    result, attempts = generate_image_with_retries(
        _previz_generate_fn(tmp_path),
        on_reviewed=lambda concern, attempt: next(decisions),
        **_retry_loop_kwargs(tmp_path),
    )

    assert result is not None
    assert result.image_path == tmp_path / "previz.png"
    # the rejected first attempt was archived, not left at previz.png or lost
    assert (tmp_path / "previz_attempt_1_rejected.png").exists()
    assert [a["accepted"] for a in attempts] == [False, True]


def test_image_review_loop_gives_up_after_max_attempts(tmp_path):
    result, attempts = generate_image_with_retries(
        _previz_generate_fn(tmp_path),
        on_reviewed=lambda concern, attempt: "continue",
        **_retry_loop_kwargs(tmp_path),
    )

    assert result is None
    assert len(attempts) == 3
    assert all(not a["accepted"] for a in attempts)
    # every rejected attempt archived, no final previz.png left behind
    for n in (1, 2, 3):
        assert (tmp_path / f"previz_attempt_{n}_rejected.png").exists()


def test_generate_scene_references_generates_and_accepts(tmp_path, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "y")

    character_refs, location_refs = generate_scene_references(
        ScenePlan(characters=[a_character()], locations=[a_location()], beats=[a_beat()]),
        previz_model="gemini/gemini-2.5-flash-image",
        image_kwargs={"image_fn": _fake_image_fn},
        out_dir=tmp_path,
    )

    assert character_refs["influencer"] == tmp_path / "character_influencer" / "reference.png"
    assert location_refs["street"] == tmp_path / "location_street" / "reference.png"


def test_generate_scene_references_passes_style_through_to_both_prompts(tmp_path, monkeypatch):
    # docs/decisions/0033, 0039
    monkeypatch.setattr("builtins.input", lambda _: "y")
    captured_prompts = []

    def _capturing_image_fn(**kwargs):
        captured_prompts.append(kwargs["prompt"])
        return SimpleNamespace(data=[SimpleNamespace(b64_json=TINY_PNG_B64)])

    generate_scene_references(
        ScenePlan(characters=[a_character()], locations=[a_location()], beats=[a_beat()]),
        previz_model="gemini/gemini-2.5-flash-image",
        image_kwargs={"image_fn": _capturing_image_fn},
        out_dir=tmp_path,
        style="cel-shaded",
    )

    assert len(captured_prompts) == 2
    assert all("Cel-shaded" in p for p in captured_prompts)


def test_generate_scene_references_regenerates_until_accepted(tmp_path, monkeypatch):
    # First reference offered is rejected ("n"), the regenerated one accepted.
    responses = iter(["n", "y"])
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    calls = {"n": 0}

    def _counting_image_fn(**kwargs):
        calls["n"] += 1
        return SimpleNamespace(data=[SimpleNamespace(b64_json=TINY_PNG_B64)])

    character_refs, _ = generate_scene_references(
        ScenePlan(characters=[a_character()], locations=[], beats=[a_beat()]),
        previz_model="gemini/gemini-2.5-flash-image",
        image_kwargs={"image_fn": _counting_image_fn},
        out_dir=tmp_path,
    )

    assert calls["n"] == 2
    assert "influencer" in character_refs


def _write_reference_png(tmp_path, name):
    import base64

    path = tmp_path / name
    path.write_bytes(base64.b64decode(TINY_PNG_B64))
    return path


def test_beat_gallery_dir_exists_immediately_before_any_beat_is_linked(tmp_path):
    # The gallery folder must exist as soon as a run starts -- not only
    # after the first beat finishes -- so a run cancelled before any beat
    # completes still leaves a (empty) folder behind, per the project
    # owner's own reported use case (restarting runs often).
    gallery = beat_gallery_dir(tmp_path)

    assert gallery == tmp_path / "all_beats"
    assert gallery.is_dir()
    assert list(gallery.iterdir()) == []


def test_link_beat_into_gallery_symlinks_by_index(tmp_path):
    beat1_dir = tmp_path / "beat_1"
    beat1_dir.mkdir()
    image1 = _write_reference_png(beat1_dir, "previz.png")

    link_beat_into_gallery(tmp_path, 1, str(image1))

    link = tmp_path / "all_beats" / "beat_1.png"
    assert link.is_symlink()
    assert link.resolve() == image1.resolve()


def test_link_beat_into_gallery_is_idempotent(tmp_path):
    beat1_dir = tmp_path / "beat_1"
    beat1_dir.mkdir()
    image1 = _write_reference_png(beat1_dir, "previz.png")

    link_beat_into_gallery(tmp_path, 1, str(image1))
    link_beat_into_gallery(tmp_path, 1, str(image1))  # re-linking must not raise

    assert (tmp_path / "all_beats" / "beat_1.png").resolve() == image1.resolve()


def _generate_beats_with_choices_kwargs(out_dir, *, image_fn=_fake_image_fn, edit_fn=_fake_image_fn):
    return {
        "previz_model": "gemini/gemini-2.5-flash-image",
        "image_kwargs": {"image_fn": image_fn, "edit_fn": edit_fn},
        "out_dir": out_dir,
    }


def test_generate_beats_with_choices_auto_accepts_under_yes(tmp_path):
    scene_plan = ScenePlan(characters=[a_character()], locations=[a_location()], beats=[a_beat()])
    char_ref = _write_reference_png(tmp_path, "char_ref.png")
    loc_ref = _write_reference_png(tmp_path, "loc_ref.png")

    results = generate_beats_with_choices(
        scene_plan,
        character_refs={"influencer": char_ref},
        location_refs={"street": loc_ref},
        auto_yes=True,
        **_generate_beats_with_choices_kwargs(tmp_path),
    )

    assert len(results) == 1
    assert results[0]["image_path"] is not None
    assert results[0]["beat"]["action"] == "checks her phone"
    # The gallery is populated as beats are accepted, as part of this same
    # call -- not a separate step a caller has to remember to run
    # afterward (see link_beat_into_gallery's docstring).
    link = tmp_path / "all_beats" / "beat_1.png"
    assert link.is_symlink()
    assert link.resolve() == Path(results[0]["image_path"]).resolve()


def test_generate_beats_with_choices_reroll_generates_again_then_accepts(tmp_path, monkeypatch):
    responses = iter(["r", "a"])
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    scene_plan = ScenePlan(characters=[], locations=[a_location()], beats=[a_beat()])
    calls = {"n": 0}

    def _counting_image_fn(**kwargs):
        calls["n"] += 1
        return SimpleNamespace(data=[SimpleNamespace(b64_json=TINY_PNG_B64)])

    kwargs = _generate_beats_with_choices_kwargs(tmp_path, image_fn=_counting_image_fn)
    # Each generation attempt (the rerolled one and the accepted one) goes
    # through its own previz_review pass before the human choice is even
    # asked -- two accepted verdicts needed, not one.

    results = generate_beats_with_choices(
        scene_plan, character_refs={}, location_refs={}, **kwargs
    )

    assert calls["n"] == 2  # one rerolled attempt, then the accepted one
    assert results[0]["image_path"] is not None


def test_generate_beats_with_choices_edit_changes_the_beat_before_regenerating(tmp_path, monkeypatch):
    # "e" to edit -- a beat's edit is restricted to action/camera/lighting
    # (BEAT_QUICK_EDIT_FIELDS), not every field -- then a new action,
    # blank for camera/lighting, then "a" to accept.
    responses = iter(["e", "smiles warmly", "", "", "a"])
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    scene_plan = ScenePlan(characters=[], locations=[a_location()], beats=[a_beat()])
    kwargs = _generate_beats_with_choices_kwargs(tmp_path)

    results = generate_beats_with_choices(
        scene_plan, character_refs={}, location_refs={}, **kwargs
    )

    assert results[0]["beat"]["action"] == "smiles warmly"


def test_a_human_can_retry_past_the_unattended_attempt_cap(tmp_path, monkeypatch):
    """The cap exists to stop an UNATTENDED run regenerating forever. Once
    every attempt is an explicit human choice, refusing one that was just
    asked for is wrong -- choosing (r)etry on the last allowed attempt
    silently behaved as a give-up, reported from a real run:

        Attempt 3/3 -- ... / (r)etry carrying 3 review concerns / ...: r
        No image kept for this beat after 3 attempt(s).
    """
    # Four retries -- one more than MAX_PREVIZ_ATTEMPTS -- then accept.
    responses = iter(["r", "r", "r", "r", "a"])
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    scene_plan = ScenePlan(characters=[], locations=[a_location()], beats=[a_beat()])
    kwargs = _generate_beats_with_choices_kwargs(tmp_path)

    results = generate_beats_with_choices(
        scene_plan, character_refs={}, location_refs={}, **kwargs
    )

    assert results[0]["image_path"] is not None, "the 5th attempt was refused"
    assert len(results[0]["attempts"]) == 5


def test_an_unattended_run_accepts_the_first_attempt(tmp_path):
    """--yes has nobody to ask and nothing to grade the image, so it takes
    attempt 1 rather than spending the cap (docs/decisions/0055)."""
    scene_plan = ScenePlan(characters=[], locations=[a_location()], beats=[a_beat()])
    kwargs = _generate_beats_with_choices_kwargs(tmp_path)

    results = generate_beats_with_choices(
        scene_plan,
        character_refs={},
        location_refs={},
        auto_yes=True,
        **kwargs,
    )

    assert results[0]["image_path"] is not None
    assert len(results[0]["attempts"]) == 1


def test_generate_beats_with_choices_passes_style_through(tmp_path):
    # docs/decisions/0033
    captured_prompts = []

    def _capturing_image_fn(**kwargs):
        captured_prompts.append(kwargs["prompt"])
        return SimpleNamespace(data=[SimpleNamespace(b64_json=TINY_PNG_B64)])

    scene_plan = ScenePlan(characters=[], locations=[a_location()], beats=[a_beat()])
    kwargs = _generate_beats_with_choices_kwargs(tmp_path, image_fn=_capturing_image_fn)

    generate_beats_with_choices(
        scene_plan,
        character_refs={},
        location_refs={},
        style="semi-realistic",
        auto_yes=True,
        **kwargs,
    )

    assert len(captured_prompts) == 1
    assert "Pixar/Disney" in captured_prompts[0]


def test_generate_beats_with_choices_gives_up_early_when_human_declines_to_keep_retrying(
    tmp_path, monkeypatch
):
    # Only one rejected attempt should happen -- (g)ive up at the very
    # first on-rejection prompt must stop the retry loop immediately
    # rather than burning the remaining automatic attempts.
    responses = iter(["g"])
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    scene_plan = ScenePlan(characters=[], locations=[a_location()], beats=[a_beat()])
    kwargs = _generate_beats_with_choices_kwargs(tmp_path)

    results = generate_beats_with_choices(
        scene_plan, character_refs={}, location_refs={}, **kwargs
    )

    assert results[0]["image_path"] is None
    assert len(results[0]["attempts"]) == 1


def test_generate_beats_with_choices_lets_human_give_feedback_on_rejection_and_retry(
    tmp_path, monkeypatch
):
    # (f)eedback appends a short note to the beat's existing action text
    # instead of rewriting it -- a targeted correction, not a full edit,
    # for the common case where the plan was mostly right.
    responses = iter(["f", "make her noticeably smaller", "a"])
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    scene_plan = ScenePlan(characters=[], locations=[a_location()], beats=[a_beat()])
    kwargs = _generate_beats_with_choices_kwargs(tmp_path)

    results = generate_beats_with_choices(
        scene_plan, character_refs={}, location_refs={}, **kwargs
    )

    assert results[0]["image_path"] is not None
    assert results[0]["beat"]["action"] == "checks her phone make her noticeably smaller"


def test_generate_beats_with_choices_lets_human_edit_beat_on_rejection_and_retry(
    tmp_path, monkeypatch
):
    # docs/decisions/0028-era work follow-up: a rejection caused by
    # something baked into the beat's own text (not bad luck) needs an
    # edit-and-retry path, not just three guaranteed-to-fail blind
    # attempts. (e)dit at the on-rejection prompt, then blank through
    # action/camera/lighting (BEAT_QUICK_EDIT_FIELDS, keep as-is for
    # this test), should restart a fresh attempt cycle that can then be
    # accepted normally.
    responses = iter(["e", "", "", "", "a"])
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    scene_plan = ScenePlan(characters=[], locations=[a_location()], beats=[a_beat()])
    kwargs = _generate_beats_with_choices_kwargs(tmp_path)

    results = generate_beats_with_choices(
        scene_plan, character_refs={}, location_refs={}, **kwargs
    )

    assert results[0]["image_path"] is not None
    # Both cycles are recorded. The restarted cycle is a fresh
    # generate_image_with_retries call, and its own attempt log used to be
    # the only one kept -- so choosing (e)dit silently discarded the
    # rejected attempt that prompted the edit, which is the judgement
    # worth keeping (docs/decisions/0053).
    attempts = results[0]["attempts"]
    assert [a["cycle"] for a in attempts] == [1, 2]
    assert [a["accepted"] for a in attempts] == [False, True]
    # The human's action at the first cycle's prompt is the label.
    assert attempts[0]["human_action"] == "e"


def test_generate_beats_with_choices_uses_first_character_for_every_beat(tmp_path):
    # Documented v1 simplification (docs/decisions/0024): Beat has no
    # character_id field, so with multiple characters the first is used
    # for every beat.
    second_character = Character(
        id="second",
        face_build="a man",
        hair="short",
        wardrobe_signature="a tunic",
        wardrobe_flexible="none",
        distinguishing_detail="a beard",
    )
    scene_plan = ScenePlan(
        characters=[a_character(), second_character], locations=[a_location()], beats=[a_beat()]
    )
    char_ref = _write_reference_png(tmp_path, "char.png")
    second_char_ref = _write_reference_png(tmp_path, "char2.png")
    loc_ref = _write_reference_png(tmp_path, "loc.png")
    captured = {}

    def _capturing_edit_fn(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(data=[SimpleNamespace(b64_json=TINY_PNG_B64)])

    generate_beats_with_choices(
        scene_plan,
        character_refs={"influencer": char_ref, "second": second_char_ref},
        location_refs={"street": loc_ref},
        auto_yes=True,
        **_generate_beats_with_choices_kwargs(tmp_path, edit_fn=_capturing_edit_fn),
    )

    assert captured["image"][0] == char_ref.read_bytes()
    assert not (tmp_path / "previz.png").exists()


def test_image_review_loop_calls_on_image_generated_before_review(tmp_path):
    calls = []

    result, _ = generate_image_with_retries(
        _previz_generate_fn(tmp_path),
        **_retry_loop_kwargs(tmp_path),
        on_image_generated=calls.append,
    )

    assert len(calls) == 1
    assert calls[0] == result


def _rejecting_generate_fn(out_dir, image_name="previz.png"):
    """A generate_fn that writes a real file each call, like the real one."""
    counter = {"n": 0}

    def _generate():
        counter["n"] += 1
        path = out_dir / image_name
        path.write_bytes(f"image bytes {counter['n']}".encode())
        # A list, since docs/decisions/0046 made every generate_fn return
        # candidates rather than a single result.
        return [PrevizResult(image_path=path, prompt_used=f"prompt {counter['n']}")]

    return _generate


def test_rejected_attempts_survive_a_second_cycle_on_the_same_beat(tmp_path):
    """Regression test for a real data-loss bug found in a paid run.

    A (r)eroll, or an (e)dit-and-retry whose attempts then fail, starts a
    fresh `generate_image_with_retries` call against the same directory
    and the same `archive_prefix`. Its attempt counter restarts at 1, so
    it reused `<prefix>_1_rejected.png` -- and `Path.rename` replaces the
    destination silently on POSIX, destroying the earlier cycle's already
    paid-for images with no warning.
    """
    out_dir = tmp_path / "beat_1"
    out_dir.mkdir()
    common = {
        "out_dir": out_dir,
        "archive_prefix": "beat1_attempt",
    }

    # One generator across both cycles, so every image has distinct bytes
    # and an overwrite can't hide behind identical content.
    generate_fn = _rejecting_generate_fn(out_dir)
    for _ in range(2):
        generate_image_with_retries(
            generate_fn,
            # Keep saying retry so every attempt is archived, which is
            # what this test is about.
            on_reviewed=lambda concern, attempt: "continue",
            **common,
        )

    archived = sorted(p.name for p in out_dir.glob("*_rejected.png"))
    assert len(archived) == 6, (
        f"expected both cycles' 3 rejected attempts to survive, found {archived}"
    )
    # Every archived file must have distinct content -- an overwrite would
    # leave the right count only if names collided, so check bytes too.
    assert len({(out_dir / name).read_bytes() for name in archived}) == 6


def test_each_finished_beat_is_persisted_immediately(tmp_path):
    """Regression test for a real run that was interrupted partway and
    recorded zero beats in its log, despite two having been accepted and
    paid for. The images survived; the metadata pairing them with their
    prompts -- what --video-gen-from needs -- did not."""
    scene_plan = ScenePlan(
        characters=[], locations=[a_location()], beats=[a_beat(), a_beat(), a_beat()]
    )
    kwargs = _generate_beats_with_choices_kwargs(tmp_path)
    snapshots = []

    generate_beats_with_choices(
        scene_plan,
        character_refs={},
        location_refs={},
        auto_yes=True,
        on_beat_complete=lambda results: snapshots.append(
            [(r["index"], r.get("in_progress", False)) for r in results]
        ),
        **kwargs,
    )

    # Each beat is written while still in flight and again once finished,
    # so an interrupt at any point keeps what was already generated and
    # paid for (docs/decisions/0056).
    assert snapshots[0][-1] == (1, True), "beat 1 must reach disk before it finishes"
    assert (1, False) in snapshots[-1], "and be marked finished once it is"
    # Cumulative every time, and the last write has all three finished.
    assert snapshots[-1] == [(1, False), (2, False), (3, False)]
    # An in-progress beat never lingers once it finishes.
    assert not any(flag for _, flag in snapshots[-1])


def test_a_restarted_cycle_says_so_instead_of_reprinting_the_beat_header(tmp_path, monkeypatch, capsys):
    """A (r)eroll re-enters the same beat's loop. It used to reprint the
    original '=== beat i/N: <action> ===' header, which read as a new beat
    being generated rather than the same one starting over."""
    # An (e)dit restarts the cycle; a plain (r)etry now stays inside it.
    responses = iter(["e", "", "", "", "a"])
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    scene_plan = ScenePlan(characters=[], locations=[a_location()], beats=[a_beat()])
    kwargs = _generate_beats_with_choices_kwargs(tmp_path)

    generate_beats_with_choices(
        scene_plan, character_refs={}, location_refs={}, **kwargs
    )

    out = capsys.readouterr().out
    assert out.count("=== beat 1/1:") == 1, "the full beat header should appear only once"
    assert "restarting, attempt cycle 2" in out


# --- recorded paths must survive a moved outputs/ tree ---


def test_rejected_reference_images_are_kept_not_overwritten(tmp_path, monkeypatch):
    """References wrote to a fixed "reference.png", so rejecting one and
    regenerating destroyed it -- while beats had archived their rejected
    attempts all along. Every rejected reference in a real session of UX
    testing was lost this way."""
    responses = iter(["n", "n", "y"])  # reject twice, accept the third
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    counter = {"n": 0}

    def _image_fn(**kwargs):
        counter["n"] += 1
        return SimpleNamespace(data=[SimpleNamespace(b64_json=TINY_PNG_B64)])

    character_refs, _ = generate_scene_references(
        ScenePlan(characters=[a_character()], locations=[], beats=[]),
        previz_model="gemini/gemini-2.5-flash-image",
        image_kwargs={"image_fn": _image_fn},
        out_dir=tmp_path,
    )

    ref_dir = next(iter(character_refs.values())).parent
    kept = sorted(p.name for p in ref_dir.glob("reference_attempt_*.png"))
    assert kept == ["reference_attempt_1_rejected.png", "reference_attempt_2_rejected.png"]
    assert (ref_dir / "reference.png").exists()


def test_an_accepted_image_the_human_retried_is_kept_not_overwritten(tmp_path, monkeypatch):
    """A human can now retry an image the reviewer was happy with, so that
    image has to be archived like any other superseded attempt rather than
    silently overwritten by the next one."""
    responses = iter(["r", "a"])
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    scene_plan = ScenePlan(characters=[], locations=[a_location()], beats=[a_beat()])
    kwargs = _generate_beats_with_choices_kwargs(tmp_path)

    generate_beats_with_choices(
        scene_plan, character_refs={}, location_refs={}, **kwargs
    )

    archived = list((tmp_path / "beat_1").glob("*_rejected.png"))
    assert len(archived) == 1, f"expected the retried image to be kept, found {archived}"


def test_there_is_no_default_that_spends_money(tmp_path, monkeypatch):
    """Enter used to mean "keep auto-retrying", so the cheapest keystroke
    was the one that spent money. Blank input is now simply re-prompted."""
    responses = iter(["", "   ", "g"])
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    scene_plan = ScenePlan(characters=[], locations=[a_location()], beats=[a_beat()])
    kwargs = _generate_beats_with_choices_kwargs(tmp_path)

    results = generate_beats_with_choices(
        scene_plan, character_refs={}, location_refs={}, **kwargs
    )

    # Two blanks were re-prompted rather than triggering a retry, so only
    # one image was ever generated before the human gave up.
    assert results[0]["image_path"] is None
    assert len(results[0]["attempts"]) == 1


def test_candidates_are_all_generated_and_all_kept(tmp_path, monkeypatch):
    """A real run already spent 1.8 images per beat sequentially, discarding
    each before the next existed. These cost the same and are shown
    together, so none is thrown away unseen."""
    monkeypatch.setattr(
        "builtins.input", lambda prompt: "2" if "Keep which" in prompt else "a"
    )
    scene_plan = ScenePlan(characters=[], locations=[a_location()], beats=[a_beat()])
    kwargs = _generate_beats_with_choices_kwargs(tmp_path)

    results = generate_beats_with_choices(
        scene_plan,
        character_refs={},
        location_refs={},
        candidates=3,
        **kwargs,
    )

    kept = sorted(p.name for p in (tmp_path / "beat_1").glob("candidate_*.png"))
    assert len(kept) == 3, f"every generated candidate should survive, found {kept}"
    assert results[0]["image_path"].endswith("candidate_1_2.png"), "the chosen one is the beat's"


def test_rejecting_every_candidate_rejects_the_attempt_not_the_beat(tmp_path, monkeypatch):
    """"None of them" is a verdict on this attempt. The loop should then
    offer the usual choices rather than silently abandoning the beat."""
    responses = iter(["n", "g"])
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    scene_plan = ScenePlan(characters=[], locations=[a_location()], beats=[a_beat()])
    kwargs = _generate_beats_with_choices_kwargs(tmp_path)

    results = generate_beats_with_choices(
        scene_plan,
        character_refs={},
        location_refs={},
        candidates=2,
        **kwargs,
    )

    assert results[0]["image_path"] is None
    assert results[0]["attempts"][0]["concern"] == "human rejected every candidate"
    # Both are still on disk -- they were paid for.
    assert len(list((tmp_path / "beat_1").glob("candidate_*.png"))) == 2


def test_one_candidate_is_the_previous_behaviour(tmp_path, monkeypatch):
    """The default must not change what an existing run does: one image,
    named previz.png, and no selection prompt."""
    prompts_shown = []

    def _capturing_input(prompt):
        prompts_shown.append(prompt)
        return "a"

    monkeypatch.setattr("builtins.input", _capturing_input)
    scene_plan = ScenePlan(characters=[], locations=[a_location()], beats=[a_beat()])
    kwargs = _generate_beats_with_choices_kwargs(tmp_path)

    generate_beats_with_choices(
        scene_plan, character_refs={}, location_refs={}, **kwargs
    )

    assert (tmp_path / "beat_1" / "previz.png").exists()
    assert not list((tmp_path / "beat_1").glob("candidate_*.png"))
    assert not any("Keep which" in p for p in prompts_shown)


def test_unattended_runs_take_the_first_candidate(tmp_path):
    """--yes has nobody to ask. Taking the first is arbitrary, and is at
    least honest about being arbitrary."""
    scene_plan = ScenePlan(characters=[], locations=[a_location()], beats=[a_beat()])
    kwargs = _generate_beats_with_choices_kwargs(tmp_path)

    results = generate_beats_with_choices(
        scene_plan,
        character_refs={},
        location_refs={},
        auto_yes=True,
        candidates=2,
        **kwargs,
    )

    assert results[0]["image_path"].endswith("candidate_1_1.png")


# --- references are optional (ADR 0047) ---


@pytest.mark.parametrize(
    ("want_character", "want_location", "expect_char", "expect_loc"),
    [(True, True, 1, 1), (False, True, 0, 1), (True, False, 1, 0), (False, False, 0, 0)],
)
def test_reference_generation_can_be_turned_off_per_kind(
    tmp_path, monkeypatch, want_character, want_location, expect_char, expect_loc
):
    """Each reference is a separate hypothesis: a location reference was
    added to stop cross-beat setting drift, a character reference to hold
    identity. Both also pin composition, so they need to be testable apart."""
    monkeypatch.setattr("builtins.input", lambda _: "y")
    calls = {"n": 0}

    def _image_fn(**kwargs):
        calls["n"] += 1
        return SimpleNamespace(data=[SimpleNamespace(b64_json=TINY_PNG_B64)])

    character_refs, location_refs = generate_scene_references(
        ScenePlan(characters=[a_character()], locations=[a_location()], beats=[a_beat()]),
        previz_model="gemini/gemini-2.5-flash-image",
        image_kwargs={"image_fn": _image_fn},
        out_dir=tmp_path,
        want_character=want_character,
        want_location=want_location,
    )

    assert len(character_refs) == expect_char
    assert len(location_refs) == expect_loc
    assert calls["n"] == expect_char + expect_loc, "should not pay for a reference it won't use"


def test_beats_generate_with_no_conditioning_when_references_are_off(tmp_path, monkeypatch):
    """The whole point: every beat prompt already carries the character and
    location text, so nothing is lost but the conditioning images."""
    monkeypatch.setattr("builtins.input", lambda _: "a")
    seen = []

    def _image_fn(**kwargs):
        seen.append(kwargs)
        return SimpleNamespace(data=[SimpleNamespace(b64_json=TINY_PNG_B64)])

    def _edit_fn(**kwargs):
        raise AssertionError("image_edit must not be called with no references")

    scene_plan = ScenePlan(characters=[a_character()], locations=[a_location()], beats=[a_beat()])
    kwargs = _generate_beats_with_choices_kwargs(tmp_path, image_fn=_image_fn)
    kwargs["image_kwargs"]["edit_fn"] = _edit_fn

    results = generate_beats_with_choices(
        scene_plan,
        character_refs={},
        location_refs={},
        **kwargs,
    )

    assert results[0]["image_path"] is not None
    # The character's own description still reaches the model as text.
    assert "white crop top" in seen[0]["prompt"]
