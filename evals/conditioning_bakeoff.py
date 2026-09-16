"""Can the pipeline have playful cameras AND cross-beat consistency?

Reference-image conditioning was introduced by docs/decisions/0024, when
this project was about historical accuracy and location fidelity mattered.
Its stated finding still stands: "text description alone, even good text
description, already failed" at holding a location steady across beats. So
references are doing real work and cannot simply be deleted.

But after the pivot to horror they became the main thing suppressing
composition. Measured: this project's own style A/B produced obeyed camera
angles using plain text-to-image, while the reference-conditioned pipeline
produced eye-level shots three attempts running against an explicit
high-angle instruction, and the reference-anchor experiment's no-reference
arm won camera picks where the shipped arm won none.

The underlying problem is that ONE mechanism serves THREE needs -- art
style, location structure, and character identity -- and the strongest of
them, identity, sets the conditioning strength for all three. Composition
is crushed by a dial turned up for the face.

`gemini/gemini-2.5-flash-image` offers no way to separate them: via
litellm, conditioning is all-or-nothing. `black-forest-labs/flux-dev`
offers two controls that might --

  prompt_strength   how far the output may depart from the reference
                    (1.0 = "full destruction of information in image")
  seed              reproducible generation, so consistency can come from
                    a fixed seed with NO conditioning image at all

Three beats in one location with deliberately different cameras, through
four conditions. Scored on three axes separately, because they can come
apart: did the camera obey, is it the same room, is it the same art style.

Usage:
    uv run python evals/conditioning_bakeoff.py --dry-run
    uv run python evals/conditioning_bakeoff.py --mock
    uv run python evals/conditioning_bakeoff.py --reference <location ref .png>
"""

from __future__ import annotations

import argparse
import base64
import json
import random
import shutil
from datetime import UTC, datetime
from pathlib import Path

import litellm

from historical_video_ai.config import load_environment
from historical_video_ai.replicate_client import download_output, file_to_data_uri, run_prediction

EVALS_DIR = Path(__file__).parent
_SEED = 20260916  # fixed, so the seed-only condition is actually testing a seed

_TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)

STYLE = (
    "Stylized horror comic panel -- heavy inked black shadows, bold confident linework, "
    "flat colour fills, high contrast between lit and unlit areas. Explicitly NOT "
    "photorealistic, NOT 3D-rendered."
)

# One location, described identically every time. Cross-beat consistency of
# THIS is what the references exist to protect.
LOCATION = (
    "SETTING: a narrow upstairs hallway in an old house. Pale green wallpaper with a faded "
    "vertical stripe, bare dark floorboards, a white-painted door at the far end standing "
    "ajar, a small round mirror on the left wall, a threadbare red runner rug."
)

# Deliberately different cameras, in the vocabulary ADR 0044 settled on.
BEATS = {
    "b1_wide_high_behind": (
        "ACTION: a woman in a grey sweatshirt walks away down the hallway toward the far door, "
        "shoulders tense\n"
        "CAMERA: wide shot, high above looking down, subject seen from behind"
    ),
    "b2_close_low_profile": (
        "ACTION: the same woman stops and presses one hand flat against the wallpaper, jaw tight\n"
        "CAMERA: close-up, low angle near the floor looking up, subject in profile"
    ),
    "b3_medium_eye_facing": (
        "ACTION: the same woman turns back toward us, eyes wide, mouth open in fright\n"
        "CAMERA: medium shot, eye level, subject facing camera"
    ),
}

CONDITIONS = {
    "gemini_ref": {"model": "gemini/gemini-2.5-flash-image", "use_ref": True},
    "flux_ref_0.8": {"model": "replicate/black-forest-labs/flux-dev", "use_ref": True, "strength": 0.8},
    "flux_ref_0.9": {"model": "replicate/black-forest-labs/flux-dev", "use_ref": True, "strength": 0.9},
    "flux_seed_only": {"model": "replicate/black-forest-labs/flux-dev", "use_ref": False},
}


def _generate(cond: dict, prompt: str, reference: Path | None) -> bytes:
    if cond["model"].startswith("gemini/"):
        if reference is not None:
            response = litellm.image_edit(
                model=cond["model"], prompt=prompt, image=[reference.read_bytes()]
            )
        else:
            response = litellm.image_generation(
                model=cond["model"], prompt=prompt, size="720x1280"
            )
        data = getattr(response, "data", None) or []
        if not data:
            raise RuntimeError("empty data list (silent refusal)")
        return base64.b64decode(data[0].b64_json)

    payload: dict = {
        "prompt": prompt,
        "aspect_ratio": "9:16",
        "output_format": "png",
        "disable_safety_checker": True,
        "seed": _SEED,
    }
    if reference is not None:
        payload["image"] = file_to_data_uri(reference)
        payload["prompt_strength"] = cond["strength"]
    prediction = run_prediction(cond["model"].removeprefix("replicate/"), payload)
    output = prediction.get("output")
    if isinstance(output, list):
        output = output[0] if output else None
    if not output:
        raise RuntimeError("prediction returned no image")
    return download_output(output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print the plan, spend nothing")
    parser.add_argument("--mock", action="store_true", help="run end to end with fake images")
    parser.add_argument(
        "--reference",
        type=Path,
        help="a location reference to condition on. Omitted, one is generated from the same "
        "LOCATION text below -- which is what the pipeline actually does, and avoids "
        "conditioning a hallway prompt on an unrelated room.",
    )
    parser.add_argument("--conditions", default=",".join(CONDITIONS))
    parser.add_argument("--seed", type=int, help="fix the blind shuffle")
    args = parser.parse_args()

    conditions = {k: CONDITIONS[k] for k in args.conditions.split(",")}
    n_ref = 1 if any(c["use_ref"] for c in conditions.values()) and not args.reference else 0
    total = len(conditions) * len(BEATS) + n_ref
    print(
        f"{len(conditions)} condition(s) x {len(BEATS)} beat(s)"
        + (" + 1 generated location reference" if n_ref else "")
        + f" = {total} images"
    )
    for name, cond in conditions.items():
        ref = "reference" if cond["use_ref"] else f"no reference, seed {_SEED}"
        strength = f" @ prompt_strength {cond['strength']}" if "strength" in cond else ""
        print(f"  {name:<16} {cond['model']}  ({ref}{strength})")
    if args.dry_run:
        print("\n--dry-run: nothing called, nothing spent.")
        return


    if not args.mock:
        load_environment()
    run_dir = EVALS_DIR / "results" / f"conditioning-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
    run_dir.mkdir(parents=True)

    # Generated from the same LOCATION text rather than required as an
    # argument. The beats describe one specific hallway, so conditioning on
    # some other room would measure confusion rather than consistency -- and
    # generating it here is what the pipeline itself does.
    reference_path = args.reference
    if any(c["use_ref"] for c in conditions.values()) and reference_path is None:
        reference_path = run_dir / "_the_reference.png"
        ref_prompt = (
            f"{LOCATION}\n"
            "CAMERA: wide establishing shot, eye level, no person in frame -- this is a "
            "location reference, not a character shot.\n"
            f"STYLE: {STYLE}"
        )
        data = (
            base64.b64decode(_TINY_PNG_B64)
            if args.mock
            else _generate(
                {"model": "gemini/gemini-2.5-flash-image", "use_ref": False}, ref_prompt, None
            )
        )
        reference_path.write_bytes(data)
        print(f"generated location reference -> {reference_path.name}")

    rng = random.Random(args.seed)
    labels = [chr(ord("P") + n) for n in range(len(conditions))]
    rng.shuffle(labels)
    key = dict(zip(labels, conditions, strict=True))

    manifest = []
    for beat_name, beat in BEATS.items():
        for label, cond_name in key.items():
            cond = conditions[cond_name]
            prompt = f"{beat}\n{LOCATION}\nSTYLE: {STYLE}"
            reference = reference_path if cond["use_ref"] else None
            try:
                data = (
                    base64.b64decode(_TINY_PNG_B64)
                    if args.mock
                    else _generate(cond, prompt, reference)
                )
            except Exception as exc:  # noqa: BLE001 -- one bad cell shouldn't end the sweep
                print(f"  FAILED {beat_name}/{label}: {exc}")
                manifest.append({"beat": beat_name, "label": label, "outcome": "failed"})
                continue
            (run_dir / label).mkdir(exist_ok=True)
            out = run_dir / label / f"{beat_name}.png"
            out.write_bytes(data)
            print(f"  ok {beat_name}/{label}")
            manifest.append({"beat": beat_name, "label": label, "outcome": "ok"})

    if args.reference and args.reference.exists():
        shutil.copy2(args.reference, run_dir / "_the_reference.png")

    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (run_dir / "conditioning_key.json").write_text(json.dumps(key, indent=2))

    lines = [
        "# Conditioning bake-off — cameras vs consistency",
        "",
        "Each lettered folder is one condition: the same three beats, same location text,",
        "same style text. Only how the model is conditioned differs.",
        "",
        "**Do not open conditioning_key.json until you're done.**",
        "",
        "## Part 1 — did the camera obey? (per image, yes/no)",
        "",
        "The three beats asked for, in order: *wide / high above / from behind*,",
        "then *close-up / low angle / profile*, then *medium / eye level / facing camera*.",
        "",
        "| condition | b1 wide-high-behind | b2 close-low-profile | b3 medium-eye-facing |",
        "|---|---|---|---|",
    ]
    lines += [f"| {label} | | | |" for label in sorted(key)]
    lines += [
        "",
        "## Part 2 — is it the same room across its three beats?",
        "",
        "Compare `_the_reference.png` too, if there is one.",
        "",
        "| condition | same room? | notes |",
        "|---|---|---|",
    ]
    lines += [f"| {label} | | |" for label in sorted(key)]
    lines += [
        "",
        "## Part 3 — is the art style consistent across its three beats?",
        "",
        "| condition | same style? | notes |",
        "|---|---|---|",
    ]
    lines += [f"| {label} | | |" for label in sorted(key)]
    lines += [
        "",
        "Scored separately on purpose: a condition can hold the room and lose the camera,",
        "or hold the style and lose the room. Which axes come apart is the finding.",
        "",
    ]
    (run_dir / "SCORING.md").write_text("\n".join(lines))

    print(f"\nImages in {run_dir}")
    print(f"Score in {run_dir / 'SCORING.md'}")


if __name__ == "__main__":
    main()
