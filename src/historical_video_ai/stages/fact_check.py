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

from historical_video_ai import _litellm_workarounds  # noqa: F401 -- see CLAUDE.md
from historical_video_ai.config import get_stage_model
from historical_video_ai.json_utils import strip_markdown_json_fence
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
class PremiseConflict:
    """A concern raised about the SCENE ITSELF, not any one claim -- the
    requested scene (time, place, what happens) asks for something that
    verifiably could not have happened, e.g. a technology, structure, or
    event that didn't exist yet at this time and place. Distinct from a
    ClaimFlag: a claim being wrong is a research error; a premise conflict
    means depicting the scene at all requires fabricating something.

    `suggested_alternative` is None when no reasonably close, still-true
    version of the scene exists (a fictional or physically impossible
    premise, not just an anachronistic one) -- the model is instructed not
    to force a strained guess in that case."""

    explanation: str
    suggested_alternative: str | None


@dataclass(frozen=True)
class FactCheckResult:
    """The reviewable artifact stage 3 produces: the original fact sheet,
    unmodified, plus any flags an independent pass raised against it, and
    whether the scene's own premise conflicts with what research found.

    Deliberately does not silently rewrite or drop claims, or silently
    proceed past an unresolved premise conflict -- per docs/pipeline.md's
    review gate for this stage, a human "resolves" flags (accept the claim,
    cut it, or soften the language) and decides how to handle a premise
    conflict (see cli.py's _resolve_premise_conflict and
    docs/decisions/0008-refuse-impossible-premises.md), not the model.
    """

    fact_sheet: FactSheet
    flags: list[ClaimFlag] = field(default_factory=list)
    premise_conflict: PremiseConflict | None = None


_PROMPT_TEMPLATE = """\
You are independently fact-checking a research pass for a short historical \
video scene. Your job is to find reasons these claims could be WRONG -- not \
to summarize them, and not to confirm them just because they sound \
plausible. Actively try to falsify each claim: does it conflict with other \
well-established facts about this time and place? Is the source vague, \
missing, or not credible? Is a date, name, or detail likely wrong or \
anachronistic?

Separately, check the SCENE ITSELF -- not any individual claim -- for \
whether its premise (what happens) could actually have occurred at this \
time and place, based on the claims above. This is different from a claim \
being wrong: it's the requested scene depicting something that verifiably \
didn't exist or couldn't have happened yet, like a technology, structure, \
or event from a later era. If so, this pipeline refuses to depict it as \
requested rather than fabricate it -- your job here is only to flag the \
conflict and, if a genuinely close and still-true version of the scene \
exists, suggest it; a human decides how to proceed.

Scene -- Time: {time} | Place: {place} | What happens: {description}

Claims to check:
{claims_block}

Respond with ONLY a JSON object (no prose, no markdown fences) matching this \
exact shape. Only include a claim in "flags" if you found a real, specific \
problem -- an empty list is a legitimate result if nothing holds up to \
scrutiny as wrong. Set "premise_conflict" to null if the scene's premise is \
historically plausible given the claims above:

{{
  "flags": [
    {{
      "claim_text": "<the exact claim text you're flagging>",
      "concern": "<specifically what's wrong or uncertain, and why>",
      "severity": "<'contradicted' if you have reason to believe it's wrong, 'uncertain'
        if you can't find independent support either way>"
    }}
  ],
  "premise_conflict": {{
    "explanation": "<why the scene's premise could not have happened at this time and place>",
    "suggested_alternative": "<a one-sentence, genuinely close and historically plausible
      version of the scene -- or null if no reasonable close alternative exists. Don't force
      a strained guess just to fill this in.>"
  }}
}}

("premise_conflict" itself should be the JSON value null, not an object with null fields,
when the scene's premise is fine.)
"""


def _format_claims(claims: list[Claim]) -> str:
    lines = []
    for c in claims:
        date_part = f" (date: {c.date})" if c.date else ""
        lines.append(f"- {c.text}{date_part} [source: {c.source}]")
    return "\n".join(lines) if lines else "(no claims)"


def _parse_flags(raw_flags: list, claims: list[Claim]) -> list[ClaimFlag]:
    known_claim_texts = {c.text for c in claims}

    flags: list[ClaimFlag] = []
    for i, raw_flag in enumerate(raw_flags):
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
        claim_text = raw_flag["claim_text"]
        if claim_text not in known_claim_texts:
            # A model that paraphrases or appends extra detail (date, source)
            # instead of copying the claim text verbatim breaks every later
            # attempt to correlate this flag back to its claim -- e.g.
            # previz silently failing to exclude a claim it should have.
            # Fail loud here instead, matching this project's convention of
            # not letting malformed model output degrade silently downstream.
            raise FactCheckError(
                f"Flag {i}'s 'claim_text' doesn't exactly match any claim from "
                f"research (the model may have paraphrased or added detail "
                f"instead of copying it verbatim): {claim_text!r}"
            )
        flags.append(
            ClaimFlag(
                claim_text=claim_text,
                concern=raw_flag["concern"],
                severity=severity,
            )
        )

    return flags


def _parse_premise_conflict(raw: object) -> PremiseConflict | None:
    if raw is None:
        return None
    if not isinstance(raw, dict) or not raw.get("explanation"):
        raise FactCheckError("'premise_conflict' is present but missing 'explanation'")
    suggested_alternative = raw.get("suggested_alternative")
    if suggested_alternative is not None and not isinstance(suggested_alternative, str):
        raise FactCheckError(
            "'premise_conflict.suggested_alternative' must be a string or null, got "
            f"{suggested_alternative!r}"
        )
    return PremiseConflict(
        explanation=raw["explanation"],
        suggested_alternative=suggested_alternative or None,
    )


def run_fact_check_stage(
    fact_sheet: FactSheet,
    *,
    model: str | None = None,
    completion_fn: Callable = litellm.completion,
) -> FactCheckResult:
    """Independently review `fact_sheet`'s claims for accuracy, and check
    whether the scene's own premise conflicts with what research found (see
    PremiseConflict and docs/decisions/0008-refuse-impossible-premises.md).

    `model` defaults to the pinned model for the "fact_check" stage in
    config/models.yaml (see docs/decisions/0003 and 0007 -- pinned to a
    different provider than research on purpose). `completion_fn` defaults
    to litellm.completion and exists as an injection point for tests -- pass
    a fake to avoid making a real API call.

    Raises FactCheckError if the model's response isn't valid JSON, is
    missing required fields, flags a claim_text that doesn't exactly match
    one of fact_sheet's claims, or has a malformed premise_conflict --
    rather than returning a partial/guessed result, or a flag nothing
    downstream can reliably act on.
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
    try:
        data = json.loads(strip_markdown_json_fence(raw_content))
    except json.JSONDecodeError as exc:
        raise FactCheckError(f"Fact-check stage response was not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or "flags" not in data:
        raise FactCheckError("Fact-check stage response is missing 'flags'")

    flags = _parse_flags(data["flags"], fact_sheet.claims)
    premise_conflict = _parse_premise_conflict(data.get("premise_conflict"))
    return FactCheckResult(fact_sheet=fact_sheet, flags=flags, premise_conflict=premise_conflict)
