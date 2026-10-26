"""Dashboard backend: config CRUD and connectivity checks. Only imported in --gui mode."""

from __future__ import annotations

import asyncio
import os
import shlex
import sys
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from imgswitch import PROJECT_ROOT
from imgswitch.config import (
    PROVIDER_NAMES,
    AppConfig,
    config_path,
    is_masked,
    load_config,
    mask_secret,
    save_config,
)
from imgswitch.providers import PROVIDERS, ProviderError
from imgswitch.providers.openai_compat import is_image_model

STATIC_DIR = Path(__file__).parent / "static"
LOCAL_HOSTS = ["127.0.0.1", "localhost"]
KEY_ENV_VARS = ("IMGSWITCH_OPENAI_API_KEY", "OPENAI_API_KEY")
# Providers whose config holds an api_key that the dashboard must never echo back.
SECRET_PROVIDERS = ("openai", "unsloth")


def _env_key_var() -> str | None:
    return next((v for v in KEY_ENV_VARS if os.environ.get(v)), None)


def _masked(cfg: AppConfig) -> dict[str, Any]:
    data = cfg.model_dump(mode="json")
    for name in SECRET_PROVIDERS:
        data["providers"][name]["api_key"] = mask_secret(getattr(cfg.providers, name).api_key)
    return data


def _resolve_key(name: str, submitted: str) -> str:
    """A masked value coming back from the form means "unchanged"."""
    if is_masked(submitted):
        return getattr(load_config(apply_env=False).providers, name).api_key
    return submitted


def _provider_from_form(name: str, form: dict[str, Any]):
    if name not in PROVIDERS:
        raise HTTPException(404, f"Unknown provider {name!r}")
    cfg = load_config()
    saved = getattr(cfg.providers, name)
    try:
        merged = type(saved).model_validate({**saved.model_dump(), **form})
    except ValidationError as e:
        raise HTTPException(422, e.errors(include_url=False, include_context=False)) from None
    if name in SECRET_PROVIDERS:
        # Fall back to the env var or the stored key so "Test" works before a key is typed.
        merged.api_key = _resolve_key(name, merged.api_key) if merged.api_key else saved.api_key
    return PROVIDERS[name](merged)


def create_app(allowed_hosts: list[str] | None = None) -> FastAPI:
    app = FastAPI(title="ImgSwitch", docs_url=None, redoc_url=None)
    if allowed_hosts:
        # Blocks DNS-rebinding pages from reaching the local API.
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/api/config")
    async def get_config() -> dict[str, Any]:
        return _masked(load_config(apply_env=False))

    @app.put("/api/config")
    async def put_config(body: dict[str, Any]) -> dict[str, Any]:
        try:
            cfg = AppConfig.model_validate(body)
        except ValidationError as e:
            raise HTTPException(422, e.errors(include_url=False, include_context=False)) from None
        for name in SECRET_PROVIDERS:
            submitted = getattr(cfg.providers, name)
            submitted.api_key = _resolve_key(name, submitted.api_key)
        save_config(cfg)
        return _masked(cfg)

    @app.get("/api/meta")
    async def meta() -> dict[str, Any]:
        main_py = PROJECT_ROOT / "main.py"
        return {
            "config_path": str(config_path()),
            "api_key_env_var": _env_key_var(),
            "claude_command": f"claude mcp add --scope user imgswitch -- {shlex.quote(sys.executable)} {shlex.quote(str(main_py))}",
        }

    @app.post("/api/providers/{name}/test")
    async def test_provider(name: str, form: dict[str, Any]) -> dict[str, Any]:
        status = await _provider_from_form(name, form).health_check()
        return status.__dict__

    @app.get("/api/status")
    async def status() -> dict[str, Any]:
        cfg = load_config()
        providers = [PROVIDERS[n](getattr(cfg.providers, n)) for n in PROVIDER_NAMES]
        results = await asyncio.gather(*(p.health_check() for p in providers))
        return {p.name: r.__dict__ for p, r in zip(providers, results)}

    @app.post("/api/comfyui/checkpoints")
    async def comfyui_checkpoints(form: dict[str, Any]) -> list[str]:
        provider = _provider_from_form("comfyui", form)
        try:
            async with provider.client(timeout=10) as client:
                return await provider.list_checkpoints(client)
        except httpx.HTTPError as e:
            raise HTTPException(502, provider.describe_http_error(e)) from None
        except ProviderError as e:
            raise HTTPException(502, str(e)) from None

    @app.post("/api/openai/models")
    async def openai_models(form: dict[str, Any]) -> dict[str, list[str]]:
        provider = _provider_from_form("openai", form)
        try:
            models = await provider.list_models()
        except httpx.HTTPError as e:
            raise HTTPException(502, provider.describe_http_error(e)) from None
        except ProviderError as e:
            raise HTTPException(502, str(e)) from None
        return {
            "image": [m for m in models if is_image_model(m)],
            "other": [m for m in models if not is_image_model(m)],
        }

    return app

