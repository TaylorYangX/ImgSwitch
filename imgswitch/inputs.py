"""Load the images passed to generate_image for editing."""

from __future__ import annotations

import io
import math

from PIL import Image, UnidentifiedImageError

from imgswitch.config import resolve_output_dir
from pathlib import Path

from imgswitch.providers.base import InputImage

MAX_INPUT_BYTES = 50 * 1024 * 1024
# Formats every backend accepts as they are; anything else is converted to PNG.
KEEP_FORMATS = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}


def load_input_images(paths: list[str], base: Path | None = None) -> list[InputImage]:
    return [_load(p, base) for p in paths]


def _load(p: str, base: Path | None) -> InputImage:
    # Same rule as output folders: relative to the calling agent's workspace.
    path = resolve_output_dir(p, base)
    if not path.is_file():
        raise ValueError(f"Input image not found: {path}")
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError(f"Input image {path} is larger than {MAX_INPUT_BYTES // 2**20} MB")
    data = path.read_bytes()
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            fmt, (width, height) = img.format, img.size
            if fmt not in KEEP_FORMATS:
                if img.mode not in ("RGB", "RGBA", "L", "LA", "P"):
                    img = img.convert("RGBA")
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                data, fmt = buf.getvalue(), "PNG"
    except (UnidentifiedImageError, OSError) as e:
        raise ValueError(f"Input image {path} is not a readable image: {e}") from None
    return InputImage(
        data=data,
        mime_type=KEEP_FORMATS[fmt],
        filename=f"{path.stem}.{fmt.lower()}",
        width=width,
        height=height,
        path=str(path),
    )


def fit_size(src_w: int, src_h: int, target_w: int, target_h: int) -> tuple[int, int]:
    """The input's aspect ratio at the backend's default pixel area, in multiples of 64."""
    scale = math.sqrt(target_w * target_h / (src_w * src_h))

    def snap(side: int) -> int:
        return min(4096, max(64, round(side * scale / 64) * 64))

    return snap(src_w), snap(src_h)
