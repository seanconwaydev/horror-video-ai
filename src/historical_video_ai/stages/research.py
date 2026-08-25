"""Stage 2: Research -- produce a structured, sourced fact sheet for one
described scene.

See docs/pipeline.md ("2. Research") for the stage's purpose and review
gate, and docs/decisions/0006-narrow-v1-scope-single-image.md for why this
stage takes a (time, place, description) scene instead of a bare topic.

Grounding: per docs/decisions/0007-research-fact-check-previz-models.md,
this stage is pinned to a Perplexity Sonar model, which performs live web
search as part of generating its answer -- no separate search tool needs to
be wired in here the way Gemini's grounding does (see the fact_check stage).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field

import litellm

from historical_video_ai.config import get_stage_model
from historical_video_ai.json_utils import strip_markdown_json_fence


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
    """The reviewable artifact stage 2 produces: the scene that was asked
    for, plus the sourced claims needed to depict it accurately."""

    time: str
    place: str
    description: str
    claims: list[Claim]


_PROMPT_TEMPLATE = """\
You are a historical researcher producing a sourced fact sheet to help \
accurately depict ONE specific scene for a short video. The scene's main \
character is a generic, unnamed person -- do not invent a specific \
historical figure unless the description below names one. Write and think \
about the scene in third person.

Time: {time}
Place: {place}
What happens: {description}

Research enough about this time and place to describe how it would \
accurately look and feel: architecture, clothing/attire, objects and \
technology available then, atmosphere, and any specific historical detail \
relevant to what happens in the description above. Historical accuracy is \
the thing most likely to publicly embarrass the channel if it's wrong, so \
nothing here should be unsourced -- if you are not confident a claim is \
accurate, omit it rather than guess.

Respond with ONLY a JSON object (no prose, no markdown fences) matching this \
exact shape:

{{
  "claims": [
    {{
      "text": "<a single factual/visual claim relevant to depicting this scene>",
      "source": "<a citation or source for this specific claim -- required>",
      "date": "<date associated with this claim, or null>",
      "names": ["<person, place, or object names involved>"]
    }}
  ]
}}
"""


def _parse_claims(raw_content: str) -> list[Claim]:
    try:
        data = json.loads(strip_markdown_json_fence(raw_content))
    except json.JSONDecodeError as exc:
        raise ResearchError(f"Research stage response was not valid JSON: {exc}") from exc

    if not isinstance(data, dict) or "claims" not in data:
        raise ResearchError("Research stage response is missing 'claims'")

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

    return claims


def run_research_stage(
    time: str,
    place: str,
    description: str,
    *,
    model: str | None = None,
    completion_fn: Callable = litellm.completion,
) -> FactSheet:
    """Produce a sourced fact sheet for the scene described by
    (time, place, description).

    `model` defaults to the pinned model for the "research" stage in
    config/models.yaml (see docs/decisions/0003). `completion_fn` defaults
    to litellm.completion and exists as an injection point for tests -- pass
    a fake to avoid making a real API call.

    Raises ResearchError if the model's response isn't valid JSON or is
    missing required fields, rather than returning a partial/guessed result.
    """
    resolved_model = model or get_stage_model("research")

    prompt = _PROMPT_TEMPLATE.format(time=time, place=place, description=description)
    response = completion_fn(
        model=resolved_model,
        messages=[{"role": "user", "content": prompt}],
    )
    raw_content = response.choices[0].message.content
    claims = _parse_claims(raw_content)
    return FactSheet(time=time, place=place, description=description, claims=claims)
