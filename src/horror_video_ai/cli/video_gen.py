"""Stage 9, run standalone against a finished previz run (--video-gen-from).

Deliberately not part of the interactive pipeline run: previz is the
spend gate, and video generation should always be a separate, deliberate
invocation (docs/decisions/0010). It reads a run directory back off disk
rather than taking anything in memory, which is why archived runs in the
old single-image shape are still usable here even though nothing
generates that shape any more (docs/decisions/0051).

Every scene gets a free, advisory moderation check before the paid call
(docs/decisions/0038): it reports flagged categories and never blocks,
because horror routinely trips the violence category and this project's
video model has no vendor moderation for it to predict.
"""

from __future__ import annotations

import dataclasses
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from horror_video_ai.cli.mocks import (
    mock_download,
    mock_moderation_policy_check,
    mock_prediction,
)
from horror_video_ai.cli.runlog import read_log, write_log
from horror_video_ai.config import get_stage_model
from horror_video_ai.stages.moderation import run_moderation_policy_check
from horror_video_ai.stages.video_generation import run_video_generation_stage


@dataclasses.dataclass(frozen=True)
class VideoGenTarget:
    """One (image, prompt) pair ready for video generation -- either the
    whole of an old-style single-image run (docs/decisions/0010), or one
    accepted beat within a new-style multi-beat scene-plan run
    (docs/decisions/0023/0024's --video-gen-from follow-up).

    `beat_index` is None for the old-style case; for a beat, it locates
    where to record a video/moderation-flag result back in the parent
    run's run_log.json (see _record_video_gen_result) -- nested under
    that beat's own entry, not mixed into one flat list across every beat.
    """

    run_dir: Path
    image_path: Path
    prompt_used: str
    output_dir: Path
    label: str
    beat_index: int | None


def _resolve_recorded_path(recorded: str, run_dir: Path) -> Path:
    """Resolve a path recorded in a run log, tolerating a moved outputs/.

    Run logs store absolute paths, so they embed wherever the project
    happened to live when the run executed. Moving or copying a run folder
    -- or handing one to someone else -- breaks every reference in it, even
    though the files are sitting right beside the log. The gallery
    symlinks were deliberately made relative for exactly this reason
    (cli/beats.py's `link_beat_into_gallery`); the log was not.

    The portion of a recorded path after the run directory's own name is
    still correct relative to wherever that directory is now, so fall back
    to that. Returns the original path unchanged if neither resolves, so
    the caller's error message still names what it actually looked for.
    """
    path = Path(recorded)
    if path.exists():
        return path
    parts = path.parts
    if run_dir.name in parts:
        candidate = run_dir.joinpath(*parts[parts.index(run_dir.name) + 1 :])
        if candidate.exists():
            return candidate
    return path


def load_video_gen_targets(
    run_dir: Path, *, prompt_override: str | None = None
) -> list[VideoGenTarget]:
    """Expand one run_dir into its video-generation targets. A new-style
    run (a "previz_beats" list in its run_log.json, docs/decisions/0023)
    produces one target per beat that has an accepted image -- a beat
    with no accepted image (every previz_review attempt was rejected) is
    silently skipped, not an error, since that's a real, expected
    per-beat outcome. An old-style run (docs/decisions/0010) produces a
    single target, via load_previz_output unchanged.

    Raises FileNotFoundError if run_dir has no run_log.json or a
    referenced image no longer exists, and ValueError if there's no
    completed previz result to work from (old-style: see
    load_previz_output; new-style: no beat produced an accepted image,
    or an accepted beat has no recorded prompt_used -- a run from before
    docs/decisions/0024 started saving it).
    """
    log_path = run_dir / "run_log.json"
    if not log_path.exists():
        raise FileNotFoundError(f"No run_log.json found in {run_dir}")
    data = json.loads(log_path.read_text())

    if "previz_beats" not in data:
        image_path, prompt_used = load_previz_output(run_dir, prompt_override=prompt_override)
        return [
            VideoGenTarget(
                run_dir=run_dir,
                image_path=image_path,
                prompt_used=prompt_used,
                output_dir=run_dir,
                label=run_dir.name,
                beat_index=None,
            )
        ]

    targets = []
    for beat_result in data["previz_beats"]:
        if beat_result.get("image_path") is None:
            continue
        index = beat_result["index"]
        prompt_used = prompt_override or beat_result.get("prompt_used")
        if not prompt_used:
            raise ValueError(
                f"{log_path}: beat {index} has an accepted image but no recorded "
                "'prompt_used' -- pass --video-prompt, or point --video-gen-from at a run "
                "generated after docs/decisions/0024 started recording it."
            )
        image_path = _resolve_recorded_path(beat_result["image_path"], run_dir)
        if not image_path.exists():
            raise FileNotFoundError(
                f"Beat {index}'s image referenced by {log_path} no longer exists: {image_path}"
            )
        targets.append(
            VideoGenTarget(
                run_dir=run_dir,
                image_path=image_path,
                prompt_used=prompt_used,
                output_dir=image_path.parent,
                label=f"{run_dir.name} beat {index}",
                beat_index=index,
            )
        )
    if not targets:
        raise ValueError(
            f"{log_path} has a scene plan but no beat produced an accepted image -- "
            "nothing to generate video from."
        )
    return targets


def _record_video_gen_result(
    target: VideoGenTarget, key: str, entry: dict, *, supersede_on: str | None = None
) -> None:
    """Append `entry` to list `key` in this target's run_log.json -- at
    the top level for an old-style single-image run, or nested under the
    matching beat's own entry in "previz_beats" for a new-style
    multi-beat run, so a beat's video/moderation history stays co-located
    with that beat's own record instead of mixed into one flat list
    across every beat.

    `supersede_on` names a field that identifies one attempt across
    several writes: an existing entry carrying the same value is replaced
    rather than a second one appended. That is what lets a clip be
    recorded the moment it exists on Replicate and then filled in once it
    is on disk, without the log growing two entries per video
    (docs/decisions/0056's "later writes for the same attempt supersede
    earlier ones", applied to stage 9 -- see docs/decisions/0068).
    """

    def _merge(entries: list) -> None:
        if supersede_on is not None:
            marker = entry.get(supersede_on)
            for i, existing in enumerate(entries):
                if marker and existing.get(supersede_on) == marker:
                    entries[i] = entry
                    return
        entries.append(entry)

    log = read_log(target.run_dir)
    if target.beat_index is None:
        _merge(log.setdefault(key, []))
    else:
        for beat_result in log["previz_beats"]:
            if beat_result["index"] == target.beat_index:
                _merge(beat_result.setdefault(key, []))
                break
    write_log(target.run_dir, log)


def load_previz_output(run_dir: Path, *, prompt_override: str | None = None) -> tuple[Path, str]:
    """Load a previously generated previz image and its prompt from an
    existing run's run_log.json, so --video-gen-from can run stage 9
    standalone instead of requiring a fresh planning/previz pass every
    time (docs/decisions/0010).

    `prompt_override` (--video-prompt), if given, is returned instead of
    the saved previz prompt -- lets a hand-written, video-specific prompt
    be tested against an already-approved image without a fresh (and
    separately costly) previz pass. Still requires the run to have a
    valid image on disk; only the *text* is substituted.

    Raises FileNotFoundError if run_dir has no run_log.json or the image
    it references no longer exists, and ValueError if the log doesn't show
    a completed previz result.
    """
    log_path = run_dir / "run_log.json"
    if not log_path.exists():
        raise FileNotFoundError(f"No run_log.json found in {run_dir}")

    data = json.loads(log_path.read_text())
    image_path_str = data.get("previz_image_path")
    prompt_used = prompt_override or data.get("previz_prompt_used")
    if not image_path_str or not prompt_used:
        raise ValueError(
            f"{log_path} has no completed previz result (missing "
            "'previz_image_path' or 'previz_prompt_used') -- point "
            "--video-gen-from at a run that finished previz successfully."
        )

    image_path = _resolve_recorded_path(image_path_str, run_dir)
    if not image_path.exists():
        raise FileNotFoundError(
            f"Previz image referenced by {log_path} no longer exists: {image_path}"
        )

    return image_path, prompt_used


# Research found 2-3 sequential beats is the practical ceiling for one
# generation call before quality degrades (docs/playbook/video-generation-
# prompting.md) -- flagged, not enforced, since a human may have a good
# reason to try more anyway.
MAX_RECOMMENDED_BEATS = 3


def check_video_prompt_practices(prompt: str) -> list[str]:
    """Cheap, mechanical checks against docs/playbook/video-generation-
    prompting.md's findings -- advisory only, never blocks a run. Exists
    because a hand-written --video-prompt is free-form text with no
    structure enforced anywhere, and it's easy to leave out something the
    playbook already learned the hard way (a real run did exactly this).
    Deliberately narrow: flags concrete, objectively-checkable omissions
    (no character block, too many beats crammed into one call) rather than
    judging actual prompt quality, which isn't something this can do
    reliably and isn't its job -- a human still decides whether to proceed.

    Two checks were removed in docs/decisions/0038 when the video model
    changed: an audio-direction check (Wan generates no audio at all, so
    asking a prompt to describe sound is dead weight until a real
    sound-design step exists) and a list of words that had tripped Sora's
    moderation -- "fight", "attack", "blood", "weapon" and similar. That
    list steered prompts away from the exact vocabulary this project's own
    genre needs, and the model it was protecting against is gone.
    """
    found = []
    if "CHARACTER:" not in prompt:
        found.append(
            "no 'CHARACTER:' block -- character consistency across beats relies on "
            "reusing one verbatim"
        )
    # [-–] not just "-": the playbook's own documented timecode format
    # ("(0–3s)") uses an en-dash, not an ASCII hyphen -- an ASCII-only
    # pattern silently counted zero beats in a prompt written exactly the
    # way the playbook shows.
    beat_count = len(re.findall(r"\(\d+[-–]\d+s\)", prompt))
    if beat_count > MAX_RECOMMENDED_BEATS:
        found.append(
            f"{beat_count} timecoded beats in one prompt -- {MAX_RECOMMENDED_BEATS} is "
            "the practical ceiling before quality degrades; consider a separate image + "
            "generation per beat instead"
        )
    return found


def run_video_generation_only(
    run_dirs: list[Path],
    *,
    mock: bool,
    video_model: str | None = None,
    video_seconds: float | None = None,
    video_prompt: str | None = None,
) -> None:
    """Run stage 9 (video generation) standalone against one or more
    already-completed previz outputs, skipping planning and previz for
    this invocation (docs/decisions/0010). Each run_dir expands into
    one or more `VideoGenTarget`s (`load_video_gen_targets`) -- a single
    target for an old-style single-image run, or one target per accepted
    beat for a new-style multi-beat scene-plan run (docs/decisions/0023/
    0024). Blocks and polls each target to completion before starting the
    next (0010's v1 choice, not the SQS fan-out named for this stage in
    0004). Lets VideoGenerationError propagate uncaught, same fail-loud
    convention as every other stage.

    Before each target's paid video-generation call, runs the free
    moderation check (docs/decisions/0038) against the actual image and
    prompt about to be submitted. Flagged categories are printed and
    recorded, and the run continues either way -- this project's genre
    trips the violence category as a matter of course, and the model being
    called has no vendor moderation for the check to predict. It is a
    YouTube-policy signal for the human reading the run log, not a gate.

    `video_seconds`, if given, requests that duration -- validated against
    the model's real supported range before any call (0020, 0038).

    `video_prompt` (--video-prompt), if given, replaces the saved previz
    prompt for every run_dir -- a deliberately simple one-override-for-all
    shape, since this exists for testing one hand-written prompt against
    one (or a few identically-treated) already-approved image(s), not for
    driving several different scenes' worth of independent prompts at
    once. When `video_prompt` is given, it's checked against
    `check_video_prompt_practices` first -- printed as warnings, never
    blocking (docs/decisions/0021) -- since this is free-form hand-written
    text with nothing else enforcing the playbook's own findings on it.

    Each video is written directly into its source run_dir as
    `video_<timestamp>.mp4` -- the timestamp avoids collisions when
    re-running against the same previz output (e.g. a different
    duration), and the scene's existing run_log.json gets a `"videos"`
    list appended to rather than a separate log file, so one folder holds
    a scene's whole history.
    """
    video_kwargs: dict[str, Any] = (
        {"prediction_fn": mock_prediction, "download_fn": mock_download} if mock else {}
    )
    policy_check_kwargs: dict[str, Any] = (
        {"moderation_fn": mock_moderation_policy_check} if mock else {}
    )

    video_model = video_model or get_stage_model("video_generation")

    if video_prompt is not None:
        practice_warnings = check_video_prompt_practices(video_prompt)
        if practice_warnings:
            print("\n--video-prompt doesn't follow known best practice:")
            for warning in practice_warnings:
                print(f"- {warning}")
            print("Proceeding anyway -- this is advisory, not a block.")

    targets = [
        target
        for run_dir in run_dirs
        for target in load_video_gen_targets(run_dir, prompt_override=video_prompt)
    ]

    for i, target in enumerate(targets, start=1):
        print(f"\n--- video generation (model: {video_model}, scene {i}/{len(targets)}) ---")
        print(f"Source: {target.label} (image: {target.image_path})")

        print("Running moderation check (advisory -- docs/decisions/0038)...")
        policy_result = run_moderation_policy_check(
            target.prompt_used, target.image_path, **policy_check_kwargs
        )
        if policy_result.flagged:
            categories = ", ".join(policy_result.flagged_categories)
            print(
                f"Note: omni-moderation-latest flagged [{categories}]. Recorded for "
                "YouTube-policy review; not blocking generation."
            )
            _record_video_gen_result(
                target,
                "moderation_flags",
                {
                    "flagged_categories": policy_result.flagged_categories,
                    "prompt_used": target.prompt_used,
                },
            )

        # Microsecond precision, not just seconds -- two attempts against
        # the same previz output (e.g. comparing --video-seconds values)
        # can easily land in the same second, and a filename collision
        # would silently overwrite the earlier video instead of
        # accumulating both.
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
        # Omitted entirely rather than passed as None when unset, so the
        # stage's own default applies (docs/decisions/0020).
        seconds_kwarg: dict[str, Any] = (
            {"seconds": video_seconds} if video_seconds is not None else {}
        )
        # Written the moment the clip exists on Replicate, before the
        # download that can still fail -- otherwise a dropped connection
        # discards a generated, billed clip leaving nothing that points at
        # it (docs/decisions/0068). Superseded below by the full entry.
        def _record_prediction(
            prediction_id: str, output_url: str, target: VideoGenTarget = target
        ) -> None:
            _record_video_gen_result(
                target,
                "videos",
                {
                    "prediction_id": prediction_id,
                    "output_url": output_url,
                    "video_generation_model": video_model,
                    "prompt_used": target.prompt_used,
                    "mock": mock,
                    "downloaded": False,
                },
                supersede_on="prediction_id",
            )

        result = run_video_generation_stage(
            target.image_path,
            target.prompt_used,
            model=video_model,
            output_dir=target.output_dir,
            output_filename=f"video_{timestamp}.mp4",
            on_prediction=_record_prediction,
            **seconds_kwarg,
            **video_kwargs,
        )
        print(
            f"Video saved to {result.video_path} "
            f"(requested {result.seconds_requested:.2f}s, actual {result.seconds_actual:.2f}s)"
        )

        _record_video_gen_result(
            target,
            "videos",
            {
                "prediction_id": result.prediction_id,
                "video_generation_model": video_model,
                "video_path": str(result.video_path),
                "seconds_requested": result.seconds_requested,
                "seconds_actual": result.seconds_actual,
                "mock": mock,
                "downloaded": True,
                # Recorded per attempt, not just once for the run, so
                # comparing several --video-prompt overrides against the
                # same image stays traceable -- which prompt produced
                # which file -- instead of only the latest being visible.
                "prompt_used": target.prompt_used,
            },
            supersede_on="prediction_id",
        )

    print("\nDone.")
