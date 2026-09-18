"""The interactive CLI.

`historical-video-ai` resolves to `main` below (pyproject.toml), which
lives in app.py alongside the argument parser. The rest is one module per
seam: research_flow, beats, review, video_gen, runlog, mocks.
"""

from __future__ import annotations

from historical_video_ai.cli.app import main

__all__ = ["main"]
