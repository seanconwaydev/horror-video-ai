"""Stage 9 run standalone against a finished previz run
(cli/video_gen.py, --video-gen-from).

Split out of test_cli.py alongside the module itself. Everything here
builds a run directory on disk first, because that is the module's only
input -- it never receives a live pipeline's objects.
"""

import json
import shutil
from pathlib import Path

import pytest
from PIL import Image

from historical_video_ai.cli.video_gen import (
    check_video_prompt_practices,
    load_previz_output,
    load_video_gen_targets,
    run_video_generation_only,
)


def _write_previz_run_log(run_dir, *, image_path=None, prompt="A prompt from previz."):
    run_dir.mkdir(parents=True, exist_ok=True)
    if image_path is None:
        image_path = run_dir / "previz.png"
        # A real 9:16 PNG standing in for a previz output. The video
        # stage no longer opens it (docs/decisions/0038), but the run log
        # it's referenced from is read by code that does.
        Image.new("RGB", (720, 1280), color="blue").save(image_path, format="PNG")
    log = {"previz_image_path": str(image_path), "previz_prompt_used": prompt}
    (run_dir / "run_log.json").write_text(json.dumps(log))
    return image_path


def test_load_previz_output_returns_image_path_and_prompt(tmp_path):
    run_dir = tmp_path / "run_1"
    image_path = _write_previz_run_log(run_dir, prompt="Scene one's prompt.")

    result_image_path, prompt = load_previz_output(run_dir)

    assert result_image_path == image_path
    assert prompt == "Scene one's prompt."


def test_load_previz_output_prompt_override_replaces_saved_prompt(tmp_path):
    # --video-prompt: test a hand-written prompt against an already-
    # approved image without a fresh previz pass. Image path still comes
    # from the saved run -- only the prompt text is substituted.
    run_dir = tmp_path / "run_1"
    image_path = _write_previz_run_log(run_dir, prompt="Scene one's prompt.")

    result_image_path, prompt = load_previz_output(
        run_dir, prompt_override="A hand-written video-specific prompt."
    )

    assert result_image_path == image_path
    assert prompt == "A hand-written video-specific prompt."


def test_load_previz_output_raises_when_no_run_log(tmp_path):
    run_dir = tmp_path / "run_missing"
    run_dir.mkdir()

    with pytest.raises(FileNotFoundError, match="No run_log.json"):
        load_previz_output(run_dir)


def test_load_previz_output_raises_when_previz_incomplete(tmp_path):
    run_dir = tmp_path / "run_incomplete"
    run_dir.mkdir()
    (run_dir / "run_log.json").write_text(json.dumps({"time": "1969"}))

    with pytest.raises(ValueError, match="no completed previz result"):
        load_previz_output(run_dir)


def test_load_previz_output_raises_when_image_file_missing(tmp_path):
    run_dir = tmp_path / "run_stale"
    run_dir.mkdir()
    missing_image = run_dir / "previz.png"
    log = {"previz_image_path": str(missing_image), "previz_prompt_used": "A prompt."}
    (run_dir / "run_log.json").write_text(json.dumps(log))

    with pytest.raises(FileNotFoundError, match="no longer exists"):
        load_previz_output(run_dir)


def _write_beat_image(run_dir, name, *, action="checks her phone") -> dict:
    beat_dir = run_dir / name
    beat_dir.mkdir(parents=True, exist_ok=True)
    image_path = beat_dir / "previz.png"
    Image.new("RGB", (720, 1280), color="blue").save(image_path, format="PNG")
    return {
        "index": int(name.split("_")[1]),
        "beat": {"action": action},
        "image_path": str(image_path),
        "prompt_used": f"Prompt for {name}.",
        "attempts": [{"attempt": 1, "accepted": True, "concern": None}],
    }


def _write_multi_beat_run_log(run_dir, *, beats=None):
    """A new-style scene-plan run (docs/decisions/0023/0024) -- one
    real image per accepted beat, mirroring _generate_beats_with_choices's
    actual output shape."""
    run_dir.mkdir(parents=True, exist_ok=True)
    if beats is None:
        beats = [_write_beat_image(run_dir, "beat_1"), _write_beat_image(run_dir, "beat_2")]
    log = {"previz_beats": beats}
    (run_dir / "run_log.json").write_text(json.dumps(log))
    return beats


def test_load_video_gen_targets_old_style_returns_single_target(tmp_path):
    run_dir = tmp_path / "run_old"
    image_path = _write_previz_run_log(run_dir, prompt="Scene A's prompt.")

    targets = load_video_gen_targets(run_dir)

    assert len(targets) == 1
    assert targets[0].image_path == image_path
    assert targets[0].prompt_used == "Scene A's prompt."
    assert targets[0].output_dir == run_dir
    assert targets[0].beat_index is None


def test_load_video_gen_targets_multi_beat_returns_one_target_per_accepted_beat(tmp_path):
    run_dir = tmp_path / "run_new"
    beats = _write_multi_beat_run_log(run_dir)

    targets = load_video_gen_targets(run_dir)

    assert len(targets) == 2
    assert targets[0].image_path == Path(beats[0]["image_path"])
    assert targets[0].prompt_used == "Prompt for beat_1."
    assert targets[0].output_dir == Path(beats[0]["image_path"]).parent
    assert targets[0].beat_index == 1
    assert targets[1].beat_index == 2


def test_load_video_gen_targets_skips_beats_with_no_accepted_image(tmp_path):
    run_dir = tmp_path / "run_new"
    accepted = _write_beat_image(run_dir, "beat_1")
    rejected = {
        "index": 2,
        "beat": {"action": "rejected beat"},
        "image_path": None,
        "attempts": [{"attempt": 1, "accepted": False, "concern": "Anachronism."}] * 3,
    }
    _write_multi_beat_run_log(run_dir, beats=[accepted, rejected])

    targets = load_video_gen_targets(run_dir)

    assert len(targets) == 1
    assert targets[0].beat_index == 1


def test_load_video_gen_targets_raises_when_no_beat_has_an_accepted_image(tmp_path):
    run_dir = tmp_path / "run_new"
    rejected = {
        "index": 1,
        "beat": {"action": "rejected beat"},
        "image_path": None,
        "attempts": [],
    }
    _write_multi_beat_run_log(run_dir, beats=[rejected])

    with pytest.raises(ValueError, match="no beat produced an accepted image"):
        load_video_gen_targets(run_dir)


def test_load_video_gen_targets_raises_when_accepted_beat_has_no_prompt_used(tmp_path):
    run_dir = tmp_path / "run_new"
    beat = _write_beat_image(run_dir, "beat_1")
    del beat["prompt_used"]
    _write_multi_beat_run_log(run_dir, beats=[beat])

    with pytest.raises(ValueError, match="no recorded 'prompt_used'"):
        load_video_gen_targets(run_dir)


def test_load_video_gen_targets_prompt_override_applies_to_every_beat(tmp_path):
    run_dir = tmp_path / "run_new"
    _write_multi_beat_run_log(run_dir)

    targets = load_video_gen_targets(run_dir, prompt_override="A hand-written prompt.")

    assert all(t.prompt_used == "A hand-written prompt." for t in targets)


def test_run_video_generation_only_generates_one_video_per_beat(tmp_path):
    run_dir = tmp_path / "run_new"
    _write_multi_beat_run_log(run_dir)

    run_video_generation_only([run_dir], mock=True, video_model="replicate/owner/model")

    log = json.loads((run_dir / "run_log.json").read_text())
    assert len(log["previz_beats"][0]["videos"]) == 1
    assert len(log["previz_beats"][1]["videos"]) == 1
    assert list((run_dir / "beat_1").glob("video_*.mp4"))
    assert list((run_dir / "beat_2").glob("video_*.mp4"))


def test_run_video_generation_only_writes_video_into_source_run_dir(tmp_path):
    # The video lands directly in the source previz run's own directory --
    # right next to the previz.png it came from -- rather than a separate
    # new folder that only ever held a copy of the image.
    source_a = tmp_path / "source_run_a"
    source_b = tmp_path / "source_run_b"
    _write_previz_run_log(source_a, prompt="Scene A's prompt.")
    _write_previz_run_log(source_b, prompt="Scene B's prompt.")

    run_video_generation_only([source_a, source_b], mock=True, video_model="replicate/owner/model")

    videos_a = list(source_a.glob("video_*.mp4"))
    videos_b = list(source_b.glob("video_*.mp4"))
    assert len(videos_a) == 1
    assert len(videos_b) == 1
    assert (source_a / "previz.png").exists()  # untouched, still there too


def test_run_video_generation_only_appends_to_existing_run_log(tmp_path):
    # Regression test: this used to write a brand new run_log.json into a
    # separate output folder ("mode": "video_generation_only") instead of
    # extending the scene's own existing log -- fragmenting one scene's
    # history (research through video) across two files in two folders.
    source_a = tmp_path / "source_run_a"
    _write_previz_run_log(source_a, prompt="Scene A's prompt.")
    original_log = json.loads((source_a / "run_log.json").read_text())

    run_video_generation_only([source_a], mock=True, video_model="replicate/owner/model")

    log = json.loads((source_a / "run_log.json").read_text())
    # Everything previz/research/fact-check already wrote is still there.
    assert log["previz_prompt_used"] == original_log["previz_prompt_used"]
    assert len(log["videos"]) == 1
    assert log["videos"][0]["video_generation_model"] == "replicate/owner/model"
    assert Path(log["videos"][0]["video_path"]).parent == source_a


def test_run_video_generation_only_records_prompt_used_per_video(tmp_path):
    source_a = tmp_path / "source_run_a"
    _write_previz_run_log(source_a, prompt="Scene A's prompt.")

    run_video_generation_only([source_a], mock=True, video_model="replicate/owner/model")

    log = json.loads((source_a / "run_log.json").read_text())
    assert log["videos"][0]["prompt_used"] == "Scene A's prompt."


def test_run_video_generation_only_video_prompt_overrides_saved_prompt(tmp_path):
    # --video-prompt: test a hand-written prompt against an already-
    # approved image without a fresh previz pass.
    source_a = tmp_path / "source_run_a"
    _write_previz_run_log(source_a, prompt="Scene A's original previz prompt.")

    run_video_generation_only(
        [source_a],
        mock=True,
        video_model="replicate/owner/model",
        video_prompt="A hand-written, timecoded video prompt.",
    )

    log = json.loads((source_a / "run_log.json").read_text())
    assert log["videos"][0]["prompt_used"] == "A hand-written, timecoded video prompt."
    # The original previz prompt on record is untouched -- only this
    # video attempt used the override.
    assert log["previz_prompt_used"] == "Scene A's original previz prompt."


def test_check_video_prompt_practices_flags_missing_character_block():
    found = check_video_prompt_practices("Just a plain description with no structure.")
    assert any("CHARACTER" in w for w in found)



def test_check_video_prompt_practices_flags_too_many_beats():
    prompt = "CHARACTER: Someone\nAudio: footsteps.\n" + "".join(
        f"({n}-{n + 1}s) Something happens.\n" for n in range(5)
    )
    found = check_video_prompt_practices(prompt)
    assert any("beats" in w for w in found)


def test_check_video_prompt_practices_flags_too_many_beats_with_en_dash_timecodes():
    # Regression test: the playbook's own documented timecode format uses
    # an en-dash ("(0–3s)"), not an ASCII hyphen -- a prompt written
    # exactly that way must still be counted.
    prompt = "CHARACTER: Someone\nAudio: footsteps.\n" + "".join(
        f"({n}–{n + 1}s) Something happens.\n" for n in range(5)
    )
    found = check_video_prompt_practices(prompt)
    assert any("beats" in w for w in found)




def test_check_video_prompt_practices_does_not_flag_horror_vocabulary():
    """Regression test for docs/decisions/0038. These checks used to warn
    about words that had tripped Sora's moderation -- "attack", "weapon",
    "blood" and similar -- which steered prompts away from exactly the
    vocabulary this project's own genre needs. The video model those
    warnings protected against is gone, and so are they."""
    prompt = (
        "CHARACTER: Someone\n"
        "(0-3s) Action: a shape attacks from the dark, a weapon raised, blood on the wall."
    )
    assert check_video_prompt_practices(prompt) == []


def test_check_video_prompt_practices_returns_nothing_for_a_well_formed_prompt():
    prompt = (
        "CHARACTER: Someone\n"
        "ROLE: main\n"
        "(0-3s) Action: walks calmly across a room.\n"
        "Audio: footsteps on wood."
    )
    assert check_video_prompt_practices(prompt) == []


def test_run_video_generation_only_prints_practice_warnings_but_still_generates(
    tmp_path, capsys
):
    # Advisory only -- warnings are printed, generation still proceeds.
    source_a = tmp_path / "source_run_a"
    _write_previz_run_log(source_a, prompt="Scene A's original previz prompt.")

    run_video_generation_only(
        [source_a],
        mock=True,
        video_model="replicate/owner/model",
        video_prompt="No structure at all here.",
    )

    captured = capsys.readouterr()
    assert "doesn't follow known best practice" in captured.out
    assert "CHARACTER" in captured.out
    log = json.loads((source_a / "run_log.json").read_text())
    assert len(log["videos"]) == 1  # still generated despite the warnings


def test_run_video_generation_only_accumulates_multiple_video_attempts(tmp_path):
    # Re-running against the same previz output (e.g. trying a different
    # --video-seconds) should add another video, not overwrite the last one.
    source_a = tmp_path / "source_run_a"
    _write_previz_run_log(source_a, prompt="Scene A's prompt.")

    run_video_generation_only([source_a], mock=True, video_model="replicate/owner/model")
    run_video_generation_only([source_a], mock=True, video_model="replicate/owner/model")

    assert len(list(source_a.glob("video_*.mp4"))) == 2
    log = json.loads((source_a / "run_log.json").read_text())
    assert len(log["videos"]) == 2


def test_video_gen_targets_resolve_after_the_run_folder_is_moved(tmp_path):
    """Run logs record absolute paths, so they embed wherever the project
    lived when the run executed. Moving or copying a run folder -- or
    sharing one -- used to break every reference in it, even though the
    images sit right beside the log."""
    original = tmp_path / "old_home" / "outputs" / "run_20260101-000000_scene"
    (original / "beat_1").mkdir(parents=True)
    image = original / "beat_1" / "previz.png"
    image.write_bytes(b"png")
    (original / "run_log.json").write_text(
        json.dumps(
            {
                "previz_beats": [
                    {
                        "index": 1,
                        "image_path": str(image),
                        "prompt_used": "a prompt",
                    }
                ]
            }
        )
    )

    moved = tmp_path / "new_home" / "outputs" / "run_20260101-000000_scene"
    moved.parent.mkdir(parents=True)
    shutil.move(str(original), str(moved))

    targets = load_video_gen_targets(moved)

    assert len(targets) == 1
    assert targets[0].image_path == moved / "beat_1" / "previz.png"
    assert targets[0].image_path.exists()
