"""The generation pipeline and backend overview, shared by the MCP tools and the desktop app."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from imgswitch import history
from imgswitch.config import PROVIDER_NAMES, AppConfig, parse_size, resolve_output_dir
from imgswitch.inputs import fit_size, load_input_images
from imgswitch.output import save_images
from imgswitch.providers import PROVIDERS, GeneratedImage, GenerationRequest, ImageProvider, InputImage, ProviderError
from imgswitch.router import get_provider

logger = logging.getLogger(__name__)


class GenerationError(Exception):
    """A failure with a message fit to show the user (or Claude) as it is."""


@dataclass
class GenerationResult:
    backend: ImageProvider
    width: int
    height: int
    inputs: list[InputImage]
    images: list[GeneratedImage]
    paths: list[Path]
    history_id: str | None

    def summary(self) -> str:
        source = f" from {len(self.inputs)} input image(s)" if self.inputs else ""
        return (
            f"Generated {len(self.paths)} image(s){source} with {self.backend.label} ({self.backend.model_label}) "
            f"at {self.width}x{self.height}:"
        )


async def generate(
    cfg: AppConfig,
    *,
    prompt: str,
    input_images: list[str] | None = None,
    strength: float | None = None,
    size: str | None = None,
    negative_prompt: str | None = None,
    n: int = 1,
    seed: int | None = None,
    provider: str | None = None,
    output_dir: str | None = None,
    filename: str | None = None,
    source: str = "claude",
) -> GenerationResult:
    try:
        backend = get_provider(cfg, provider)
        inputs = load_input_images(input_images or [])
        if size or not inputs:
            width, height = parse_size(size or backend.config.default_size)
        else:
            width, height = fit_size(inputs[0].width, inputs[0].height, *parse_size(backend.config.default_size))
    except (ProviderError, ValueError) as e:
        raise GenerationError(str(e)) from e
    # Create the folder first so a bad path fails before a (possibly paid) generation.
    out_dir = resolve_output_dir(output_dir or cfg.output.dir)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise GenerationError(f"Cannot create output folder {out_dir}: {e}") from e
    try:
        req = GenerationRequest(
            prompt=prompt,
            width=width,
            height=height,
            negative_prompt=negative_prompt,
            n=n,
            seed=seed,
            images=inputs,
            strength=strength,
            auto_size=bool(inputs) and not size,
        )
        logger.info(
            "Generating %d image(s) at %dx%d from %d input image(s) via %s", n, width, height, len(inputs), backend.name
        )
        images = await backend.generate(req)
    except (ProviderError, ValueError) as e:
        raise GenerationError(str(e)) from e

    try:
        paths = save_images(images, prompt, out_dir, filename)
    except OSError as e:
        raise GenerationError(f"Could not save images to {out_dir}: {e}") from e
    entry = history.record({
        "source": source,
        "backend": backend.name,
        "backend_label": backend.label,
        "model": backend.model_label,
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "width": width,
        "height": height,
        "seed": seed,
        "n": n,
        "strength": strength,
        "inputs": [img.path for img in inputs],
        "outputs": [str(p) for p in paths],
        "cwd": os.getcwd(),
    })
    return GenerationResult(backend, width, height, inputs, images, paths, entry["id"] if entry else None)


async def describe_backends(cfg: AppConfig, names: list[str] | None = None) -> list[dict]:
    """Status, model and image-input support for each named backend (all of them by default), checked live."""
    names = names if names is not None else list(PROVIDER_NAMES)
    backends = [PROVIDERS[name](getattr(cfg.providers, name)) for name in names]
    statuses, image_inputs = await asyncio.gather(
        asyncio.gather(*(b.health_check() for b in backends)),
        # A malformed answer from one backend shouldn't hide every backend's status.
        asyncio.gather(*(b.image_input() for b in backends), return_exceptions=True),
    )
    return [
        {
            "name": b.name,
            "label": b.label,
            "description": b.description,
            "enabled": b.config.enabled,
            "active": b.name == cfg.active_provider,
            "ok": status.ok,
            "detail": status.detail,
            "latency_ms": status.latency_ms,
            "image_input": image_input if isinstance(image_input, str) else "unknown",
        }
        for b, status, image_input in zip(backends, statuses, image_inputs)
    ]
