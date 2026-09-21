"""The interactive CLI.

`horror-video-ai` resolves to `main` below (pyproject.toml), which
lives in app.py alongside the argument parser. The rest is one module per
seam: beats, review, video_gen, runlog, mocks.
"""

from __future__ import annotations

from horror_video_ai.cli.app import main

__all__ = ["main"]
