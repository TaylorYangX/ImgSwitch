"""The MCP server and its generate_image and list_backends tools."""

from __future__ import annotations

from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ImageContent, TextContent
from pydantic import Field

from imgswitch import service
from imgswitch.config import PROVIDER_NAMES, AppConfig, ProviderName, config_path, load_config
from imgswitch.output import inline_content
from imgswitch.providers import PROVIDERS

mcp = MCPServer(
    "imgswitch",
    instructions=(
        "Generates images from text prompts with the backends enabled in the ImgSwitch dashboard "
        "(an OpenAI-compatible cloud API, Stable Diffusion WebUI, ComfyUI, or Unsloth Studio). "
        "generate_image uses the dashboard's active backend unless `provider` names another. "
        "When the user asks for a specific model or backend, or a call fails, call list_backends to see which "
        "backends are available, whether each is reachable, and which model each runs, then pass the matching one "
        "as `provider`. If the requested model isn't available, say so instead of switching to another backend or "
        "model on your own. To edit an existing image (e.g. one generate_image saved earlier), pass its path in "
        "`input_images` and describe the change in the prompt; list_backends shows which backends accept input "
        "images. Images are saved in the current working directory (or the folder configured in the dashboard) and "
        "the file paths are returned."
    ),
)

PROVIDER_HELP = (
    "Backend for this one call instead of the dashboard's active one. Omit it unless the user asks for a model or "
    "backend that a different backend serves; call list_backends to see which backends are available and what each "
    "runs. " + " ".join(f"{name}: {cls.description}" for name, cls in PROVIDERS.items())
)


def _load_config() -> AppConfig:
    # Re-read on every call so dashboard changes apply without restarting the MCP client.
    try:
        return load_config()
    except (ValueError, OSError) as e:  # pydantic's ValidationError is a ValueError
        raise ToolError(
            f"Cannot read the ImgSwitch config {config_path()}: {e}\n"
            "If ImgSwitch was updated after this session started, reconnect it with /mcp."
        ) from e


@mcp.tool(structured_output=False)
async def generate_image(
    prompt: Annotated[
        str,
        Field(
            description="Text description of the image to generate, or with input_images, of the change to make",
            min_length=1,
        ),
    ],
    input_images: Annotated[
        list[str] | None,
        Field(
            description="Paths of existing images to edit or use as references, e.g. a file an earlier call saved. "
            "The first is the image being edited and the prompt describes the change; any others are references. "
            "Relative paths are inside the current working directory. Only backends that accept image input can "
            "take them (see list_backends).",
            min_length=1,
            max_length=16,
        ),
    ] = None,
    strength: Annotated[
        float | None,
        Field(
            description="With input_images on img2img backends (Stable Diffusion WebUI, ComfyUI, Unsloth img2img "
            "models): how much to change the input, 0.2 = touch-up, 1 = redraw. Default 0.6. Ignored by "
            "instruction-editing models (OpenAI gpt-image, Unsloth edit models).",
            gt=0,
            le=1,
        ),
    ] = None,
    size: Annotated[
        str | None,
        Field(
            description="Image size as WIDTHxHEIGHT, e.g. 1024x1024 or 1344x768. Defaults to the backend's setting; "
            "with input_images, to the first image's aspect ratio at that size."
        ),
    ] = None,
    negative_prompt: Annotated[
        str | None,
        Field(description="Things to avoid in the image (used by local backends; ignored by OpenAI-compatible cloud APIs)"),
    ] = None,
    n: Annotated[int, Field(description="Number of images to generate", ge=1, le=4)] = 1,
    seed: Annotated[int | None, Field(description="Random seed for reproducible output (local backends)")] = None,
    provider: Annotated[ProviderName | None, Field(description=PROVIDER_HELP)] = None,
    output_dir: Annotated[
        str | None,
        Field(
            description="Folder to save the images in, e.g. 'assets/images'. Relative paths are inside the "
            "current working directory. Defaults to the folder configured in the dashboard."
        ),
    ] = None,
    filename: Annotated[
        str | None,
        Field(
            description="File name without folder, e.g. 'hero-banner'. The extension is added automatically; "
            "with n > 1 a -1, -2, ... suffix is appended. Existing files are never overwritten."
        ),
    ] = None,
) -> list[TextContent | ImageContent]:
    """Generate one or more images from a text prompt, or edit existing images passed in input_images, and return
    the saved file paths plus previews."""
    cfg = _load_config()
    try:
        result = await service.generate(
            cfg,
            prompt=prompt,
            input_images=input_images,
            strength=strength,
            size=size,
            negative_prompt=negative_prompt,
            n=n,
            seed=seed,
            provider=provider,
            output_dir=output_dir,
            filename=filename,
            source="claude",
        )
    except service.GenerationError as e:
        raise ToolError(str(e)) from e
    lines = [result.summary()] + [f"- {p}" for p in result.paths]
    content: list[TextContent | ImageContent] = [TextContent(type="text", text="\n".join(lines))]
    if cfg.output.return_inline:
        content += [inline_content(img, cfg.output.inline_max_px) for img in result.images]
    return content


@mcp.tool(structured_output=False)
async def list_backends() -> str:
    """List the image backends enabled in the ImgSwitch dashboard: which one is active, whether each is reachable
    right now, which model it runs, and whether it accepts input images for editing. Use it to pick `provider` for
    generate_image when the user asks for a specific model or backend, or wants to edit an image."""
    cfg = _load_config()
    enabled = cfg.enabled_providers()
    backends = await service.describe_backends(cfg, enabled)

    lines = [f"Active backend: {cfg.active_provider} (used when generate_image is called without provider)", ""]
    for b in backends:
        active = " [active]" if b["active"] else ""
        state = "available" if b["ok"] else "unavailable"
        lines.append(f"- {b['name']}{active}: {b['label']}, {state}. {b['detail']}")
        lines.append(f"  {b['description']}")
        lines.append(f"  Image input: {b['image_input']}")
    disabled = [name for name in PROVIDER_NAMES if name not in enabled]
    if disabled:
        lines += ["", f"Disabled in the dashboard (can't be used): {', '.join(disabled)}"]
    return "\n".join(lines)
