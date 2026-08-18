"""Stage 2: Research -- produce a structured, sourced fact sheet for a topic.

See docs/pipeline.md ("2. Research") for the stage's purpose and review gate.

Grounding note: the research model needs real web-search capability so it
isn't just relying on parametric recall, and which model/provider actually
provides that is still an open question (see docs/architecture.md, "Open
questions"). This module calls whatever model is pinned in
config/models.yaml with a plain prompt -- no search tool wired in yet.
Treat any fact sheet produced today as a placeholder until that decision is
made and recorded as its own ADR.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field

import litellm

from historical_video_ai.config import get_stage_model


class ResearchError(Exception):
    """Raised when a research stage response is missing or malformed."""


@dataclass(frozen=True)
class Claim:
    """A single sourced claim in a fact sheet.

    Per docs/pipeline.md: "nothing here should be unsourced" -- `source` is
    required, not optional.
    """

    text: str
    source: str
    date: str | None = None
    names: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FactSheet:
    """The reviewable artifact stage 2 produces: a topic plus its sourced claims."""

    topic: str
    claims: list[Claim]


_PROMPT_TEMPLATE = """\
You are a historical researcher producing a fact sheet for a short video on \
the following topic. Respond with ONLY a JSON object (no prose, no markdown \
fences) matching this exact shape:

{{
  "topic": "<the topic, restated>",
  "claims": [
    {{
      "text": "<a single factual claim>",
      "source": "<a citation or source for this specific claim -- required>",
      "date": "<date associated with this claim, or null>",
      "names": ["<person or place names involved>"]
    }}
  ]
}}

Every claim must have a real, credible source -- do not include unsourced
claims. If you are not confident a claim is accurate, omit it rather than
guess.

Topic: {topic}
"""


def _parse_fact_sheet(raw_content: str) -> FactSheet:
    try:
        data = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        raise ResearchError(f"Research stage response was not valid JSON: {exc}") from exc

    if not isinstance(data, dict) or "topic" not in data or "claims" not in data:
        raise ResearchError("Research stage response is missing 'topic' or 'claims'")

    claims: list[Claim] = []
    for i, raw_claim in enumerate(data["claims"]):
        if not isinstance(raw_claim, dict) or not raw_claim.get("text"):
            raise ResearchError(f"Claim {i} is missing 'text'")
        if not raw_claim.get("source"):
            raise ResearchError(
                f"Claim {i} ('{raw_claim.get('text')}') is missing a 'source'"
            )
        claims.append(
            Claim(
                text=raw_claim["text"],
                source=raw_claim["source"],
                date=raw_claim.get("date"),
                names=list(raw_claim.get("names") or []),
            )
        )

    return FactSheet(topic=data["topic"], claims=claims)


def run_research_stage(
    topic: str,
    *,
    model: str | None = None,
    completion_fn: Callable = litellm.completion,
) -> FactSheet:
    """Produce a sourced fact sheet for `topic`.

    `model` defaults to the pinned model for the "research" stage in
    config/models.yaml (see docs/decisions/0003). `completion_fn` defaults
    to litellm.completion and exists as an injection point for tests -- pass
    a fake to avoid making a real API call.

    Raises ResearchError if the model's response isn't valid JSON or is
    missing required fields, rather than returning a partial/guessed result.
    """
    resolved_model = model or get_stage_model("research")

    response = completion_fn(
        model=resolved_model,
        messages=[{"role": "user", "content": _PROMPT_TEMPLATE.format(topic=topic)}],
    )
    raw_content = response.choices[0].message.content
    return _parse_fact_sheet(raw_content)
