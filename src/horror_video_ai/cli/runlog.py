"""Where a run's files go, and how a finished run is read back.

Every path a run writes is built here: the run directory itself, the
archive name for a rejected image, and the sanitised form of a
model-authored id before it is used as a directory name, plus reading a
run's log back.

It used to reconstruct a FactSheet/FactCheckResult from a saved log,
which is what --fixture replayed. docs/decisions/0069 deleted research
and fact-check, so there is nothing expensive left to replay: a scene is
three strings on the command line.

Two of these encode bugs found in real runs rather than anything
self-evident, and their docstrings say which: `next_archive_path` (a
counter that reused a name and silently destroyed a paid-for image) and
`project_root` (outputs/ nesting inside outputs/).
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path


def safe_path_component(value: str) -> str:
    """Make a scene-plan id safe to use as a directory name.

    Ids come from a planning model and can be changed by hand at review
    time, so they are not guaranteed to be single path components. An id
    containing a separator -- "a/../../evil" being the worst shape --
    resolved outside the run directory entirely.
    """
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    return cleaned or "unnamed"


def next_archive_path(out_dir: Path, prefix: str, *, suffix: str = "rejected") -> Path:
    """First unused `<prefix>_<n>_rejected.png` in `out_dir`.

    Deliberately not derived from the retry loop's own attempt counter.
    A (r)eroll, or an (e)dit-and-retry whose attempts then fail, starts a
    *fresh* `_generate_image_with_retries` call against the same directory
    -- its counter restarts at 1, so deriving the name from it reused
    `<prefix>_1_rejected.png`, and `Path.rename` replaces the destination
    silently on POSIX. That destroyed the earlier cycle's already-paid-for
    images with no warning, found in a real run.

    The index is therefore a monotonic count of rejected images kept for
    this beat, not the "attempt N/3" shown while generating -- those are
    genuinely different things once a beat has had more than one cycle.
    Each attempt's own record in the run log carries its real image path,
    so nothing depends on the two agreeing.
    """
    # Globs on the index rather than the full name: the same index must not
    # be reused under a different suffix, or a superseded image would
    # overwrite a rejected one with the same number.
    n = 1
    while any(out_dir.glob(f"{prefix}_{n}_*.png")):
        n += 1
    return out_dir / f"{prefix}_{n}_{suffix}.png"


def slugify(text: str, max_length: int = 40) -> str:
    """Turn free text into a short, filesystem-safe fragment for a run
    directory name -- lowercase, every run of non-alphanumeric characters
    collapsed to a single hyphen, trimmed to `max_length` without cutting
    a word in half where a hyphen boundary is nearby, and hyphens stripped
    from both ends.

    Returns "" if nothing usable remains (empty input, or input that's
    entirely punctuation) -- callers should treat an empty slug as "no
    context available" rather than tack on a trailing separator with
    nothing after it.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if len(slug) <= max_length:
        return slug
    truncated = slug[:max_length]
    if "-" in truncated:
        truncated = truncated.rsplit("-", 1)[0]
    return truncated


def project_root() -> Path:
    """Walk up from this file looking for pyproject.toml, so outputs/
    always lands in the same place regardless of the directory the command
    was invoked from. (Previously outputs/ was created relative to the
    current working directory, which silently nested outputs/outputs/ if
    you happened to be inside a prior run's outputs/ folder when you ran
    the command again.)

    Raises RuntimeError if no ancestor has a pyproject.toml -- fail loud
    rather than guess at a directory (e.g. a fixed parents[2] offset) that
    was never actually confirmed to be the project root, which would risk
    reintroducing the exact silent-nesting bug this function exists to
    prevent."""
    here = Path(__file__).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise RuntimeError(
        f"Could not find pyproject.toml in any ancestor directory of {here} -- "
        "outputs/ needs a real, confirmed project root."
    )


def new_run_dir(slug: str | None = None) -> Path:
    """Create (and return) this run's output directory, named
    `run_<timestamp>` or `run_<timestamp>_<slug>` if `slug` is given and
    non-empty. The timestamp alone told you *when* a run happened but
    nothing about *what* it was -- telling scenes apart meant opening
    run_log.json in each candidate folder. `slug` should already be a
    filesystem-safe fragment (see `slugify`) -- this function doesn't
    sanitize it itself, so callers building one from free text must slugify
    it first."""
    run_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    base = f"run_{run_id}_{slug}" if slug else f"run_{run_id}"
    outputs = project_root() / "outputs"

    # Second precision alone is not unique: re-running the same command
    # right after a failed attempt -- routine while iterating -- lands in
    # the same second with the same slug, and `exist_ok=True` then let the
    # second run write its images and log straight over the first one's.
    # A numeric suffix keeps the readable name while making a collision
    # impossible. (video_generation.py already reached for microsecond
    # precision against this same hazard; this keeps folder names legible
    # instead.)
    dir_name, n = base, 1
    while (outputs / dir_name).exists():
        n += 1
        dir_name = f"{base}-{n}"

    d = outputs / dir_name
    d.mkdir(parents=True)
    return d


def write_log(out_dir: Path, log: dict) -> None:
    """Replace run_log.json atomically: write a sibling temp file, then
    rename it over the target.

    A plain `write_text` truncates the real file first, so any interruption
    between truncate and the last chunk leaves invalid JSON and
    `read_log` loses the whole run -- research, fact-check and every
    finished beat, not just the write in progress. Real logs run to tens
    of kilobytes, so that window spans several write syscalls rather than
    one.

    It is a live risk rather than a theoretical one because
    docs/decisions/0056 deliberately made these writes frequent -- three
    per beat attempt -- to stop an abandoned run losing its work, and
    abandoning a run part-way is the normal way this pipeline is used.
    `os.replace` is atomic on POSIX when both paths are on one
    filesystem, which a sibling temp file guarantees.

    No fsync: this protects against the process dying (Ctrl-C, a crash),
    which is what actually happens here, not against power loss, which
    would cost a flush on every one of those writes.
    """
    path = out_dir / "run_log.json"
    tmp_path = path.parent / f"{path.name}.tmp"
    tmp_path.write_text(json.dumps(log, indent=2, default=str))
    os.replace(tmp_path, path)


def read_log(out_dir: Path) -> dict:
    return json.loads((out_dir / "run_log.json").read_text())
