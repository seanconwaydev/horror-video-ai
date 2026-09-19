"""An eval fixture must either match today's prompt shape or say it doesn't.

`evals/anchor_scene.json` sat five ADRs stale for weeks without anything
noticing, because `_parse_staging`'s fallback degrades gracefully: a beat
with no `staging` silently becomes one entry for the first character with
empty `blocking`, `size_in_frame` and `occlusion`, so the prompt loses its
STANDS:/SIZE IN FRAME:/HIDDEN BY: lines and nothing raises. The previous
instance of the same rot (ADR 0045 deleting `Beat.cinematography` while
the fixture kept it) at least crashed.

CI cannot catch it from the eval scripts themselves -- the smoke job runs
their `--dry-run`s, which parse a fixture but never build a prompt from
it. So the guard lives here. Per ADR 0064 a deliberately frozen fixture
opts out by marker, and everything else must carry current-shape staging.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from historical_video_ai.stages.scene_planning import load_scene_plan

EVALS_DIR = Path(__file__).resolve().parents[1] / "evals"


def scene_plan_fixtures() -> list[Path]:
    """Every committed evals/*.json holding a scene plan."""
    found = []
    for path in sorted(EVALS_DIR.glob("*.json")):
        raw = json.loads(path.read_text())
        if isinstance(raw, dict) and isinstance(raw.get("plan"), dict):
            found.append(path)
    return found


def test_there_is_at_least_one_scene_plan_fixture_to_check():
    """Guards the guard: a glob that matches nothing passes silently."""
    assert scene_plan_fixtures()


@pytest.mark.parametrize("path", scene_plan_fixtures(), ids=lambda p: p.name)
def test_fixture_carries_current_staging_or_declares_itself_historical(path):
    raw = json.loads(path.read_text())

    if raw.get("_historical"):
        assert raw.get("_note", "").strip(), (
            f"{path.name} is marked historical but says nothing about why. "
            "The marker is an opt-out from the staging check, so it has to "
            "carry the reasoning that justifies it (ADR 0064)."
        )
        return

    plan = load_scene_plan(raw["plan"])
    for index, beat in enumerate(plan.beats, start=1):
        assert beat.staging, (
            f"{path.name} beat {index} carries no `staging`, so the prompt "
            "built from it has no STANDS:/SIZE IN FRAME:/HIDDEN BY: lines "
            "(ADR 0049). Re-freeze it from a current run, or mark the "
            "fixture `\"_historical\": true` with a note saying why."
        )
        for entry in beat.staging:
            assert entry.blocking.strip(), (
                f"{path.name} beat {index}: staging for '{entry.character_id}' "
                "has no `blocking` (ADR 0059)."
            )
            assert entry.size_in_frame.strip(), (
                f"{path.name} beat {index}: staging for '{entry.character_id}' "
                "has no `size_in_frame` -- the strongest placement instruction "
                "measured so far, 14/14 (ADR 0059)."
            )
