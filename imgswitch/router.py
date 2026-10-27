"""Route a request to the configured backend."""

from __future__ import annotations

from imgswitch.config import AppConfig
from imgswitch.providers import PROVIDERS, ImageProvider, ProviderError


def get_provider(cfg: AppConfig, name: str | None = None) -> ImageProvider:
    """Build the adapter for `name`, or for the config's active provider when name is None."""
    name = name or cfg.active_provider
    cls = PROVIDERS.get(name)
    if cls is None:
        raise ProviderError(f"Unknown provider {name!r}; choose one of {', '.join(PROVIDERS)}")
    config = getattr(cfg.providers, name)
    if not config.enabled:
        raise ProviderError(
            f"The {name!r} backend is disabled in the ImgSwitch app. "
            f"Available: {', '.join(cfg.enabled_providers())}. Call list_backends to see what each runs."
        )
    return cls(config)
