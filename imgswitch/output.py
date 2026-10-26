"""Save generated images to disk and build inline previews for the MCP client."""

from __future__ import annotations

import base64
import io
import re
from datetime import datetime
from pathlib import Path

from mcp_types import ImageContent
from PIL import Image, UnidentifiedImageError

from imgswitch.providers import GeneratedImage

EXTENSIONS = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}
# Send the original bytes inline only when they are already small; otherwise re-encode.
INLINE_PASSTHROUGH_BYTES = 1_500_000


def _slug(prompt: str, max_len: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", prompt.lower()).strip("-")
    return slug[:max_len].rstrip("-") or "image"


def _safe_stem(filename: str) -> str:
    """Turn a caller-supplied name into a bare file stem: no folders, no extension, no odd characters."""
    name = Path(filename).name
    if Path(name).suffix.lower() in {*EXTENSIONS.values(), ".jpeg"}:
        name = Path(name).stem
    return re.sub(r"[^\w.-]+", "-", name).strip("-.") or "image"


def save_images(
    images: list[GeneratedImage], prompt: str, out_dir: Path, filename: str | None = None
) -> list[Path]:
    """Write images to out_dir and return their paths. Existing files are never overwritten."""
    out_dir.mkdir(parents=True, exist_ok=True)
    if filename:
        stem = _safe_stem(filename)
        names = [stem] if len(images) == 1 else [f"{stem}-{i}" for i in range(1, len(images) + 1)]
    else:
        stem = f"{datetime.now():%Y%m%d-%H%M%S}-{_slug(prompt)}"
        names = [f"{stem}-{i}" for i in range(1, len(images) + 1)]
    paths = []
    for name, img in zip(names, images):
        ext = EXTENSIONS.get(img.mime_type, ".png")
        path = out_dir / f"{name}{ext}"
        n = 2
        while path.exists():
            path = out_dir / f"{name}-{n}{ext}"
            n += 1
        path.write_bytes(img.data)
        paths.append(path)
    return paths


def inline_content(img: GeneratedImage, max_px: int) -> ImageContent:
    """Return the image as ImageContent, downscaled so its long edge is at most max_px."""
    original = ImageContent(type="image", data=base64.b64encode(img.data).decode(), mime_type=img.mime_type)
    try:
        im = Image.open(io.BytesIO(img.data))
    except UnidentifiedImageError:
        return original
    with im:
        if max(im.size) <= max_px and len(img.data) <= INLINE_PASSTHROUGH_BYTES:
            return original
        im = im.copy()
        im.thumbnail((max_px, max_px), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        if im.mode in ("RGBA", "LA", "P"):
            im.save(buf, format="PNG", optimize=True)
            mime = "image/png"
        else:
            im.convert("RGB").save(buf, format="JPEG", quality=90)
            mime = "image/jpeg"
    return ImageContent(type="image", data=base64.b64encode(buf.getvalue()).decode(), mime_type=mime)
