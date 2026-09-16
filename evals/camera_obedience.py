"""Does any image model follow a camera instruction at all?

A real run specified "high wide shot from a ceiling corner... looking down
its full length" and got an eye-level shot three attempts running, with the
reviewer correctly reporting the miss each time. The instruction was
already positive, already in the CAMERA field, and already first in the
prompt. Repeating it differently is unlikely to help if the model simply
does not act on camera direction.

That is a yes/no question, not a preference one, so this does not ask which
image is nicer. It uses camera specs whose obedience is unmistakable from a
glance -- straight down from above, or from the floor looking up, cannot be
confused with each other -- and asks only whether each image did what it
was told.

Everything except the camera line is held constant, so a failure cannot be
blamed on the subject or the setting.

Usage:
    uv run python evals/camera_obedience.py --dry-run
    uv run python evals/camera_obedience.py --mock
    uv run python evals/camera_obedience.py
"""

from __future__ import annotations

import argparse
import base64
import json
import random
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import litellm

from historical_video_ai.config import load_environment
from historical_video_ai.replicate_client import download_output, run_prediction

EVALS_DIR = Path(__file__).parent

_TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)

# Held constant across every cell. Deliberately simple: a complicated
# subject gives the model something else to fail at.
BODY = """\
SUBJECT: a woman in a dark coat, alone
ACTION: she stands still in the middle of an empty concrete car park at night, \
arms at her sides, looking straight ahead
SETTING: an underground concrete car park at night, square pillars, painted bay \
lines, one fluorescent tube overhead
LIGHTING: one hard fluorescent tube directly overhead
STYLE: Stylized horror comic panel -- heavy inked black shadows, bold confident \
linework, flat colour fills. Explicitly NOT photorealistic."""

# Each is unmistakable at a glance, and mutually exclusive with the others.
CAMERA_SPECS = {
    "top_down": (
        "CAMERA: extreme high angle, camera mounted on the ceiling directly above her, "
        "looking straight down at the top of her head and the floor around her. Her face "
        "is not visible. We see the floor, not the walls."
    ),
    "ground_up": (
        "CAMERA: extreme low angle, camera lying on the floor a metre in front of her "
        "looking steeply upward past her legs to her face and the ceiling above. We see "
        "the ceiling, not the floor."
    ),
    "from_behind": (
        "CAMERA: directly behind her at shoulder height, looking at the back of her head "
        "and shoulders. Her face is NOT visible at all -- we see only her back."
    ),
}


def _generate_gemini(model: str, prompt: str) -> bytes:
    response = litellm.image_generation(model=model, prompt=prompt, size="720x1280")
    data = getattr(response, "data", None) or []
    if not data:
        raise RuntimeError("empty data list (silent refusal)")
    return base64.b64decode(data[0].b64_json)


def _generate_replicate(model: str, prompt: str) -> bytes:
    prediction = run_prediction(
        model.removeprefix("replicate/"),
        {
            "prompt": prompt,
            "aspect_ratio": "9:16",
            "output_format": "png",
            "disable_safety_checker": True,
        },
    )
    output = prediction.get("output")
    if isinstance(output, list):
        output = output[0] if output else None
    if not output:
        raise RuntimeError("prediction returned no image")
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

_QUESTION = {
    "top_down": "Are we looking STRAIGHT DOWN at her from above (floor visible, face not)?",
    "ground_up": "Are we looking STEEPLY UP at her from the floor (ceiling visible)?",
    "from_behind": "Are we behind her, seeing only her BACK (face not visible)?",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print the plan, spend nothing")
    parser.add_argument("--mock", action="store_true", help="run end to end with fake images")
    parser.add_argument("--models", default=",".join(MODELS))
    parser.add_argument("--seed", type=int, help="fix the blind shuffle")
    args = parser.parse_args()

    models = {k: MODELS[k] for k in args.models.split(",")}
    total = len(models) * len(CAMERA_SPECS)
    print(f"{len(models)} model(s) x {len(CAMERA_SPECS)} camera spec(s) = {total} images")
    for name in models:
        print(f"  {name}")
    for spec in CAMERA_SPECS:
        print(f"  spec: {spec}")
    if args.dry_run:
        print("\n--dry-run: nothing called, nothing spent.")
        return

    if not args.mock:
        load_environment()
    run_dir = EVALS_DIR / "results" / f"camera-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
    run_dir.mkdir(parents=True)

    rng = random.Random(args.seed)
    labels = [f"m{n}" for n in range(1, len(models) + 1)]
    rng.shuffle(labels)
    key = dict(zip(labels, models, strict=True))

    manifest = []
    for spec_name, camera in CAMERA_SPECS.items():
        for label, model_name in key.items():
            spec = models[model_name]
            prompt = f"{BODY}\n{camera}"
            try:
                data = (
                    base64.b64decode(_TINY_PNG_B64)
                    if args.mock
                    else spec["generate"](spec["model"], prompt)
                )
            except Exception as exc:  # noqa: BLE001 -- one bad cell shouldn't end the sweep
                print(f"  FAILED {spec_name}/{label}: {exc}")
                manifest.append({"spec": spec_name, "label": label, "outcome": "failed"})
                continue
            out = run_dir / f"{spec_name}__{label}.png"
            out.write_bytes(data)
            print(f"  ok {spec_name}/{label} -> {out.name}")
            manifest.append({"spec": spec_name, "label": label, "file": out.name, "outcome": "ok"})

    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (run_dir / "camera_key.json").write_text(json.dumps(key, indent=2))

    lines = [
        "# Camera obedience — yes or no",
        "",
        "One question per image. Not which is better — only whether it did what",
        "it was told. Everything except the camera line was identical.",
        "",
        "**Do not open camera_key.json until you're done.**",
        "",
    ]
    for spec_name in CAMERA_SPECS:
        lines += [
            f"## {spec_name}",
            "",
            f"> {_QUESTION[spec_name]}",
            "",
            "| image | yes / no | notes |",
            "|---|---|---|",
        ]
        lines += [f"| {spec_name}__{label}.png | | |" for label in sorted(key)]
        lines.append("")
    (run_dir / "SCORING.md").write_text("\n".join(lines))

    print(f"\nImages in {run_dir}")
    print(f"Score in {run_dir / 'SCORING.md'} -- one yes/no per image.")
    print("\nIf every model fails every spec, camera direction is not promptable")
    print("and no amount of rewording the CAMERA field will change that.")


if __name__ == "__main__":
    main()
