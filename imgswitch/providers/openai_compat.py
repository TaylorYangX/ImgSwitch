"""OpenAI-compatible image endpoint (OpenAI DALL-E / gpt-image, or any proxy speaking the same API)."""

from __future__ import annotations

import base64
import re

import httpx

from imgswitch.providers.base import GeneratedImage, GenerationRequest, ImageProvider, ProviderError, sniff_mime

# /models lists every model on the account; these name patterns pick out image generators,
# including common ones served by OpenAI-compatible proxies.
IMAGE_MODEL_RE = re.compile(
    r"dall-e|image|flux|stable-diffusion|sdxl|sd3|midjourney|imagen|seedream|kolors|recraft|ideogram", re.I
)
# gpt-image models always return base64 and reject the response_format parameter.
GPT_IMAGE_RE = re.compile(r"gpt-image|chatgpt-image", re.I)
DALLE2_RE = re.compile(r"dall-e-2", re.I)
DALLE3_RE = re.compile(r"dall-e-3", re.I)


def is_image_model(model_id: str) -> bool:
    return bool(IMAGE_MODEL_RE.search(model_id))


class OpenAICompatProvider(ImageProvider):
    name = "openai"
    label = "OpenAI-compatible API"
    description = (
        "Cloud API: OpenAI or an OpenAI-compatible proxy. Uses the model set in the ImgSwitch app. Usually billed per image."
    )

    @property
    def model_label(self) -> str:
        return self.config.model

    def _headers(self) -> dict[str, str]:
        if not self.config.api_key:
            raise ProviderError("No API key configured for the OpenAI-compatible provider")
        return {"Authorization": f"Bearer {self.config.api_key}"}

    async def generate(self, req: GenerationRequest) -> list[GeneratedImage]:
        is_gpt_image = bool(GPT_IMAGE_RE.search(self.config.model))
        fields: dict = {"model": self.config.model, "prompt": req.prompt, "n": req.n}
        if self.config.response_format != "omit" and not is_gpt_image:
            fields["response_format"] = self.config.response_format
        if not req.images:
            fields["size"] = f"{req.width}x{req.height}"
            return await self._request("/images/generations", json=fields)

        self._check_edit(req)
        if not req.auto_size:
            fields["size"] = f"{req.width}x{req.height}"
        elif is_gpt_image:
            fields["size"] = "auto"  # follow the input image's shape
        # One image goes as "image", several as repeated "image[]" fields.
        key = "image" if len(req.images) == 1 else "image[]"
        files = [(key, (img.filename, img.data, img.mime_type)) for img in req.images]
        return await self._request("/images/edits", data={k: str(v) for k, v in fields.items()}, files=files)

    def _check_edit(self, req: GenerationRequest) -> None:
        model = self.config.model
        if DALLE3_RE.search(model):
            raise ProviderError(f"{model} can't edit images; choose a gpt-image model (or dall-e-2) in the ImgSwitch app")
        if DALLE2_RE.search(model) and len(req.images) > 1:
            raise ProviderError("dall-e-2 edits take one input image")

    async def image_input(self) -> str:
        model = self.config.model
        if GPT_IMAGE_RE.search(model):
            return f"yes, up to 16 images ({model} edits by instruction)"
        if DALLE2_RE.search(model):
            return "yes, 1 square PNG (dall-e-2)"
        if DALLE3_RE.search(model):
            return f"no ({model} can't edit images)"
        return f"maybe, through /images/edits if this API supports it for {model}"

    async def _request(self, path: str, **kwargs) -> list[GeneratedImage]:
        try:
            async with self.client() as client:
                resp = await client.post(path, headers=self._headers(), **kwargs)
                resp.raise_for_status()
                items = resp.json().get("data") or []
                images = [await self._decode(client, item) for item in items]
        except httpx.HTTPError as e:
            raise ProviderError(self.describe_http_error(e)) from e
        if not images:
            raise ProviderError("The API returned no images")
        return images

    async def _decode(self, client: httpx.AsyncClient, item: dict) -> GeneratedImage:
        if item.get("b64_json"):
            data = base64.b64decode(item["b64_json"])
        elif item.get("url"):
            # Absolute URL on another host, so this bypasses base_url.
            r = await client.get(item["url"], follow_redirects=True)
            r.raise_for_status()
            data = r.content
        else:
            raise ProviderError("API response item contains neither b64_json nor url")
        return GeneratedImage(data=data, mime_type=sniff_mime(data))

    async def list_models(self) -> list[str]:
        async with self.client(timeout=10) as client:
            resp = await client.get("/models", headers=self._headers())
            resp.raise_for_status()
        return sorted(m["id"] for m in resp.json().get("data") or [] if isinstance(m, dict) and m.get("id"))

    async def _probe(self) -> str:
        await self.list_models()
        return f"Authenticated, model {self.config.model}"
