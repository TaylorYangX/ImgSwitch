"""Unsloth Studio / Desktop local API.

Text-to-image goes through the OpenAI-compatible /v1/images/generations. Besides the OpenAI fields
it accepts seed, negative_prompt, steps and guidance (Studio builds from 2026-10-20 on; older ones
silently ignore them). Studio has no /v1/images/edits, so edits use its native
/api/inference/images/generate, whose workflow depends on what the loaded model reports it can do.
Either way Studio uses whichever image model is loaded in its Images tab, so no model is sent.
"""

from __future__ import annotations

import base64

import httpx

from imgswitch.providers.base import (
    DEFAULT_STRENGTH,
    GeneratedImage,
    GenerationRequest,
    ImageProvider,
    ProviderError,
    sniff_mime,
)

NO_KEY_HINT = "Create a key in Unsloth: avatar → Settings → API."


class UnslothProvider(ImageProvider):
    name = "unsloth"
    label = "Unsloth Studio"
    description = (
        "Local Unsloth Studio. Uses whichever image model is loaded in Studio's Images tab "
        "(e.g. Qwen-Image, FLUX, Z-Image, SDXL)."
    )

    def __init__(self, config):
        super().__init__(config)
        self.loaded_model: str | None = None  # filled in after a generation, for the result text

    @property
    def model_label(self) -> str:
        return self.loaded_model or "model loaded in Studio"

    def client(self, timeout: float | None = None) -> httpx.AsyncClient:
        # Paths include /v1 or /api themselves; accept the server root the CLI prints as well as a pasted .../v1.
        root = self.config.base_url.rstrip("/").removesuffix("/v1")
        return httpx.AsyncClient(base_url=root, timeout=timeout if timeout is not None else self.config.timeout)

    def _headers(self) -> dict[str, str]:
        # Without a key the server's own 401 explains the problem, with the hint below.
        return {"Authorization": f"Bearer {self.config.api_key}"} if self.config.api_key else {}

    async def generate(self, req: GenerationRequest) -> list[GeneratedImage]:
        if req.images:
            return await self._edit(req)
        # b64_json saves a second download from the signed gallery URL and is required without a key.
        body: dict = {"prompt": req.prompt, "n": req.n, "size": f"{req.width}x{req.height}", "response_format": "b64_json"}
        extras = {
            "negative_prompt": req.negative_prompt,
            "seed": req.seed,
            "steps": self.config.steps,
            "guidance": self.config.guidance,
        }
        body.update({k: v for k, v in extras.items() if v is not None})

        try:
            async with self.client() as client:
                resp = await client.post("/v1/images/generations", json=body, headers=self._headers())
                resp.raise_for_status()
                try:
                    self.loaded_model = ", ".join(await self._loaded_image_models(client)) or None
                except httpx.HTTPError:
                    pass  # only used to name the model in the result text
        except httpx.HTTPError as e:
            raise ProviderError(self.describe_http_error(e)) from e

        images = []
        for item in resp.json().get("data") or []:
            if not item.get("b64_json"):
                raise ProviderError("Unsloth Studio response item contains no b64_json")
            data = base64.b64decode(item["b64_json"])
            images.append(GeneratedImage(data=data, mime_type=sniff_mime(data)))
        if not images:
            raise ProviderError("Unsloth Studio returned no images")
        return images

    async def _edit(self, req: GenerationRequest) -> list[GeneratedImage]:
        try:
            async with self.client() as client:
                status = await self._image_status(client)
                body = self._edit_body(req, status)
                resp = await client.post("/api/inference/images/generate", json=body, headers=self._headers())
                resp.raise_for_status()
                images = []
                # The native route returns gallery records; each url serves the saved PNG.
                for record in resp.json().get("images") or []:
                    r = await client.get(record["url"], headers=self._headers())
                    r.raise_for_status()
                    images.append(GeneratedImage(data=r.content, mime_type=sniff_mime(r.content)))
        except httpx.HTTPError as e:
            raise ProviderError(self.describe_http_error(e)) from e
        if not images:
            raise ProviderError("Unsloth Studio returned no images")
        self.loaded_model = status.get("repo_id") or None
        return images

    def _edit_body(self, req: GenerationRequest, status: dict) -> dict:
        workflows = status.get("workflows") or []
        model = status.get("repo_id") or "The loaded model"
        body: dict = {
            "prompt": req.prompt,
            "width": req.width,
            "height": req.height,
            "batch_size": req.n,
            "init_image": req.images[0].data_url(),
        }
        if "edit" in workflows:
            # The prompt is an instruction over the first image; the others are references.
            limit = _max_images(status)
            if len(req.images) > limit:
                raise ProviderError(f"{model} takes at most {limit} input image(s), got {len(req.images)}")
            body["workflow"] = "edit"
            if len(req.images) > 1:
                body["reference_images"] = [img.data_url() for img in req.images[1:]]
        elif "img2img" in workflows:
            self._require_single_image(req)
            body["strength"] = req.strength if req.strength is not None else DEFAULT_STRENGTH
        else:
            raise ProviderError(
                f"{model} in Unsloth Studio can't take an input image (workflows: {', '.join(workflows) or 'none'}). "
                "Load an edit model such as Qwen-Image-Edit or FLUX.1 Kontext in Studio's Images tab."
            )
        extras = {
            "negative_prompt": req.negative_prompt,
            "seed": req.seed,
            "steps": self.config.steps,
            "guidance": self.config.guidance,
        }
        body.update({k: v for k, v in extras.items() if v is not None})
        return body

    async def _image_status(self, client: httpx.AsyncClient) -> dict:
        resp = await client.get("/api/inference/images/status", headers=self._headers())
        resp.raise_for_status()
        status = resp.json()
        if not status.get("loaded"):
            raise ProviderError("No image model loaded in Unsloth Studio. Load one in its Images tab first.")
        return status

    async def image_input(self) -> str:
        try:
            async with self.client(timeout=10) as client:
                status = await self._image_status(client)
        except ProviderError:
            return "load an image model in Studio first"
        except httpx.HTTPError:
            return "unknown (Studio's image status is not reachable)"
        workflows = status.get("workflows") or []
        model = status.get("repo_id") or "the loaded model"
        if "edit" in workflows:
            return f"yes, edit by instruction with up to {_max_images(status)} images ({model})"
        if "img2img" in workflows:
            return f"yes, 1 image (img2img; strength applies) ({model})"
        return f"no ({model} only does {', '.join(workflows) or 'txt2img'})"

    def describe_http_error(self, e: httpx.HTTPError) -> str:
        detail = super().describe_http_error(e)
        if isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 401:
            return f"{detail.rstrip('.')}. {NO_KEY_HINT}"
        return detail

    async def _loaded_image_models(self, client: httpx.AsyncClient) -> list[str]:
        # /models lists chat and image models, downloaded or loaded; image ones carry a task like "text-to-image".
        resp = await client.get("/v1/models", headers=self._headers())
        resp.raise_for_status()
        return [
            m["id"]
            for m in resp.json().get("data") or []
            if isinstance(m, dict) and m.get("id") and m.get("loaded") and "image" in str(m.get("task", ""))
        ]

    async def _probe(self) -> str:
        async with self.client(timeout=10) as client:
            loaded = await self._loaded_image_models(client)
        if loaded:
            return f"Connected, image model {', '.join(loaded)}"
        return "Connected. Load an image model in Studio's Images tab before generating."


def _max_images(status: dict) -> int:
    return (status.get("conditioning") or {}).get("max_condition_images") or 1
