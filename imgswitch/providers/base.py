"""Common provider interface."""

from __future__ import annotations

import base64
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar

import httpx


# img2img strength when a call gives none: keeps the composition while clearly applying the prompt.
DEFAULT_STRENGTH = 0.6


class ProviderError(Exception):
    """A generation or health-check failure with a message fit to show the user."""


@dataclass
class InputImage:
    """An existing image passed in to be edited or used as a reference."""

    data: bytes
    mime_type: str
    filename: str
    width: int
    height: int
    path: str = ""  # where it was loaded from, for the history

    def b64(self) -> str:
        return base64.b64encode(self.data).decode()

    def data_url(self) -> str:
        return f"data:{self.mime_type};base64,{self.b64()}"


@dataclass
class GenerationRequest:
    prompt: str
    width: int
    height: int
    negative_prompt: str | None = None
    n: int = 1
    seed: int | None = None
    # The first image is the one being edited, the rest are references; empty for text-to-image.
    images: list[InputImage] = field(default_factory=list)
    strength: float | None = None
    # The size was derived from the input image rather than asked for, so a backend may choose its own.
    auto_size: bool = False


@dataclass
class GeneratedImage:
    data: bytes
    mime_type: str = "image/png"


@dataclass
class HealthStatus:
    ok: bool
    detail: str
    latency_ms: int | None = None


class ImageProvider(ABC):
    name: ClassVar[str]
    label: ClassVar[str]
    # Tells the agent what the backend is and where its model comes from (tool docs and list_backends).
    description: ClassVar[str]

    def __init__(self, config):
        self.config = config

    @property
    def model_label(self) -> str:
        return self.label

    def client(self, timeout: float | None = None) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.config.base_url.rstrip("/"),
            timeout=timeout if timeout is not None else self.config.timeout,
        )

    @abstractmethod
    async def generate(self, req: GenerationRequest) -> list[GeneratedImage]: ...

    async def image_input(self) -> str:
        """One line for list_backends on whether and how this backend takes input images."""
        return "no"

    def _require_single_image(self, req: GenerationRequest) -> InputImage:
        if len(req.images) > 1:
            raise ProviderError(f"{self.label} takes one input image, got {len(req.images)}")
        return req.images[0]

    @abstractmethod
    async def _probe(self) -> str:
        """Run a cheap request against the backend and return a short description."""

    async def health_check(self) -> HealthStatus:
        start = time.perf_counter()
        try:
            detail = await self._probe()
        except ProviderError as e:
            return HealthStatus(ok=False, detail=str(e))
        except httpx.HTTPError as e:
            return HealthStatus(ok=False, detail=self.describe_http_error(e))
        return HealthStatus(ok=True, detail=detail, latency_ms=round((time.perf_counter() - start) * 1000))

    def describe_http_error(self, e: httpx.HTTPError) -> str:
        base = self.config.base_url
        if isinstance(e, httpx.ConnectError):
            return f"{self.label} not reachable at {base}. Is it running?"
        if isinstance(e, httpx.TimeoutException):
            return f"{self.label} at {base} timed out"
        if isinstance(e, httpx.HTTPStatusError):
            return f"{self.label} returned HTTP {e.response.status_code}: {_error_text(e.response)}"
        return f"{self.label} request failed: {e}"


def _error_text(resp: httpx.Response) -> str:
    """Pull the human-readable message out of common JSON error shapes."""
    try:
        body = resp.json()
    except ValueError:
        return resp.text.strip().replace("\n", " ")[:300] or resp.reason_phrase
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])
        for key in ("error", "detail", "message"):
            if isinstance(body.get(key), str):
                return body[key]
    return str(body)[:300]


def sniff_mime(data: bytes) -> str:
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "image/png"
