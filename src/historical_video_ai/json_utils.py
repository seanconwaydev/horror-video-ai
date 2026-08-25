"""Shared JSON-parsing helpers used across pipeline stages.

Every stage that asks a model to "respond with ONLY a JSON object, no
markdown fences" (research, fact_check, previz's review) can still get one
back wrapped in a ```json ... ``` fence anyway -- observed for real against
a live claude-sonnet-5 call while testing previz_review (not a hypothetical
edge case): the same prompt and image produced raw JSON on one call and a
fenced response on the next. `json.loads()` fails on the fence with
"Expecting value: line 1 column 1", the exact same error text truly empty
content produces -- indistinguishable from a traceback alone.

This is a common, harmless formatting quirk in how models emit JSON, not a
sign of a genuinely wrong or hallucinated response, so stripping the fence
before parsing doesn't loosen this project's fail-loud validation of the
response's *content* -- a response that's still malformed after stripping
any fence still raises the same JSONDecodeError it always would.
"""

from __future__ import annotations

import re

_FENCE_PATTERN = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL)


def strip_markdown_json_fence(raw: str) -> str:
    """Strip a leading/trailing markdown code fence (```json ... ``` or
    plain ``` ... ```) from `raw`, if present.

    Returns `raw` unchanged if it isn't fenced -- this only removes a
    wrapper, never touches what's inside it, so a still-malformed JSON
    body raises exactly the same error it would have without this step.
    """
    stripped = raw.strip()
    match = _FENCE_PATTERN.match(stripped)
    return match.group(1).strip() if match else raw
