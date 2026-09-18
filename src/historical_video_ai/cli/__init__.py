"""The interactive CLI, split across modules by seam.

`historical-video-ai` resolves to `main` below (pyproject.toml). The
package is being split one seam at a time out of what was a single
2,500-line module -- see docs/playbook/open-tasks.md for what has moved
and what has not.
"""

from __future__ import annotations

from historical_video_ai.cli.app import main

__all__ = ["main"]
