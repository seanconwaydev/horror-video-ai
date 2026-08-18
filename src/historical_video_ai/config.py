"""Per-stage model configuration.

Each pipeline stage's model choice lives in config/models.yaml, not in code,
per docs/decisions/0003-model-configuration-via-litellm.md. Versions are
pinned explicitly in that file and are only ever changed by a human editing
it directly -- nothing in this module substitutes a different model
automatically.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

# src/historical_video_ai/config.py -> src/historical_video_ai -> src -> repo root
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "models.yaml"


class ConfigError(Exception):
    """Raised when stage configuration is missing or invalid."""


@dataclass(frozen=True)
class StageConfig:
    """Configuration for a single pipeline stage.

    Just a pinned model string for now. Extend this (e.g. temperature,
    max_tokens) as individual stages need it -- each stage's block in
    models.yaml is independent, so adding a field to one stage doesn't
    affect the others.
    """

    model: str


def load_stage_configs(path: Path = DEFAULT_CONFIG_PATH) -> dict[str, StageConfig]:
    """Load all stage configs from the given YAML file.

    Raises ConfigError if the file is missing, empty, or a stage entry
    doesn't specify a model.
    """
    if not path.exists():
        raise ConfigError(f"Model config file not found: {path}")

    with path.open() as f:
        raw = yaml.safe_load(f)

    if not raw:
        raise ConfigError(f"Model config file is empty: {path}")

    configs: dict[str, StageConfig] = {}
    for stage_name, settings in raw.items():
        if not settings or "model" not in settings:
            raise ConfigError(
                f"Stage '{stage_name}' is missing a 'model' entry in {path}"
            )
        configs[stage_name] = StageConfig(model=settings["model"])

    return configs


def get_stage_model(stage_name: str, path: Path = DEFAULT_CONFIG_PATH) -> str:
    """Return the pinned model string for a given stage.

    Raises ConfigError if the stage isn't configured.
    """
    configs = load_stage_configs(path)
    if stage_name not in configs:
        raise ConfigError(
            f"No model configured for stage '{stage_name}'. "
            f"Configured stages: {sorted(configs)}"
        )
    return configs[stage_name].model


def load_environment() -> None:
    """Load API keys and other secrets from .env into the process environment.

    Call this explicitly at the start of a run (e.g. in a stage's entry
    point) -- not done automatically on import, so importing this module
    never has hidden side effects.
    """
    load_dotenv()
