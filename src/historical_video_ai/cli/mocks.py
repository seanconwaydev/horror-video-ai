"""Offline stand-ins for every paid call the pipeline makes, behind --mock.

Each returns the shape the real provider returns and nothing more, so a
--mock run exercises the pipeline's own mechanics -- stage ordering, the
confirm-loop, run logging -- with no network call, no API key and no
spend. CI's smoke job runs the whole pipeline through these, which is the
only automated coverage the cross-stage wiring has (.github/workflows/ci.yml).
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

# 90x160 (9:16, tiny for speed). The aspect-ratio guard that originally
# forced a real image here is gone with Sora (docs/decisions/0038) -- the
# video stage now only base64-encodes whatever file it's given -- but a
# real PNG is still the honest stand-in for a previz output, and previz's
# own code paths do open it.
MOCK_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAFoAAACgCAIAAAADw+wqAAABOUlEQVR4nO3SsQ3AMBAD"
    "sY/339mpYvgyA1mpPuiZ2cNnnYUcf94RcoQcIUfIEXKEHCFHyBFyhBwhR8gRcoQcIUfI"
    "EXKEHCFHyBFyhBwhR8gRcoQcIUfIEXKEHCFHyBFyhBwhR8gRcoQcIUfIEXKEHCFHyBFy"
    "hBwhR8gRcoQcIUfIEXKEHCFHyBFyhBwhR8gRcoQcIUfIEXKEHCFHyBFyhBwhR8gRcoQc"
    "IUfIEXKEHCFHyBFyhBwhR8gRcoQcIUfIEXKEHCFHyBFyhBwhR8gRcoQcIUfIEXKEHCFH"
    "yBFyhBwhR8gRcoQcIUfIEXKEHCFHyBFyhBwhR8gRcoQcIUfIEXKEHCFHyBFyhBwhR8gR"
    "coQcIUfIEXKEHCFHyBFyhBwhR8gRcoQcIUfIEXKEHCFHyBFyhBwhR8gxtxdJIAI/Sl4X"
    "NwAAAABJRU5ErkJggg=="
)


def mock_completion(**kwargs: Any) -> SimpleNamespace:
    """Research and fact-check both go through litellm.completion, so the
    prompt is what distinguishes them: only fact-check's carries the
    claims it was asked to check."""
    prompt = kwargs["messages"][0]["content"]
    if "Claims to check" in prompt:
        content = json.dumps({"flags": []})
    else:
        content = json.dumps(
            {
                "claims": [
                    {
                        "text": "[MOCK] A placeholder claim standing in for real research.",
                        "source": "[MOCK] no real source -- this is a dry run",
                        "date": None,
                        "names": [],
                    }
                ]
            }
        )
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def mock_image(**kwargs: object) -> SimpleNamespace:
    return SimpleNamespace(data=[SimpleNamespace(b64_json=MOCK_PNG_B64)])


def mock_image_edit(**kwargs: object) -> SimpleNamespace:
    return SimpleNamespace(data=[SimpleNamespace(b64_json=MOCK_PNG_B64)])


def mock_scene_planning_completion(**kwargs: object) -> SimpleNamespace:
    """A minimal ScenePlan that satisfies every validator the real stage
    runs over model output (docs/decisions/0023): one character, one
    location, and a beat whose staging references both by id."""
    content = json.dumps(
        {
            "characters": [
                {
                    "id": "mock-character",
                    "face_build": "[MOCK]",
                    "hair": "[MOCK]",
                    "wardrobe_signature": "[MOCK]",
                    "wardrobe_flexible": "[MOCK]",
                    "distinguishing_detail": "[MOCK]",
                }
            ],
            "locations": [
                {
                    "id": "mock-location",
                    "architecture": "[MOCK]",
                    "fixed_props": "[MOCK]",
                    "ambient_light": "[MOCK]",
                }
            ],
            "beats": [
                {
                    "location_id": "mock-location",
                    "subject": "[MOCK]",
                    "action": "[MOCK]",
                    "staging": [
                        {
                            "character_id": "mock-character",
                            "action": "[MOCK]",
                            "blocking": "[MOCK]",
                            "size_in_frame": "[MOCK]",
                            "occlusion": "[MOCK]",
                        }
                    ],
                    "camera": "[MOCK]",
                    "lighting": "[MOCK]",
                    "audio": "[MOCK]",
                    "duration_seconds": "4",
                }
            ],
        }
    )
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def mock_prediction(*args: object, **kwargs: object) -> dict:
    """Already 'succeeded', so --video-gen-from --mock exercises payload
    building and output handling without the real poll loop."""
    return {
        "id": "mock-prediction-id",
        "status": "succeeded",
        "output": "https://example.invalid/mock-video.mp4",
        "error": None,
    }


def mock_download(*args: object, **kwargs: object) -> bytes:
    return b"[MOCK] not a real video file"


def mock_moderation_policy_check(**kwargs: object) -> SimpleNamespace:
    """Always clean, so --mock exercises the moderation pre-flight's
    mechanics (docs/decisions/0038) without a call."""
    return SimpleNamespace(results=[SimpleNamespace(flagged=False, categories={})])
