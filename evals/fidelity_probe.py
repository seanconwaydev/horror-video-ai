"""The model column of a prompt-fidelity probe: one vision call per
image, one row per claim.

Drives docs/playbook/prompt-fidelity-probe-2.md, which decides whether
automated fidelity checking gets built at all
(docs/playbook/prompt-fidelity-checking-scope.md). The claims are parsed
out of that sheet rather than restated here, so the two columns cannot
drift apart.

Answers are written to the gitignored evals/results/ on purpose: the
owner answers the same sheet independently, and the probe is only
meaningful if neither column is visible to the other reader first.

--dry-run parses the sheet and answers from a canned response, calling
nothing. This is not the fidelity stage the scope doc describes -- it is
the measurement that decides whether to write one.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

SHEET = Path("docs/playbook/prompt-fidelity-probe-2.md")
MODEL = "anthropic/claude-sonnet-5"

# From the sheet's image table. Sheet id -> image, relative to outputs/.
IMAGES = {
    "B2": "run_20260922-002146_a-night-porter-loading-a-cart-hears-a/beat_2/beat2_attempt_1_rejected.png",
    "B4": "run_20260922-002146_a-night-porter-loading-a-cart-hears-a/beat_4/beat4_attempt_1_rejected.png",
    "B5": "run_20260922-002146_a-night-porter-loading-a-cart-hears-a/beat_5/beat5_attempt_1_rejected.png",
    "L1": "run_20260921-220038_a-lookout-scanning-the-treeline-sees/beat_1/candidate_1_1.png",
    "L2": "run_20260921-220038_a-lookout-scanning-the-treeline-sees/beat_2/candidate_1_2.png",
    "L3": "run_20260921-220038_a-lookout-scanning-the-treeline-sees/beat_3/candidate_2_2.png",
    "L4": "run_20260921-220038_a-lookout-scanning-the-treeline-sees/beat_4/candidate_2_1.png",
}

INSTRUCTIONS = """\
This image was generated from a written plan. Below are claims taken from \
that plan, before anyone looked at the image. For each one, answer whether \
the image honours it.

Answer exactly one of:
  y  -- yes, the image honours the claim
  n  -- no, it does not
  ?  -- you cannot tell at a glance

"?" is a real answer, not a last resort: this image ships as a phone-sized \
vertical short, so anything you have to study is one a viewer cannot read. \
Answer each claim on its own; do not let one claim's answer soften another's. \
Do not give the image the benefit of the doubt.

Claims:
{claims}

Reply with JSON only: an object mapping each claim id to "y", "n" or "?". \
No other text."""


def parse_claims(sheet: Path) -> dict[str, list[tuple[str, str]]]:
    """sheet id -> [(claim id, claim text)], in the order written."""
    claims: dict[str, list[tuple[str, str]]] = {}
    for line in sheet.read_text().splitlines():
        m = re.match(r"\|\s*([BL]\d)-(\d+)\s*(?:`†`)?\s*\|\s*([^|]+?)\s*\|", line)
        if m:
            claims.setdefault(m.group(1), []).append(
                (f"{m.group(1)}-{m.group(2)}", m.group(3))
            )
    return claims


def ask(
    image: Path,
    items: list[tuple[str, str]],
    completion_fn: Callable[..., Any],
) -> dict[str, str]:
    prompt = INSTRUCTIONS.format(
        claims="\n".join(f"{cid}: {text}" for cid, text in items)
    )
    b64 = base64.b64encode(image.read_bytes()).decode()
    response = completion_fn(
        model=MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    },
                ],
            }
        ],
    )
    text = response.choices[0].message.content.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    return json.loads(text)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--out", default="evals/results/probe2_model_answers.json")
    args = parser.parse_args()

    claims = parse_claims(SHEET)
    missing = [s for s in IMAGES if s not in claims]
    if missing:
        print(f"no claims parsed for {missing}", file=sys.stderr)
        return 1
    total = sum(len(v) for v in claims.values())
    print(f"{total} claims across {len(claims)} images; model {MODEL}")

    if args.dry_run:
        def completion_fn(**kwargs: Any) -> Any:
            text = json.dumps({cid: "y" for cid, _ in claims["B2"]})
            print(
                f"  [dry-run] would send "
                f"{len(kwargs['messages'][0]['content'])} parts"
            )
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=text))]
            )
    else:
        from litellm import completion as completion_fn

        from horror_video_ai.config import load_environment

        load_environment()

    answers: dict[str, str] = {}
    for sheet_id, rel in IMAGES.items():
        image = Path("outputs") / rel
        items = claims[sheet_id]
        if args.dry_run and sheet_id != "B2":
            continue
        print(f"--- {sheet_id}: {len(items)} claims, {image.name}")
        answers.update(ask(image, items, completion_fn))

    if args.dry_run:
        print(f"parsed {len(answers)} answers from the canned response")
        print("--dry-run: nothing called, nothing spent.")
        return 0

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"model": MODEL, "answers": answers}, indent=1))
    print(f"\n{len(answers)}/{total} answered -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
