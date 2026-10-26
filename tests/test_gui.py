import json

import pytest
import respx
from fastapi.testclient import TestClient

from imgswitch.config import load_config, save_config
from imgswitch.gui.app import LOCAL_HOSTS, create_app

from .conftest import b64


@pytest.fixture
def client(config_file):
    cfg = load_config(config_file)
    cfg.providers.openai.api_key = "sk-stored-secret-9999"
    cfg.providers.unsloth.api_key = "sk-unsloth-stored-7777"
    save_config(cfg, config_file)
    return TestClient(create_app())


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "ImgSwitch" in r.text


def test_key_is_masked(client):
    data = client.get("/api/config").json()
    assert data["providers"]["openai"]["api_key"] == "••••9999"
    assert data["providers"]["unsloth"]["api_key"] == "••••7777"


def test_put_with_masked_key_keeps_stored_key(client, config_file):
    data = client.get("/api/config").json()
    data["active_provider"] = "a1111"
    data["providers"]["a1111"]["steps"] = 40

    r = client.put("/api/config", json=data)

    assert r.status_code == 200
    saved = json.loads(config_file.read_text())
    assert saved["active_provider"] == "a1111"
    assert saved["providers"]["a1111"]["steps"] == 40
    assert saved["providers"]["openai"]["api_key"] == "sk-stored-secret-9999"
    assert saved["providers"]["unsloth"]["api_key"] == "sk-unsloth-stored-7777"


def test_put_new_key_replaces_it(client, config_file):
    data = client.get("/api/config").json()
    data["providers"]["openai"]["api_key"] = "sk-new-key-0000"
    client.put("/api/config", json=data)
    assert load_config(config_file, apply_env=False).providers.openai.api_key == "sk-new-key-0000"


def test_put_invalid_rejected_and_file_untouched(client, config_file):
    before = config_file.read_text()
    data = client.get("/api/config").json()
    data["providers"]["a1111"]["default_size"] = "huge"
    r = client.put("/api/config", json=data)
    assert r.status_code == 422
    assert config_file.read_text() == before


def test_put_disabling_active_backend_rejected(client, config_file):
    before = config_file.read_text()
    data = client.get("/api/config").json()
    data["providers"][data["active_provider"]]["enabled"] = False
    r = client.put("/api/config", json=data)
    assert r.status_code == 422 and "can't be disabled" in r.text
    assert config_file.read_text() == before


@respx.mock
def test_connection_test_uses_unsaved_form_values(client):
    route = respx.get("http://10.0.0.5:7860/sdapi/v1/options").respond(json={"sd_model_checkpoint": "sdxl"})
    r = client.post("/api/providers/a1111/test", json={"base_url": "http://10.0.0.5:7860"})
    assert r.json()["ok"] and "sdxl" in r.json()["detail"]
    assert route.called


@respx.mock
def test_openai_test_with_masked_key_uses_stored_key(client):
    route = respx.get("https://api.openai.com/v1/models").respond(json={"data": []})
    r = client.post("/api/providers/openai/test", json={"api_key": "••••9999"})
    assert r.json()["ok"]
    assert route.calls.last.request.headers["authorization"] == "Bearer sk-stored-secret-9999"


@respx.mock
def test_unsloth_test_with_masked_key_uses_stored_key(client):
    route = respx.get("http://127.0.0.1:8888/v1/models").respond(json={"data": []})
    r = client.post("/api/providers/unsloth/test", json={"api_key": "••••7777"})
    assert r.json()["ok"]
    assert route.calls.last.request.headers["authorization"] == "Bearer sk-unsloth-stored-7777"


@respx.mock
def test_openai_models_split_into_image_and_other(client):
    route = respx.get("https://api.openai.com/v1/models").respond(
        json={"data": [{"id": "gpt-4o"}, {"id": "dall-e-2"}, {"id": "gpt-image-1"}, {"id": "dall-e-3"}]}
    )
    r = client.post("/api/openai/models", json={"api_key": "••••9999"})
    assert r.json() == {"image": ["dall-e-2", "dall-e-3", "gpt-image-1"], "other": ["gpt-4o"]}
    assert route.calls.last.request.headers["authorization"] == "Bearer sk-stored-secret-9999"


@respx.mock
def test_openai_models_bad_key(client):
    respx.get("https://api.openai.com/v1/models").respond(401, json={"error": {"message": "Incorrect API key"}})
    r = client.post("/api/openai/models", json={"api_key": "sk-wrong"})
    assert r.status_code == 502 and "Incorrect API key" in r.json()["detail"]


def test_unknown_provider(client):
    assert client.post("/api/providers/midjourney/test", json={}).status_code == 404


@respx.mock
def test_status_reports_every_provider(client):
    respx.get("https://api.openai.com/v1/models").respond(json={"data": []})
    respx.get("http://127.0.0.1:7860/sdapi/v1/options").respond(404)
    respx.get("http://127.0.0.1:8188/system_stats").respond(500)
    respx.get("http://127.0.0.1:8888/v1/models").respond(401, json={"detail": "Invalid API key."})
    data = client.get("/api/status").json()
    assert data["openai"]["ok"]
    assert not data["a1111"]["ok"] and "--api" in data["a1111"]["detail"]
    assert not data["comfyui"]["ok"]
    assert not data["unsloth"]["ok"] and "Settings → API" in data["unsloth"]["detail"]


def test_foreign_host_header_blocked(config_file):
    client = TestClient(create_app(LOCAL_HOSTS), base_url="http://127.0.0.1:8765")
    assert client.get("/api/config").status_code == 200
    assert client.get("/api/config", headers={"host": "evil.example"}).status_code == 400


@pytest.fixture
def playground(client, config_file, tmp_path):
    cfg = load_config(config_file)
    cfg.active_provider = "a1111"
    cfg.output.playground_dir = str(tmp_path / "playground")
    save_config(cfg, config_file)
    return tmp_path / "playground"


@respx.mock
def test_generate_records_history_and_serves_files(client, playground, png):
    respx.post("http://127.0.0.1:7860/sdapi/v1/txt2img").respond(json={"images": [b64(png)]})

    r = client.post("/api/generate", json={"prompt": "a red fox", "size": "512x512", "seed": 3})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"].startswith("Generated 1 image(s) with Stable Diffusion WebUI") and body["width"] == 512
    [path] = body["paths"]
    assert path.startswith(str(playground)) and open(path, "rb").read() == png

    items = client.get("/api/history").json()["items"]
    assert items[0]["id"] == body["history_id"] and items[0]["source"] == "playground"
    assert (items[0]["prompt"], items[0]["seed"], items[0]["outputs"]) == ("a red fox", 3, [path])

    full = client.get(f"/api/history/{body['history_id']}/outputs/0")
    assert full.status_code == 200 and full.content == png
    thumb = client.get(f"/api/history/{body['history_id']}/outputs/0?thumb=1")
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/webp"
    # Only files recorded in the history are served.
    assert client.get(f"/api/history/{body['history_id']}/outputs/1").status_code == 404
    assert client.get(f"/api/history/{body['history_id']}/inputs/0").status_code == 404
    assert client.get("/api/history/nope/outputs/0").status_code == 404
    assert client.get(f"/api/history/{body['history_id']}/etc/0").status_code == 422


def test_generate_errors_are_readable(client, playground, tmp_path):
    r = client.post("/api/generate", json={"prompt": "x", "input_images": [str(tmp_path / "missing.png")]})
    assert r.status_code == 400 and "Input image not found" in r.json()["detail"]


def test_upload_then_use_as_input(client, config_file, png):
    r = client.post("/api/uploads", json={"name": "../../evil name.png", "data": "data:image/png;base64," + b64(png)})
    path = r.json()["path"]
    assert r.status_code == 200 and path.startswith(str(config_file.parent / "uploads")) and "evil-name.png" in path
    assert open(path, "rb").read() == png
    assert client.post("/api/uploads", json={"name": "x.png", "data": "not base64!"}).status_code == 400


def test_history_delete_and_clear(client, config_file):
    from imgswitch import history

    a, b = history.record({"prompt": "a"}), history.record({"prompt": "b"})
    assert client.delete(f"/api/history/{a['id']}").json() == {"ok": True}
    assert client.delete(f"/api/history/{a['id']}").status_code == 404
    assert client.delete("/api/history").json() == {"removed": 1}
    assert client.get("/api/history").json() == {"items": [], "total": 0}
    assert b["id"]


def test_backends_overview(client):
    with respx.mock(assert_all_mocked=False, assert_all_called=False) as mock:
        mock.route(host="api.openai.com").respond(json={"data": []})
        mock.route(host="127.0.0.1").respond(500)
        data = client.get("/api/backends").json()
    assert [b["name"] for b in data] == ["openai", "a1111", "comfyui", "unsloth"]
    openai = data[0]
    assert openai["active"] and openai["enabled"] and openai["ok"] and openai["image_input"].startswith("no")
    assert not data[1]["ok"]


def test_claude_endpoints(client, tmp_path, monkeypatch):
    monkeypatch.setenv("IMGSWITCH_CLAUDE_JSON", str(tmp_path / "c.json"))
    monkeypatch.setenv("IMGSWITCH_CLAUDE_SETTINGS", str(tmp_path / "settings.json"))
    data = client.get("/api/claude").json()
    assert data["registrations"] == [] and "imgswitch" in data["register_command"]
    assert data["permissions"]["allowed"] == {"mcp__imgswitch__generate_image": False, "mcp__imgswitch__list_backends": False}
    assert isinstance(data["servers"], list)
    assert all(client.post("/api/claude/permissions").json()["allowed"].values())


def test_meta(client):
    meta = client.get("/api/meta").json()
    assert meta["version"] and meta["history_path"].endswith("history.jsonl") and meta["app_mode"] is False
    assert "claude mcp add --scope user imgswitch" in meta["claude_command"]


def test_app_mode_allows_only_the_tauri_origin(config_file):
    app_client = TestClient(create_app(LOCAL_HOSTS, app_mode=True), base_url="http://127.0.0.1:8765")
    ok = app_client.get("/api/meta", headers={"origin": "tauri://localhost"})
    assert ok.headers["access-control-allow-origin"] == "tauri://localhost"
    other = app_client.get("/api/meta", headers={"origin": "https://evil.example"})
    assert "access-control-allow-origin" not in other.headers
    plain = TestClient(create_app(LOCAL_HOSTS), base_url="http://127.0.0.1:8765")
    assert "access-control-allow-origin" not in plain.get("/api/meta", headers={"origin": "tauri://localhost"}).headers


def test_thumbnail_of_a_picked_image(client, tmp_path):
    from .conftest import make_png

    picked = tmp_path / "big.png"
    picked.write_bytes(make_png(1200, 600))
    data_url = client.post("/api/thumbnail", json={"path": str(picked)}).json()["data_url"]
    assert data_url.startswith("data:image/webp;base64,")
    (tmp_path / "notes.txt").write_text("hi")
    assert client.post("/api/thumbnail", json={"path": str(tmp_path / "notes.txt")}).status_code == 415
    assert client.post("/api/thumbnail", json={"path": str(tmp_path / "nope.png")}).status_code == 404
