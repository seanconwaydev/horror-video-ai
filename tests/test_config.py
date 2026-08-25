from pathlib import Path

import pytest
import yaml

from historical_video_ai.config import (
    REPO_ROOT,
    ConfigError,
    get_stage_model,
    load_stage_configs,
)


def write_yaml(tmp_path: Path, content: dict) -> Path:
    path = tmp_path / "models.yaml"
    path.write_text(yaml.dump(content))
    return path


def test_load_stage_configs_reads_model_per_stage(tmp_path):
    path = write_yaml(
        tmp_path,
        {
            "research": {"model": "anthropic/claude-sonnet-5"},
            "fact_check": {"model": "anthropic/claude-sonnet-5"},
        },
    )

    configs = load_stage_configs(path)

    assert configs["research"].model == "anthropic/claude-sonnet-5"
    assert configs["fact_check"].model == "anthropic/claude-sonnet-5"


def test_get_stage_model_returns_pinned_model_string(tmp_path):
    path = write_yaml(tmp_path, {"research": {"model": "deepseek/deepseek-chat"}})

    assert get_stage_model("research", path) == "deepseek/deepseek-chat"


def test_get_stage_model_raises_for_unknown_stage(tmp_path):
    path = write_yaml(tmp_path, {"research": {"model": "anthropic/claude-sonnet-5"}})

    with pytest.raises(ConfigError, match="No model configured for stage 'narrative'"):
        get_stage_model("narrative", path)


def test_load_stage_configs_raises_for_missing_file(tmp_path):
    missing_path = tmp_path / "does-not-exist.yaml"

    with pytest.raises(ConfigError, match="not found"):
        load_stage_configs(missing_path)


def test_load_stage_configs_raises_for_empty_file(tmp_path):
    path = tmp_path / "models.yaml"
    path.write_text("")

    with pytest.raises(ConfigError, match="empty"):
        load_stage_configs(path)


def test_load_stage_configs_raises_when_stage_missing_model(tmp_path):
    path = write_yaml(tmp_path, {"research": {"not_model": "oops"}})

    with pytest.raises(ConfigError, match="research.*missing a 'model'"):
        load_stage_configs(path)


def test_real_project_config_is_valid():
    """The actual committed config/models.yaml should always load cleanly
    and define every stage that has code depending on it so far."""
    configs = load_stage_configs(REPO_ROOT / "config" / "models.yaml")

    expected_stages = {
        "research",
        "fact_check",
        "previz",
        "previz_review",
        "narrative",
        "narrative_review",
        "shot_list",
        "video_prompts",
    }
    assert expected_stages.issubset(configs.keys())
    for stage_name, config in configs.items():
        assert "/" in config.model, (
            f"Stage '{stage_name}' model '{config.model}' should be in "
            "'<provider>/<model-name>' format"
        )
