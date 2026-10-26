"""Backend for the desktop app and the browser dashboard: config, backends, Playground, history and
Claude Code status. Only imported in --gui mode.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import functools
import io
import os
import re
import shlex
import sys
import uuid
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field, ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from imgswitch import PROJECT_ROOT, __version__, claude_code, history, service
from imgswitch.config import (
    PROVIDER_NAMES,
    AppConfig,
    ProviderName,
    config_path,
    data_dir,
    is_masked,
    load_config,
    mask_secret,
    resolve_output_dir,
    save_config,
)
from imgswitch.inputs import MAX_INPUT_BYTES
from imgswitch.providers import PROVIDERS, ProviderError
from imgswitch.providers.openai_compat import is_image_model

# The UI is built from app/ (npm run build) into dist/.
DIST_DIR = Path(__file__).parent / "dist"
# The desktop app's webview loads the UI from its own origin (or, in `npm run tauri dev`, the Vite dev
# server) and calls this API cross-origin.
TAURI_ORIGINS = ["tauri://localhost", "http://tauri.localhost", "https://tauri.localhost", "http://localhost:1420"]
THUMB_PX = 384
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


class GenerateBody(BaseModel):
    prompt: str = Field(min_length=1)
    provider: ProviderName | None = None
    input_images: list[str] | None = Field(default=None, min_length=1, max_length=16)
    strength: float | None = Field(default=None, gt=0, le=1)
    size: str | None = None
    negative_prompt: str | None = None
    n: int = Field(default=1, ge=1, le=4)
    seed: int | None = None
    filename: str | None = None


class UploadBody(BaseModel):
    name: str
    data: str  # base64, optionally as a data: URL


class PathBody(BaseModel):
    path: str


@functools.lru_cache(maxsize=512)
def _thumbnail(path: str, mtime_ns: int) -> bytes:
    """A small WebP for the History grid; cached per file version."""
    with Image.open(path) as im:
        im = im.convert("RGBA") if im.mode not in ("RGB", "RGBA") else im.copy()
    im.thumbnail((THUMB_PX, THUMB_PX), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="WEBP", quality=82)
    return buf.getvalue()


def _is_wsl() -> bool:
    try:
        return "microsoft" in Path("/proc/version").read_text().lower()
    except OSError:
        return False


FALLBACK_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>ImgSwitch</title></head>
<body style="font-family:system-ui;max-width:40rem;margin:4rem auto;line-height:1.5">
<h1>ImgSwitch</h1><p>The interface hasn't been built yet. Build it once with:</p>
<pre>cd app &amp;&amp; npm install &amp;&amp; npm run build</pre><p>then reload this page.</p></body></html>"""


def create_app(allowed_hosts: list[str] | None = None, app_mode: bool = False) -> FastAPI:
    app = FastAPI(title="ImgSwitch", docs_url=None, redoc_url=None)
    if allowed_hosts:
        # Blocks DNS-rebinding pages from reaching the local API.
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
    if app_mode:
        app.add_middleware(CORSMiddleware, allow_origins=TAURI_ORIGINS, allow_methods=["*"], allow_headers=["*"])

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
        return {
            "version": __version__,
            "project_root": str(PROJECT_ROOT),
            "config_path": str(config_path()),
            "data_dir": str(data_dir()),
            "history_path": str(history.history_path()),
            "playground_dir": str(resolve_output_dir(load_config().output.playground_dir)),
            "python": sys.executable,
            "app_mode": app_mode,
            "wsl": _is_wsl(),
            "api_key_env_var": _env_key_var(),
            "claude_command": shlex.join(claude_code.register_command()),
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

    @app.get("/api/backends")
    async def backends() -> list[dict[str, Any]]:
        return await service.describe_backends(load_config())

    @app.post("/api/generate")
    async def generate(body: GenerateBody) -> dict[str, Any]:
        cfg = load_config()
        try:
            result = await service.generate(
                cfg, **body.model_dump(), output_dir=cfg.output.playground_dir, source="playground"
            )
        except service.GenerationError as e:
            raise HTTPException(400, str(e)) from None
        return {
            "summary": result.summary(),
            "history_id": result.history_id,
            "paths": [str(p) for p in result.paths],
            "width": result.width,
            "height": result.height,
            "backend": result.backend.name,
            "model": result.backend.model_label,
        }

    @app.post("/api/uploads")
    async def upload(body: UploadBody) -> dict[str, str]:
        """Store an image dropped into the browser UI, which has no file paths, and return its path."""
        raw = body.data.split(",", 1)[1] if body.data.startswith("data:") else body.data
        try:
            data = base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(400, "The upload isn't valid base64") from None
        if len(data) > MAX_INPUT_BYTES:
            raise HTTPException(413, f"Images over {MAX_INPUT_BYTES // 2**20} MB can't be used as input")
        folder = data_dir() / "uploads"
        folder.mkdir(parents=True, exist_ok=True)
        name = re.sub(r"[^\w.-]+", "-", Path(body.name).name).strip("-.") or "image.png"
        path = folder / f"{uuid.uuid4().hex[:8]}-{name}"
        path.write_bytes(data)
        return {"path": str(path)}

    @app.post("/api/thumbnail")
    def thumbnail(body: PathBody) -> dict[str, str]:
        """A preview of an image the user picked as Playground input (a POST, so other sites can't embed it)."""
        path = Path(body.path).expanduser()
        if not path.is_file():
            raise HTTPException(404, f"{path} doesn't exist")
        try:
            data = _thumbnail(str(path), path.stat().st_mtime_ns)
        except (UnidentifiedImageError, OSError):
            raise HTTPException(415, f"{path} isn't a readable image") from None
        return {"data_url": "data:image/webp;base64," + base64.b64encode(data).decode()}

    @app.get("/api/history")
    def history_list(
        offset: int = Query(0, ge=0),
        limit: int = Query(60, ge=1, le=500),
        q: str = "",
        source: str | None = None,
        backend: str | None = None,
    ) -> dict[str, Any]:
        items, total = history.list_entries(offset, limit, q, source, backend)
        return {"items": items, "total": total}

    @app.delete("/api/history")
    def history_clear() -> dict[str, int]:
        return {"removed": history.clear()}

    @app.delete("/api/history/{entry_id}")
    def history_delete(entry_id: str) -> dict[str, bool]:
        if not history.delete(entry_id):
            raise HTTPException(404, "No such history entry")
        return {"ok": True}

    @app.get("/api/history/{entry_id}/{kind}/{index}")
    def history_file(entry_id: str, kind: Literal["outputs", "inputs"], index: int, thumb: bool = False) -> Response:
        """Serve an image recorded in the history, and nothing else."""
        entry = history.get(entry_id)
        paths = (entry or {}).get(kind) or []
        if not 0 <= index < len(paths):
            raise HTTPException(404, "No such image in this history entry")
        path = Path(paths[index])
        if not path.is_file():
            raise HTTPException(404, f"{path} no longer exists")
        if not thumb:
            return FileResponse(path)
        try:
            data = _thumbnail(str(path), path.stat().st_mtime_ns)
        except (UnidentifiedImageError, OSError) as e:
            raise HTTPException(415, f"Can't read {path}: {e}") from None
        return Response(data, media_type="image/webp", headers={"Cache-Control": "max-age=86400"})

    @app.get("/api/claude")
    def claude_status() -> dict[str, Any]:
        return claude_code.status()

    @app.post("/api/claude/register")
    def claude_register() -> dict[str, Any]:
        return claude_code.register()

    @app.post("/api/claude/permissions")
    def claude_permissions() -> dict[str, Any]:
        return claude_code.allow_tools()

    # The UI comes last, so that /api/* always wins.
    if (DIST_DIR / "index.html").is_file():
        app.mount("/", StaticFiles(directory=DIST_DIR, html=True), name="ui")
    else:

        @app.get("/", include_in_schema=False)
        async def index() -> HTMLResponse:
            return HTMLResponse(FALLBACK_HTML)

    return app

