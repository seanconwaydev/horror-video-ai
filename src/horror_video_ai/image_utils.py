"""Shared helper for building vision-model image inputs -- every stage that
sends a reference image to a vision-capable model (moderation's policy
check, and previz_review, which survives only for evals per
docs/decisions/0055) base64-encodes it and wraps it in the same
`{"type": "image_url", "image_url": {"url": "data:..."}}` content-block
shape litellm.completion() and litellm.moderation() both expect for an
image input part.
"""

from __future__ import annotations

import base64
from pathlib import Path


def build_image_content_block(image_path: Path, *, mime_type: str = "image/png") -> dict:
    """Read `image_path`, base64-encode it, and return the image content
    block shape used in a vision message's `content` list (or as one item
    of litellm.moderation()'s multi-modal `input` list)."""
    image_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_b64}"}}
