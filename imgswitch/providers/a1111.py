"""Stable Diffusion WebUI (AUTOMATIC1111 / Forge) via /sdapi/v1/txt2img and /img2img. The WebUI must run with --api."""

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

NO_API_HINT = "Is the WebUI started with the --api flag?"


class A1111Provider(ImageProvider):
    name = "a1111"
    label = "Stable Diffusion WebUI"
    description = "Local Stable Diffusion WebUI (AUTOMATIC1111 / Forge). Uses the checkpoint loaded in the WebUI."

    @property
    def model_label(self) -> str:
        return f"A1111 ({self.config.sampler_name}, {self.config.steps} steps)"

    async def generate(self, req: GenerationRequest) -> list[GeneratedImage]:
        body = {
            "prompt": req.prompt,
            "negative_prompt": req.negative_prompt or "",
            "width": req.width,
            "height": req.height,
            "steps": self.config.steps,
            "cfg_scale": self.config.cfg_scale,
            "sampler_name": self.config.sampler_name,
            "seed": req.seed if req.seed is not None else -1,
            "batch_size": req.n,
        }
        endpoint = "/sdapi/v1/txt2img"
        if req.images:
            endpoint = "/sdapi/v1/img2img"
            body["init_images"] = [self._require_single_image(req).b64()]
            body["denoising_strength"] = req.strength if req.strength is not None else DEFAULT_STRENGTH
        try:
            async with self.client() as client:
                resp = await client.post(endpoint, json=body)
                if resp.status_code == 404:
                    raise ProviderError(f"{endpoint} not found at {self.config.base_url}. {NO_API_HINT}")
                resp.raise_for_status()
        except httpx.HTTPError as e:
            raise ProviderError(self.describe_http_error(e)) from e

        images = []
        for b64 in resp.json().get("images") or []:
            # Some forks prefix a data URI.
            data = base64.b64decode(b64.split(",", 1)[1] if b64.startswith("data:") else b64)
            images.append(GeneratedImage(data=data, mime_type=sniff_mime(data)))
        if not images:
            raise ProviderError("The WebUI returned no images")
        # With batch_size > 1 the WebUI may prepend a grid image; keep only the individual images.
        return images[-req.n :]

    async def image_input(self) -> str:
        return "yes, 1 image (img2img; strength applies)"

    async def _probe(self) -> str:
        async with self.client(timeout=10) as client:
            resp = await client.get("/sdapi/v1/options")
            if resp.status_code == 404:
                raise ProviderError(f"WebUI API not found at {self.config.base_url}. {NO_API_HINT}")
            resp.raise_for_status()
        model = resp.json().get("sd_model_checkpoint") or "unknown model"
        return f"Connected, checkpoint {model}"
