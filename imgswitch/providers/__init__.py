"""Provider registry."""

from imgswitch.providers.a1111 import A1111Provider
from imgswitch.providers.base import (
    GeneratedImage,
    GenerationRequest,
    HealthStatus,
    ImageProvider,
    InputImage,
    ProviderError,
)
from imgswitch.providers.comfyui import ComfyUIProvider
from imgswitch.providers.openai_compat import OpenAICompatProvider
from imgswitch.providers.unsloth import UnslothProvider

PROVIDERS: dict[str, type[ImageProvider]] = {
    OpenAICompatProvider.name: OpenAICompatProvider,
    A1111Provider.name: A1111Provider,
    ComfyUIProvider.name: ComfyUIProvider,
    UnslothProvider.name: UnslothProvider,
}

__all__ = [
    "PROVIDERS",
    "GeneratedImage",
    "GenerationRequest",
    "HealthStatus",
    "ImageProvider",
    "InputImage",
    "ProviderError",
]
