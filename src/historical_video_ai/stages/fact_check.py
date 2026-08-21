"""Stage 3: Fact-check -- an independent, adversarial pass over the
research stage's fact sheet.

See docs/pipeline.md ("3. Fact-check pass") for the stage's purpose and
review gate.

Deliberately uses a different model/provider than the research stage (see
docs/decisions/0007-research-fact-check-previz-models.md) -- same-provider
verification risks the same training-data gaps and search-ranking biases
producing the same mistake twice, so this isn't an independent check.

Prompted adversarially on purpose: research on confirmation bias in language
models shows they default toward generating evidence that CONFIRMS a claim
rather than evidence that would falsify it, and that explicitly instructing
a model to construct the opposing case measurably reduces this. This stage's
prompt asks the model to find reasons a claim could be wrong, not to
summarize or confirm it.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field

import litellm

from historical_video_ai.config import get_stage_model
from historical_video_ai.stages.research import Claim, FactSheet


class FactCheckError(Exception):
    """Raised when a fact-check stage response is missing or malformed."""


@dataclass(frozen=True)
class ClaimFlag:
    """A concern raised about one claim from the research stage."""

    claim_text: str
    concern: str
    severity: str  # "contradicted" | "uncertain"


@dataclass(frozen=True)
class FactCheckResult:
    """The reviewable artifact stage 3 produces: the original fact sheet,
    unmodified, plus any flags an independent pass raised against it.

    Deliberately does not silently rewrite or drop claims -- per
    docs/pipeline.md's review gate for this stage, a human "resolves" flags
    (accept the claim, cut it, or soften the language), not the model.
    """

    fact_sheet: FactSheet
    flags: list[ClaimFlag] = field(default_factory=list)


_PROMPT_TEMPLATE = """\
You are independently fact-checking a research pass for a short historical \
video scene. Your job is to find reasons these claims could be WRONG -- not \
to summarize them, and not to confirm them just because they sound \
plausible. Actively try to falsify each claim: does it conflict with other \
well-established facts about this time and place? Is the source vague, \
missing, or not credible? Is a date, name, or detail likely wrong or \
anachronistic?

Scene -- Time: {time} | Place: {place} | What happens: {description}

Claims to check:
{claims_block}

Respond with ONLY a JSON object (no prose, no markdown fences) matching this \
exact shape. Only include a claim in "flags" if you found a real, specific \
problem -- an empty list is a legitimate result if nothing holds up to \
scrutiny as wrong:

{{
  "flags": [
    {{
      "claim_text": "<the exact claim text you're flagging>",
      "concern": "<specifically what's wrong or uncertain, and why>",
      "severity": "<'contradicted' if you have reason to believe it's wrong, 'uncertain'
        if you can't find independent support either way>"
    }}
  ]
}}
"""


def _format_claims(claims: list[Claim]) -> str:
    lines = []
    for c in claims:
        date_part = f" (date: {c.date})" if c.date else ""
        lines.append(f"- {c.text}{date_part} [source: {c.source}]")
    return "\n".join(lines) if lines else "(no claims)"


def _parse_flags(raw_content: str) -> list[ClaimFlag]:
    try:
        data = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        raise FactCheckError(f"Fact-check stage response was not valid JSON: {exc}") from exc

    if not isinstance(data, dict) or "flags" not in data:
        raise FactCheckError("Fact-check stage response is missing 'flags'")

    flags: list[ClaimFlag] = []
    for i, raw_flag in enumerate(data["flags"]):
        if not isinstance(raw_flag, dict) or not raw_flag.get("claim_text"):
            raise FactCheckError(f"Flag {i} is missing 'claim_text'")
        if not raw_flag.get("concern"):
            raise FactCheckError(f"Flag {i} is missing 'concern'")
        severity = raw_flag.get("severity")
        if severity not in ("contradicted", "uncertain"):
            raise FactCheckError(
                f"Flag {i} has an invalid 'severity' ({severity!r}); "
                "expected 'contradicted' or 'uncertain'"
            )
        flags.append(
            ClaimFlag(
                claim_text=raw_flag["claim_text"],
                concern=raw_flag["concern"],
                severity=severity,
            )
        )

    return flags


def run_fact_check_stage(
    fact_sheet: FactSheet,
    *,
    model: str | None = None,
    completion_fn: Callable = litellm.completion,
) -> FactCheckResult:
    """Independently review `fact_sheet`'s claims for accuracy.

    `model` defaults to the pinned model for the "fact_check" stage in
    config/models.yaml (see docs/decisions/0003 and 0007 -- pinned to a
    different provider than research on purpose). `completion_fn` defaults
    to litellm.completion and exists as an injection point for tests -- pass
    a fake to avoid making a real API call.

    Raises FactCheckError if the model's response isn't valid JSON or is
    missing required fields, rather than returning a partial/guessed result.
    """
    resolved_model = model or get_stage_model("fact_check")

    prompt = _PROMPT_TEMPLATE.format(
        time=fact_sheet.time,
        place=fact_sheet.place,
        description=fact_sheet.description,
        claims_block=_format_claims(fact_sheet.claims),
    )
    response = completion_fn(
        model=resolved_model,
        messages=[{"role": "user", "content": prompt}],
    )
    raw_content = response.choices[0].message.content
    flags = _parse_flags(raw_content)
    return FactCheckResult(fact_sheet=fact_sheet, flags=flags)
