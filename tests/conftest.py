import base64
import io

import pytest
from PIL import Image

from imgswitch.config import AppConfig, save_config


def make_png(width: int = 64, height: int = 64, color=(200, 80, 40)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, format="PNG")
    return buf.getvalue()


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    """Point the app at an isolated config whose output dir lives in tmp_path."""
    path = tmp_path / "config.json"
    monkeypatch.setenv("IMGSWITCH_CONFIG", str(path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("IMGSWITCH_OPENAI_API_KEY", raising=False)
    cfg = AppConfig()
    cfg.output.dir = str(tmp_path / "outputs")
    save_config(cfg, path)
    return path


@pytest.fixture
def png() -> bytes:
    return make_png()
