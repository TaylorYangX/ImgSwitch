import json

import pytest
import respx
from fastapi.testclient import TestClient

from imgswitch.config import load_config, save_config
from imgswitch.gui.app import LOCAL_HOSTS, create_app


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
