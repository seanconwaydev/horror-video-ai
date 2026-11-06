"""The short flow's two gates: nothing generates from unreviewed shots,
and a bake-off does not tell you which video came from which vendor."""

import json

import pytest

from horror_video_ai.cli.short import run_bakeoff, run_short_generation
from horror_video_ai.stages.shot_writing import Shot, ShotList
from horror_video_ai.video_backends._http import VideoBackendError

LOOK = "IR night-vision security cam, locked off high in a corner. Camera static."


def _write_shots(tmp_path, *, count=2, prompt="A door creeps open. Audio: hiss."):
    shot_list = ShotList(
        shots=[Shot(prompt=prompt, duration_seconds=4) for _ in range(count)],
        look=LOOK,
        negative_prompt="nude, naked",
    )
    path = tmp_path / "shots.json"
    path.write_text(shot_list.to_json())
    return path


def test_generation_writes_the_video_and_its_payload(tmp_path):
    shots = _write_shots(tmp_path)
    run_short_generation(shots, backend_name="veo", mock=True, auto_yes=True)
    assert (tmp_path / "veo" / "short.mp4").read_bytes()
    assert json.loads((tmp_path / "veo" / "payloads.json").read_text())


def test_declining_the_confirmation_spends_nothing(tmp_path, monkeypatch):
    shots = _write_shots(tmp_path)
    monkeypatch.setattr("builtins.input", lambda *_: "n")
    run_short_generation(shots, backend_name="veo", mock=True)
    assert not (tmp_path / "veo").exists()


def test_unreadable_shots_file_fails_loud(tmp_path):
    bad = tmp_path / "shots.json"
    bad.write_text("{not json")
    with pytest.raises(Exception, match="Unusable shot list"):
        run_short_generation(bad, backend_name="veo", mock=True, auto_yes=True)


def test_bakeoff_hides_which_vendor_made_which_video(tmp_path):
    """The labelled directories a human browses must not name a vendor --
    not in a filename, not in a payload. Judging a video you know cost
    more is not a neutral act."""
    shots = _write_shots(tmp_path)
    run_bakeoff(shots, mock=True, auto_yes=True)

    bakeoff = tmp_path / "bakeoff"
    labels = sorted(p.name for p in bakeoff.iterdir() if p.is_dir() and p.name != "reveal")
    assert labels == ["A", "B", "C"]
    for label in labels:
        assert (bakeoff / label / "short.mp4").exists()
        # Only the video. The payload names the model, so it lives under reveal/.
        assert [p.name for p in (bakeoff / label).iterdir()] == ["short.mp4"]

    key = json.loads((bakeoff / "reveal" / "key.json").read_text())
    assert sorted(key) == ["A", "B", "C"]
    assert sorted(key.values()) == ["kling", "veo", "wan"]


def test_bakeoff_label_assignment_is_actually_shuffled(tmp_path):
    """A stable mapping would make the blinding decorative."""
    import random

    mappings = set()
    for seed in range(12):
        target = tmp_path / f"run{seed}"
        target.mkdir()
        shots = _write_shots(target)
        run_bakeoff(shots, mock=True, auto_yes=True, rng=random.Random(seed))
        key = json.loads((target / "bakeoff" / "reveal" / "key.json").read_text())
        mappings.add(tuple(sorted(key.items())))
    assert len(mappings) > 1


def test_bakeoff_skips_a_backend_that_cannot_take_the_shots(tmp_path, monkeypatch):
    shots = _write_shots(tmp_path)

    from horror_video_ai.cli import short as short_module

    real_backend = short_module._backend

    def broken(name, *, resolution, mock):
        backend = real_backend(name, resolution=resolution, mock=mock)
        if name == "kling":
            backend.validate = lambda _: ["too long"]  # type: ignore[method-assign]
        return backend

    monkeypatch.setattr(short_module, "_backend", broken)
    run_bakeoff(shots, mock=True, auto_yes=True)
    key = json.loads((tmp_path / "bakeoff" / "reveal" / "key.json").read_text())
    assert "kling" not in key.values()
    assert len(key) == 2


def test_bakeoff_with_no_usable_backend_spends_nothing(tmp_path, monkeypatch):
    shots = _write_shots(tmp_path)

    from horror_video_ai.cli import short as short_module

    def all_broken(name, *, resolution, mock):
        backend = short_module._MockBackend(name)
        backend.validate = lambda _: ["nope"]  # type: ignore[method-assign]
        return backend

    monkeypatch.setattr(short_module, "_backend", all_broken)
    with pytest.raises(VideoBackendError, match="No backend"):
        run_bakeoff(shots, mock=True, auto_yes=True)
    assert not (tmp_path / "bakeoff").exists()


def test_planning_writes_a_shots_file_and_generates_nothing(tmp_path, monkeypatch):
    """--short is the half that is cheap. It must stop before any video."""
    from horror_video_ai.cli import runlog
    from horror_video_ai.cli.short import run_short_planning
    from horror_video_ai.stages.scene_planning import Scene

    monkeypatch.setattr(runlog, "project_root", lambda: tmp_path)
    shots_path = run_short_planning(
        Scene(time="night", place="a bedroom", description="someone is in the doorway"),
        genre="horror",
        tone="dread",
        mock=True,
    )
    shot_list = ShotList.from_json(shots_path.read_text())
    assert shot_list.total_seconds == 15
    assert shot_list.shots
    assert not list(shots_path.parent.glob("**/*.mp4"))

    log = json.loads((shots_path.parent / "run_log.json").read_text())
    assert log["shots"]["shots"]
    assert log["shot_writer_model"]
