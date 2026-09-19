"""Argument parsing, the run's order and its money gates: main().

What is left of the CLI once each seam moved to its own module: the order
stages run in and the confirmations before each spend live here, the work
itself does not. Research, fact-check and the flag gate are in
research_flow.py, the beat loop in beats.py, the
review prompts in review.py, --video-gen-from in video_gen.py, run
directories and the run log in runlog.py, and the --mock fakes in
mocks.py.

Collects a scene (time, place, description) and runs it through research
-> fact-check -> scene planning -> previz (docs/decisions/0006, 0023).
Run with `uv run historical-video-ai`. Every image comes from a beat of
the reviewed scene plan; the single-image path was deleted once scene
planning made it unreachable (docs/decisions/0051), though archived runs
in that older shape are still readable by --video-gen-from.

Flags:
- `--mock`: no network calls, no API keys -- synthetic data for every stage.
- `--fixture <path>`: replays a captured real research+fact-check result,
  skipping those API calls while still running previz for real -- see
  tests/fixtures/. Combine with --mock for a fully offline previz too.
- `--video-gen-from <run_dir> [...]`: runs stage 9 standalone against one
  or more completed previz outputs (docs/decisions/0010), writing each
  video into its source run_dir and appending to that run's existing log.
- `--video-seconds`: requests a clip duration, validated against the
  video model's real supported range before any API call
  (docs/decisions/0020, 0038).
- `--video-prompt`: overrides the saved previz prompt for --video-gen-from,
  to test a hand-written prompt against an already-approved image.
- `--yes`: non-interactive -- auto-confirms every prompt and auto-accepts
  an "uncertain" fact-check flag, but stops the run on a "contradicted"
  one rather than auto-accepting it (docs/decisions/0017, 0019). Note
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
import json
from pathlib import Path
from typing import Any

from historical_video_ai.cli.beats import (
    beat_gallery_dir,
    generate_beats_with_choices,
    generate_scene_references,
)
from historical_video_ai.cli.mocks import (
    mock_completion,
    mock_image,
    mock_image_edit,
    mock_scene_planning_completion,
)
from historical_video_ai.cli.research_flow import (
    record_research_claims,
    resolve_flags,
    resolve_premise_conflict,
    run_research_and_fact_check,
)
from historical_video_ai.cli.review import (
    confirm,
    prompt_if_missing,
    review_scene_plan,
)
from historical_video_ai.cli.runlog import (
    load_fact_sheet_from_fixture,
    load_fixture,
    new_run_dir,
    slugify,
    write_log,
)
from historical_video_ai.cli.video_gen import (
    run_video_generation_only,
)
from historical_video_ai.config import get_stage_model, load_environment
from historical_video_ai.stages.fact_check import (
    FactCheckResult,
)
from historical_video_ai.stages.previz import (
    DEFAULT_STYLE,
    PHOTOREAL_STYLES,
    STYLE_PRESETS,
)
from historical_video_ai.stages.research import FactSheet
from historical_video_ai.stages.scene_planning import (
    run_scene_planning_stage,
)
from historical_video_ai.stages.video_generation import (
    MAX_VIDEO_SECONDS,
    MIN_VIDEO_SECONDS,
)

# Real, checked per-image costs (docs/decisions/0024) -- never a guessed
# number. Keyed by the exact pinned model string, so a config change that
# swaps the previz model automatically falls back to "cost unknown" rather
# than silently reporting a stale price for a different model.
_KNOWN_IMAGE_MODEL_COSTS_USD = {
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
        description="Run the research -> fact-check -> previz pipeline for one scene."
    )
    parser.add_argument("--time", help="When the scene takes place, e.g. 'July 1969'.")
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
            "auto-accept every fact-check flag as-is (never auto-cut or "
            "auto-soften). --time/--place/--description must be given as "
            "flags in this mode -- there's nothing sensible to prompt for "
            "interactively. See docs/decisions/0017-non-interactive-mode.md."
        ),
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        help=(
            "Path to a previously captured real run_log.json -- replays its "
            "research + fact-check output instead of calling those APIs "
            "again (previz still runs for real unless --mock is also set)."
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
            "research, fact-check, and previz entirely for this "
            "invocation. Combine with --mock to exercise the polling loop "
            "without a real API call."
        ),
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
            "research/fact-check/previz pass just to change the wording."
        ),
    )
    parser.add_argument(
        "--genre",
        default="historical",
        help=(
            "What kind of scene this is -- e.g. 'historical', 'meme', "
            "'vlog', 'kids-content', 'abstract'. Free text, not a fixed "
            "list: fed into scene-planning's prompt to inform staging and "
            "convention choices (docs/decisions/0035). Only 'historical' "
            "(the default) requires real-world grounding -- every other "
            "value skips research and fact-check entirely and drops the "
            "historical-accuracy framing from scene-planning and "
            "previz_review's prompts, since that framing is actively "
            "wrong (not just unhelpful overhead) for a scene that was "
            "never claiming to be real. Scene planning's plan-fidelity "
            "check (does the image match what was planned) still applies "
            "regardless of genre."
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
    parser.add_argument(
        "--experiment-model",
        help=(
            "Override the pinned research + fact_check models for this run "
            "only (config/models.yaml is untouched) -- e.g. "
            "'deepseek/deepseek-v4-flash' to try DeepSeek in place of "
            "Perplexity/Gemini. Note this drops fact_check's live search grounding "
            "(docs/decisions/0007), since DeepSeek doesn't have it -- this "
            "is meant for a quick quality/cost comparison, not a real "
            "replacement for the pinned choices. previz is unaffected "
            "(DeepSeek isn't an image model). Has no effect on the initial "
            "research/fact-check in --fixture mode (loaded from the "
            "fixture, not run) -- but still applies if a premise-conflict "
            "correction (see docs/decisions/0008) triggers a real "
            "re-verification pass."
        ),
    )
    return parser


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    if not args.mock:
        load_environment()

    if args.video_gen_from:
        run_video_generation_only(
            args.video_gen_from,
            mock=args.mock,
            video_seconds=args.video_seconds,
            video_prompt=args.video_prompt,
        )
        return

    completion_kwargs: dict[str, Any] = {"completion_fn": mock_completion} if args.mock else {}
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

    research_model = args.experiment_model or get_stage_model("research")
    fact_check_model = args.experiment_model or get_stage_model("fact_check")

    if args.fixture:
        # A fixture saved after a fact-check-stage crash has research but
        # no fact_check_flags key yet (docs/decisions/0015 persists
        # research before fact-check runs) -- that's a real, valid,
        # cheaper-to-resume case, not a malformed fixture: run fact-check
        # for real against the loaded research instead of requiring a full
        # fixture. `load_fixture` needs a completed fact-check result;
        # peek at the raw fixture first to tell which case this is.
        has_fact_check = "fact_check_flags" in json.loads(args.fixture.read_text())

        fact_sheet = load_fact_sheet_from_fixture(args.fixture)
        time, place, description = fact_sheet.time, fact_sheet.place, fact_sheet.description
        # Computed here, not before the scene is known -- see new_run_dir's
        # docstring on why the directory name now carries a content hint,
        # not just a timestamp.
        out_dir = new_run_dir(slugify(description))
        beat_gallery_dir(out_dir)  # exists from the very start -- see its own docstring
        log = {"time": time, "place": place, "description": description, "mock": args.mock}
        log["fixture"] = str(args.fixture)
        # A fixture is always a replay of a previously completed *real*
        # research + fact-check run, so its fact sheet is already grounded
        # and --genre cannot un-ground it: requires_grounding stays True
        # whatever was passed.
        #
        # The genre itself is still live, though. It routes composition
        # mode and threat mode (docs/decisions/0036, 0060) regardless of
        # grounding, so `--fixture X --genre horror` really does plan a
        # horror scene -- historical horror being an ordinary thing to
        # want here. Recording a hardcoded "historical" made the run log
        # disagree with the run, and evals/export_judgements.py stamps
        # every judgement row with this field precisely so rows made under
        # different conditions are not compared.
        requires_grounding = True
        log["genre"] = args.genre
        log["tone"] = args.tone
        log["requires_grounding"] = requires_grounding

        if has_fact_check:
            fact_check_result = load_fixture(args.fixture)
            print(f"\n--- research (loaded from fixture: {args.fixture}) ---")
            for c in fact_sheet.claims:
                print(f"- {c.text} [source: {c.source}]")

            print("\n--- fact-check (loaded from fixture) ---")
            if fact_check_result.flags:
                for f in fact_check_result.flags:
                    print(f"- [{f.severity}] {f.claim_text} -- {f.concern}")
            else:
                print("No issues flagged.")
        else:
            print(f"\nFixture {args.fixture} has research but no completed fact-check -- running fact-check for real against it.")
            result = run_research_and_fact_check(
                time,
                place,
                description,
                research_model=research_model,
                fact_check_model=fact_check_model,
                completion_kwargs=completion_kwargs,
                auto_yes=args.yes,
                fact_sheet=fact_sheet,
            )
            if result is None:
                write_log(out_dir, log)
                print(f"Stopped by user. Run artifacts saved in {out_dir}")
                return
            fact_sheet, fact_check_result = result
    else:
        time = prompt_if_missing(args.time, "Time", auto_yes=args.yes)
        place = prompt_if_missing(args.place, "Place", auto_yes=args.yes)
        description = prompt_if_missing(
            args.description, "What the main character does", auto_yes=args.yes
        )
        out_dir = new_run_dir(slugify(description))
        beat_gallery_dir(out_dir)  # exists from the very start -- see its own docstring
        log = {"time": time, "place": place, "description": description, "mock": args.mock}
        # docs/decisions/0035: genre, not a binary flag, is what determines
        # this -- "historical" (the default) is the only value that needs
        # real-world grounding; every other genre skips it.
        requires_grounding = args.genre.strip().lower() == "historical"
        log["genre"] = args.genre
        log["tone"] = args.tone
        log["requires_grounding"] = requires_grounding

        if not requires_grounding:
            # docs/decisions/0034/0035: skip research + fact-check entirely
            # -- a scene that was never claiming to be real gets no value
            # from historical-accuracy machinery, and the machinery's own
            # framing (premise conflicts, "verified claims") is actively
            # wrong for it, not just unhelpful overhead.
            print(f"\n--genre {args.genre!r}: skipping research and fact-check.")
            fact_sheet = FactSheet(time=time, place=place, description=description, claims=[])
            fact_check_result = FactCheckResult(fact_sheet=fact_sheet)
        else:
            result = run_research_and_fact_check(
                time,
                place,
                description,
                research_model=research_model,
                fact_check_model=fact_check_model,
                completion_kwargs=completion_kwargs,
                auto_yes=args.yes,
                on_research_completed=lambda fs: record_research_claims(
                    fs, research_model=research_model, out_dir=out_dir, log=log
                ),
            )
            if result is None:
                write_log(out_dir, log)
                print(f"Stopped by user. Run artifacts saved in {out_dir}")
                return
            fact_sheet, fact_check_result = result

    # Only the models that actually ran. An ungrounded run
    # (docs/decisions/0034/0035) skips research and fact-check entirely,
    # so stamping their pinned models here recorded two calls that never
    # happened -- and the run log is the judgement dataset
    # (docs/decisions/0053), where a field recording what produced a row
    # has to be true or it is worse than absent.
    if requires_grounding:
        log["research_model"] = research_model
        log["fact_check_model"] = fact_check_model
    log["research_claims"] = [dataclasses.asdict(c) for c in fact_sheet.claims]
    log["fact_check_flags"] = [dataclasses.asdict(f) for f in fact_check_result.flags]
    original_premise_conflict = fact_check_result.premise_conflict
    log["premise_conflict"] = (
        dataclasses.asdict(original_premise_conflict) if original_premise_conflict else None
    )
    write_log(out_dir, log)

    resolved = resolve_premise_conflict(
        fact_sheet,
        fact_check_result,
        time=time,
        place=place,
        research_model=research_model,
        fact_check_model=fact_check_model,
        completion_kwargs=completion_kwargs,
        auto_yes=args.yes,
        on_research_completed=lambda fs: record_research_claims(
            fs, research_model=research_model, out_dir=out_dir, log=log
        ),
    )
    if resolved is None:
        log["stopped_reason"] = "premise_conflict_unresolved"
        write_log(out_dir, log)
        print(f"Stopped. Run artifacts saved in {out_dir}")
        return
    fact_sheet, fact_check_result, resolution_type = resolved

    if original_premise_conflict is not None:
        log["premise_conflict_resolved_with_description"] = fact_sheet.description
        log["premise_conflict_resolution"] = resolution_type
    # docs/decisions/0027: re-written from the *resolved* state, not left
    # as the stale pre-resolution snapshot from before _resolve_premise_
    # conflict ran -- otherwise a --fixture replay of this exact run would
    # reconstruct a still-open conflict and immediately re-trip previz's
    # hard-refuse check, regardless of how this run actually resolved it.
    log["premise_conflict"] = (
        dataclasses.asdict(fact_check_result.premise_conflict)
        if fact_check_result.premise_conflict
        else None
    )
    log["acknowledged_fiction"] = fact_check_result.acknowledged_fiction
    log["description"] = fact_sheet.description
    log["research_claims"] = [dataclasses.asdict(c) for c in fact_sheet.claims]
    log["fact_check_flags"] = [dataclasses.asdict(f) for f in fact_check_result.flags]
    write_log(out_dir, log)

    resolved_fact_sheet = resolve_flags(fact_sheet, fact_check_result.flags, auto_yes=args.yes)
    if resolved_fact_sheet is None:
        log["stopped_reason"] = "contradicted_flag_unresolved"
        write_log(out_dir, log)
        print(f"Stopped. Run artifacts saved in {out_dir}")
        return
    fact_check_result = dataclasses.replace(fact_check_result, fact_sheet=resolved_fact_sheet)
    log["research_claims"] = [dataclasses.asdict(c) for c in resolved_fact_sheet.claims]
    write_log(out_dir, log)

    # Wording (and whether to ask at all) depends on whether there's
    # actually a fact-check result to confirm -- a genre that skipped
    # research/fact-check entirely (requires_grounding=False) has nothing
    # here worth a human decision on; asking "proceed with this
    # fact-check result?" for a scene that was never fact-checked is a
    # confusing, pointless confirm, not a real checkpoint.
    if requires_grounding and not confirm(
        "\nProceed to scene planning with this fact-check result?", auto_yes=args.yes
    ):
        print(f"Stopped by user. Run artifacts saved in {out_dir}")
        return

    # Scene planning (docs/decisions/0023): characters, locations, and
    # beats, planned and reviewed before any image generation. Not yet
    # wired into previz's actual generation calls -- that's
    # docs/decisions/0024. previz below still runs from fact_check_result
    # alone, same as before this stage existed.
    scene_planning_model = get_stage_model("scene_planning")
    log["scene_planning_model"] = scene_planning_model
    print(f"\n--- scene planning (model: {scene_planning_model}) ---")
    scene_plan = run_scene_planning_stage(
        fact_check_result,
        model=scene_planning_model,
        max_beats=args.max_beats,
        requires_grounding=requires_grounding,
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
