"""Configuration model and persistence.

The config file is the only channel between the dashboard (which writes it) and the
stdio MCP server (which reads it on every tool call), so writes are atomic.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from imgswitch import PROJECT_ROOT

PROVIDER_NAMES = ("openai", "a1111", "comfyui", "unsloth")
ProviderName = Literal["openai", "a1111", "comfyui", "unsloth"]

MASK_PREFIX = "••••"


def parse_size(size: str) -> tuple[int, int]:
    """Parse "WIDTHxHEIGHT" into a (width, height) tuple."""
    try:
        w, h = size.lower().replace(" ", "").split("x")
        width, height = int(w), int(h)
    except ValueError:
        raise ValueError(f"Invalid size {size!r}; expected WIDTHxHEIGHT, e.g. 1024x1024") from None
    if not (64 <= width <= 4096 and 64 <= height <= 4096):
        raise ValueError(f"Size {size!r} out of range; each side must be between 64 and 4096")
    return width, height


class _SizedProvider(BaseModel):
    # Off hides the backend from Claude: list_backends skips it and generate_image refuses it.
    enabled: bool = True
    default_size: str = "1024x1024"
    timeout: float = Field(default=300, gt=0)

    @field_validator("default_size")
    @classmethod
    def _check_size(cls, v: str) -> str:
        parse_size(v)
        return v


class OpenAIConfig(_SizedProvider):
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "dall-e-3"
    # "omit" leaves the field out entirely: gpt-image-1 and some proxies reject it.
    response_format: Literal["b64_json", "url", "omit"] = "b64_json"
    timeout: float = Field(default=120, gt=0)


class A1111Config(_SizedProvider):
    base_url: str = "http://127.0.0.1:7860"
    steps: int = Field(default=25, ge=1, le=150)
    cfg_scale: float = Field(default=7.0, ge=1, le=30)
    sampler_name: str = "DPM++ 2M"


class ComfyUIConfig(_SizedProvider):
    base_url: str = "http://127.0.0.1:8188"
    workflow_path: str = "workflows/comfyui_txt2img.json"
    # Used when input images are passed; needs the {{image}} placeholder (and usually {{denoise}}).
    edit_workflow_path: str = "workflows/comfyui_img2img.json"
    checkpoint: str = ""
    steps: int = Field(default=25, ge=1, le=150)
    cfg_scale: float = Field(default=7.0, ge=1, le=30)


class UnslothConfig(_SizedProvider):
    base_url: str = "http://127.0.0.1:8888"
    api_key: str = ""
    # None leaves the field out, so Studio uses the loaded model's own default.
    steps: int | None = Field(default=None, ge=1, le=100)
    guidance: float | None = Field(default=None, ge=0, le=20)


class ProvidersConfig(BaseModel):
    openai: OpenAIConfig = Field(default_factory=OpenAIConfig)
    a1111: A1111Config = Field(default_factory=A1111Config)
    comfyui: ComfyUIConfig = Field(default_factory=ComfyUIConfig)
    unsloth: UnslothConfig = Field(default_factory=UnslothConfig)


class OutputConfig(BaseModel):
    # Relative paths resolve against the server's working directory, which is the
    # project folder Claude Code was started in ("." = that folder itself).
    dir: str = "."
    return_inline: bool = True
    inline_max_px: int = Field(default=1024, ge=128, le=4096)
    # Where the desktop app's Playground saves; unlike Claude it has no session folder of its own.
    playground_dir: str = "~/Pictures/ImgSwitch"


class UIConfig(BaseModel):
    language: Literal["en", "zh-CN"] = "en"
    theme: Literal["system", "light", "dark"] = "system"


class AppConfig(BaseModel):
    active_provider: ProviderName = "openai"
    output: OutputConfig = Field(default_factory=OutputConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    ui: UIConfig = Field(default_factory=UIConfig)

    @model_validator(mode="after")
    def _active_is_enabled(self) -> AppConfig:
        if not getattr(self.providers, self.active_provider).enabled:
            raise ValueError(
                f"The active backend {self.active_provider!r} can't be disabled; choose another active backend first"
            )
        return self

    def enabled_providers(self) -> list[str]:
        return [name for name in PROVIDER_NAMES if getattr(self.providers, name).enabled]


def config_path() -> Path:
    """Resolve the config file location independently of the current working directory."""
    env = os.environ.get("IMGSWITCH_CONFIG")
    return Path(env).expanduser().resolve() if env else PROJECT_ROOT / "config.json"


def data_dir() -> Path:
    """Folder for the generation history and Playground uploads: next to the config file."""
    return config_path().parent


def resolve_project_path(p: str) -> Path:
    """Resolve an ImgSwitch resource path (e.g. a workflow): relative to the ImgSwitch folder."""
    path = Path(p).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def resolve_output_dir(p: str) -> Path:
    """Resolve an output folder: relative to the working directory of the calling client.

    Claude Code starts stdio servers in the folder the session runs in, so "." is the
    user's project.
    """
    path = Path(p).expanduser()
    return (path if path.is_absolute() else Path.cwd() / path).resolve()


def load_config(path: Path | None = None, *, apply_env: bool = True) -> AppConfig:
    """Load the config, creating it with defaults if it does not exist yet.

    With apply_env, environment variables override secrets for this process only; they are
    never written back to the file.
    """
    path = path or config_path()
    if path.exists():
        cfg = AppConfig.model_validate(json.loads(path.read_text(encoding="utf-8")))
    else:
        cfg = AppConfig()
        save_config(cfg, path)
    if apply_env:
        key = os.environ.get("IMGSWITCH_OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY")
        if key:
            cfg.providers.openai.api_key = key
    return cfg


def save_config(cfg: AppConfig, path: Path | None = None) -> None:
    """Write the config atomically so a concurrent reader never sees a partial file."""
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(cfg.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)  # the file holds an API key
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def mask_secret(secret: str) -> str:
    if not secret:
        return ""
    return MASK_PREFIX + secret[-4:] if len(secret) > 8 else MASK_PREFIX


def is_masked(value: str) -> bool:
    return value.startswith(MASK_PREFIX)
