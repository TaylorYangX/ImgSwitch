import json
import stat

import pytest
from pydantic import ValidationError

from imgswitch.config import AppConfig, is_masked, load_config, mask_secret, parse_size, save_config


def test_missing_file_is_created_with_defaults(tmp_path):
    path = tmp_path / "config.json"
    cfg = load_config(path)
    assert path.exists()
    assert cfg.active_provider == "openai"
    assert json.loads(path.read_text())["providers"]["a1111"]["base_url"] == "http://127.0.0.1:7860"


def test_round_trip_and_permissions(tmp_path):
    path = tmp_path / "config.json"
    cfg = AppConfig()
    cfg.active_provider = "comfyui"
    cfg.providers.openai.api_key = "sk-secret-1234"
    save_config(cfg, path)

    loaded = load_config(path, apply_env=False)
    assert loaded == cfg
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert [p.name for p in tmp_path.iterdir()] == ["config.json"]  # no temp files left behind


def test_env_key_overrides_without_being_persisted(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    save_config(AppConfig(), path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    assert load_config(path).providers.openai.api_key == "sk-from-env"
    assert load_config(path, apply_env=False).providers.openai.api_key == ""
    assert "sk-from-env" not in path.read_text()


@pytest.mark.parametrize("size,expected", [("1024x1024", (1024, 1024)), ("1344X768", (1344, 768)), (" 512 x 768", (512, 768))])
def test_parse_size(size, expected):
    assert parse_size(size) == expected


@pytest.mark.parametrize("size", ["1024", "big", "10x10", "1024x99999"])
def test_parse_size_rejects(size):
    with pytest.raises(ValueError):
        parse_size(size)


def test_invalid_values_rejected():
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"active_provider": "midjourney"})
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"providers": {"a1111": {"default_size": "huge"}}})


def test_mask_secret():
    assert mask_secret("") == ""
    assert mask_secret("sk-abcdefgh1234") == "••••1234"
    assert mask_secret("short") == "••••"
    assert is_masked(mask_secret("sk-abcdefgh1234"))
    assert not is_masked("sk-abcdefgh1234")


def test_enabled_providers():
    cfg = AppConfig()
    assert cfg.enabled_providers() == ["openai", "a1111", "comfyui", "unsloth"]
    cfg.providers.a1111.enabled = False
    cfg.providers.comfyui.enabled = False
    assert cfg.enabled_providers() == ["openai", "unsloth"]


def test_active_backend_cannot_be_disabled():
    with pytest.raises(ValidationError, match="active backend 'unsloth' can't be disabled"):
        AppConfig.model_validate({"active_provider": "unsloth", "providers": {"unsloth": {"enabled": False}}})
