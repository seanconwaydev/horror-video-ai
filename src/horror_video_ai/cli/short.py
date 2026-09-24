"""The short-form flow: plan shots, let a human edit them, then generate.

Two deliberately separate invocations, for the same reason previz and
video generation are separate (docs/decisions/0010): the planning half is
cheap and the generating half is not, and nothing should be generated
from shots nobody has read.

    horror-video-ai --short ...              # writes shots.json, stops
    horror-video-ai --shots <file> --backend veo
    horror-video-ai --shots <file> --bakeoff

The middle step is a human opening shots.json in an editor. That is the
gate, and it is where the one short worth watching so far actually came
from -- the first machine draft had the threat lunging at the camera.
"""

from __future__ import annotations

import dataclasses
import json
import random
from pathlib import Path
from typing import Any

from horror_video_ai.cli.mocks import (
    mock_scene_planning_completion,
    mock_shot_writer_completion,
    mock_video_bytes,
)
from horror_video_ai.cli.review import confirm
from horror_video_ai.cli.runlog import new_run_dir, slugify, write_log
from horror_video_ai.config import get_stage_model
from horror_video_ai.stages.scene_planning import Scene, run_scene_planning_stage
from horror_video_ai.stages.shot_writing import (
    DEFAULT_TOTAL_SECONDS,
    ShotList,
    run_shot_writing_stage,
)
from horror_video_ai.video_backends import (
    BACKEND_NAMES,
    PORTRAIT_9_16,
    GeneratedVideo,
    VideoBackend,
    VideoBackendError,
    build_backend,
)

# Found footage earns its place: infrared grain, a fixed mount and a
# crushed tonal range are the format's own texture, so the artifacts a
# video model produces read as camera artifacts rather than as mistakes.
# Kept terse because it is repeated inside every shot's character budget.
DEFAULT_LOOK = (
    "IR night-vision security cam, locked off high in a corner, angled down. "
    "Monochrome grey-green, heavy grain, blown highlights. Camera static."
)


class _MockBackend:
    """Stands in for any vendor under --mock: same interface, no network,
    no key, no spend."""

    supports_multishot = True
    max_seconds_per_call = 60

    def __init__(self, name: str) -> None:
        self.name = name
        self.model = f"mock/{name}"

    def validate(self, shot_list: ShotList) -> list[str]:
        return []

    def estimate_cost_usd(self, seconds: int) -> float | None:
        return 0.0

    def generate(
        self, shot_list: ShotList, *, aspect_ratio: str = PORTRAIT_9_16
    ) -> GeneratedVideo:
        return GeneratedVideo(
            data=mock_video_bytes(),
            backend=self.name,
            seconds=shot_list.total_seconds,
            request_payloads=[{"mock": True, "shots": len(shot_list.shots)}],
        )


def _backend(name: str, *, resolution: str, mock: bool) -> VideoBackend:
    return _MockBackend(name) if mock else build_backend(name, resolution=resolution)


def show_shots(shot_list: ShotList) -> None:
    print(f"\n{len(shot_list.shots)} shots, {shot_list.total_seconds}s total")
    print(f"look: {shot_list.look}\n")
    for index, shot in enumerate(shot_list.shots, start=1):
        print(f"  shot {index} ({shot.duration_seconds}s, {len(shot.prompt)} chars)")
        print(f"    {shot.prompt}\n")


def run_short_planning(
    scene: Scene,
    *,
    genre: str,
    tone: str | None,
    look: str = DEFAULT_LOOK,
    total_seconds: int = DEFAULT_TOTAL_SECONDS,
    max_beats: int | None = None,
    mock: bool = False,
) -> Path:
    """Plan a scene, write the shots, and stop before anything is spent.

    Returns the shots file, which is what a human edits next.
    """
    planning_kwargs: dict[str, Any] = (
        {"completion_fn": mock_scene_planning_completion} if mock else {}
    )
    writing_kwargs: dict[str, Any] = (
        {"completion_fn": mock_shot_writer_completion} if mock else {}
    )

    out_dir = new_run_dir(slugify(scene.description))
    log: dict[str, Any] = {
        "time": scene.time,
        "place": scene.place,
        "description": scene.description,
        "genre": genre,
        "tone": tone,
        "look": look,
        "mock": mock,
    }
    write_log(out_dir, log)

    planning_model = get_stage_model("scene_planning")
    log["scene_planning_model"] = planning_model
    print(f"\n--- scene planning (model: {planning_model}) ---")
    plan = run_scene_planning_stage(
        scene,
        model=planning_model,
        max_beats=max_beats,
        genre=genre,
        tone=tone,
        **planning_kwargs,
    )
    log["scene_plan"] = dataclasses.asdict(plan)
    write_log(out_dir, log)
    print(
        f"  {len(plan.characters)} character(s), {len(plan.locations)} location(s), "
        f"{len(plan.beats)} beat(s)"
    )

    writer_model = get_stage_model("shot_writer")
    log["shot_writer_model"] = writer_model
    print(f"\n--- shot writing (model: {writer_model}) ---")
    shot_list = run_shot_writing_stage(
        plan,
        look=look,
        total_seconds=total_seconds,
        model=writer_model,
        **writing_kwargs,
    )
    log["shots"] = dataclasses.asdict(shot_list)
    write_log(out_dir, log)

    shots_path = out_dir / "shots.json"
    shots_path.write_text(shot_list.to_json())
    show_shots(shot_list)
    print(f"Shots written to {shots_path}")
    print("Read them, edit them, then generate with:")
    print(f"  uv run horror-video-ai --shots {shots_path} --backend veo")
    return shots_path


def _describe_cost(backend: VideoBackend, seconds: int) -> str:
    cost = backend.estimate_cost_usd(seconds)
    return "cost unknown" if cost is None else f"~${cost:.2f}"


def _generate_one(
    backend: VideoBackend,
    shot_list: ShotList,
    out_dir: Path,
    *,
    label: str | None = None,
    payloads_dir: Path | None = None,
) -> None:
    # Under a blind label, print the label and NOT the vendor -- otherwise
    # the console narrates the answer the blinding exists to withhold, and
    # payloads.json names the model too, so it is written only once the
    # watching is done (see run_bakeoff).
    name = label or backend.name
    print(f"\n--- {name} ({backend.model if label is None else 'hidden until reveal'}) ---")
    video = backend.generate(shot_list)
    target = out_dir / name
    target.mkdir(parents=True, exist_ok=True)
    (target / "short.mp4").write_bytes(video.data)
    # The payload names the model, so under a blind label it goes beside
    # key.json rather than beside the video a human is about to watch.
    payload_target = (payloads_dir / f"{name}.payloads.json") if payloads_dir else (
        target / "payloads.json"
    )
    payload_target.parent.mkdir(parents=True, exist_ok=True)
    payload_target.write_text(json.dumps(video.request_payloads, indent=1))
    size_mb = len(video.data) / 1_000_000
    print(f"  wrote {target / 'short.mp4'} ({size_mb:.1f} MB, {video.seconds}s)")


def _report_validation(backend: VideoBackend, shot_list: ShotList) -> bool:
    """Print a backend's own limit violations. Returns False if any of
    them is fatal rather than a note -- notes start with "note:"."""
    problems = backend.validate(shot_list)
    fatal = [p for p in problems if not p.startswith("note:")]
    for problem in problems:
        print(f"  {'!' if not problem.startswith('note:') else '-'} {problem}")
    return not fatal


def run_short_generation(
    shots_path: Path,
    *,
    backend_name: str,
    resolution: str = "720p",
    auto_yes: bool = False,
    mock: bool = False,
) -> None:
    """Generate from an already-reviewed shots file, on one backend."""
    shot_list = ShotList.from_json(shots_path.read_text())
    show_shots(shot_list)

    backend = _backend(backend_name, resolution=resolution, mock=mock)
    print(f"Checking {backend.name}'s limits...")
    if not _report_validation(backend, shot_list):
        raise VideoBackendError(
            f"{backend.name} cannot generate this shot list as written -- edit "
            f"{shots_path} and try again. Nothing was spent."
        )

    cost = _describe_cost(backend, shot_list.total_seconds)
    if not confirm(
        f"Generate {shot_list.total_seconds}s on {backend.name} at {resolution} ({cost})?",
        auto_yes=auto_yes,
    ):
        print(f"Stopped. The shots are still in {shots_path}")
        return
    _generate_one(backend, shot_list, shots_path.parent)


def run_bakeoff(
    shots_path: Path,
    *,
    backend_names: tuple[str, ...] = BACKEND_NAMES,
    resolution: str = "720p",
    auto_yes: bool = False,
    mock: bool = False,
    rng: random.Random | None = None,
) -> None:
    """Run one reviewed shot list on every backend and write the results
    under blind labels.

    Labelled A/B/C with the mapping in key.json rather than by vendor
    name, so they can be watched without knowing which is which -- the
    same discipline evals/run_eval.py already applies to images. Judging a
    model you paid more for is not a neutral act.
    """
    shot_list = ShotList.from_json(shots_path.read_text())
    show_shots(shot_list)

    backends = [_backend(name, resolution=resolution, mock=mock) for name in backend_names]
    usable = []
    total_cost = 0.0
    unknown_cost = False
    for backend in backends:
        print(f"\nChecking {backend.name}'s limits...")
        if not _report_validation(backend, shot_list):
            print(f"  skipping {backend.name} -- it cannot generate this shot list")
            continue
        cost = backend.estimate_cost_usd(shot_list.total_seconds)
        if cost is None:
            unknown_cost = True
        else:
            total_cost += cost
        usable.append(backend)

    if not usable:
        raise VideoBackendError(
            f"No backend can generate this shot list -- edit {shots_path}. Nothing was spent."
        )

    estimate = f"~${total_cost:.2f}" + (" plus an unknown" if unknown_cost else "")
    names = ", ".join(b.name for b in usable)
    if not confirm(
        f"Generate {shot_list.total_seconds}s on {len(usable)} backend(s) [{names}] ({estimate})?",
        auto_yes=auto_yes,
    ):
        print(f"Stopped. The shots are still in {shots_path}")
        return

    out_dir = shots_path.parent / "bakeoff"
    out_dir.mkdir(parents=True, exist_ok=True)
    labels = [chr(ord("A") + i) for i in range(len(usable))]
    (rng or random.Random()).shuffle(labels)

    key = {label: backend.name for label, backend in zip(labels, usable, strict=True)}
    # Everything that names a vendor lives under reveal/ -- the key and the
    # request payloads both do -- so the directory a human browses to watch
    # contains only the videos. Written before generating: a run that dies
    # halfway still leaves the mapping for whatever did finish.
    reveal_dir = out_dir / "reveal"
    reveal_dir.mkdir(parents=True, exist_ok=True)
    (reveal_dir / "key.json").write_text(json.dumps(key, indent=1))

    for label, backend in zip(labels, usable, strict=True):
        _generate_one(backend, shot_list, out_dir, label=label, payloads_dir=reveal_dir)

    print(f"\nWatch {', '.join(sorted(labels))} in {out_dir} without looking at")
    print(f"{reveal_dir / 'key.json'}, then reveal.")
