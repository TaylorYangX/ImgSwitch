"""ComfyUI via its HTTP API: queue an API-format workflow, poll history, download outputs.

The workflow is a JSON template whose string values may be placeholders such as "{{prompt}}"
or "{{width}}". A value that is exactly a placeholder is replaced with a typed value. Edits use
a second workflow that loads the uploaded input image through "{{image}}".
"""

from __future__ import annotations

import asyncio
import json
import random
import time
import uuid
from typing import Any

import httpx

from imgswitch.config import resolve_project_path
from imgswitch.providers.base import (
    DEFAULT_STRENGTH,
    GeneratedImage,
    GenerationRequest,
    ImageProvider,
    InputImage,
    ProviderError,
    sniff_mime,
)

POLL_INTERVAL = 1.0


def fill_placeholders(node: Any, values: dict[str, Any]) -> Any:
    if isinstance(node, dict):
        return {k: fill_placeholders(v, values) for k, v in node.items()}
    if isinstance(node, list):
        return [fill_placeholders(v, values) for v in node]
    if isinstance(node, str) and node.startswith("{{") and node.endswith("}}"):
        key = node[2:-2].strip()
        if key not in values:
            raise ProviderError(f"Unknown workflow placeholder {node!r}")
        return values[key]
    return node


class ComfyUIProvider(ImageProvider):
    name = "comfyui"
    label = "ComfyUI"
    description = "Local ComfyUI. Runs the dashboard's workflow with the checkpoint chosen there."

    @property
    def model_label(self) -> str:
        return f"ComfyUI ({self.config.checkpoint or 'first checkpoint'})"

    def _load_workflow(self, workflow_path: str) -> dict:
        path = resolve_project_path(workflow_path)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise ProviderError(f"ComfyUI workflow not found: {path}") from None
        except json.JSONDecodeError as e:
            raise ProviderError(f"ComfyUI workflow {path} is not valid JSON: {e}") from None

    async def list_checkpoints(self, client: httpx.AsyncClient) -> list[str]:
        resp = await client.get("/object_info/CheckpointLoaderSimple")
        resp.raise_for_status()
        info = resp.json().get("CheckpointLoaderSimple", {})
        return list(info.get("input", {}).get("required", {}).get("ckpt_name", [[]])[0])

    async def generate(self, req: GenerationRequest) -> list[GeneratedImage]:
        image = self._require_single_image(req) if req.images else None
        workflow = self._load_workflow(self.config.edit_workflow_path if image else self.config.workflow_path)
        try:
            async with self.client() as client:
                checkpoint = self.config.checkpoint
                if not checkpoint:
                    available = await self.list_checkpoints(client)
                    if not available:
                        raise ProviderError("ComfyUI has no checkpoints installed")
                    checkpoint = available[0]
                values = {
                    "prompt": req.prompt,
                    "negative_prompt": req.negative_prompt or "",
                    "width": req.width,
                    "height": req.height,
                    "steps": self.config.steps,
                    "cfg": self.config.cfg_scale,
                    "seed": req.seed if req.seed is not None else random.randint(0, 2**32 - 1),
                    "checkpoint": checkpoint,
                    "batch_size": req.n,
                }
                if image:
                    values["image"] = await self._upload(client, image)
                    values["denoise"] = req.strength if req.strength is not None else DEFAULT_STRENGTH
                prompt_id = await self._queue(client, fill_placeholders(workflow, values))
                outputs = await self._wait(client, prompt_id)
                images = [await self._download(client, ref) for ref in outputs]
        except httpx.HTTPError as e:
            raise ProviderError(self.describe_http_error(e)) from e
        if not images:
            raise ProviderError("The ComfyUI workflow produced no output images")
        return images

    async def _upload(self, client: httpx.AsyncClient, image: InputImage) -> str:
        """Put the input image in ComfyUI's input folder and return the name LoadImage takes."""
        resp = await client.post(
            "/upload/image",
            files={"image": (f"imgswitch-{uuid.uuid4().hex[:8]}-{image.filename}", image.data, image.mime_type)},
            data={"overwrite": "true"},
        )
        resp.raise_for_status()
        ref = resp.json()
        return f"{ref['subfolder']}/{ref['name']}" if ref.get("subfolder") else ref["name"]

    async def image_input(self) -> str:
        path = resolve_project_path(self.config.edit_workflow_path)
        if not path.is_file():
            return f"no (edit workflow {self.config.edit_workflow_path} not found)"
        return f"yes, 1 image via {self.config.edit_workflow_path} (img2img; strength applies)"

    async def _queue(self, client: httpx.AsyncClient, workflow: dict) -> str:
        resp = await client.post("/prompt", json={"prompt": workflow, "client_id": uuid.uuid4().hex})
        if resp.status_code == 400 and resp.headers.get("content-type", "").startswith("application/json"):
            err = resp.json()
            msg = err.get("error", {}).get("message", "invalid workflow")
            node_errors = "; ".join(
                f"node {nid}: {e.get('message')}"
                for nid, ne in (err.get("node_errors") or {}).items()
                for e in ne.get("errors", [])
            )
            raise ProviderError(f"ComfyUI rejected the workflow: {msg}" + (f" ({node_errors})" if node_errors else ""))
        resp.raise_for_status()
        return resp.json()["prompt_id"]

    async def _wait(self, client: httpx.AsyncClient, prompt_id: str) -> list[dict]:
        deadline = time.monotonic() + self.config.timeout
        while time.monotonic() < deadline:
            resp = await client.get(f"/history/{prompt_id}")
            resp.raise_for_status()
            entry = resp.json().get(prompt_id)
            if entry:
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    raise ProviderError(f"ComfyUI execution failed: {self._error_message(status)}")
                if status.get("completed", True):
                    refs = [img for out in entry.get("outputs", {}).values() for img in out.get("images", [])]
                    saved = [r for r in refs if r.get("type") == "output"]
                    return saved or refs
            await asyncio.sleep(POLL_INTERVAL)
        raise ProviderError(f"ComfyUI did not finish within {self.config.timeout:g}s")

    @staticmethod
    def _error_message(status: dict) -> str:
        for kind, data in status.get("messages", []):
            if kind == "execution_error":
                return f"{data.get('node_type', 'node')}: {data.get('exception_message', '').strip()}"
        return "unknown error"

    async def _download(self, client: httpx.AsyncClient, ref: dict) -> GeneratedImage:
        params = {"filename": ref["filename"], "subfolder": ref.get("subfolder", ""), "type": ref.get("type", "output")}
        resp = await client.get("/view", params=params)
        resp.raise_for_status()
        return GeneratedImage(data=resp.content, mime_type=sniff_mime(resp.content))

    async def _probe(self) -> str:
        async with self.client(timeout=10) as client:
            resp = await client.get("/system_stats")
            resp.raise_for_status()
            checkpoints = await self.list_checkpoints(client)
        version = resp.json().get("system", {}).get("comfyui_version", "")
        if self.config.checkpoint and self.config.checkpoint not in checkpoints:
            raise ProviderError(f"Checkpoint {self.config.checkpoint!r} is not installed in ComfyUI")
        checkpoint = self.config.checkpoint or (checkpoints[0] if checkpoints else "none")
        return f"Connected{f', ComfyUI {version}' if version else ''}, checkpoint {checkpoint} ({len(checkpoints)} installed)"
