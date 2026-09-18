"""Interactive CLI entry point for the v1 pipeline: collects a scene
(time, place, description), runs it through research -> fact-check ->
scene planning -> previz (docs/decisions/0006, 0023). Run with
`uv run historical-video-ai`.

Every image comes from a beat of the reviewed scene plan. The
single-image path that generated one image from fact_check_result alone
was deleted once scene planning made it unreachable
(docs/decisions/0051); archived runs in that older shape are still
readable by --video-gen-from.

Refuses rather than fabricates in two cases: fact-check flagging the
scene's premise as historically impossible (docs/decisions/0008,
resolve_premise_conflict -- offers a suggested alternative or your own
corrected description, re-verified before continuing), and previz's own
generated image failing independent review (docs/decisions/0009,
_generate_image_with_retries -- regenerates with each prior concern fed
back in, up to _MAX_PREVIZ_ATTEMPTS times, then gives up).

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
import os
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

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
    BEAT_QUICK_EDIT_FIELDS,
    confirm,
    edit_item_fields,
    prompt_if_missing,
    review_scene_plan,
)
from historical_video_ai.cli.runlog import (
    load_fact_sheet_from_fixture,
    load_fixture,
    new_run_dir,
    next_archive_path,
    safe_path_component,
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
    PrevizResult,
    build_character_sheet_prompt,
    build_location_reference_prompt,
    run_beat_image_stage,
    run_reference_image_stage,
)
from historical_video_ai.stages.research import FactSheet
from historical_video_ai.stages.scene_planning import (
    Beat,
    Character,
    Location,
    ScenePlan,
    run_scene_planning_stage,
)
from historical_video_ai.stages.video_generation import (
    MAX_VIDEO_SECONDS,
    MIN_VIDEO_SECONDS,
)

# See docs/decisions/0009-previz-image-review.md -- your call: bounded, not
# tunable via a flag, to keep behavior predictable rather than open-ended.
_MAX_PREVIZ_ATTEMPTS = 3

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


def _beat_review_context(beat: Beat, characters: Sequence[Character]) -> str:
    """The plan text a candidate image is being judged against.

    Shown at the candidate prompt rather than only at scene-plan review,
    which by then is hundreds of lines up the scrollback
    (docs/decisions/0053). Camera and staging specifically: those are what
    an image most visibly honours or ignores, and checking them was the
    judgement the interface made hardest to perform.
    """
    by_id = {c.id: c for c in characters}
    lines = [f"Judging against -- beat: {beat.action}", f"  camera: {beat.camera}"]
    for staged in beat.staging:
        name = by_id[staged.character_id].id if staged.character_id in by_id else staged.character_id
        lines.append(f"  {name} doing: {staged.action}")
        if staged.frame_position:
            lines.append(f"  {name} in frame: {staged.frame_position}")
        if staged.occlusion:
            lines.append(f"  {name} hidden by: {staged.occlusion}")
    return "\n".join(lines)


def _choose_candidate(
    candidates: list[PrevizResult], *, auto_yes: bool, context: str | None = None
) -> PrevizResult | None:
    """Ask which of several candidate images to keep, or None to reject all.

    Generating one image per attempt meant a single roll of a
    non-deterministic process, which is indistinguishable from luck -- the
    project owner's own read of an improved beat was "not super obvious it's
    not just getting lucky". A real run spent 1.8 images per beat anyway, one
    at a time, discarding each before the next existed. Showing them together
    costs the same money and turns a gamble into a choice
    (docs/decisions/0046).

    Unattended, the first candidate is taken: there is nobody to ask, and
    picking arbitrarily is at least honest about that.
    """
    if auto_yes:
        return candidates[0]

    folder = candidates[0].image_path.parent
    # What the image is being judged against, repeated here on purpose.
    # It was last printed at scene-plan review, hundreds of lines of
    # generation output ago, so checking whether the render honoured the
    # plan meant scrolling back every time (docs/decisions/0053).
    if context:
        print(f"\n{context}")
    print(f"\n{len(candidates)} candidates in {folder}:")
    for n, candidate in enumerate(candidates, start=1):
        print(f"  {n}. {candidate.image_path.name}")
    # One command that opens them together, since comparing them side by
    # side is the entire point.
    print(f"  open {folder}/candidate_*.png")

    valid = {str(n) for n in range(1, len(candidates) + 1)} | {"n"}
    choice = ""
    while choice not in valid:
        choice = input(
            f"  Keep which? [1-{len(candidates)}] or (n)one of them: "
        ).strip().lower()
    return None if choice == "n" else candidates[int(choice) - 1]


def _generate_image_with_retries(
    generate_fn: Callable[[], list[PrevizResult]],
    *,
    out_dir: Path,
    archive_prefix: str = "previz_attempt",
    on_image_generated: Callable[[PrevizResult], None] | None = None,
    on_reviewed: Callable[[str | None, int], str] | None = None,
    on_attempt: Callable[[dict], None] | None = None,
    choose_auto: bool = False,
    max_attempts: int | None = _MAX_PREVIZ_ATTEMPTS,
    context: str | None = None,
) -> tuple[PrevizResult | None, list[dict]]:
    """Generate an image via `generate_fn` (a callable producing one
    PrevizResult from the concerns accumulated so far -- a closure over
    run_beat_image_stage for a scene-plan beat, docs/decisions/0023/0024),
    then have an independent pass review the actual image against the
    scene (docs/decisions/0009). On rejection, regenerates -- now with
    every prior rejection reason handed to `generate_fn` too (see below),
    not a truly blind identical retry -- unless `on_reviewed` says to
    stop, capped at _MAX_PREVIZ_ATTEMPTS regardless. Shared by both
    generation paths -- only how the image itself gets made differs
    between them.

    `generate_fn` receives the list of rejection reasons accumulated on
    this beat so far (empty on the first attempt). Real usage (2026-09-15)
    found previz_review's own rejection text -- e.g. "the image shows
    anger, not the fear/terror the beat calls for" -- is itself a
    near-ready corrective instruction, confirmed by a human manually
    typing almost the same correction via the (f)eedback option and
    getting a fixed result. Previously a blind retry reused the exact
    same prompt with zero new information on every attempt; feeding the
    reviewer's own concerns back into generation is strictly more
    information than that, at no extra cost (no added model call -- the
    concern text already exists from the review that just ran).

    Returns (accepted PrevizResult, attempt log), or (None, attempt log)
    if the human kept nothing, or `on_reviewed` stopped early. A
    rejected attempt's image is archived as `<archive_prefix>_<n>_rejected.png`
    rather than overwritten.

    `on_image_generated`, if given, is called with each attempt's
    PrevizResult right after the image is written -- *before* review runs,
    which can itself fail. Without this, a review-stage crash left a real,
    already-paid-for image on disk with no record of it in the log.

    `on_reviewed`, if given, is called after EVERY review -- not only
    after a rejection -- with (concern or None, attempt), and its return
    value picks one of three outcomes: "accept" keeps this attempt's
    image, "stop" ends the loop with nothing kept, anything else
    regenerates with the accumulated concerns folded in.

    Asking on every review, rather than letting the reviewer's verdict
    decide whether to ask at all, is docs/decisions/0043. previz_review
    was measured ranking four arms in exact reverse of blind human
    judgement, and rejecting 88% of images; letting it choose the default
    action spent money retrying images a human would have kept, and never
    offered the choice on images a human would have rerolled.

    With no callback the reviewer's verdict is followed, which is what
    --yes does.
    """
    attempts: list[dict] = []
    # `max_attempts=None` means no ceiling. The cap exists to stop an
    # UNATTENDED run regenerating forever; once every attempt is an
    # explicit human choice (docs/decisions/0043) it stops being a guard
    # and becomes a refusal to do what was just asked for. Choosing
    # (r)etry on the last allowed attempt silently behaved as a give-up.
    attempt = 0
    while max_attempts is None or attempt < max_attempts:
        attempt += 1
        candidates = generate_fn()
        for candidate in candidates:
            print(f"Image saved to {candidate.image_path}")
            if on_image_generated is not None:
                on_image_generated(candidate)

        def _candidate_records(
            kept: PrevizResult | None,
            # Bound as a default rather than closed over, same as the
            # beat loop's own captures -- this is redefined every
            # iteration and ruff correctly flags the bare closure (B023).
            candidates: list[PrevizResult] = candidates,
        ) -> list[dict]:
            return [
                {
                    "path": str(c.image_path),
                    "prompt_used": c.prompt_used,
                    "kept": kept is not None and c.image_path == kept.image_path,
                }
                for c in candidates
            ]

        # The images are paid for the moment they exist, and the very next
        # thing is a prompt a human may never answer. Record them before
        # asking anything (docs/decisions/0056) -- `kept` is not known yet
        # and the later writes for this attempt supersede this one.
        if on_attempt is not None:
            on_attempt(
                {
                    "attempt": attempt,
                    "accepted": None,
                    "concern": None,
                    "human_choice": None,
                    "unattended": choose_auto,
                    "candidates": _candidate_records(None),
                }
            )

        if len(candidates) > 1:
            chosen = _choose_candidate(
                candidates, auto_yes=choose_auto, context=context
            )
            if chosen is None:
                # Rejecting every candidate is a rejection of the attempt,
                # not of the beat -- the loop offers the usual choices next.
                print("None kept.")
                record = {
                    "attempt": attempt,
                    "accepted": False,
                    "concern": "human rejected every candidate",
                    "human_choice": "none",
                    "unattended": choose_auto,
                    "candidates": _candidate_records(None),
                }
                attempts.append(record)
                if on_attempt is not None:
                    on_attempt(record)
                decision = (
                    on_reviewed("none of the candidates were usable", attempt)
                    if on_reviewed is not None
                    else "continue"
                )
                if decision in ("accept", "stop"):
                    break
                continue
            previz_result = chosen
            # Under --yes nobody was asked and candidates[0] is taken, which
            # is indistinguishable from a human picking candidate 1. Marked
            # so preference studies can exclude it (docs/decisions/0053).
            human_choice = None if choose_auto else str(candidates.index(chosen) + 1)
        else:
            previz_result = candidates[0]
            human_choice = None

        if on_attempt is not None:
            on_attempt(
                {
                    "attempt": attempt,
                    "accepted": None,  # not decided yet
                    "concern": None,
                    "human_choice": human_choice,
                    "unattended": choose_auto,
                    "candidates": _candidate_records(previz_result),
                }
            )

        # No automated review here any more (docs/decisions/0055). The
        # human is asked after every attempt, which is what
        # docs/decisions/0043 established was doing the actual work.
        decision = on_reviewed(None, attempt) if on_reviewed is not None else "accept"

        if decision == "accept":
            attempts.append(
                {
                    "attempt": attempt,
                    "accepted": True,
                    "concern": None,
                    "human_choice": human_choice,
                    "unattended": choose_auto,
                    "candidates": _candidate_records(previz_result),
                }
            )
            if on_attempt is not None:
                on_attempt(attempts[-1])
            return previz_result, attempts

        # Archived rather than overwritten: the human passed over this
        # image, and the next attempt must not silently destroy it.
        archived_path = next_archive_path(out_dir, archive_prefix, suffix="rejected")
        previz_result.image_path.rename(archived_path)
        attempts.append(
            {
                "attempt": attempt,
                "accepted": False,
                "concern": None,
                "image_path": str(archived_path),
                "human_choice": human_choice,
                "unattended": choose_auto,
                # The chosen candidate moved; record where it actually is
                # now, or the label points at a path that no longer exists.
                "candidates": [
                    {**c, "path": str(archived_path) if c["kept"] else c["path"]}
                    for c in _candidate_records(previz_result)
                ],
            }
        )
        if on_attempt is not None:
            on_attempt(attempts[-1])
        if decision == "stop":
            break
        if max_attempts is None or attempt < max_attempts:
            print("Regenerating...")

    print(f"\nNo image kept for this beat after {len(attempts)} attempt(s).")
    return None, attempts


def _generate_scene_references(
    scene_plan: ScenePlan,
    *,
    previz_model: str,
    image_kwargs: dict,
    out_dir: Path,
    style: str = DEFAULT_STYLE,
    auto_yes: bool = False,
    want_character: bool = True,
    want_location: bool = True,
) -> tuple[dict[str, Path], dict[str, Path]]:
    """Generate one canonical reference image per Character and per
    Location in scene_plan (docs/decisions/0024). Each gets its own
    accept/regenerate confirm before moving on -- a bad reference is far
    cheaper to catch here than after generating several beats off it.
    `style` (docs/decisions/0033) is the run's single authoritative
    realism-level source.

    Returns (character_refs, location_refs), each a dict keyed by id.
    """
    character_refs: dict[str, Path] = {}
    for i, character in enumerate(scene_plan.characters if want_character else [], start=1):
        prompt = build_character_sheet_prompt(character, style=style)
        while True:
            print(
                f"\n--- character reference '{character.id}' "
                f"({i}/{len(scene_plan.characters)}) ---"
            )
            result = run_reference_image_stage(
                prompt,
                model=previz_model,
                output_dir=out_dir / f"character_{safe_path_component(character.id)}",
                on_transient_retry=lambda n, exc: print(
                    f"Transient error ({exc}) -- retrying (attempt {n + 1})..."
                ),
                **image_kwargs,
            )
            print(f"Reference saved to {result.image_path}")
            if confirm("Accept this reference?", auto_yes=auto_yes):
                character_refs[character.id] = result.image_path
                break
            # Archive rather than let the next attempt overwrite it.
            # References wrote to a fixed "reference.png", so every
            # rejected one was destroyed with no way to compare or go
            # back -- while beats had archived their rejects all along.
            archived = next_archive_path(result.image_path.parent, "reference_attempt")
            result.image_path.rename(archived)
            print(f"Previous attempt kept at {archived.name}. Regenerating...")

    location_refs: dict[str, Path] = {}
    for i, location in enumerate(scene_plan.locations if want_location else [], start=1):
        prompt = build_location_reference_prompt(location, style=style)
        while True:
            print(f"\n--- location reference '{location.id}' ({i}/{len(scene_plan.locations)}) ---")
            result = run_reference_image_stage(
                prompt,
                model=previz_model,
                output_dir=out_dir / f"location_{safe_path_component(location.id)}",
                on_transient_retry=lambda n, exc: print(
                    f"Transient error ({exc}) -- retrying (attempt {n + 1})..."
                ),
                **image_kwargs,
            )
            print(f"Reference saved to {result.image_path}")
            if confirm("Accept this reference?", auto_yes=auto_yes):
                location_refs[location.id] = result.image_path
                break
            archived = next_archive_path(result.image_path.parent, "reference_attempt")
            result.image_path.rename(archived)
            print(f"Previous attempt kept at {archived.name}. Regenerating...")

    return character_refs, location_refs


def _generate_beats_with_choices(
    scene_plan: ScenePlan,
    *,
    character_refs: dict[str, Path],
    location_refs: dict[str, Path],
    previz_model: str,
    image_kwargs: dict,
    out_dir: Path,
    style: str = DEFAULT_STYLE,
    auto_yes: bool = False,
    candidates: int = 1,
    on_beat_complete: Callable[[list[dict]], None] | None = None,
) -> list[dict]:
    """Generate each beat's image (docs/decisions/0024). `style`
    (docs/decisions/0033) is the run's single authoritative realism-level
    source. Every attempt
    still goes through previz_review's own automatic reject-and-regenerate
    loop (docs/decisions/0009, via _generate_image_with_retries), but now
    with an on-rejection hook (docs/decisions/0029): after *any*
    rejection, not just after all attempts are exhausted, a human can edit
    the beat's text and retry fresh, or give up on this beat now --
    otherwise Enter keeps the existing blind-retry behavior. This matters
    because some rejections are attributable to something baked into the
    prompt itself (e.g. an anachronistic detail on the shared Character),
    which fails identically on every blind attempt -- see the real run
    that motivated this. Under `auto_yes` there's no human to ask, so the
    hook instead applies a cheap heuristic: an identical rejection concern
    twice in a row gives up rather than spending the last attempt on a
    near-certain repeat (0029 -- a real judgment call on "is this doomed"
    needs a model in the loop, which is future work, not this).

    Once an attempt is accepted by review, a human gets three further
    choices, not an automatic proceed: (a)ccept, (r)eroll (same beat text,
    another blind attempt -- for "unlucky roll"), or (e)dit (update the
    beat's text first, reusing 0023's per-item edit mechanism, then retry
    -- for "this needs an actual change," not just another random draw).

    Assumes a single main character, the common case in every real scene
    built so far: with zero characters, no character reference is used;
    with more than one, the first is used for every beat. A known v1
    simplification (Beat has no character_id field to disambiguate), not
    a silent bug -- worth revisiting if a real scene needs more than one
    named character across its beats.

    Returns a list of per-beat result dicts (index, beat, image path or
    None if every review attempt was rejected, attempt log) for
    run_log.json.
    """
    characters_by_id = {c.id: c for c in scene_plan.characters}
    locations_by_id = {loc.id: loc for loc in scene_plan.locations}

    beat_results = []

    def _record(entry: dict) -> None:
        """Append a finished beat and persist immediately.

        Persisting per beat rather than once at the end: a real run was
        interrupted partway through and its log recorded zero beats,
        despite two having been accepted and paid for. The images
        survived; the metadata pairing them with their prompts -- which is
        what --video-gen-from needs later -- did not.
        """
        beat_results.append(entry)
        if on_beat_complete is not None:
            on_beat_complete(beat_results)

    def _persist_in_progress(index: int, beat: Beat, attempts_so_far: list[dict]) -> None:
        """Write the beat currently being worked on, before it finishes.

        Per-beat persistence still lost whatever was in flight, and the
        owner abandons most runs partway through, so that was the common
        case rather than an edge one: across 26 real runs, 27% of every
        image generated had no record at all. Since
        docs/decisions/0053 the same gap loses human judgements, which
        cost more to produce than the images. See docs/decisions/0056.
        """
        if on_beat_complete is None:
            return
        on_beat_complete(
            beat_results
            + [
                {
                    "index": index,
                    "beat": dataclasses.asdict(beat),
                    "image_path": None,
                    "attempts": attempts_so_far,
                    "in_progress": True,
                }
            ]
        )

    for i, beat in enumerate(scene_plan.beats, start=1):
        # Every character the beat says is present, not just the scene's
        # first one (docs/decisions/0041, now via staging -- 0049). A beat
        # that stages nobody falls back to the first character, which is
        # what every beat got before.
        beat_character_ids = [s.character_id for s in beat.staging] or (
            [scene_plan.characters[0].id] if scene_plan.characters else []
        )
        beat_characters = [
            characters_by_id[cid] for cid in beat_character_ids if cid in characters_by_id
        ]
        beat_character_refs = [
            character_refs[c.id] for c in beat_characters if c.id in character_refs
        ]
        location = locations_by_id.get(beat.location_id)
        location_ref = location_refs.get(beat.location_id)
        beat_out_dir = out_dir / f"beat_{i}"

        # Spans attempt cycles, unlike the list inside
        # _generate_image_with_retries, which is per call. An (e)dit or
        # (f)eedback starts a new call, and the reviewer's concerns must
        # survive that (docs/decisions/0043).
        # Spans cycles because each
        # _generate_image_with_retries call returns only its own attempts,
        # and the previous binding used to be thrown away at an (e)dit or
        # (f)eedback boundary (docs/decisions/0053).
        all_attempts: list[dict] = []
        # What the human did at each attempt's prompt, keyed by cycle and
        # attempt number -- the judgement itself, as opposed to what was
        # generated.
        human_actions: dict[tuple[int, int], dict] = {}
        cycle = 0
        while True:
            cycle += 1
            if cycle == 1:
                print(f"\n=== beat {i}/{len(scene_plan.beats)}: {beat.action} ===")
            else:
                # A (r)eroll or an (e)dit-and-retry re-enters this loop for
                # the SAME beat. Reprinting the original header made that
                # read as a new beat being generated, which it isn't.
                print(
                    f"\n=== beat {i}/{len(scene_plan.beats)} -- restarting, "
                    f"attempt cycle {cycle} ==="
                )
            attempt_n = 0
            beat_was_edited = False

            def _on_reviewed(
                concern: str | None,
                attempt: int,
                i: int = i,
                # Bound as a default like the other loop captures
                # (ruff B023). It is mutated in place, not rebound,
                # so the caller sees every append.
                cycle: int = cycle,
                human_actions: dict = human_actions,
            ) -> str:
                """One prompt after every attempt. The human decides.

                There is no automated verdict any more
                (docs/decisions/0055) -- previz_review agreed with the
                owner's keep/discard decision on only 56% of 78 images it
                had never scored, against 79% for accepting everything, so
                as a gate it was worse than not having one.
                """
                nonlocal beat, beat_was_edited
                if auto_yes:
                    # Unattended, nobody is asked and nothing grades the
                    # image, so the first attempt is taken. --yes is a
                    # secondary mode (docs/decisions/0043); the
                    # interactive path is where the judgement happens.
                    return "accept"

                choice = None
                while choice not in ("a", "r", "e", "f", "g"):
                    # No "/3": interactively there is no ceiling, so a
                    # denominator would promise a limit that isn't there.
                    # The running count is the cost signal instead.
                    choice = input(
                        f"  Attempt {attempt} -- (a)ccept / (r)etry / "
                        "(e)dit the beat / (f)eedback then retry / (g)ive up: "
                    ).strip().lower()
                human_actions[(cycle, attempt)] = {"human_action": choice}
                if choice == "a":
                    return "accept"
                if choice == "e":
                    print(f"\nBeat {i}:")
                    beat = edit_item_fields(beat, fields=BEAT_QUICK_EDIT_FIELDS)
                    beat_was_edited = True
                    return "stop"
                if choice == "f":
                    # A targeted correction ("keep this, just make her
                    # smaller") appended to the existing action text --
                    # cheaper than rewriting a field that was already
                    # mostly right, for the common case where the plan was
                    # fine and only the render missed one specific thing.
                    note = ""
                    while not note:
                        note = input("  Feedback (appended to the beat's action): ").strip()
                    # A human-authored correction naming exactly what the
                    # render got wrong -- the highest-value text in the
                    # whole loop and previously unrecorded.
                    human_actions[(cycle, attempt)]["feedback"] = note
                    beat = dataclasses.replace(beat, action=f"{beat.action} {note}")
                    beat_was_edited = True
                    return "stop"
                if choice == "g":
                    return "stop"
                return "continue"

            # Default-argument bindings, not closures over the loop
            # variables directly: `_generate` is redefined fresh each
            # while-loop iteration specifically so an (e)dited `beat`
            # takes effect on the next attempt -- these defaults capture
            # each variable's *current* value at definition time, which is
            # exactly what's wanted, but spelling it as a bare closure
            # over loop variables is a real footgun ruff correctly flags
            # (B023) even though this particular control flow is safe.
            def _generate(
                candidates: int = candidates,
                beat: Beat = beat,
                location: Location | None = location,
                location_ref: Path | None = location_ref,
                beat_out_dir: Path = beat_out_dir,
                beat_characters: list = beat_characters,
                beat_character_refs: list = beat_character_refs,
            ) -> list[PrevizResult]:
                nonlocal attempt_n
                attempt_n += 1
                cap = f"/{_MAX_PREVIZ_ATTEMPTS}" if auto_yes else ""
                print(
                    f"--- beat image (model: {previz_model}, "
                    f"attempt {attempt_n}{cap}) ---"
                )
                # One call per candidate. Gemini's image API has no n>1
                # parameter via litellm, so the fan-out lives here rather
                # than in the provider call (docs/decisions/0046).
                return [
                    run_beat_image_stage(
                        beat,
                        characters=beat_characters,
                        location=location,
                        character_references=beat_character_refs,
                        location_reference=location_ref,
                        style=style,
                        model=previz_model,
                        output_dir=beat_out_dir,
                        filename=(
                            "previz.png"
                            if candidates == 1
                            else f"candidate_{attempt_n}_{n}.png"
                        ),
                        on_transient_retry=lambda n, exc: print(
                            f"Transient error ({exc}) -- retrying (attempt {n + 1})..."
                        ),
                        **image_kwargs,
                    )
                    for n in range(1, candidates + 1)
                ]

            def _on_attempt(
                record: dict,
                cycle: int = cycle,
                i: int = i,
                beat: Beat = beat,
                all_attempts: list[dict] = all_attempts,
            ) -> None:
                entry = {"cycle": cycle, **record}
                # A provisional record for the same attempt is replaced,
                # not duplicated -- it is fired before the accept/retry
                # prompt precisely so quitting there keeps something.
                for n, existing in enumerate(all_attempts):
                    if (existing["cycle"], existing["attempt"]) == (cycle, record["attempt"]):
                        all_attempts[n] = entry
                        break
                else:
                    all_attempts.append(entry)
                _persist_in_progress(i, beat, all_attempts)

            beat_context = _beat_review_context(beat, beat_characters)
            previz_result, _ = _generate_image_with_retries(
                _generate,
                out_dir=beat_out_dir,
                archive_prefix=f"beat{i}_attempt",
                on_reviewed=_on_reviewed,
                on_attempt=_on_attempt,
                choose_auto=auto_yes,
                max_attempts=_MAX_PREVIZ_ATTEMPTS if auto_yes else None,
                context=beat_context,
            )
            # _on_attempt already recorded each attempt as it happened;
            # this only folds in the human's action, which is not known
            # until they answer the prompt.
            for n, entry in enumerate(all_attempts):
                action = human_actions.get((entry["cycle"], entry["attempt"]))
                if action:
                    all_attempts[n] = {**entry, **action}

            if previz_result is None:
                if beat_was_edited:
                    continue  # human edited the beat -- restart a fresh attempt cycle
                _record(
                    {
                        "index": i,
                        "beat": dataclasses.asdict(beat),
                        "image_path": None,
                        "attempts": all_attempts,
                    }
                )
                break  # every automatic attempt was rejected, or the human gave up on this beat

            # A returned result means the human already chose to keep it at
            # the single review prompt (docs/decisions/0043). Asking
            # accept/reroll/edit again here was the same question twice.
            print("Beat accepted.")
            _link_beat_into_gallery(out_dir, i, str(previz_result.image_path))
            _record(
                {
                    "index": i,
                    "beat": dataclasses.asdict(beat),
                    "image_path": str(previz_result.image_path),
                    # The actual prompt sent to the image model for the
                    # accepted attempt -- video generation (the
                    # --video-gen-from follow-up to docs/decisions/0024)
                    # needs this alongside the image itself, the same way
                    # the old single-image flow paired previz_image_path
                    # with previz_prompt_used.
                    "prompt_used": previz_result.prompt_used,
                    "attempts": all_attempts,
                }
            )
            break

    return beat_results


def _beat_gallery_dir(out_dir: Path) -> Path:
    """Create (if needed) and return this run's flat `all_beats/` folder --
    clicking through `beat_1/`, `beat_2/`, ... individually to review a
    run's images was real, reported friction. Called as early as possible
    (right when `out_dir` itself is created), not only after beat
    generation finishes, since the project owner reported restarting runs
    often -- a folder that only appears at the very end is useless to
    someone who never reaches the end.
    """
    gallery_dir = out_dir / "all_beats"
    gallery_dir.mkdir(exist_ok=True)
    return gallery_dir


def _link_beat_into_gallery(out_dir: Path, index: int, image_path: str) -> None:
    """Symlink one beat's accepted image into `_beat_gallery_dir(out_dir)`,
    named by beat index. Called immediately once a beat's image is
    finalized (both the override-accept and normal-accept paths), not
    batched until the whole run finishes -- same reasoning as
    `_beat_gallery_dir`. Symlinks rather than copies, per the project
    owner's own correction: same one-folder browsing convenience with no
    extra disk space, and macOS Finder/Preview/Quick Look all follow them
    transparently. Relative targets so the links stay valid if the whole
    run folder (or all of `outputs/`) is later moved or copied elsewhere
    as a unit.
    """
    gallery_dir = _beat_gallery_dir(out_dir)
    source = Path(image_path)
    link = gallery_dir / f"beat_{index}{source.suffix}"
    link.unlink(missing_ok=True)  # re-running against the same out_dir shouldn't fail
    link.symlink_to(os.path.relpath(source, start=gallery_dir))


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
        "--max-references",
        type=int,
        help=(
            "Cap characters + locations combined -- these, not beats, set "
            "a run's real minimum image cost (one reference image each, "
            "before a single beat generates). Same soft-target-plus-"
            "enforcement idea as --max-beats, but the enforcement is "
            "best-effort, not guaranteed: only references no beat actually "
            "uses get dropped, so a scene where every character/location "
            "is genuinely in use may still land over this number -- see "
            "the printed cost estimate before confirming either way."
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
        _beat_gallery_dir(out_dir)  # exists from the very start -- see its own docstring
        log = {"time": time, "place": place, "description": description, "mock": args.mock}
        log["fixture"] = str(args.fixture)
        # A fixture is always a replay of a previously completed *real*
        # research + fact-check run -- --genre didn't exist when it was
        # captured, and there's nothing to un-ground.
        requires_grounding = True
        log["genre"] = "historical"
        log["tone"] = args.tone

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
        _beat_gallery_dir(out_dir)  # exists from the very start -- see its own docstring
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
        max_references=args.max_references,
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

    character_refs, location_refs = _generate_scene_references(
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

    beat_results = _generate_beats_with_choices(
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
    # linked in immediately on acceptance (_link_beat_into_gallery), not
    # batched here at the end.

    accepted = sum(1 for b in beat_results if b["image_path"] is not None)
    print(f"\nDone: {accepted}/{len(beat_results)} beat(s) produced an accepted image.")
    print(f"Run artifacts saved in {out_dir}")
    print(f"All accepted beat images linked in {out_dir / 'all_beats'}")


if __name__ == "__main__":
    main()
