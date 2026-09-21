"""Generating a scene plan's beats into images, one beat at a time.

The expensive half of a run and the one with a human in the loop at every
step: reference images for each character and location first, then per
beat a set of candidates to choose between (docs/decisions/0024), with
reject-and-retry, edit-and-retry, and reroll on top
(docs/decisions/0029, 0043).

Two behaviours here are load-bearing and easy to undo by accident. Every
attempt is recorded and every finished beat is written to the run log
immediately, because runs are routinely abandoned partway and the
judgements are the point (docs/decisions/0053, 0056). And a rejected
image is archived under a monotonic index rather than the attempt
counter, because a restarted cycle reuses the counter and silently
overwrote a paid-for image (see runlog.next_archive_path).
"""

from __future__ import annotations

import dataclasses
import os
from collections.abc import Callable, Sequence
from pathlib import Path

from horror_video_ai.cli.review import (
    BEAT_QUICK_EDIT_FIELDS,
    confirm,
    edit_item_fields,
)
from horror_video_ai.cli.runlog import next_archive_path, safe_path_component
from horror_video_ai.stages.previz import (
    DEFAULT_STYLE,
    PrevizResult,
    build_character_sheet_prompt,
    build_location_reference_prompt,
    run_beat_image_stage,
    run_reference_image_stage,
)
from horror_video_ai.stages.scene_planning import Beat, Character, Location, ScenePlan

# See docs/decisions/0009-previz-image-review.md -- your call: bounded, not
# tunable via a flag, to keep behavior predictable rather than open-ended.
MAX_PREVIZ_ATTEMPTS = 3

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
        if staged.blocking:
            lines.append(f"  {name} stands: {staged.blocking}")
        if staged.size_in_frame:
            lines.append(f"  {name} size in frame: {staged.size_in_frame}")
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


def generate_image_with_retries(
    generate_fn: Callable[[], list[PrevizResult]],
    *,
    out_dir: Path,
    archive_prefix: str = "previz_attempt",
    on_image_generated: Callable[[PrevizResult], None] | None = None,
    on_reviewed: Callable[[str | None, int], str] | None = None,
    on_attempt: Callable[[dict], None] | None = None,
    choose_auto: bool = False,
    max_attempts: int | None = MAX_PREVIZ_ATTEMPTS,
    context: str | None = None,
) -> tuple[PrevizResult | None, list[dict]]:
    """Generate one attempt's candidate images via `generate_fn`, ask the
    human what to do, and regenerate until something is kept or the human
    stops -- capped at `max_attempts`. Shared by both generation paths;
    only how the image itself gets made differs between them.

    `generate_fn` takes no arguments. Anything an attempt needs to carry
    forward -- human (f)eedback from an earlier cycle, an edited beat --
    is closed over by the caller when it builds the closure, because that
    state outlives a single call to this function (see
    `generate_beats_with_choices`).

    There is no automated review step. docs/decisions/0055 deleted
    `previz_review` from the pipeline after measuring 56% agreement with
    the owner's own accept/reject calls, against 79% for accepting
    everything. Asking the human after every attempt rather than only
    after a rejection is docs/decisions/0043, and it is what was doing the
    work even while the reviewer was still running.

    Returns (accepted PrevizResult, attempt log), or (None, attempt log)
    if the human kept nothing or stopped early. A rejected attempt's image
    is archived as `<archive_prefix>_<n>_rejected.png` rather than
    overwritten.

    `on_image_generated`, if given, is called with each attempt's
    PrevizResult right after the image is written and before anything can
    fail or block on input -- without it, an interrupted run left a real,
    already-paid-for image on disk with no record of it
    (docs/decisions/0056).

    `on_reviewed`, if given, is called once per attempt as
    `(None, attempt)` -- the first argument is a vestige of the deleted
    reviewer's concern text and is always None. Its return value picks one
    of three outcomes: "accept" keeps this attempt's image, "stop" ends the
    loop with nothing kept, anything else regenerates. With no callback
    every attempt is accepted, which is what --yes does.
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


def generate_scene_references(
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


def generate_beats_with_choices(
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
    loop (docs/decisions/0009, via generate_image_with_retries), but now
    with an on-rejection hook (docs/decisions/0029): after *any*
    rejection, not just after all attempts are exhausted, a human can edit
    the beat's text and retry fresh, or give up on this beat now --
    otherwise Enter keeps the existing blind-retry behavior. This matters
    because some rejections are attributable to something baked into the
    prompt itself (e.g. a wrong detail on the shared Character),
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
        # generate_image_with_retries, which is per call: an (e)dit or
        # (f)eedback starts a fresh call that returns only its own
        # attempts, and the previous binding used to be thrown away at
        # that boundary (docs/decisions/0053).
        all_attempts: list[dict] = []
        # What the human did at each attempt's prompt, keyed by cycle and
        # attempt number -- the judgement itself, as opposed to what was
        # generated.
        human_actions: dict[tuple[int, int], dict] = {}
        # Human-typed (f)eedback, oldest first. Spans cycles like
        # all_attempts, because feedback ends a cycle and the next one has
        # to carry it. Kept separate from the beat rather than appended to
        # `beat.action`: a planned action and a correction to a render are
        # different facts, and the recorded beat should stay as it was
        # written (docs/decisions/0057).
        corrections: list[str] = []
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
                corrections: list = corrections,
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
                    # smaller") carried into every later attempt on this
                    # beat -- cheaper than rewriting a field that was
                    # already mostly right, for the common case where the
                    # plan was fine and only the render missed one thing.
                    note = ""
                    while not note:
                        note = input("  Feedback (applied to the next attempt): ").strip()
                    # A human-authored correction naming exactly what the
                    # render got wrong -- the highest-value text in the
                    # whole loop.
                    human_actions[(cycle, attempt)]["feedback"] = note
                    corrections.append(note)
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
                # Read at call time, not at definition time: _on_reviewed
                # appends to this same list between cycles, and a fresh
                # _generate is defined each iteration, so the next
                # attempt sees every correction typed so far.
                corrections: list = corrections,
            ) -> list[PrevizResult]:
                nonlocal attempt_n
                attempt_n += 1
                cap = f"/{MAX_PREVIZ_ATTEMPTS}" if auto_yes else ""
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
                        corrections=tuple(corrections),
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
            previz_result, _ = generate_image_with_retries(
                _generate,
                out_dir=beat_out_dir,
                archive_prefix=f"beat{i}_attempt",
                on_reviewed=_on_reviewed,
                on_attempt=_on_attempt,
                choose_auto=auto_yes,
                max_attempts=MAX_PREVIZ_ATTEMPTS if auto_yes else None,
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
            link_beat_into_gallery(out_dir, i, str(previz_result.image_path))
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


def beat_gallery_dir(out_dir: Path) -> Path:
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


def link_beat_into_gallery(out_dir: Path, index: int, image_path: str) -> None:
    """Symlink one beat's accepted image into `beat_gallery_dir(out_dir)`,
    named by beat index. Called immediately once a beat's image is
    finalized (both the override-accept and normal-accept paths), not
    batched until the whole run finishes -- same reasoning as
    `beat_gallery_dir`. Symlinks rather than copies, per the project
    owner's own correction: same one-folder browsing convenience with no
    extra disk space, and macOS Finder/Preview/Quick Look all follow them
    transparently. Relative targets so the links stay valid if the whole
    run folder (or all of `outputs/`) is later moved or copied elsewhere
    as a unit.
    """
    gallery_dir = beat_gallery_dir(out_dir)
    source = Path(image_path)
    link = gallery_dir / f"beat_{index}{source.suffix}"
    link.unlink(missing_ok=True)  # re-running against the same out_dir shouldn't fail
    link.symlink_to(os.path.relpath(source, start=gallery_dir))
