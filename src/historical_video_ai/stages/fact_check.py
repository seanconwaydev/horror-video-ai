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

from collections.abc import Callable
from dataclasses import dataclass, field

import litellm

from historical_video_ai.config import get_stage_model
from historical_video_ai.json_utils import parse_json_response
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

    `acknowledged_fiction`, if set, is the explanation of a premise
    conflict a human explicitly chose to keep as intentional fiction
    rather than correct (docs/decisions/0025) -- carried forward so
    previz_review knows not to re-flag that specific, already-acknowledged
    thing as a new problem (docs/decisions/0026), unlike `premise_conflict`
    itself, which is cleared once acknowledged so the downstream stage's own
    hard-refuse check is satisfied.
    """

    fact_sheet: FactSheet
    flags: list[ClaimFlag] = field(default_factory=list)
    premise_conflict: PremiseConflict | None = None
    acknowledged_fiction: str | None = None


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

Claims to check (numbered -- refer to a claim by its number in "flags" below, \
don't copy its text):
{claims_block}

Respond with ONLY a JSON object (no prose, no markdown fences) matching this \
exact shape. Only include a claim in "flags" if you found a real, specific \
problem -- an empty list is a legitimate result if nothing holds up to \
scrutiny as wrong. Set "premise_conflict" to null if the scene's premise is \
historically plausible given the claims above:

{{
  "flags": [
    {{
      "claim_number": <the number of the claim you're flagging, from the numbered list above>,
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
    for i, c in enumerate(claims, start=1):
        date_part = f" (date: {c.date})" if c.date else ""
        lines.append(f"{i}. {c.text}{date_part} [source: {c.source}]")
    return "\n".join(lines) if lines else "(no claims)"


def _parse_flags(raw_flags: list, claims: list[Claim]) -> list[ClaimFlag]:
    """Parse the model's flags, resolving each one's `claim_number` back to
    the real claim's text ourselves -- see docs/decisions/0014-fact-check-
    claims-by-number.md for why this replaced asking the model to copy
    claim_text back verbatim. `ClaimFlag.claim_text` is populated from our
    own claims list, not the model's response, so it's always exactly
    right by construction; nothing downstream (cli.py's _resolve_flags,
    previz, --fixture loading) needed to change."""
    flags: list[ClaimFlag] = []
    for i, raw_flag in enumerate(raw_flags):
        if not isinstance(raw_flag, dict):
            raise FactCheckError(f"Flag {i} is not a JSON object")
        claim_number = raw_flag.get("claim_number")
        # bool is a subclass of int in Python -- isinstance(True, int) is
        # True -- so exclude it explicitly rather than accept "true" as
        # claim number 1.
        if not isinstance(claim_number, int) or isinstance(claim_number, bool):
            raise FactCheckError(
                f"Flag {i} is missing a valid integer 'claim_number' (got {claim_number!r})"
            )
        if not raw_flag.get("concern"):
            raise FactCheckError(f"Flag {i} is missing 'concern'")
        severity = raw_flag.get("severity")
        if severity not in ("contradicted", "uncertain"):
            raise FactCheckError(
                f"Flag {i} has an invalid 'severity' ({severity!r}); "
                "expected 'contradicted' or 'uncertain'"
            )
        if not (1 <= claim_number <= len(claims)):
            raise FactCheckError(
                f"Flag {i}'s 'claim_number' ({claim_number}) is out of range -- "
                f"there are {len(claims)} claim(s), numbered 1 to {len(claims)}"
            )
        flags.append(
            ClaimFlag(
                claim_text=claims[claim_number - 1].text,
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
    whether the scene's own premise conflicts with what research found
    (PremiseConflict, docs/decisions/0008).

    `model` defaults to the pinned "fact_check" model (docs/decisions/0007
    -- a different provider than research, on purpose). `completion_fn` is
    an injection point for tests.

    Raises FactCheckError if the response isn't valid JSON, is missing
    required fields, flags a claim_number outside range, or has a
    malformed premise_conflict.
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
    data = parse_json_response(raw_content, FactCheckError, "Fact-check stage response")
    if not isinstance(data, dict) or "flags" not in data:
        raise FactCheckError("Fact-check stage response is missing 'flags'")

    flags = _parse_flags(data["flags"], fact_sheet.claims)
    premise_conflict = _parse_premise_conflict(data.get("premise_conflict"))
    return FactCheckResult(fact_sheet=fact_sheet, flags=flags, premise_conflict=premise_conflict)
