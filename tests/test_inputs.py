import io

import pytest
from PIL import Image

from imgswitch.inputs import fit_size, load_input_images

from .conftest import make_png


def _save(path, fmt, size=(80, 40)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (10, 120, 200)).save(path, format=fmt)
    return path


def test_relative_path_resolves_against_cwd(tmp_path, monkeypatch):
    png = make_png(96, 48)
    (tmp_path / "figs").mkdir()
    (tmp_path / "figs" / "chart.png").write_bytes(png)
    monkeypatch.chdir(tmp_path)

    [img] = load_input_images(["figs/chart.png"])

    assert img.data == png and img.mime_type == "image/png"
    assert (img.width, img.height) == (96, 48) and img.filename == "chart.png"
    assert img.data_url().startswith("data:image/png;base64,")


def test_jpeg_kept_and_bmp_converted(tmp_path):
    jpg = _save(tmp_path / "photo.jpg", "JPEG")
    bmp = _save(tmp_path / "scan.bmp", "BMP")

    kept, converted = load_input_images([str(jpg), str(bmp)])

    assert kept.data == jpg.read_bytes() and kept.mime_type == "image/jpeg"
    assert converted.mime_type == "image/png" and converted.filename == "scan.png"
    assert Image.open(io.BytesIO(converted.data)).format == "PNG"


def test_missing_and_unreadable_files_rejected(tmp_path):
    with pytest.raises(ValueError, match="Input image not found"):
        load_input_images([str(tmp_path / "nope.png")])
    notes = tmp_path / "notes.png"
    notes.write_text("not really a picture")
    with pytest.raises(ValueError, match="not a readable image"):
        load_input_images([str(notes)])


@pytest.mark.parametrize(
    "src,target,expected",
    [
        ((1024, 1024), (1024, 1024), (1024, 1024)),  # an image this backend made stays as it is
        ((1344, 768), (1024, 1024), (1344, 768)),
        ((4000, 3000), (1024, 1024), (1152, 896)),  # a large photo comes down to the backend's usual area
        ((512, 512), (1024, 1024), (1024, 1024)),
        ((100, 10000), (1024, 1024), (128, 4096)),  # clamped to the allowed range
    ],
)
def test_fit_size(src, target, expected):
    assert fit_size(*src, *target) == expected
