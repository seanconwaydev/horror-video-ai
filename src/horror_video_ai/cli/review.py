"""The interactive review widgets: confirm, prompt, show, edit, accept.

Every stage that costs money is gated on one of these
(docs/architecture.md, "Design principles"), and the interactive path is
where this project's design effort goes -- --yes is the secondary mode
(docs/decisions/0043).

`review_item` and `edit_item_fields` work on any frozen dataclass
artifact the pipeline produces -- Character, Location, Beat -- which is
what `ItemT` names.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any, TypeVar

from horror_video_ai.stages.scene_planning import (
    Beat,
    ScenePlan,
    ScenePlanningError,
    beat_visibility_warnings,
    check_beat_location_references,
    check_staging_visibility,
    check_unique_ids,
    identity_field_pose_warnings,
)


def confirm(prompt: str, *, auto_yes: bool = False) -> bool:
    """`auto_yes` (--yes) answers every confirm prompt as yes without
    calling input() at all -- see docs/decisions/0017-non-interactive-mode.md.
    Prints the prompt either way, so a run's transcript still shows every
    decision point even when nothing was actually typed."""
    if auto_yes:
        print(f"{prompt} [y/n]: y (--yes)")
        return True
    while True:
        answer = input(f"{prompt} [y/n]: ").strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("Please answer y or n.")


def prompt_if_missing(value: str | None, label: str, *, auto_yes: bool = False) -> str:
    """time/place/description are all required (docs/decisions/0006) --
    loop until a non-empty value is given, printing an explicit error on
    every empty attempt (whether it came in empty via a CLI flag or was
    left blank at the prompt) rather than silently re-prompting.

    `auto_yes` (--yes) can't answer a free-text field -- there's nothing
    sensible to guess -- so a missing value under --yes raises instead of
    blocking on input(), which would just hang (or crash with EOFError)
    in a genuinely non-interactive context anyway.
    """
    if not value and auto_yes:
        raise ValueError(
            f"{label} is required and cannot be empty -- --yes can't answer this "
            "for you, pass it explicitly as a flag."
        )
    while not value:
        print(f"Error: {label} is required and cannot be empty.")
        value = input(f"{label}: ").strip()
    return value

if TYPE_CHECKING:  # typeshed-only; not importable at runtime.
    from _typeshed import DataclassInstance

#: Any frozen dataclass artifact the review loop edits -- Character,
#: Location or Beat. Named so edit_item_fields and review_item can say
#: they return the same type they were handed, which `object` erased at
#: every call site.
ItemT = TypeVar("ItemT", bound="DataclassInstance")


def print_item_fields(item: ItemT) -> None:
    for f in dataclasses.fields(item):
        value = getattr(item, f.name)
        # staging is a list of dataclasses; its repr is unreadable in a
        # review prompt, and this is the field a human most needs to read
        # (docs/decisions/0049).
        if f.name == "staging" and value:
            print("  staging:")
            for s in value:
                print(f"    - {s.character_id}: {s.action}")
                print(f"      stands: {s.blocking}")
                if s.size_in_frame:
                    print(f"      size in frame: {s.size_in_frame}")
                if s.occlusion:
                    print(f"      hidden by: {s.occlusion}")
            continue
        print(f"  {f.name}: {value}")


# A human editing a beat is almost always reacting to a specific rendered
# mismatch (the wrong action, the wrong framing, a missing shadow), so
# this skips the fields that don't drive the picture -- notably
# location_id, which shouldn't change here without the revalidation
# decisions/0028 requires for a real structural edit. `contact` and
# `intensity` earn their place because the two failures they exist to fix
# -- characters not touching, nobody moving -- are exactly what a human
# rejects an image for (docs/decisions/0071).
BEAT_QUICK_EDIT_FIELDS = ("staging", "action", "contact", "intensity", "camera", "lighting")


def edit_item_fields(item: ItemT, *, fields: tuple[str, ...] | None = None) -> ItemT:
    """Prompt for a new value per field (blank keeps the current one) and
    return the updated item -- the shared editing mechanism behind both
    review_item's (a)ccept/(e)dit loop and the beat-generation loop's
    (e)dit choice (docs/decisions/0023, 0024). Generic over any frozen
    dataclass with string fields.

    `fields`, if given, restricts prompting to just those field names --
    every other field keeps its current value untouched. See
    BEAT_QUICK_EDIT_FIELDS."""
    updates: dict[str, Any] = {}
    field_names = fields if fields is not None else [f.name for f in dataclasses.fields(item)]
    for name in field_names:
        current = getattr(item, name)
        # staging is a list of dataclasses, so walk into it rather than
        # asking for a literal repr back. It is also where a beat's most
        # editable content now lives (docs/decisions/0049).
        if name == "staging":
            edited = [
                dataclasses.replace(
                    s,
                    **{
                        k: v
                        for k, v in (
                            ("action", input(f"  {s.character_id} action [{s.action}]: ").strip()),
                            ("blocking",
                             input(f"  {s.character_id} stands [{s.blocking}]: ").strip()),
                            ("size_in_frame",
                             input(
                                 f"  {s.character_id} size in frame [{s.size_in_frame}]: "
                             ).strip()),
                            ("occlusion",
                             input(f"  {s.character_id} hidden by [{s.occlusion}]: ").strip()),
                        )
                        if v
                    },
                )
                for s in current
            ]
            if edited != list(current):
                updates[name] = edited
            continue
        new_value = input(f"  {name} [{current}]: ").strip()
        if new_value:
            updates[name] = new_value
    return dataclasses.replace(item, **updates)


def review_item(item: ItemT, *, item_desc: str, auto_yes: bool = False) -> ItemT:
    """Print one scene-plan item (Character/Location/Beat) and let a human
    accept it as-is or edit it field-by-field -- docs/decisions/0023's
    per-item review loop. Editing replaces the item directly and is never
    re-verified through another LLM pass: these are creative fields (a
    character's hairstyle, a location's lighting), and there is nothing
    to check them against.

    Generic over any frozen dataclass with string fields -- Character,
    Location, and Beat all qualify, so one function serves all three
    review passes in `review_scene_plan`. A Beat's edit is restricted to
    BEAT_QUICK_EDIT_FIELDS rather than every field -- see that constant.
    """
    print(f"\n{item_desc}:")
    print_item_fields(item)

    if auto_yes:
        print("(a)ccept or (e)dit? [a/e]: a (--yes)")
        return item

    action = ""
    while action not in ("a", "e"):
        action = input("(a)ccept or (e)dit? [a/e]: ").strip().lower()
    if action == "a":
        return item
    if isinstance(item, Beat):
        return edit_item_fields(item, fields=BEAT_QUICK_EDIT_FIELDS)
    return edit_item_fields(item)


def _review_list_with_unique_ids(items: list, *, item_label: str, auto_yes: bool) -> list:
    """Review each item (Character or Location) via review_item, then
    re-check the whole reviewed list for a duplicate id -- an edit can
    introduce a collision the LLM's original output didn't have just as
    easily as the LLM itself can (docs/decisions/0028). If one turns up
    interactively, re-review the whole list rather than crash a review
    session the human otherwise just finished; under auto_yes no edit
    could have happened, so a failure here means the LLM's own output was
    already broken and _parse_scene_plan should have already caught it --
    raising here is a safety net, not the expected path.
    """
    while True:
        reviewed = [
            review_item(item, item_desc=f"{item_label} '{item.id}'", auto_yes=auto_yes)
            for item in items
        ]
        try:
            check_unique_ids(reviewed, label=item_label.lower())
        except ScenePlanningError as exc:
            print(f"\n{exc}")
            if auto_yes:
                raise
            print("Reviewing these again -- fix the colliding id(s).")
            items = reviewed
            continue
        return reviewed


def review_scene_plan(plan: ScenePlan, *, auto_yes: bool = False) -> ScenePlan:
    """Per-item accept-or-edit review of a full ScenePlan --
    docs/decisions/0023. Reviewed in a fixed, strictly linear order --
    characters, then locations, then beats -- with no going back to reopen
    an earlier list once later ones are under review. Deliberate v1
    simplification, not an oversight: beats are reviewed against an
    already-finalized set of characters/locations, matching the natural
    dependency order, rather than building a free-form editor.

    Re-validates after edits, not just the LLM's original output
    (docs/decisions/0028): an edited beat's location_id, or an edited
    location's own id, can silently stop matching anything, which would
    otherwise drop all location grounding for that beat with no warning
    at all.
    """
    print("\n--- scene plan review (docs/decisions/0023) ---")
    for warning in identity_field_pose_warnings(plan.characters):
        print(f"\nheads up: {warning}")
    for warning in beat_visibility_warnings(plan.beats):
        print(f"\nheads up: {warning}")
    reviewed_characters = _review_list_with_unique_ids(
        plan.characters, item_label="Character", auto_yes=auto_yes
    )
    still_posed = identity_field_pose_warnings(reviewed_characters)
    if still_posed and not auto_yes:
        print(f"\n{len(still_posed)} identity field(s) still look like a pose; continuing anyway.")
    reviewed_locations = _review_list_with_unique_ids(
        plan.locations, item_label="Location", auto_yes=auto_yes
    )

    reviewed_beats = []
    for b in plan.beats:
        while True:
            reviewed_beat = review_item(
                b, item_desc=f"Beat at '{b.location_id}': {b.action}", auto_yes=auto_yes
            )
            try:
                check_beat_location_references([reviewed_beat], reviewed_locations)
                check_staging_visibility([reviewed_beat])
            except ScenePlanningError as exc:
                print(f"\n{exc}")
                if auto_yes:
                    raise
                print("Reviewing this beat again.")
                b = reviewed_beat
                continue
            reviewed_beats.append(reviewed_beat)
            break

    return ScenePlan(characters=reviewed_characters, locations=reviewed_locations, beats=reviewed_beats)
