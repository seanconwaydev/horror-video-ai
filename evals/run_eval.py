"""Generate images for every scene under one or more prompt-construction
variants (and/or models), then hand back a blind scoring sheet.

Two things are measured. Refusals are counted automatically, because an
empty-but-successful response is exactly how a silent content block
presents itself and counting it as a crash would hide the finding.
Quality is judged by a human -- but blind, and against named criteria,
because "which do you prefer" on a single image tells you nothing you can
act on and is biased toward whichever one you know is new.

When a run produces exactly two images per scene, they are written as
`<scene>__A` and `<scene>__B` with the A/B assignment randomised per
scene and recorded in key.json. Score first, reveal after.

Usage:
    uv run python evals/run_eval.py --dry-run
    uv run python evals/run_eval.py --variants current,single_source
    uv run python evals/run_eval.py --models gemini-2.5-flash-image,flux-dev --variants single_source
    uv run python evals/run_eval.py --reveal evals/results/20260915-224500
"""

from __future__ import annotations

import argparse
import base64
import json
import random
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import litellm
import yaml

from historical_video_ai.config import load_environment
from historical_video_ai.replicate_client import download_output, run_prediction
from historical_video_ai.stages.moderation import run_moderation_policy_check

EVALS_DIR = Path(__file__).parent
sys.path.insert(0, str(EVALS_DIR))
from selection import require_known, select
from variants import VARIANTS

ASPECT_RATIO = "9:16"  # this project is Shorts-only (docs/decisions/0002)

CRITERIA = [
    ("composition", "Does the framing do anything, or is it centered and safe?"),
    ("style", "One confident look, or hedged mush?"),
    ("fidelity", "Does the subject match the description?"),
    ("mood", "Does it actually read as dread?"),
    ("motion", "Does this frame imply a next moment, or is it a frozen tableau?"),
]


class _Refused(Exception):
    """A successful call that produced no image -- how a silent content
    block presents itself, deliberately not the same thing as an error."""


def _generate_gemini(model: str, prompt: str) -> bytes:
    response = litellm.image_generation(model=model, prompt=prompt, size="720x1280")
    data = getattr(response, "data", None) or []
    if not data:
        raise _Refused("empty data list (no image, no error detail)")
    b64 = getattr(data[0], "b64_json", None)
    if not b64:
        raise _Refused("response item carried no image payload")
    return base64.b64decode(b64)


def _generate_replicate(model: str, prompt: str) -> bytes:
    prediction = run_prediction(
        model.removeprefix("replicate/"),
        {
            "prompt": prompt,
            "aspect_ratio": ASPECT_RATIO,
            "output_format": "png",
            "disable_safety_checker": True,
        },
    )
    output = prediction.get("output")
    if isinstance(output, list):
        output = output[0] if output else None
    if not output:
        raise _Refused(f"prediction {prediction.get('id')} returned no image")
    return download_output(output)


MODELS: dict[str, dict[str, Any]] = {
    "gemini-2.5-flash-image": {
        "model": "gemini/gemini-2.5-flash-image",
        "generate": _generate_gemini,
    },
    "flux-dev": {"model": "replicate/black-forest-labs/flux-dev", "generate": _generate_replicate},
    "flux-schnell": {
        "model": "replicate/black-forest-labs/flux-schnell",
        "generate": _generate_replicate,
    },
}


def _write_scoring_sheet(path: Path, scenes: list[dict], blind: bool) -> None:
    lines = [
        "# Scoring sheet",
        "",
        "Open each scene's two images side by side. For every criterion put **A** or **B**.",
        "Forced choice, not a 1-5 score -- your internal scale drifts across a session,",
        "but a direct comparison doesn't. Add a few words of *why* only when you have them;",
        "that fragment is what becomes the next fix.",
        "",
        "Judge every scene before concluding anything. One lucky image is not a result.",
        "",
    ]
    if blind:
        lines += [
            "**Do not open key.json until you're done.** Knowing which is new is enough",
            "to bias the judgement.",
            "",
            "Reveal with: `uv run python evals/run_eval.py --reveal <this folder>`",
            "",
        ]
    for scene in scenes:
        lines += [f"## {scene['id']}", f"_{scene['probes']}_", "", "| criterion | A or B | why |", "|---|---|---|"]
        lines += [f"| {name} — {question} | | |" for name, question in CRITERIA]
        lines.append("")
    path.write_text("\n".join(lines))


def _reveal(run_dir: Path) -> None:
    key = json.loads((run_dir / "key.json").read_text())
    print(f"Key for {run_dir}:\n")
    for scene_id, mapping in key.items():
        print(f"  {scene_id}")
        for slot, label in mapping.items():
            print(f"    {slot} = {label}")
    print("\nNow re-read SCORING.md: count how often each label won, per criterion.")
    print("A variant that wins composition but loses fidelity is a more useful")
    print("result than one that 'wins overall' -- that's what tells you what to change.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print the plan, call nothing, spend nothing")
    parser.add_argument("--scenes", help="comma-separated scene ids (default: all)")
    parser.add_argument("--models", default="gemini-2.5-flash-image", help="comma-separated model keys")
    parser.add_argument("--variants", default="current", help="comma-separated variant names")
    parser.add_argument("--reveal", help="print the A/B key for a finished run directory")
    parser.add_argument("--seed", type=int, help="fix the A/B shuffle, for reproducibility")
    parser.add_argument(
        "--moderate",
        action="store_true",
        help="run each generated image and its prompt through the free omni-moderation "
        "classifier and record the flagged categories. Not YouTube's system -- a real "
        "major-vendor classifier, used here as a measurable proxy for whether automated "
        "moderation reacts differently to photorealistic versus stylized versions of the "
        "same scene.",
    )
    args = parser.parse_args()

    if args.reveal:
        _reveal(Path(args.reveal))
        return

    scenes = yaml.safe_load((EVALS_DIR / "scenes.yaml").read_text())["scenes"]
    if args.scenes:
        wanted = require_known(
            parser, (s["id"] for s in scenes), args.scenes, flag="scenes"
        )
        scenes = [s for s in scenes if s["id"] in wanted]

    models = select(parser, MODELS, args.models, flag="models")
    variants = select(parser, VARIANTS, args.variants, flag="variants")
    cells = [(m, v) for m in models for v in variants]

    print(f"{len(scenes)} scene(s) x {len(cells)} cell(s) = {len(scenes) * len(cells)} images")
    for model_key, variant_key in cells:
        print(f"  {model_key} / {variant_key}")
    blind = len(cells) == 2
    print(f"  blind A/B: {'yes' if blind else 'no (needs exactly 2 cells)'}")

    if args.dry_run:
        print("\n--dry-run: nothing called, nothing spent.")
        return

    load_environment()
    rng = random.Random(args.seed)
    run_dir = EVALS_DIR / "results" / datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True)
    manifest: list[dict] = []
    key: dict[str, dict[str, str]] = {}

    for scene in scenes:
        slots = ["A", "B"] if blind else [f"{m}__{v}" for m, v in cells]
        if blind:
            rng.shuffle(slots)
        for (model_key, variant_key), slot in zip(cells, slots, strict=True):
            label = f"{model_key}/{variant_key}"
            key.setdefault(scene["id"], {})[slot] = label
            prompt = variants[variant_key](scene["body"], scene["style"])
            try:
                image_bytes = models[model_key]["generate"](models[model_key]["model"], prompt)
            except _Refused as exc:
                print(f"  REFUSED  {scene['id']} {label}: {exc}")
                manifest.append({"scene": scene["id"], "cell": label, "outcome": "refused", "detail": str(exc)})
                continue
            except Exception as exc:  # noqa: BLE001 -- one bad cell shouldn't end the sweep
                print(f"  ERROR    {scene['id']} {label}: {type(exc).__name__}: {exc}")
                manifest.append({"scene": scene["id"], "cell": label, "outcome": "error", "detail": str(exc)})
                continue
            out = run_dir / f"{scene['id']}__{slot}.png"
            out.write_bytes(image_bytes)
            row = {"scene": scene["id"], "cell": label, "slot": slot, "outcome": "ok", "file": out.name}
            if args.moderate:
                verdict = run_moderation_policy_check(prompt, out)
                row["moderation_flagged"] = verdict.flagged
                row["moderation_categories"] = verdict.flagged_categories
                flags = ", ".join(verdict.flagged_categories) or "none"
                print(f"  ok       {scene['id']} -> {out.name}  [moderation: {flags}]")
            else:
                print(f"  ok       {scene['id']} -> {out.name}")
            manifest.append(row)

    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (run_dir / "key.json").write_text(json.dumps(key, indent=2))
    _write_scoring_sheet(run_dir / "SCORING.md", scenes, blind)

    print(f"\nResults in {run_dir}")
    print("Refusals by cell:")
    for model_key, variant_key in cells:
        label = f"{model_key}/{variant_key}"
        rows = [m for m in manifest if m["cell"] == label]
        refused = sum(1 for m in rows if m["outcome"] == "refused")
        print(f"  {label:<40} {refused}/{len(rows)} refused")
    if args.moderate:
        print("\nModeration flags (proxy for automated-classifier sensitivity to realism):")
        for row in manifest:
            if "moderation_flagged" in row:
                flags = ", ".join(row["moderation_categories"]) or "none"
                print(f"  {row['scene']:<30} {flags}")

    print(f"\nScore blind in {run_dir / 'SCORING.md'}, then reveal with:")
    print(f"  uv run python evals/run_eval.py --reveal {run_dir}")


if __name__ == "__main__":
    main()
