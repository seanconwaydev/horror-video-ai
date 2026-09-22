"""Resolving a comma-separated eval flag against the options that exist.

Every eval script takes at least one `--arms`/`--models`/`--variants`-style
flag and looked its values up directly: `{k: MODELS[k] for k in
args.models.split(",")}`. A typo therefore ended the run with a bare
`KeyError: 'sonnet'`, which names the thing that failed and nothing about
what would have worked -- the same complaint `config.py` already answers
for stage names by listing the configured ones.

`run_eval.py --scenes` was worse: an unknown id matched no scene, filtered
the list to empty, and the run proceeded to do nothing while reporting
"0 scene(s)".

`blocking_space.py` already validated its `--arms` properly, against
`ARMS`, via `parser.error`. This is that, shared, so the next script does
not have to remember.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping
from typing import TypeVar

V = TypeVar("V")


def select(
    parser: argparse.ArgumentParser,
    mapping: Mapping[str, V],
    raw: str,
    *,
    flag: str,
) -> dict[str, V]:
    """Resolve `raw` (comma-separated keys) against `mapping`, preserving
    the order given. Exits via `parser.error` -- naming every unknown key
    and every valid one -- rather than raising KeyError.
    """
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys:
        parser.error(f"--{flag} was empty -- choose from: {', '.join(mapping)}")
    unknown = [k for k in keys if k not in mapping]
    if unknown:
        parser.error(
            f"unknown --{flag} value(s): {', '.join(repr(u) for u in unknown)} -- "
            f"choose from: {', '.join(mapping)}"
        )
    return {k: mapping[k] for k in keys}


def require_known(
    parser: argparse.ArgumentParser,
    known: Iterable[str],
    raw: str,
    *,
    flag: str,
) -> set[str]:
    """Same check for a flag that filters a list rather than indexing a
    mapping, where an unknown value silently selects nothing.
    """
    known_set = set(known)
    wanted = {k.strip() for k in raw.split(",") if k.strip()}
    if not wanted:
        parser.error(f"--{flag} was empty -- choose from: {', '.join(sorted(known_set))}")
    unknown = sorted(wanted - known_set)
    if unknown:
        parser.error(
            f"unknown --{flag} value(s): {', '.join(repr(u) for u in unknown)} -- "
            f"choose from: {', '.join(sorted(known_set))}"
        )
    return wanted
