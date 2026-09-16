"""An ADR that supersedes another is linked from both ends.

Supersession used to be recorded only forwards -- the superseding ADR
named the one it replaced, and the replaced ADR said nothing, so opening
it returned a decision that read as current. Sixteen backlinks were added
by hand (docs/playbook/repo-audit-brief.md, finding 6); this keeps the
next one from being forgotten.

Only the Status block is checked, since that is where a reader looks to
find out whether a decision still stands. An ADR discussing a
supersession in its Context prose is not making the claim this enforces.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

DECISIONS = Path(__file__).resolve().parent.parent / "docs" / "decisions"

# Active voice only: "Supersedes 0012" is a forward declaration, while
# "Superseded by 0038" is the backlink it demands and must not be read as
# one itself.
_DECLARES = re.compile(r"\b(Supersedes|Amends|Narrows|voids|Voids)\b")

# The number comes from the link target, not the link text -- 0035 writes
# its link as [decisions/0034](./0034-creative-flag-...md).
_ADR_LINK = re.compile(r"\[[^\]]*\]\(\.?/?(\d{4})-[^)]+\)")


def _status_block(path: Path) -> str:
    """Everything before the first '## Context'. Covers both ADR layouts:
    an inline 'Status: Accepted' line and a '## Status' section."""
    return path.read_text().split("## Context")[0]


def _adr_number(path: Path) -> str:
    return path.name[:4]


def _declared_supersessions(path: Path) -> set[str]:
    """ADR numbers this one claims to supersede, amend or void.

    Split on sentence ends and semicolons so a supporting citation in a
    neighbouring clause isn't swept up as a target -- 0050 supersedes 0024
    and, separately, cites 0047 for where the mechanism went."""
    targets = set()
    for segment in re.split(r"[.;]\s|\n\n", _status_block(path)):
        if _DECLARES.search(segment):
            targets.update(_ADR_LINK.findall(segment))
    return targets - {_adr_number(path)}


_ADRS = sorted(p for p in DECISIONS.glob("[0-9][0-9][0-9][0-9]-*.md"))


@pytest.mark.parametrize("path", _ADRS, ids=_adr_number)
def test_superseded_adr_links_back_to_the_one_that_replaced_it(path):
    number = _adr_number(path)
    missing = []
    for target in sorted(_declared_supersessions(path)):
        matches = sorted(DECISIONS.glob(f"{target}-*.md"))
        assert matches, f"{path.name} supersedes {target}, which doesn't exist"
        if number not in _ADR_LINK.findall(_status_block(matches[0])):
            missing.append(matches[0].name)
    assert not missing, (
        f"{path.name} declares it supersedes {missing}, but their Status blocks "
        f"don't link back to {number}. Add a line under Status there, e.g. "
        f"'Superseded by [{number}](./{path.name}).'"
    )
