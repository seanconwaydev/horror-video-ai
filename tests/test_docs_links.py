"""Every relative markdown link in the repo's docs resolves to a real file.

Nothing checked these before, so they accumulated silently: five were
broken when the repo audit started, every one a filename typo in a recent
ADR (docs/playbook/repo-audit-brief.md, finding 7). Broken links are what
let a superseded decision keep reading as current.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# [text](target) -- skip image embeds, which start with "!".
_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")


def _markdown_files():
    return sorted(
        path
        for path in REPO_ROOT.rglob("*.md")
        if not any(part in {".git", ".venv", "node_modules"} for part in path.parts)
    )


def _relative_links(path: Path):
    """Link targets that name a file in this repo, with any #anchor and
    ?query stripped. Absolute URLs and bare anchors aren't ours to check."""
    for target in _LINK.findall(path.read_text()):
        target = target.strip().split()[0] if target.strip() else ""
        if not target or target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        yield target, target.split("#")[0].split("?")[0]


@pytest.mark.parametrize("path", _markdown_files(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_relative_markdown_links_resolve(path):
    broken = []
    for original, filename in _relative_links(path):
        if not filename:
            continue  # a pure anchor once the fragment is stripped
        resolved = (REPO_ROOT / filename) if filename.startswith("/") else (path.parent / filename)
        if not resolved.exists():
            broken.append(original)
    assert not broken, (
        f"{path.relative_to(REPO_ROOT)} links to files that don't exist: {broken}"
    )
