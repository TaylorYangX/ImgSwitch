import base64
import io
import json
from pathlib import Path

import respx
from mcp.client import Client
from mcp_types import Implementation, ListRootsResult, Root
from PIL import Image

from imgswitch.config import load_config, save_config
from imgswitch.server import mcp

from .conftest import b64, make_png

TXT2IMG = "http://127.0.0.1:7860/sdapi/v1/txt2img"


def use_provider(config_file, name, **output):
    cfg = load_config(config_file)
    cfg.active_provider = name
    for k, v in output.items():
        setattr(cfg.output, k, v)
    save_config(cfg, config_file)


async def test_tool_is_listed(config_file):
    async with Client(mcp) as client:
        tools = (await client.list_tools()).tools
    assert [t.name for t in tools] == ["generate_image", "list_backends"]
    props = tools[0].input_schema["properties"]
    assert {"prompt", "size", "negative_prompt", "n", "seed", "provider", "output_dir", "filename"} <= props.keys()
    assert tools[0].input_schema["required"] == ["prompt"]
    # Claude must be able to tell which backend runs which model from the schema alone.
    provider_help = props["provider"]["description"]
    assert all(f"{name}:" in provider_help for name in ("openai", "a1111", "comfyui", "unsloth"))
    assert "loaded in Studio's Images tab" in provider_help and "list_backends" in provider_help
    assert props["input_images"]["anyOf"][0]["type"] == "array" and "strength" in props
    assert "ctx" not in props  # the MCP context is injected, not a tool argument


@respx.mock
async def test_generate_returns_path_and_inline_image(config_file, png):
    use_provider(config_file, "a1111")
    respx.post(TXT2IMG).respond(json={"images": [b64(png)]})

    async with Client(mcp) as client:
        result = await client.call_tool("generate_image", {"prompt": "A red fox!", "size": "512x512"})

    assert not result.is_error
    text, image = result.content
    path = Path(text.text.splitlines()[1].removeprefix("- "))
    assert path.exists() and path.read_bytes() == png
    assert path.name.endswith("-a-red-fox-1.png")
    assert image.type == "image" and base64.b64decode(image.data) == png


@respx.mock
async def test_inline_preview_downscaled(config_file):
    use_provider(config_file, "a1111", inline_max_px=256)
    big = make_png(1024, 512)
    respx.post(TXT2IMG).respond(json={"images": [b64(big)]})

    async with Client(mcp) as client:
        result = await client.call_tool("generate_image", {"prompt": "wide"})

    preview = Image.open(io.BytesIO(base64.b64decode(result.content[1].data)))
    assert preview.size == (256, 128)


@respx.mock
async def test_inline_disabled(config_file, png):
    use_provider(config_file, "a1111", return_inline=False)
    respx.post(TXT2IMG).respond(json={"images": [b64(png)]})

    async with Client(mcp) as client:
        result = await client.call_tool("generate_image", {"prompt": "fox"})

    assert [c.type for c in result.content] == ["text"]


@respx.mock
async def test_provider_switch_takes_effect_without_restart(config_file, png):
    use_provider(config_file, "a1111")
    respx.post(TXT2IMG).respond(json={"images": [b64(png)]})
    comfy = respx.post("http://127.0.0.1:8188/prompt").respond(500)

    async with Client(mcp) as client:
        first = await client.call_tool("generate_image", {"prompt": "fox"})
        use_provider(config_file, "comfyui")  # what the dashboard does
        cfg = load_config(config_file)
        cfg.providers.comfyui.checkpoint = "x.ckpt"
        save_config(cfg, config_file)
        second = await client.call_tool("generate_image", {"prompt": "fox"})

    assert not first.is_error
    assert second.is_error and comfy.called


def saved_paths(result) -> list[Path]:
    return [Path(line.removeprefix("- ")) for line in result.content[0].text.splitlines()[1:]]


@respx.mock
async def test_default_saves_into_working_directory(config_file, png, tmp_path, monkeypatch):
    project = tmp_path / "my-project"
    project.mkdir()
    monkeypatch.chdir(project)  # Claude Code starts the server in the session's folder
    use_provider(config_file, "a1111", dir=".", return_inline=False)
    respx.post(TXT2IMG).respond(json={"images": [b64(png)]})

    async with Client(mcp) as client:
        result = await client.call_tool("generate_image", {"prompt": "fox"})

    [path] = saved_paths(result)
    assert path.parent == project and path.read_bytes() == png


@respx.mock
async def test_output_dir_and_filename(config_file, png, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    use_provider(config_file, "a1111", dir=".", return_inline=False)
    respx.post(TXT2IMG).respond(json={"images": [b64(png)]})
    elsewhere = tmp_path / "abs-target"

    async with Client(mcp) as client:
        rel = await client.call_tool("generate_image", {"prompt": "fox", "output_dir": "assets/img", "filename": "hero.png"})
        again = await client.call_tool("generate_image", {"prompt": "fox", "output_dir": "assets/img", "filename": "hero"})
        absolute = await client.call_tool(
            "generate_image", {"prompt": "fox", "output_dir": str(elsewhere), "filename": "../../etc/sneaky name"}
        )

    assert saved_paths(rel) == [tmp_path / "assets" / "img" / "hero.png"]
    assert saved_paths(again) == [tmp_path / "assets" / "img" / "hero-2.png"]  # never overwrites
    assert saved_paths(absolute) == [elsewhere / "sneaky-name.png"]  # folders stripped from filename


@respx.mock
async def test_filename_with_multiple_images(config_file, png, tmp_path):
    use_provider(config_file, "a1111", return_inline=False)
    respx.post(TXT2IMG).respond(json={"images": [b64(png), b64(png)]})
    async with Client(mcp) as client:
        result = await client.call_tool("generate_image", {"prompt": "fox", "n": 2, "filename": "logo"})
    assert [p.name for p in saved_paths(result)] == ["logo-1.png", "logo-2.png"]


@respx.mock
async def test_bad_output_dir_fails_before_generating(config_file, tmp_path):
    blocker = tmp_path / "a-file"
    blocker.write_text("not a folder")
    use_provider(config_file, "a1111")
    route = respx.post(TXT2IMG).respond(json={"images": []})

    async with Client(mcp) as client:
        result = await client.call_tool("generate_image", {"prompt": "fox", "output_dir": str(blocker / "sub")})

    assert result.is_error and "Cannot create output folder" in result.content[0].text
    assert not route.called


async def test_errors_are_tool_errors(config_file):
    async with Client(mcp) as client:
        bad_size = await client.call_tool("generate_image", {"prompt": "fox", "size": "huge"})
        no_key = await client.call_tool("generate_image", {"prompt": "fox", "provider": "openai"})
    assert bad_size.is_error and "Invalid size" in bad_size.content[0].text
    assert no_key.is_error and "No API key" in no_key.content[0].text


@respx.mock
async def test_unsloth_per_call_provider(config_file, png):
    use_provider(config_file, "a1111", return_inline=False)
    route = respx.post("http://127.0.0.1:8888/v1/images/generations").respond(json={"data": [{"b64_json": b64(png)}]})
    respx.get("http://127.0.0.1:8888/v1/models").respond(
        json={"data": [{"id": "unsloth/Qwen-Image-2.1-Turbo-GGUF", "task": "text-to-image", "loaded": True}]}
    )

    async with Client(mcp) as client:
        result = await client.call_tool(
            "generate_image", {"prompt": "fox", "size": "768x768", "seed": 42, "negative_prompt": "text", "provider": "unsloth"}
        )

    assert not result.is_error
    assert "with Unsloth Studio (unsloth/Qwen-Image-2.1-Turbo-GGUF) at 768x768" in result.content[0].text
    body = json.loads(route.calls.last.request.content)
    assert body["seed"] == 42 and body["negative_prompt"] == "text" and body["size"] == "768x768"


async def test_unreadable_config_is_a_tool_error(config_file):
    # e.g. a server started before an update, reading a config that names a newer backend
    config_file.write_text('{"active_provider": "midjourney"}')
    async with Client(mcp) as client:
        result = await client.call_tool("generate_image", {"prompt": "fox"})
    assert result.is_error
    assert "Cannot read the ImgSwitch config" in result.content[0].text and "active_provider" in result.content[0].text


@respx.mock
async def test_list_backends(config_file):
    cfg = load_config(config_file)
    cfg.active_provider = "unsloth"
    cfg.providers.unsloth.api_key = "k"
    cfg.providers.comfyui.enabled = False
    save_config(cfg, config_file)
    respx.get("http://127.0.0.1:8888/v1/models").respond(
        json={"data": [{"id": "unsloth/Qwen-Image-2.1-Turbo-GGUF", "task": "text-to-image", "loaded": True}]}
    )
    respx.get("http://127.0.0.1:8888/api/inference/images/status").respond(
        json={"loaded": True, "repo_id": "unsloth/Qwen-Image-2.1-Turbo-GGUF", "workflows": ["txt2img", "reference", "edit"],
              "conditioning": {"max_condition_images": 10}}
    )
    respx.get("http://127.0.0.1:7860/sdapi/v1/options").respond(json={"sd_model_checkpoint": "sdxl_base"})
    comfy = respx.get("http://127.0.0.1:8188/system_stats").respond(500)

    async with Client(mcp) as client:
        result = await client.call_tool("list_backends", {})

    text = result.content[0].text
    assert not result.is_error
    assert text.startswith("Active backend: unsloth")
    assert "- unsloth [active]: Unsloth Studio, available. Connected, image model unsloth/Qwen-Image-2.1-Turbo-GGUF" in text
    assert "- a1111: Stable Diffusion WebUI, available. Connected, checkpoint sdxl_base" in text
    assert "- openai: OpenAI-compatible API, unavailable. No API key configured" in text
    assert "Disabled in the ImgSwitch app (can't be used): comfyui" in text
    assert "Image input: yes, edit by instruction with up to 10 images (unsloth/Qwen-Image-2.1-Turbo-GGUF)" in text
    assert "Image input: yes, 1 image (img2img; strength applies)" in text  # a1111
    assert "Image input: no (dall-e-3 can't edit images)" in text
    assert not comfy.called  # disabled backends aren't even checked


@respx.mock
async def test_disabled_provider_is_refused(config_file):
    cfg = load_config(config_file)
    cfg.providers.a1111.enabled = False
    save_config(cfg, config_file)
    route = respx.post(TXT2IMG).respond(json={"images": []})

    async with Client(mcp) as client:
        result = await client.call_tool("generate_image", {"prompt": "fox", "provider": "a1111"})

    assert result.is_error
    assert "'a1111' backend is disabled" in result.content[0].text
    assert "Available: openai, comfyui, unsloth" in result.content[0].text
    assert not route.called


@respx.mock
async def test_edit_with_input_image(config_file, png, tmp_path):
    use_provider(config_file, "a1111", return_inline=False)
    source = tmp_path / "chart.png"
    source.write_bytes(make_png(1344, 768))
    route = respx.post("http://127.0.0.1:7860/sdapi/v1/img2img").respond(json={"images": [b64(png)]})

    async with Client(mcp) as client:
        result = await client.call_tool(
            "generate_image", {"prompt": "white background", "input_images": [str(source)], "strength": 0.4}
        )

    assert not result.is_error
    text = result.content[0].text
    assert "from 1 input image(s)" in text and "at 1344x768" in text  # size follows the input's shape
    body = json.loads(route.calls.last.request.content)
    assert body["init_images"] == [b64(source.read_bytes())] and body["denoising_strength"] == 0.4
    assert Path(text.splitlines()[1].removeprefix("- ")).read_bytes() == png


@respx.mock
async def test_missing_input_image_fails_before_generating(config_file, tmp_path):
    use_provider(config_file, "a1111")
    route = respx.post("http://127.0.0.1:7860/sdapi/v1/img2img").respond(json={"images": []})

    async with Client(mcp) as client:
        result = await client.call_tool("generate_image", {"prompt": "x", "input_images": [str(tmp_path / "gone.png")]})

    assert result.is_error and "Input image not found" in result.content[0].text
    assert not route.called


@respx.mock
async def test_tool_calls_are_recorded_in_history(config_file, png):
    from imgswitch import history

    use_provider(config_file, "a1111", return_inline=False)
    respx.post(TXT2IMG).respond(json={"images": [b64(png)]})

    async with Client(mcp, client_info=Implementation(name="claude-code", version="2.1.310")) as client:
        result = await client.call_tool("generate_image", {"prompt": "a lighthouse", "seed": 9})

    [entry] = history.list_entries()[0]
    assert (entry["source"], entry["backend"], entry["prompt"], entry["seed"]) == ("claude", "a1111", "a lighthouse", 9)
    assert entry["client"] == "claude-code 2.1.310"
    assert entry["outputs"] == [result.content[0].text.splitlines()[1].removeprefix("- ")]
    assert entry["cwd"] == str(Path.cwd())


@respx.mock
async def test_other_agents_are_recorded_by_name(config_file, png):
    from imgswitch import history

    use_provider(config_file, "a1111", return_inline=False)
    respx.post(TXT2IMG).respond(json={"images": [b64(png)]})
    async with Client(mcp, client_info=Implementation(name="codex-mcp-client", version="0.130.0")) as client:
        await client.call_tool("generate_image", {"prompt": "x"})
    assert history.list_entries()[0][0]["source"] == "codex"


def _roots(*paths):
    async def list_roots(context):
        return ListRootsResult(roots=[Root(uri=p.as_uri()) for p in paths])

    return list_roots


@respx.mock
async def test_relative_output_goes_to_the_agents_workspace(config_file, png, tmp_path, monkeypatch):
    """An agent that runs the server outside the project (e.g. one server for many workspaces) names its root.

    Only agents on the initialize handshake can be asked for roots; 2026-07-28 has no back-channel.
    """
    use_provider(config_file, "a1111", dir=".", return_inline=False)
    respx.post(TXT2IMG).respond(json={"images": [b64(png)]})
    elsewhere, workspace = tmp_path / "server-cwd", tmp_path / "my project"
    elsewhere.mkdir()
    workspace.mkdir()
    monkeypatch.chdir(elsewhere)

    async with Client(mcp, list_roots_callback=_roots(workspace), mode="legacy") as client:
        legacy = await client.call_tool("generate_image", {"prompt": "fox", "output_dir": "figures", "filename": "fox"})
    async with Client(mcp, list_roots_callback=_roots(workspace)) as client:  # newest protocol: no roots
        modern = await client.call_tool("generate_image", {"prompt": "fox", "output_dir": "figures", "filename": "fox"})

    assert not legacy.is_error and not modern.is_error, modern.content[0].text
    assert saved_paths(legacy) == [workspace / "figures" / "fox.png"]
    assert saved_paths(modern) == [elsewhere / "figures" / "fox.png"]


@respx.mock
async def test_cwd_inside_a_root_is_kept(config_file, png, tmp_path, monkeypatch):
    use_provider(config_file, "a1111", dir=".", return_inline=False)
    respx.post(TXT2IMG).respond(json={"images": [b64(png)]})
    project = tmp_path / "project"
    (project / "sub").mkdir(parents=True)
    monkeypatch.chdir(project / "sub")

    async with Client(mcp, list_roots_callback=_roots(project), mode="legacy") as client:
        result = await client.call_tool("generate_image", {"prompt": "fox", "filename": "fox"})

    assert saved_paths(result) == [project / "sub" / "fox.png"]
