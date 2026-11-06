"""Argument parsing, the run's order and its money gates: main().

What is left of the CLI once each seam moved to its own module: the order
stages run in and the confirmations before each spend live here, the work
itself does not. The beat loop is in beats.py, the review prompts in
review.py, --video-gen-from in video_gen.py, run directories and the run
log in runlog.py, and the --mock fakes in mocks.py.

Collects a scene (time, place, description) and runs it through scene
planning -> previz (docs/decisions/0023). Research and fact-check used to
sit in front of that and were deleted by docs/decisions/0069. Run with
`uv run horror-video-ai`. Every image comes from a beat of the
reviewed scene plan; the single-image path was deleted once scene
planning made it unreachable (docs/decisions/0051), though archived runs
in that older shape are still readable by --video-gen-from.

Flags:
- `--mock`: no network calls, no API keys -- synthetic data for every stage.
- `--video-gen-from <run_dir> [...]`: runs stage 9 standalone against one
  or more completed previz outputs (docs/decisions/0010), writing each
  video into its source run_dir and appending to that run's existing log.
- `--video-seconds`: requests a clip duration, validated against the
  video model's real supported range before any API call
  (docs/decisions/0020, 0038).
- `--video-prompt`: overrides the saved previz prompt for --video-gen-from,
  to test a hand-written prompt against an already-approved image.
- `--yes`: non-interactive -- auto-confirms every prompt and takes the
  first candidate at each beat (docs/decisions/0017). Note
  that --yes is a deliberately secondary mode: the interactive path is
  where design effort goes (docs/decisions/0043).

Every --video-gen-from scene runs a free, advisory moderation check
(docs/decisions/0038, stages/moderation.py) before the paid video-
generation call. It reports flagged categories and never blocks -- horror
routinely trips the violence category, and this project's video model has
no vendor moderation for it to predict.
"""

from __future__ import annotations

import argparse
import dataclasses
from pathlib import Path
from typing import Any

from horror_video_ai.cli.beats import (
    beat_gallery_dir,
    generate_beats_with_choices,
    generate_scene_references,
)
from horror_video_ai.cli.mocks import (
    mock_image,
    mock_image_edit,
    mock_scene_planning_completion,
)
from horror_video_ai.cli.review import (
    confirm,
    prompt_if_missing,
    review_scene_plan,
)
from horror_video_ai.cli.runlog import (
    new_run_dir,
    slugify,
    write_log,
)
from horror_video_ai.cli.short import (
    DEFAULT_LOOK,
    run_bakeoff,
    run_short_generation,
    run_short_planning,
)
from horror_video_ai.cli.video_gen import (
    run_video_generation_only,
)
from horror_video_ai.config import get_stage_model, load_environment
from horror_video_ai.stages.previz import (
    DEFAULT_STYLE,
    PHOTOREAL_STYLES,
    STYLE_PRESETS,
)
from horror_video_ai.stages.scene_planning import (
    Scene,
    run_scene_planning_stage,
)
from horror_video_ai.stages.shot_writing import DEFAULT_TOTAL_SECONDS
from horror_video_ai.stages.video_generation import (
    MAX_VIDEO_SECONDS,
    MIN_VIDEO_SECONDS,
)
from horror_video_ai.video_backends import BACKEND_NAMES

# Real, checked per-image costs (docs/decisions/0024) -- never a guessed
# number. Keyed by the exact pinned model string, so a config change that
# swaps the previz model automatically falls back to "cost unknown" rather
# than silently reporting a stale price for a different model.
_KNOWN_IMAGE_MODEL_COSTS_USD = {
    "gemini/gemini-3.1-flash-lite-image": 0.0336,
    # Shut down 2026-10-02 (docs/decisions/0079). Kept so replaying an
    # archived run reports what that run actually cost.
    "gemini/gemini-2.5-flash-image": 0.039,
}


def _estimate_image_cost(model: str, count: int) -> str:
    """A short cost-visibility string for `count` images from `model` --
    "$X.XX total" if the model's per-image cost is known, otherwise an
    honest "cost unknown" rather than a fabricated number."""
    cost = _KNOWN_IMAGE_MODEL_COSTS_USD.get(model)
    if cost is None:
        return f"{count} image(s) at an unknown per-image cost for {model}"
    return f"{count} image(s) at ~${cost:.3f} each (~${cost * count:.2f} total)"


def _build_arg_parser() -> argparse.ArgumentParser:
    """The CLI's argument parser, split out of main() so flag defaults
    are testable without running a pipeline (docs/decisions/0050)."""
    parser = argparse.ArgumentParser(
        description="Plan a scene into beats, then generate a previz image for each."
    )
    parser.add_argument("--time", help="When the scene takes place, e.g. 'present day'. A setting, not a claim about the world.")
    parser.add_argument("--place", help="Where the scene takes place.")
    parser.add_argument("--description", help="What the main character does, third person.")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="No network calls, no API keys -- exercise the pipeline's mechanics only.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help=(
            "Non-interactive: auto-confirm every 'Proceed?' prompt and "
            "take the first candidate at each beat. "
            "--time/--place/--description must be given as "
            "flags in this mode -- there's nothing sensible to prompt for "
            "interactively. See docs/decisions/0017-non-interactive-mode.md."
        ),
    )
    parser.add_argument(
        "--video-gen-from",
        type=Path,
        nargs="+",
        metavar="RUN_DIR",
        help=(
            "Run stage 9 (video generation) standalone against one or more "
            "existing run output directories that already completed previz "
            "-- each becomes one scene's anchor image + prompt. Skips "
            "scene planning and previz entirely for this invocation. "
            "Combine with --mock to exercise the polling loop "
            "without a real API call."
        ),
    )
    parser.add_argument(
        "--short",
        action="store_true",
        help=(
            "Plan a short: scene planning then shot writing, ending with a "
            "shots.json to read and edit. Generates nothing and spends nothing "
            "beyond the two text calls. Generate from the result with --shots."
        ),
    )
    parser.add_argument(
        "--shots",
        type=Path,
        metavar="FILE",
        help=(
            "Generate video from an already-written (and ideally hand-edited) "
            "shots.json. This is the spend gate: nothing is generated from shots "
            "a human has not read."
        ),
    )
    parser.add_argument(
        "--backend",
        choices=BACKEND_NAMES,
        default="veo",
        help=(
            "Which vendor to generate on, reached directly rather than through "
            "an aggregator. Defaults to veo, the only one needing no new account."
        ),
    )
    parser.add_argument(
        "--bakeoff",
        action="store_true",
        help=(
            "With --shots, generate the same shots on every backend and write "
            "them under blind A/B/C labels with the mapping in key.json."
        ),
    )
    parser.add_argument(
        "--resolution",
        choices=("720p", "1080p"),
        default="720p",
        help="Output resolution for --shots. 720p is the cheaper default.",
    )
    parser.add_argument(
        "--total-seconds",
        type=int,
        default=DEFAULT_TOTAL_SECONDS,
        help=f"Target runtime for --short (default {DEFAULT_TOTAL_SECONDS}).",
    )
    parser.add_argument(
        "--look",
        default=DEFAULT_LOOK,
        help="The visual style restated at the head of every shot, for --short.",
    )
    parser.add_argument(
        "--video-seconds",
        type=float,
        help=(
            "Requested clip duration in seconds (only used with "
            "--video-gen-from). The video model accepts a narrow range "
            f"({MIN_VIDEO_SECONDS:.2f}-{MAX_VIDEO_SECONDS:.2f}s); anything "
            "outside it is rejected before any API call "
            "(docs/decisions/0020, 0038). Defaults to the stage's own "
            "default if not given."
        ),
    )
    parser.add_argument(
        "--video-prompt",
        help=(
            "Override the saved previz prompt with this text for "
            "--video-gen-from (applied to every RUN_DIR given). Lets a "
            "hand-written, video-specific prompt be tested against an "
            "already-approved previz image without paying for a fresh "
            "planning/previz pass just to change the wording."
        ),
    )
    parser.add_argument(
        "--genre",
        default="horror",
        help=(
            "What kind of scene this is -- e.g. 'horror', 'meme', 'vlog', "
            "'kids-content', 'abstract'. Free text, not a fixed list: fed "
            "into scene-planning's prompt to inform staging and convention "
            "choices (docs/decisions/0035), and routing the composition "
            "and threat rules (0036, 0060). Nothing is grounded in "
            "real-world research any more (docs/decisions/0069), so no "
            "value is special here -- 'historical' is just another genre."
        ),
    )
    parser.add_argument(
        "--tone",
        default=None,
        help=(
            "The scene's tone -- e.g. 'comedic', 'ironic', 'sincere', "
            "'dramatic', 'wholesome'. Free text, fed into scene-planning's "
            "prompt to inform staging, expression, and wardrobe choices. "
            "Unset means the model infers tone from the description alone, "
            "same as before this flag existed."
        ),
    )
    parser.add_argument(
        "--style",
        choices=sorted(STYLE_PRESETS),
        default=DEFAULT_STYLE,
        help=(
            "Art style for every reference and beat image in this run, and "
            "the ONLY thing that sets it (docs/decisions/0033, 0039). Each "
            "preset is a single committed direction -- pick one per run and "
            "vary between runs, rather than asking for several at once. "
            f"Defaults to {DEFAULT_STYLE}. Photoreal presets "
            f"({', '.join(sorted(PHOTOREAL_STYLES))}) are supported but "
            "measurably more likely to have violent scenes silently refused "
            "by the image model -- see docs/playbook/failure-taxonomy.md."
        ),
    )
    parser.add_argument(
        "--references",
        choices=["both", "location", "character", "none"],
        default="none",
        help=(
            "Which reference images to condition beats on (docs/decisions/0024, 0047, "
            "0050). Defaults to 'none': a measured run held style, camera variety and "
            "the location's fixed props with no references at all, so they were being "
            "paid for twice over -- in money, and in the composition they pin. 'both' "
            "is the pre-0050 behaviour; the middle options condition on one or the "
            "other."
        ),
    )
    parser.add_argument(
        "--candidates",
        type=int,
        default=1,
        metavar="N",
        help=(
            "Generate N images per beat attempt and choose between them, "
            "instead of one at a time (docs/decisions/0046). A real run "
            "already spent 1.8 images per beat sequentially, discarding each "
            "before seeing the next -- this costs about the same and lets you "
            "pick. Defaults to 1, which is the previous behaviour."
        ),
    )
    parser.add_argument(
        "--max-beats",
        type=int,
        help=(
            "Cap the scene-planning stage at this many beats -- passed to "
            "the model as a soft target and enforced afterward by "
            "truncation, so the cost-control guarantee doesn't depend on "
            "the model honoring the instruction. Useful while iterating "
            "on image/video quality, to keep a run's image-generation "
            "spend small (e.g. 3-5 instead of a full 10+ beat scene). "
            "Unset means no cap, the model's own judgment decides."
        ),
    )
    return parser


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    if not args.mock:
        load_environment()

    if args.shots:
        if args.bakeoff:
            run_bakeoff(
                args.shots,
                resolution=args.resolution,
                auto_yes=args.yes,
                mock=args.mock,
            )
        else:
            run_short_generation(
                args.shots,
                backend_name=args.backend,
                resolution=args.resolution,
                auto_yes=args.yes,
                mock=args.mock,
            )
        return

    if args.short:
        run_short_planning(
            Scene(
                time=prompt_if_missing(args.time, "Time", auto_yes=args.yes),
                place=prompt_if_missing(args.place, "Place", auto_yes=args.yes),
                description=prompt_if_missing(
                    args.description, "What the main character does", auto_yes=args.yes
                ),
            ),
            genre=args.genre,
            tone=args.tone,
            look=args.look,
            total_seconds=args.total_seconds,
            max_beats=args.max_beats,
            mock=args.mock,
        )
        return

    if args.video_gen_from:
        run_video_generation_only(
            args.video_gen_from,
            mock=args.mock,
            video_seconds=args.video_seconds,
            video_prompt=args.video_prompt,
        )
        return

    # run_reference_image_stage never conditions on other references (it's
    # plain text-to-image), so it only ever takes image_fn -- edit_fn is
    # for run_beat_image_stage specifically, which does condition on
    # character/location references.
    image_kwargs: dict[str, Any] = {"image_fn": mock_image} if args.mock else {}
    beat_image_kwargs = (
        {"image_fn": mock_image, "edit_fn": mock_image_edit} if args.mock else {}
    )
    scene_planning_kwargs: dict[str, Any] = (
        {"completion_fn": mock_scene_planning_completion} if args.mock else {}
    )

    time = prompt_if_missing(args.time, "Time", auto_yes=args.yes)
    place = prompt_if_missing(args.place, "Place", auto_yes=args.yes)
    description = prompt_if_missing(
        args.description, "What the main character does", auto_yes=args.yes
    )
    out_dir = new_run_dir(slugify(description))
    beat_gallery_dir(out_dir)  # exists from the very start -- see its own docstring
    scene = Scene(time=time, place=place, description=description)

    log = {
        "time": time,
        "place": place,
        "description": description,
        "genre": args.genre,
        "tone": args.tone,
        "mock": args.mock,
    }
    write_log(out_dir, log)

    # Scene planning (docs/decisions/0023): characters, locations, and
    # beats, planned and reviewed before any image generation. Not yet
    # wired into previz's actual generation calls -- that's
    # docs/decisions/0024. previz below still runs from fact_check_result
    # alone, same as before this stage existed.
    scene_planning_model = get_stage_model("scene_planning")
    log["scene_planning_model"] = scene_planning_model
    print(f"\n--- scene planning (model: {scene_planning_model}) ---")
    scene_plan = run_scene_planning_stage(
        scene,
        model=scene_planning_model,
        max_beats=args.max_beats,
        genre=args.genre,
        tone=args.tone,
        **scene_planning_kwargs,
    )
    log["scene_plan"] = dataclasses.asdict(scene_plan)
    write_log(out_dir, log)

    scene_plan = review_scene_plan(scene_plan, auto_yes=args.yes)
    log["scene_plan"] = dataclasses.asdict(scene_plan)
    write_log(out_dir, log)

    previz_model = get_stage_model("previz")
    log["previz_model"] = previz_model
    # Part of a judgement's context, not just a generation input: a
    # rejection under one style preset says nothing about another
    # (docs/decisions/0053).
    log["style"] = args.style

    # Cost visibility (docs/decisions/0024) -- a real, checked range, not a
    # guess: one image per reference plus one per beat, times the
    # candidates each beat attempt costs. This is a floor, not a cap:
    # every retry is a human choice with no ceiling
    # (docs/decisions/0043, 0055), so the real spend is open-ended by
    # nature and pretending otherwise would be a worse number.
    # Counts only the references this run will actually generate, and the
    # candidates each beat attempt will actually cost. Both were previously
    # ignored here, so the figure a human confirmed against could be several
    # times under the real spend.
    num_references = (len(scene_plan.characters) if args.references in ("both", "character") else 0) + (
        len(scene_plan.locations) if args.references in ("both", "location") else 0
    )
    num_beats = len(scene_plan.beats)
    per_attempt = num_beats * args.candidates
    min_images = num_references + per_attempt
    candidate_note = f" x {args.candidates} candidates" if args.candidates > 1 else ""
    print(
        f"\nThis scene plan needs {num_references} reference image(s) + {num_beats} beat "
        f"image(s){candidate_note} = {min_images} previz image(s) for one attempt each "
        f"({_estimate_image_cost(previz_model, min_images)}). Every retry you choose "
        f"costs that beat's candidates again."
    )
    if not confirm("Proceed with reference and beat image generation?", auto_yes=args.yes):
        log["stopped_reason"] = "declined_before_image_generation"
        write_log(out_dir, log)
        print(f"Stopped by user. Run artifacts saved in {out_dir}")
        return

    if args.candidates < 1:
        print(f"--candidates must be at least 1, got {args.candidates}.")
        return

    character_refs, location_refs = generate_scene_references(
        scene_plan,
        previz_model=previz_model,
        image_kwargs=image_kwargs,
        out_dir=out_dir,
        style=args.style,
        auto_yes=args.yes,
        want_character=args.references in ("both", "character"),
        want_location=args.references in ("both", "location"),
    )
    if args.references != "both":
        print(
            f"\n--references {args.references}: beats will be conditioned on "
            + (
                "no reference images at all."
                if args.references == "none"
                else f"the {args.references} reference only."
            )
        )
    log["character_references"] = {k: str(v) for k, v in character_refs.items()}
    log["location_references"] = {k: str(v) for k, v in location_refs.items()}
    write_log(out_dir, log)

    def _persist_beats(results: list[dict]) -> None:
        """Write the log after every finished beat, so an interrupted run
        still has a record of what it already produced and paid for."""
        log["previz_beats"] = results
        write_log(out_dir, log)

    beat_results = generate_beats_with_choices(
        scene_plan,
        character_refs=character_refs,
        location_refs=location_refs,
        previz_model=previz_model,
        image_kwargs=beat_image_kwargs,
        out_dir=out_dir,
        style=args.style,
        auto_yes=args.yes,
        candidates=args.candidates,
        on_beat_complete=_persist_beats,
    )
    _persist_beats(beat_results)
    # Gallery is already fully populated by this point -- each beat was
    # linked in immediately on acceptance (link_beat_into_gallery), not
    # batched here at the end.

    accepted = sum(1 for b in beat_results if b["image_path"] is not None)
    print(f"\nDone: {accepted}/{len(beat_results)} beat(s) produced an accepted image.")
    print(f"Run artifacts saved in {out_dir}")
    print(f"All accepted beat images linked in {out_dir / 'all_beats'}")


if __name__ == "__main__":
    main()
