import json

import httpx
import pytest
import respx

from imgswitch.config import A1111Config, ComfyUIConfig, OpenAIConfig, UnslothConfig
from imgswitch.providers import GenerationRequest, InputImage, ProviderError
from imgswitch.providers import comfyui as comfyui_mod
from imgswitch.providers.a1111 import A1111Provider
from imgswitch.providers.comfyui import ComfyUIProvider, fill_placeholders
from imgswitch.providers.openai_compat import OpenAICompatProvider, is_image_model
from imgswitch.providers.unsloth import UnslothProvider

from .conftest import b64, make_png

REQ = GenerationRequest(prompt="a red fox", width=1024, height=768)


def edit_req(*images: bytes, **kwargs) -> GenerationRequest:
    inputs = [InputImage(data=d, mime_type="image/png", filename=f"fig{i}.png", width=64, height=64) for i, d in enumerate(images)]
    return GenerationRequest(prompt="make the sky purple", width=1024, height=1024, images=inputs, **kwargs)


# --- OpenAI-compatible ---------------------------------------------------------------------------


@respx.mock
async def test_openai_b64(png):
    route = respx.post("https://api.example.com/v1/images/generations").respond(json={"data": [{"b64_json": b64(png)}]})
    provider = OpenAICompatProvider(OpenAIConfig(base_url="https://api.example.com/v1/", api_key="sk-test"))

    images = await provider.generate(REQ)

    assert images[0].data == png and images[0].mime_type == "image/png"
    sent = route.calls.last.request
    assert sent.headers["authorization"] == "Bearer sk-test"
    assert json.loads(sent.content) == {
        "model": "dall-e-3", "prompt": "a red fox", "n": 1, "size": "1024x768", "response_format": "b64_json",
    }


@respx.mock
async def test_openai_url_download_and_omit_format(png):
    route = respx.post("https://api.example.com/v1/images/generations").respond(
        json={"data": [{"url": "https://cdn.example.com/img.png"}]}
    )
    respx.get("https://cdn.example.com/img.png").respond(content=png)
    provider = OpenAICompatProvider(
        OpenAIConfig(base_url="https://api.example.com/v1", api_key="sk-test", response_format="omit")
    )

    images = await provider.generate(REQ)

    assert images[0].data == png
    assert "response_format" not in json.loads(route.calls.last.request.content)


@respx.mock
async def test_openai_gpt_image_never_sends_response_format(png):
    route = respx.post("https://api.openai.com/v1/images/generations").respond(json={"data": [{"b64_json": b64(png)}]})
    provider = OpenAICompatProvider(OpenAIConfig(api_key="sk-x", model="gpt-image-1", response_format="b64_json"))
    await provider.generate(REQ)
    assert "response_format" not in json.loads(route.calls.last.request.content)


@respx.mock
async def test_openai_list_models():
    respx.get("https://api.openai.com/v1/models").respond(
        json={"data": [{"id": "gpt-4o"}, {"id": "dall-e-3"}, {"id": "gpt-image-1"}, {"object": "model"}]}
    )
    models = await OpenAICompatProvider(OpenAIConfig(api_key="sk-x")).list_models()
    assert models == ["dall-e-3", "gpt-4o", "gpt-image-1"]


@pytest.mark.parametrize(
    "model,expected",
    [("dall-e-2", True), ("gpt-image-1", True), ("gpt-image-1-mini", True), ("flux-1-schnell", True),
     ("gpt-4o", False), ("whisper-1", False), ("text-embedding-3-small", False)],
)
def test_is_image_model(model, expected):
    assert is_image_model(model) is expected


async def test_openai_requires_key():
    with pytest.raises(ProviderError, match="No API key"):
        await OpenAICompatProvider(OpenAIConfig()).generate(REQ)


@respx.mock
async def test_openai_http_error_is_readable():
    respx.post("https://api.openai.com/v1/images/generations").respond(401, json={"error": {"message": "bad key"}})
    with pytest.raises(ProviderError, match="HTTP 401.*bad key"):
        await OpenAICompatProvider(OpenAIConfig(api_key="sk-x")).generate(REQ)


@respx.mock
async def test_openai_health():
    respx.get("https://api.openai.com/v1/models").respond(json={"data": []})
    status = await OpenAICompatProvider(OpenAIConfig(api_key="sk-x")).health_check()
    assert status.ok and status.latency_ms is not None


# --- A1111 ---------------------------------------------------------------------------------------


@respx.mock
async def test_a1111_generate_drops_grid(png):
    grid = make_png(128, 64)
    route = respx.post("http://127.0.0.1:7860/sdapi/v1/txt2img").respond(json={"images": [b64(grid), b64(png), b64(png)]})
    provider = A1111Provider(A1111Config(steps=30))

    images = await provider.generate(GenerationRequest(prompt="fox", width=512, height=512, n=2, seed=42))

    assert [i.data for i in images] == [png, png]
    body = json.loads(route.calls.last.request.content)
    assert body["steps"] == 30 and body["seed"] == 42 and body["batch_size"] == 2 and body["width"] == 512


@respx.mock
async def test_a1111_missing_api_flag():
    respx.post("http://127.0.0.1:7860/sdapi/v1/txt2img").respond(404)
    with pytest.raises(ProviderError, match="--api"):
        await A1111Provider(A1111Config()).generate(REQ)


@respx.mock
async def test_a1111_unreachable():
    respx.get("http://127.0.0.1:7860/sdapi/v1/options").mock(side_effect=httpx.ConnectError("refused"))
    status = await A1111Provider(A1111Config()).health_check()
    assert not status.ok and "not reachable" in status.detail


# --- ComfyUI -------------------------------------------------------------------------------------


def test_fill_placeholders_keeps_types():
    tpl = {"a": {"inputs": {"w": "{{width}}", "t": "{{prompt}}", "fixed": "euler", "link": ["1", 0]}}}
    out = fill_placeholders(tpl, {"width": 768, "prompt": "fox"})
    assert out == {"a": {"inputs": {"w": 768, "t": "fox", "fixed": "euler", "link": ["1", 0]}}}
    with pytest.raises(ProviderError, match="Unknown workflow placeholder"):
        fill_placeholders({"x": "{{nope}}"}, {})


@pytest.fixture
def fast_poll(monkeypatch):
    monkeypatch.setattr(comfyui_mod, "POLL_INTERVAL", 0)


@respx.mock
async def test_comfyui_full_flow(png, fast_poll):
    base = "http://127.0.0.1:8188"
    respx.get(f"{base}/object_info/CheckpointLoaderSimple").respond(
        json={"CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": [["sdxl.safetensors", "sd15.ckpt"]]}}}}
    )
    queue = respx.post(f"{base}/prompt").respond(json={"prompt_id": "p1", "number": 1})
    done = {
        "p1": {
            "status": {"status_str": "success", "completed": True, "messages": []},
            "outputs": {"7": {"images": [{"filename": "imgswitch_0001.png", "subfolder": "", "type": "output"}]}},
        }
    }
    respx.get(f"{base}/history/p1").mock(side_effect=[httpx.Response(200, json={}), httpx.Response(200, json=done)])
    view = respx.get(f"{base}/view").respond(content=png)

    images = await ComfyUIProvider(ComfyUIConfig(steps=12)).generate(REQ)

    assert images[0].data == png
    graph = json.loads(queue.calls.last.request.content)["prompt"]
    assert graph["1"]["inputs"]["ckpt_name"] == "sdxl.safetensors"  # first available
    assert graph["4"]["inputs"] == {"width": 1024, "height": 768, "batch_size": 1}
    assert graph["5"]["inputs"]["steps"] == 12 and isinstance(graph["5"]["inputs"]["seed"], int)
    assert view.calls.last.request.url.params["filename"] == "imgswitch_0001.png"


@pytest.mark.parametrize("configured,expected", [("", "checkpoint sdxl.safetensors (2 installed)"),
                                                 ("sd15.ckpt", "checkpoint sd15.ckpt (2 installed)")])
@respx.mock
async def test_comfyui_health_names_checkpoint(configured, expected):
    base = "http://127.0.0.1:8188"
    respx.get(f"{base}/system_stats").respond(json={"system": {"comfyui_version": "0.4.1"}})
    respx.get(f"{base}/object_info/CheckpointLoaderSimple").respond(
        json={"CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": [["sdxl.safetensors", "sd15.ckpt"]]}}}}
    )
    status = await ComfyUIProvider(ComfyUIConfig(checkpoint=configured)).health_check()
    assert status.ok and status.detail == f"Connected, ComfyUI 0.4.1, {expected}"


@respx.mock
async def test_comfyui_execution_error(fast_poll):
    base = "http://127.0.0.1:8188"
    respx.post(f"{base}/prompt").respond(json={"prompt_id": "p1"})
    failed = {
        "p1": {
            "status": {
                "status_str": "error",
                "completed": False,
                "messages": [["execution_error", {"node_type": "KSampler", "exception_message": "CUDA out of memory"}]],
            },
            "outputs": {},
        }
    }
    respx.get(f"{base}/history/p1").respond(json=failed)
    with pytest.raises(ProviderError, match="KSampler: CUDA out of memory"):
        await ComfyUIProvider(ComfyUIConfig(checkpoint="sd15.ckpt")).generate(REQ)


@respx.mock
async def test_comfyui_rejected_workflow():
    respx.post("http://127.0.0.1:8188/prompt").respond(
        400,
        json={
            "error": {"message": "Prompt outputs failed validation"},
            "node_errors": {"1": {"errors": [{"message": "Value not in list: ckpt_name"}]}},
        },
    )
    with pytest.raises(ProviderError, match="node 1: Value not in list"):
        await ComfyUIProvider(ComfyUIConfig(checkpoint="missing.ckpt")).generate(REQ)


# --- Unsloth Studio ------------------------------------------------------------------------------

UNSLOTH_GEN = "http://127.0.0.1:8888/v1/images/generations"
QWEN = {"id": "unsloth/Qwen-Image-2.1-Turbo-GGUF", "task": "text-to-image", "loaded": True}


def mock_unsloth_models(*models):
    return respx.get("http://127.0.0.1:8888/v1/models").respond(json={"object": "list", "data": list(models)})


@respx.mock
async def test_unsloth_b64_and_minimal_body(png):
    route = respx.post(UNSLOTH_GEN).respond(json={"created": 1, "data": [{"b64_json": b64(png)}]})
    mock_unsloth_models(QWEN)
    provider = UnslothProvider(UnslothConfig(api_key="sk-unsloth-test"))

    images = await provider.generate(REQ)

    assert images[0].data == png and images[0].mime_type == "image/png"
    sent = route.calls.last.request
    assert sent.headers["authorization"] == "Bearer sk-unsloth-test"
    assert json.loads(sent.content) == {"prompt": "a red fox", "n": 1, "size": "1024x768", "response_format": "b64_json"}
    assert provider.model_label == "unsloth/Qwen-Image-2.1-Turbo-GGUF"


@respx.mock
async def test_unsloth_sends_extras(png):
    route = respx.post(UNSLOTH_GEN).respond(json={"data": [{"b64_json": b64(png)}, {"b64_json": b64(png)}]})
    mock_unsloth_models(QWEN)
    provider = UnslothProvider(UnslothConfig(api_key="k", steps=10, guidance=2.0))

    images = await provider.generate(
        GenerationRequest(prompt="fox", width=512, height=512, negative_prompt="blurry", n=2, seed=42)
    )

    assert len(images) == 2
    assert json.loads(route.calls.last.request.content) == {
        "prompt": "fox", "n": 2, "size": "512x512", "response_format": "b64_json",
        "negative_prompt": "blurry", "seed": 42, "steps": 10, "guidance": 2.0,
    }


@pytest.mark.parametrize("base_url", ["http://127.0.0.1:8888", "http://127.0.0.1:8888/", "http://127.0.0.1:8888/v1/"])
@respx.mock
async def test_unsloth_accepts_root_or_v1_url(png, base_url):
    route = respx.post(UNSLOTH_GEN).respond(json={"data": [{"b64_json": b64(png)}]})
    mock_unsloth_models(QWEN)
    await UnslothProvider(UnslothConfig(base_url=base_url, api_key="k")).generate(REQ)
    assert route.called


@respx.mock
async def test_unsloth_without_key_sends_no_auth(png):
    route = respx.post(UNSLOTH_GEN).respond(json={"data": [{"b64_json": b64(png)}]})
    mock_unsloth_models(QWEN)
    await UnslothProvider(UnslothConfig()).generate(REQ)
    assert "authorization" not in route.calls.last.request.headers


@respx.mock
async def test_unsloth_model_lookup_failure_keeps_images(png):
    respx.post(UNSLOTH_GEN).respond(json={"data": [{"b64_json": b64(png)}]})
    respx.get("http://127.0.0.1:8888/v1/models").respond(500)
    provider = UnslothProvider(UnslothConfig(api_key="k"))

    images = await provider.generate(REQ)

    assert images[0].data == png
    assert provider.model_label == "model loaded in Studio"


@respx.mock
async def test_unsloth_no_model_loaded():
    respx.post(UNSLOTH_GEN).respond(
        503, json={"error": {"message": "No image model loaded. Load an image model first.", "type": "api_error"}}
    )
    with pytest.raises(ProviderError, match="HTTP 503: No image model loaded"):
        await UnslothProvider(UnslothConfig(api_key="k")).generate(REQ)


@respx.mock
async def test_unsloth_401_hints_at_key():
    respx.post(UNSLOTH_GEN).respond(401, json={"detail": "Invalid API key."})
    with pytest.raises(ProviderError, match=r"Invalid API key\. Create a key in Unsloth: avatar → Settings → API"):
        await UnslothProvider(UnslothConfig(api_key="sk-unsloth-revoked")).generate(REQ)


@respx.mock
async def test_unsloth_health_reports_loaded_image_model():
    chat = {"id": "unsloth/gemma-4-E4B-it-GGUF", "loaded": True}
    idle = {"id": "unsloth/FLUX.2-klein-GGUF", "task": "text-to-image", "loaded": False}
    route = mock_unsloth_models(chat, idle, QWEN)
    status = await UnslothProvider(UnslothConfig(api_key="k")).health_check()
    assert status.ok and status.detail == "Connected, image model unsloth/Qwen-Image-2.1-Turbo-GGUF"
    assert route.calls.last.request.headers["authorization"] == "Bearer k"


@respx.mock
async def test_unsloth_health_without_loaded_image_model():
    mock_unsloth_models({"id": "unsloth/gemma-4-E4B-it-GGUF", "loaded": True})
    status = await UnslothProvider(UnslothConfig(api_key="k")).health_check()
    assert status.ok and "Images tab" in status.detail


# --- Editing (input images) ----------------------------------------------------------------------


@respx.mock
async def test_openai_edit_multipart(png):
    route = respx.post("https://api.openai.com/v1/images/edits").respond(json={"data": [{"b64_json": b64(png)}]})
    provider = OpenAICompatProvider(OpenAIConfig(api_key="sk-x", model="gpt-image-1"))

    images = await provider.generate(edit_req(png, auto_size=True))

    assert images[0].data == png
    sent = route.calls.last.request
    assert sent.headers["content-type"].startswith("multipart/form-data")
    assert sent.headers["authorization"] == "Bearer sk-x"
    assert b'name="image"; filename="fig0.png"' in sent.content
    assert b'name="size"\r\n\r\nauto' in sent.content  # follows the input's shape
    assert b'name="prompt"\r\n\r\nmake the sky purple' in sent.content
    assert b"response_format" not in sent.content


@respx.mock
async def test_openai_edit_several_images_and_explicit_size(png):
    route = respx.post("https://api.openai.com/v1/images/edits").respond(json={"data": [{"b64_json": b64(png)}]})
    await OpenAICompatProvider(OpenAIConfig(api_key="sk-x", model="gpt-image-1")).generate(edit_req(png, png))
    content = route.calls.last.request.content
    assert content.count(b'name="image[]"') == 2
    assert b'name="size"\r\n\r\n1024x1024' in content


@respx.mock
async def test_openai_dalle3_cannot_edit(png):
    route = respx.post("https://api.openai.com/v1/images/edits").respond(json={"data": []})
    provider = OpenAICompatProvider(OpenAIConfig(api_key="sk-x", model="dall-e-3"))
    with pytest.raises(ProviderError, match="dall-e-3 can't edit images"):
        await provider.generate(edit_req(png))
    assert not route.called
    assert await provider.image_input() == "no (dall-e-3 can't edit images)"


@respx.mock
async def test_a1111_img2img(png):
    route = respx.post("http://127.0.0.1:7860/sdapi/v1/img2img").respond(json={"images": [b64(png)]})
    provider = A1111Provider(A1111Config())

    await provider.generate(edit_req(png))
    default = json.loads(route.calls.last.request.content)
    await provider.generate(edit_req(png, strength=0.3))
    explicit = json.loads(route.calls.last.request.content)

    assert default["init_images"] == [b64(png)] and default["denoising_strength"] == 0.6
    assert default["prompt"] == "make the sky purple" and default["width"] == 1024
    assert explicit["denoising_strength"] == 0.3


async def test_a1111_takes_one_image(png):
    with pytest.raises(ProviderError, match="takes one input image, got 2"):
        await A1111Provider(A1111Config()).generate(edit_req(png, png))


@respx.mock
async def test_comfyui_edit_uploads_and_fills_workflow(png, fast_poll):
    base = "http://127.0.0.1:8188"
    upload = respx.post(f"{base}/upload/image").respond(json={"name": "up.png", "subfolder": "imgs", "type": "input"})
    queue = respx.post(f"{base}/prompt").respond(json={"prompt_id": "p1"})
    done = {"p1": {"status": {"status_str": "success", "completed": True},
                   "outputs": {"10": {"images": [{"filename": "imgswitch-edit_0001.png", "type": "output"}]}}}}
    respx.get(f"{base}/history/p1").respond(json=done)
    respx.get(f"{base}/view").respond(content=png)

    images = await ComfyUIProvider(ComfyUIConfig(checkpoint="sd15.ckpt")).generate(edit_req(png, strength=0.45))

    assert images[0].data == png
    assert b'filename="imgswitch-' in upload.calls.last.request.content
    graph = json.loads(queue.calls.last.request.content)["prompt"]
    assert graph["4"]["inputs"]["image"] == "imgs/up.png"
    assert graph["5"]["inputs"]["width"] == 1024 and graph["8"]["inputs"]["denoise"] == 0.45


async def test_comfyui_missing_edit_workflow(png):
    provider = ComfyUIProvider(ComfyUIConfig(checkpoint="x.ckpt", edit_workflow_path="workflows/nope.json"))
    assert await provider.image_input() == "no (edit workflow workflows/nope.json not found)"
    with pytest.raises(ProviderError, match="workflow not found"):
        await provider.generate(edit_req(png))


UNSLOTH_STATUS = "http://127.0.0.1:8888/api/inference/images/status"
UNSLOTH_NATIVE = "http://127.0.0.1:8888/api/inference/images/generate"


def mock_unsloth_status(*workflows, max_images=10, loaded=True):
    return respx.get(UNSLOTH_STATUS).respond(json={
        "loaded": loaded, "repo_id": "unsloth/Qwen-Image-2.1-Turbo-GGUF", "workflows": list(workflows),
        "conditioning": {"max_condition_images": max_images},
    })


@respx.mock
async def test_unsloth_edit_workflow(png):
    mock_unsloth_status("txt2img", "reference", "edit")
    route = respx.post(UNSLOTH_NATIVE).respond(json={"images": [{"id": "abc", "url": "/api/inference/images/gallery/abc/file"}]})
    gallery = respx.get("http://127.0.0.1:8888/api/inference/images/gallery/abc/file").respond(content=png)
    provider = UnslothProvider(UnslothConfig(api_key="k", steps=8))

    images = await provider.generate(edit_req(png, make_png(32, 32), seed=7))

    assert images[0].data == png and provider.model_label == "unsloth/Qwen-Image-2.1-Turbo-GGUF"
    body = json.loads(route.calls.last.request.content)
    assert body["workflow"] == "edit" and body["init_image"] == f"data:image/png;base64,{b64(png)}"
    assert len(body["reference_images"]) == 1 and "strength" not in body
    assert (body["width"], body["height"], body["batch_size"], body["seed"], body["steps"]) == (1024, 1024, 1, 7, 8)
    assert gallery.calls.last.request.headers["authorization"] == "Bearer k"


@respx.mock
async def test_unsloth_img2img_model(png):
    mock_unsloth_status("txt2img", "img2img", "inpaint")
    route = respx.post(UNSLOTH_NATIVE).respond(json={"images": [{"url": "/api/inference/images/gallery/x/file"}]})
    respx.get("http://127.0.0.1:8888/api/inference/images/gallery/x/file").respond(content=png)

    await UnslothProvider(UnslothConfig(api_key="k")).generate(edit_req(png))

    body = json.loads(route.calls.last.request.content)
    assert "workflow" not in body and body["strength"] == 0.6


@pytest.mark.parametrize(
    "workflows,max_images,count,message",
    [
        (["txt2img"], 1, 1, "can't take an input image \\(workflows: txt2img\\)"),
        (["txt2img", "edit"], 2, 3, "takes at most 2 input image"),
    ],
)
@respx.mock
async def test_unsloth_refuses_unsupported_edits(png, workflows, max_images, count, message):
    mock_unsloth_status(*workflows, max_images=max_images)
    route = respx.post(UNSLOTH_NATIVE).respond(json={"images": []})
    with pytest.raises(ProviderError, match=message):
        await UnslothProvider(UnslothConfig(api_key="k")).generate(edit_req(*[png] * count))
    assert not route.called


@pytest.mark.parametrize(
    "workflows,loaded,expected",
    [
        (["txt2img", "edit"], True, "yes, edit by instruction with up to 10 images (unsloth/Qwen-Image-2.1-Turbo-GGUF)"),
        (["txt2img", "img2img"], True, "yes, 1 image (img2img; strength applies) (unsloth/Qwen-Image-2.1-Turbo-GGUF)"),
        (["txt2img"], True, "no (unsloth/Qwen-Image-2.1-Turbo-GGUF only does txt2img)"),
        ([], False, "load an image model in Studio first"),
    ],
)
@respx.mock
async def test_unsloth_image_input(workflows, loaded, expected):
    mock_unsloth_status(*workflows, loaded=loaded)
    assert await UnslothProvider(UnslothConfig(api_key="k")).image_input() == expected
