# ImgSwitch

ImgSwitch gives Claude Code a `generate_image` tool through the [Model Context Protocol](https://modelcontextprotocol.io) (MCP). A local web dashboard lets you choose which image backend does the work and change its settings without touching Claude Code again.

| Backend | Kind | What ImgSwitch calls |
|---|---|---|
| **OpenAI-compatible** | Cloud | `POST {base_url}/images/generations`: OpenAI (DALL·E 2/3, gpt-image models) or any proxy that speaks the same API. Edits use `/images/edits`. |
| **Stable Diffusion WebUI** (AUTOMATIC1111 / Forge) | Local | `POST /sdapi/v1/txt2img`; edits use `/sdapi/v1/img2img` |
| **ComfyUI** | Local | `POST /prompt`, then `/history` and `/view`, driven by a workflow JSON template; edits upload the image and use an img2img template |
| **Unsloth Studio** (Unsloth Desktop / `unsloth studio`) | Local | `POST /v1/images/generations` with whichever image model is loaded in Studio (FLUX, Qwen-Image, Z-Image, SDXL, …); edits use Studio's own `/api/inference/images/generate` |

Besides generating from a text prompt, the tool can [edit an existing image](#editing-images), such as one it made earlier. Images are saved in the folder you're running Claude Code in, or wherever you ask Claude to put them. The tool returns the saved file path plus an inline preview, so Claude can see what it made.

---

## Contents

1. [How it works](#how-it-works)
2. [Install](#install)
3. [Configure a backend (dashboard)](#configure-a-backend-dashboard)
4. [Connect to Claude Code](#connect-to-claude-code)
5. [Using it in Claude Code](#using-it-in-claude-code)
6. [Troubleshooting](#troubleshooting)
7. [Configuration reference](#configuration-reference)
8. [ComfyUI workflows](#comfyui-workflows)
9. [Persistent HTTP mode](#persistent-http-mode-optional)
10. [Development](#development)

---

## How it works

ImgSwitch runs in two separate modes that share one file, `config.json`:

```
  you ──► python main.py --gui ──► dashboard (http://127.0.0.1:8765)
                                        │ writes
                                        ▼
                                   config.json
                                        ▲ reads on every call
                                        │
  Claude Code ──spawns──► python main.py ──► OpenAI-compatible API / A1111 / ComfyUI / Unsloth
  (running in          (stdio, started in       │
   ~/my-project)        ~/my-project)           ▼
                                       ~/my-project/<timestamp>-<prompt>.png
```

- **`python main.py`** (no arguments) is the MCP server. You never run it yourself: Claude Code starts it as a subprocess and talks to it over stdin/stdout. It opens no port and starts no web server.
- **`python main.py --gui`** is the dashboard. Run it only when you want to change settings, and close it when you're done. Claude Code doesn't need it running.
- The MCP server re-reads `config.json` on **every** tool call. A backend switched in the dashboard applies to Claude's next image, with no restart of Claude Code.
- Claude Code starts the server **in the folder your session is running in**, and ImgSwitch saves images relative to that folder. That's the folder you launched `claude` from, or the workspace folder open in VS Code. Images from a session in `~/my-paper` go to `~/my-paper`, and images from `~/website` go to `~/website`. `config.json` and the ComfyUI workflows always stay in the ImgSwitch folder.

---

## Install

You need Python 3.10+ and [uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
cd ImgSwitch          # the folder that contains main.py
uv sync               # creates .venv/ and installs dependencies
```

Confirm it works:

```bash
uv run pytest -q      # all tests should pass
```

Without uv: `python3 -m venv .venv && .venv/bin/pip install "mcp>=2.3,<3" httpx pydantic pillow fastapi uvicorn`. The commands below assume the interpreter is at `.venv/bin/python` either way.

---

## Configure a backend (dashboard)

```bash
uv run main.py --gui
```

Open **http://127.0.0.1:8765**. You'll see:

- **Backend cards.** Click a card to make that backend active; Claude uses it by default. The dot shows whether it's reachable (green = OK, red = problem, grey = checking), and hovering shows the detail.
- **Available to Claude** (the tick box on each card) decides which backends Claude may use at all. Untick a backend you don't want used, e.g. a paid cloud API, or a local server you rarely start. Claude won't see it in `list_backends`, and a call that names it is refused. The active backend can't be unticked; clicking an unticked card ticks it again and makes it active. See [Choosing a backend](#choosing-a-backend).
- **Settings tabs** for each backend, plus **Output**. Every change saves to `config.json` immediately, and "✓ Saved" in the top right confirms it. An invalid value shows "Not saved" with the reason, and the file keeps its last valid state.
- **Test connection** checks the values currently on screen, even unsaved ones.
- **Connect to Claude Code** shows the exact registration command for your machine, with real paths filled in.

The page loads Vue and Tailwind from a CDN, so the browser needs internet access.

### OpenAI-compatible (cloud)

| Field | Notes |
|---|---|
| API base URL | `https://api.openai.com/v1` for OpenAI. For a proxy, use its base URL, the part before `/images/generations`. |
| API key | Stored in `config.json` and shown masked once saved. You can supply it through an environment variable instead (see [below](#api-key-via-environment-variable)). |
| Model | Once a key is entered, the dropdown loads every image model that key can use. It asks the API's `GET /models` and keeps the image models by name. Click **Refresh** to reload. Pick **Custom model name…** to type an id the API doesn't list. |
| Response format | `b64_json` (default) returns image bytes directly; `url` returns a link that ImgSwitch downloads; `omit` leaves the field out for proxies that reject it. gpt-image models always return base64, so this field is never sent for them. |
| Default size | The presets change with the model: DALL·E 2 takes 256/512/1024 squares, DALL·E 3 takes 1024×1024, 1792×1024 and 1024×1792, and gpt-image takes 1024×1024, 1536×1024 and 1024×1536. If you switch to a model that can't do your saved size, it resets to 1024×1024. |

### Stable Diffusion WebUI (local)

Start the WebUI with its API enabled. Without `--api`, the endpoint ImgSwitch uses doesn't exist:

```bash
./webui.sh --api            # Linux/macOS  (Windows: add --api to COMMANDLINE_ARGS in webui-user.bat)
```

Then set the URL (default `http://127.0.0.1:7860`), sampling steps, CFG scale, sampler and default size. The size presets are aspect ratios computed for a base resolution: 512 for SD 1.5, 768 for SD 2.x, 1024 for SDXL/Flux.

### ComfyUI (local)

Set the URL (default `http://127.0.0.1:8188`). Click **Load list** to fill the checkpoint dropdown from your ComfyUI install, or leave it on *First available checkpoint*. The workflow used is `workflows/comfyui_txt2img.json` unless you point it at your own (see [ComfyUI workflows](#comfyui-workflows)).

### Unsloth Studio (local)

[Unsloth Studio](https://unsloth.ai/docs/basics/api) (the Unsloth Desktop app, or `unsloth studio` from the CLI) serves an OpenAI-compatible API, including `POST /v1/images/generations`. To use it:

1. Start Unsloth Desktop, or run `unsloth studio -H 127.0.0.1 -p 8888`.
2. Open **Images** in Studio's sidebar and load an image model. Studio generates with whichever model is loaded there; ImgSwitch doesn't pick one.
3. Create an API key: click your avatar (bottom left) → **Settings** → **API**. Copy the `sk-unsloth-…` value right away, because Studio shows it only once.

| Field | Notes |
|---|---|
| Unsloth Studio URL | Default `http://127.0.0.1:8888`. The server root or the `…/v1` URL both work. |
| API key | The `sk-unsloth-…` key. Stored in `config.json` and shown masked once saved. |
| Sampling steps / Guidance | Leave empty to use the loaded model's defaults. Some models work best at guidance 0. |
| Default size | Each side must be 256–2048 and a multiple of 16; all presets qualify. |

`seed`, `negative_prompt`, steps and guidance need a Studio build from 2026-10-20 or later; older builds silently ignore them. Run `unsloth studio update` to upgrade.

### Output

| Field | Notes |
|---|---|
| Output folder | Default output location. Relative paths are inside the folder Claude Code is working in: `.` (default) saves into that folder itself, and `images` saves into an `images/` subfolder of it. Set an absolute path such as `~/Pictures/ai` to collect every image in one place, whatever project you're in. Claude can override this per request (see [`output_dir`](#using-it-in-claude-code)). |
| Return images inline | When on, Claude receives a preview of each image. Turn it off to return file paths only, which uses less of Claude's context. |
| Inline preview max edge | Larger images are downscaled for the preview only; the file on disk keeps full size. |

---

## Connect to Claude Code

### Step 1: Register the server

Run this **from inside the ImgSwitch folder**. `$(pwd)` fills in the real absolute path, so there is nothing to edit:

```bash
cd ImgSwitch
claude mcp add --scope user imgswitch -- "$(pwd)/.venv/bin/python" "$(pwd)/main.py"
```

Expected output:

```
Added stdio MCP server imgswitch with command: /home/you/.../ImgSwitch/.venv/bin/python /home/you/.../ImgSwitch/main.py to user config
```

Notes:

- **Use absolute paths.** Claude Code starts the server from whatever project you have open, so a relative path like `main.py` won't be found. The dashboard's *Connect to Claude Code* box shows the same command with your paths filled in.
- **Don't paste placeholder paths** such as `/path/to/ImgSwitch`. Claude Code accepts any path when you add a server and only fails when it tries to start it (see [ENOENT](#failed-to-connect)).
- **Everything after `--`** is the command Claude Code runs. Options for `claude mcp add` itself, such as `--scope` and `-e`, go **before** the `--`. Put `-e` *after* the server name: `-e` accepts several values, so `-e KEY=value imgswitch` treats `imgswitch` as another variable and fails with `missing required argument 'commandOrUrl'`.
- **Using uv instead** of the venv interpreter also works, as long as `uv` is on the `PATH` Claude Code sees:

  ```bash
  claude mcp add --scope user imgswitch -- uv run --directory "$(pwd)" main.py
  ```

### Step 2: Choose a scope (and why "already exists" happens)

`--scope` controls where the registration is stored and which projects can see it:

| Scope | Stored in | Visible in | Use when |
|---|---|---|---|
| `local` (the default if you omit `--scope`) | `~/.claude.json`, under the folder you ran the command in | **Only that one folder** | You want the tool in a single project |
| `user` | `~/.claude.json`, global section | **Every project** on this machine | Recommended for ImgSwitch |
| `project` | `.mcp.json` in the current repo | Everyone who clones that repo | Rarely right here, because the paths are machine-specific |

Two things trip people up:

1. **A `local` registration only exists in the folder where you added it.** If you ran `claude mcp add imgswitch …` (no `--scope`) inside, say, `~/research/my-paper`, then Claude Code sessions in any other folder won't have the tool.
2. **Names are unique per scope.** Running `claude mcp add imgswitch …` again in the same folder, even with a corrected path, fails with:

   ```
   MCP server imgswitch already exists in local config
   ```

   Claude Code won't overwrite the entry. Remove it and add it again (see [Fixing a broken registration](#fixing-a-broken-registration)).

If the same name exists in more than one scope, **local beats project, and project beats user**. A broken local entry therefore hides a working user-scope entry in that folder. That's why you remove the old one first.

### Step 3: Verify

```bash
claude mcp get imgswitch
```

A working setup shows:

```
imgswitch:
  Scope: User config …
  Status: ✔ Connected
  Type: stdio
  Command: /home/you/.../ImgSwitch/.venv/bin/python
  Args: /home/you/.../ImgSwitch/main.py
```

`claude mcp list` shows the status of every registered server. Run both commands **from the folder you'll use Claude Code in**, because local-scope entries depend on the current directory.

### Step 4: Start a new session

Claude Code connects to MCP servers when a session starts. A session that was already open before you registered (or fixed) the server won't see the change:

- **Terminal:** exit and run `claude` again, or type `/mcp` and reconnect `imgswitch`.
- **VS Code extension:** open a new conversation, or reload the window (*Developer: Reload Window*).

Inside a session, `/mcp` lists the connected servers. `imgswitch` should show as connected, with two tools, `generate_image` and `list_backends`.

The same applies after ImgSwitch's code is updated: sessions that were already open keep running the old version until you reconnect them (see [A new backend is missing after updating ImgSwitch](#a-new-backend-is-missing-after-updating-imgswitch)).

### Fixing a broken registration

The steps below are for when Claude Code reports *failed to connect*, or `claude mcp add` says *already exists*.

```bash
# 1. Find where the broken entry lives. Run this in the folder where you see the error.
claude mcp get imgswitch          # shows "Scope:" and the command it tries to run

# 2. Remove it from that scope.
claude mcp remove imgswitch -s local      # or -s user / -s project, matching the Scope line

# 3. Re-add with real absolute paths, from inside the ImgSwitch folder.
cd /path/to/ImgSwitch
claude mcp add --scope user imgswitch -- "$(pwd)/.venv/bin/python" "$(pwd)/main.py"

# 4. Back in your working folder, check that it connects.
cd /path/to/your/project
claude mcp get imgswitch          # expect: Status: ✔ Connected
```

Then start a new Claude Code session (step 4 above).

### Allow the tool without a prompt (optional)

The first time Claude calls `generate_image` or `list_backends`, Claude Code asks for permission. To allow them permanently, choose the *don't ask again* option at that prompt, or add this to `~/.claude/settings.json`:

```json
{
  "permissions": {
    "allow": ["mcp__imgswitch__generate_image", "mcp__imgswitch__list_backends"]
  }
}
```

---

## Using it in Claude Code

Just ask:

> Generate an image of a red fox in fresh snow, 1792x1024.

> Make 2 variations of a minimalist logo for a coffee shop called "Ember", using the local Stable Diffusion backend.

> Create a 768x1344 poster background, cyberpunk city at night, avoid text and watermarks.

> Draw a hero banner for the landing page and save it as `public/images/hero`.

Claude fills in the tool parameters from your request:

| Parameter | Type | Description |
|---|---|---|
| `prompt` | string, required | What to draw, or with `input_images`, the change to make. |
| `input_images` | list of paths | Images to edit or use as references; the first is the one being edited. See [Editing images](#editing-images). |
| `strength` | 0–1 | With `input_images` on img2img backends: how much to change the input (default 0.6). |
| `size` | `"WIDTHxHEIGHT"` | e.g. `1024x1024`, `1344x768`. Defaults to the backend's configured size, or with `input_images` to the first image's aspect ratio at that size. Each side must be 64–4096; cloud models accept only their own sizes (see above). |
| `negative_prompt` | string | Things to avoid. Used by A1111, ComfyUI and Unsloth Studio (on models that support it); ignored by OpenAI-compatible APIs. |
| `n` | 1–4 | Number of images. DALL·E 3 only supports `n = 1`. |
| `seed` | integer | Reproducible results on local backends. |
| `provider` | `openai` / `a1111` / `comfyui` / `unsloth` | Use this backend for this one call instead of the active one. It must be ticked *Available to Claude*. The tool's description tells Claude what each backend is and where its model comes from. |
| `output_dir` | path | Folder to save in, e.g. `assets/img`. Relative paths are inside the folder Claude Code is working in, and the folder is created if needed. Defaults to the dashboard's output folder. |
| `filename` | string | File name without extension, e.g. `hero`. With `n > 1` it becomes `hero-1`, `hero-2`, …. Defaults to `<timestamp>-<prompt>-<n>`. |

The tool returns text like this, plus a preview for each image when inline previews are on:

```
Generated 1 image(s) with OpenAI-compatible API (dall-e-3) at 1792x1024:
- /home/you/my-project/20261021-101500-a-red-fox-in-fresh-snow-1.png
```

Where files go:

- **By default**, into the folder Claude Code is working in (the dashboard's *Output folder*, `.`).
- **When you say where**, e.g. "save it to `docs/figures`" or "call it `logo`", Claude passes `output_dir` / `filename` and the file goes exactly there.
- **Existing files are never overwritten.** If `hero.png` exists, the new image is saved as `hero-2.png`.
- The folder is created **before** the image is generated, so a bad path fails immediately instead of after a paid cloud generation.

### Choosing a backend

Each backend runs a different model: OpenAI uses the model set in the dashboard, Unsloth Studio uses whichever model is loaded in its Images tab, and so on. ImgSwitch picks one like this:

1. **Normally, the active backend.** A request that doesn't name a model or backend goes to the backend that's active in the dashboard.
2. **A named model, through `list_backends`.** If you ask for a model or backend, e.g. "use Qwen-Image-2.1", Claude calls `list_backends` and passes the backend that runs it as `provider`.
3. **Never an automatic switch.** If the model you asked for isn't available, Claude tells you instead of falling back to another backend, so a request for a local model never ends up on a paid cloud API.

Only backends ticked *Available to Claude* in the dashboard take part. `list_backends` checks each one and returns text like this:

```
Active backend: unsloth (used when generate_image is called without provider)

- openai: OpenAI-compatible API, available. Authenticated, model gpt-image-1
  Cloud API: OpenAI or an OpenAI-compatible proxy. Uses the model set in the dashboard. Usually billed per image.
  Image input: yes, up to 16 images (gpt-image-1 edits by instruction)
- comfyui: ComfyUI, unavailable. ComfyUI not reachable at http://127.0.0.1:8188. Is it running?
  Local ComfyUI. Runs the dashboard's workflow with the checkpoint chosen there.
  Image input: yes, 1 image via workflows/comfyui_img2img.json (img2img; strength applies)
- unsloth [active]: Unsloth Studio, available. Connected, image model unsloth/Qwen-Image-2.1-Turbo-GGUF
  Local Unsloth Studio. Uses whichever image model is loaded in Studio's Images tab (e.g. Qwen-Image, FLUX, Z-Image, SDXL).
  Image input: yes, edit by instruction with up to 10 images (unsloth/Qwen-Image-2.1-Turbo-GGUF)

Disabled in the dashboard (can't be used): a1111
```

You can also just ask Claude "which image backends are available?".

### Editing images

To change an image instead of starting from scratch, refer to the file. It can be one the tool just made, or any image in your project:

> Make the background of `figures/overview.png` white and enlarge the labels.

> Take the fox image you just made and turn it into a night scene with falling snow.

> Combine `logo.png` and `mascot.png` into one banner, mascot on the left.

Claude passes the files as `input_images`, and the prompt describes the change. The result is saved as a new file; the original is never touched. Unless you give a size, the result keeps the first image's aspect ratio at the backend's default resolution.

Backends edit in two different ways, and `list_backends` shows what each accepts:

| Backend | How it edits | Input images |
|---|---|---|
| OpenAI-compatible | **By instruction.** gpt-image models follow the prompt ("make it white") and keep the rest. | gpt-image: up to 16 · dall-e-2: 1 square PNG · dall-e-3: can't edit |
| Unsloth Studio | **By instruction** on edit models (Qwen-Image-2.1, Qwen-Image-Edit, FLUX.1 Kontext, …); **img2img** on models that only offer that. It depends on the model loaded in Studio. | edit models: as many as the model allows (Qwen-Image-2.1: 10) · img2img: 1 |
| Stable Diffusion WebUI | **img2img**: redraws the whole image guided by the prompt | 1 |
| ComfyUI | **img2img** through the edit workflow (see [ComfyUI workflows](#comfyui-workflows)) | 1 |

For img2img backends, `strength` controls how far the result may move from the input: around 0.2–0.4 for touch-ups, 0.6 (the default) for clear changes, 1 to redraw freely. Instruction editing ignores it. To change only part of an image, say which part in the prompt. Masks aren't supported yet.

---

## Troubleshooting

### Failed to connect

Run `claude mcp get imgswitch`. The `Issue:` line usually names the cause:

| Issue / symptom | Cause | Fix |
|---|---|---|
| `ENOENT: no such file or directory, posix_spawn '/path/to/ImgSwitch/.venv/bin/python'` | The registered path doesn't exist, usually because a placeholder was pasted or the folder was moved | [Remove and re-add](#fixing-a-broken-registration) with `$(pwd)` paths |
| `ENOENT … posix_spawn 'uv'` | `uv` isn't on the PATH Claude Code uses | Register with the `.venv/bin/python` form instead |
| Connection closed right after starting | The server crashed on startup. Most often dependencies are missing because `uv sync` wasn't run, or the system Python was registered instead of `.venv/bin/python` | Run `uv sync`, then run the registered command by hand (below) to see the traceback |
| Shows connected, but the tool isn't listed in an open session | The session started before you registered it | Start a new session, or `/mcp` → reconnect |
| Works in one folder, missing in another | It's registered in `local` scope | Remove it and re-add with `--scope user` |

**Run the server by hand.** Paste the exact `Command` and `Args` from `claude mcp get imgswitch`:

```bash
/home/you/.../ImgSwitch/.venv/bin/python /home/you/.../ImgSwitch/main.py
```

A healthy server prints nothing and waits for input; press Ctrl+C to stop it. A Python traceback means it can't start. ImgSwitch logs only to stderr, because stdout is reserved for the protocol.

**Read Claude Code's MCP logs.** Each start attempt is logged to:

```
~/.cache/claude-cli-nodejs/<your-project-path-with-slashes-as-dashes>/mcp-logs-imgswitch/
```

For example, a session in `/home/you/research/paper` logs to `~/.cache/claude-cli-nodejs/-home-you-research-paper/mcp-logs-imgswitch/`. You can also start Claude Code with `claude --debug` to see MCP errors live.

### WSL and Windows

ImgSwitch's paths are Linux paths, so Claude Code must also run **inside WSL**. Inside WSL means the `claude` CLI in a WSL terminal, or VS Code connected to WSL (bottom-left corner shows *WSL*). A Claude Code running natively on Windows can't execute `/home/...` paths. If you must use it from Windows, wrap the command: `claude mcp add --scope user imgswitch -- wsl.exe /home/you/.../ImgSwitch/.venv/bin/python /home/you/.../ImgSwitch/main.py`.

### The tool runs but generation fails

The error comes back to Claude word for word, e.g. *"Stable Diffusion WebUI not reachable at http://127.0.0.1:7860. Is it running?"*. Common causes:

| Message | Fix |
|---|---|
| `No API key configured` | Enter the key in the dashboard or [set an environment variable](#api-key-via-environment-variable) |
| `Input image not found: …` | Relative paths are inside the folder Claude Code runs in; use the absolute path Claude's earlier reply showed |
| `dall-e-3 can't edit images` | Choose a gpt-image model (or dall-e-2) in the dashboard, or edit on another backend |
| `… in Unsloth Studio can't take an input image (workflows: txt2img)` | The loaded model only generates from text; load an edit model (e.g. Qwen-Image-2.1, Qwen-Image-Edit, FLUX.1 Kontext) in Studio's Images tab |
| `… takes one input image, got 2` | A1111 and ComfyUI edit one image at a time; use an instruction-editing backend to combine several |
| `The 'x' backend is disabled in the ImgSwitch dashboard` | Tick *Available to Claude* on that backend's card, or ask for a model one of the available backends runs |
| `HTTP 401: Incorrect API key` | Wrong or revoked key; use **Test connection** to check it |
| `HTTP 400 … size` | That model doesn't support that size; pick one of its presets |
| `… not found … --api` | Restart the WebUI with `--api` |
| `ComfyUI rejected the workflow: … node 1: Value not in list: ckpt_name` | The checkpoint name doesn't exist in ComfyUI; use **Load list** and pick one |
| `ComfyUI did not finish within 300s` | First runs load models slowly; raise **Timeout** in the dashboard |
| `Unsloth Studio returned HTTP 503: No image model loaded` | Load an image model in Studio's **Images** tab |
| `Unsloth Studio returned HTTP 401 … Settings → API` | Missing or revoked key; create a new one in Studio and paste it into the dashboard |
| Unsloth ignores seed, steps or size | Studio is older than 2026-10-20; run `unsloth studio update` |
| `Unsloth Studio not reachable` from WSL | Unsloth Desktop runs on Windows, so `127.0.0.1` in WSL doesn't reach it. Turn on WSL mirrored networking, or start Studio with `-H 0.0.0.0` and use the Windows host's IP |

For slow local generation, Claude Code may also stop waiting before ImgSwitch does. Raise its limits by starting Claude Code with `MCP_TOOL_TIMEOUT=600000 claude` (tool calls, in ms) and `MCP_TIMEOUT=30000` (server startup, in ms).

### Images aren't where I expected

- Check the path in Claude's reply: it is always absolute.
- Relative output folders resolve against the folder the **Claude Code session** runs in. If you started `claude` in your home folder, images land there. Start Claude Code in the project folder, or set an absolute *Output folder* in the dashboard.
- In [persistent HTTP mode](#persistent-http-mode-optional) the server isn't started per project, so relative paths resolve against wherever you started the HTTP server. Use an absolute output folder there, or ask Claude to pass an absolute `output_dir`.

### Dashboard changes don't take effect

The server reads its config from `config.json` next to `main.py`, or from `IMGSWITCH_CONFIG` if that's set. If you registered the server with `-e IMGSWITCH_CONFIG=…`, start the dashboard with the same variable. The dashboard's footer shows which file it's editing.

### A new backend is missing after updating ImgSwitch

**Symptom.** After ImgSwitch's code is updated (for example, when the Unsloth Studio backend was added), it works in a new session but not in sessions that were already open:

- The tool's `provider` still lists only the old backends, e.g. `openai / a1111 / comfyui` without `unsloth`, or a newer tool such as `list_backends` is missing.
- With the new backend active in the dashboard, every call in those sessions fails instantly. Older versions just say *"Error executing tool generate_image"*, and the MCP log shows *"failed after 0s"*. Current versions say *"Cannot read the ImgSwitch config … reconnect it with /mcp"*.

**Cause.** Each Claude Code session starts its own ImgSwitch server when the session opens, and keeps it running. That server re-reads `config.json` on every call, so dashboard changes apply right away. But it loads the code, and gives Claude the list of backends `provider` accepts, only once, when it starts. A session opened before the update keeps the old code. That code rejects a config whose active backend it doesn't know. It isn't a registration problem: with `--scope user`, every folder runs the same `main.py`.

**Fix.** In every session that was open before the update:

- **Terminal or VS Code:** type `/mcp`, select **imgswitch**, and choose **Reconnect**. Alternatively, start a new session, or reload the VS Code window.
- **Dashboard:** if it's running, restart it too (Ctrl+C, then `uv run main.py --gui`). Its connection tests also use the code loaded at its start.
- **[Persistent HTTP mode](#persistent-http-mode-optional):** restart the HTTP server.

New sessions pick up the update automatically.

**Find the stale servers.** If you're unsure which sessions still run old code, list the server processes with their start times. Then compare those times with when ImgSwitch was updated:

```bash
ps -eo pid,lstart,args | grep "[m]ain.py"   # one line per running server, with its start time
readlink /proc/<pid>/cwd                     # the folder that server's session is working in
```

---

## Configuration reference

`config.json` is created with defaults on first run. `config.example.json` shows every field. The dashboard is the easiest way to edit it, but hand edits work too and are validated when read.

```jsonc
{
  "active_provider": "openai",              // "openai" | "a1111" | "comfyui" | "unsloth"
  "output": {
    "dir": ".",                             // relative to the folder Claude Code runs in, or absolute
    "return_inline": true,                  // send previews to Claude
    "inline_max_px": 1024                   // preview long edge, 128–4096
  },
  "providers": {
    "openai": {
      "base_url": "https://api.openai.com/v1",
      "api_key": "",
      "model": "dall-e-3",
      "response_format": "b64_json",        // "b64_json" | "url" | "omit"
      "enabled": true,                      // "Available to Claude"; every backend has it, and the active one must be true
      "default_size": "1024x1024",
      "timeout": 120                        // seconds
    },
    "a1111": {
      "base_url": "http://127.0.0.1:7860",
      "steps": 25, "cfg_scale": 7.0, "sampler_name": "DPM++ 2M",
      "default_size": "1024x1024", "timeout": 300
    },
    "comfyui": {
      "base_url": "http://127.0.0.1:8188",
      "workflow_path": "workflows/comfyui_txt2img.json",
      "edit_workflow_path": "workflows/comfyui_img2img.json",   // used for edits (input images)
      "checkpoint": "",                     // empty = first checkpoint ComfyUI reports
      "steps": 25, "cfg_scale": 7.0,
      "default_size": "1024x1024", "timeout": 300
    },
    "unsloth": {
      "base_url": "http://127.0.0.1:8888",
      "api_key": "",                        // sk-unsloth-… from Studio's Settings → API
      "steps": null, "guidance": null,      // null = the loaded model's defaults
      "default_size": "1024x1024", "timeout": 300
    }
  }
}
```

### API key via environment variable

If `IMGSWITCH_OPENAI_API_KEY` or `OPENAI_API_KEY` is set in the server's environment, it overrides the key in `config.json`. It is never written to the file. Pass it when registering:

```bash
claude mcp add imgswitch --scope user -e OPENAI_API_KEY=sk-... -- "$(pwd)/.venv/bin/python" "$(pwd)/main.py"
```

### Other environment variables

| Variable | Effect |
|---|---|
| `IMGSWITCH_CONFIG` | Path to the config file (default: `config.json` next to `main.py`) |

### Security notes

- `config.json` holds your API keys in plain text. ImgSwitch writes it with mode `600` (owner-only), and `.gitignore` excludes it. Keep it out of version control.
- The dashboard binds to `127.0.0.1` only and rejects requests whose `Host` header isn't local, which blocks DNS-rebinding attacks from web pages. Use `--host 0.0.0.0` only on a trusted network, since anyone who can reach the port can read and change your settings.

---

## ComfyUI workflows

`workflows/comfyui_txt2img.json` is a minimal text-to-image graph:

```
CheckpointLoaderSimple → CLIPTextEncode (positive + negative) → EmptyLatentImage → KSampler → VAEDecode → SaveImage
```

To use your own workflow:

1. In ComfyUI, build the workflow and export it with **Workflow → Export (API)**. You may need to enable dev mode in settings for that option to appear. The API format is a flat `{ "node_id": { "class_type": …, "inputs": … } }` object, not the UI format.
2. Replace any input you want filled per request with a placeholder. A string value that is **exactly** a placeholder is replaced with a value of the right type:

   | Placeholder | Value |
   |---|---|
   | `{{prompt}}` / `{{negative_prompt}}` | Text from the tool call |
   | `{{width}}` / `{{height}}` | From `size` (integers) |
   | `{{seed}}` | From `seed`, or random |
   | `{{steps}}` / `{{cfg}}` | From the dashboard |
   | `{{checkpoint}}` | Dashboard checkpoint, or the first one installed |
   | `{{batch_size}}` | From `n` |

3. Save the file and set **Workflow file** in the dashboard (relative to the ImgSwitch folder, or absolute).

ImgSwitch returns the images from nodes that save to ComfyUI's output folder, such as `SaveImage`.

**Edit workflow.** When Claude passes input images, ImgSwitch uploads the first one to ComfyUI (`POST /upload/image`) and runs the **Edit workflow file** instead, by default `workflows/comfyui_img2img.json`:

```
LoadImage → ImageScale (to size) → VAEEncode → RepeatLatentBatch → KSampler (denoise) → VAEDecode → SaveImage
```

An edit workflow can use every placeholder above, plus two more:

| Placeholder | Value |
|---|---|
| `{{image}}` | The uploaded input image's name, for a `LoadImage` node's `image` input |
| `{{denoise}}` | `strength` from the tool call, default 0.6 |

ComfyUI edit workflows take one input image.

---

## Persistent HTTP mode (optional)

Instead of letting Claude Code spawn the server, you can run one long-lived server and connect to it over HTTP. That's useful for sharing one server across tools, or running it on another machine.

```bash
uv run main.py --transport streamable-http --port 8000     # endpoint: http://127.0.0.1:8000/mcp
claude mcp add --scope user --transport http imgswitch http://127.0.0.1:8000/mcp
```

The server must be running before Claude Code starts. `--transport sse` is available for older clients that only speak SSE.

In this mode one server serves every project, so relative output folders resolve against the folder you started the HTTP server in, not your Claude Code project. Set an absolute *Output folder* in the dashboard, or ask Claude to save to an absolute path.

---

## Development

```bash
uv run pytest                                                  # unit + end-to-end tests
uv run main.py --debug                                         # verbose stderr logging
npx @modelcontextprotocol/inspector .venv/bin/python main.py   # call the tool interactively
```

Project layout:

```
main.py                     entry point: stdio server, --gui dashboard, --transport http/sse
imgswitch/
  config.py                 config model, atomic save, env overrides
  server.py                 MCP server and the generate_image tool
  router.py                 picks the provider for a call
  output.py                 saves files, builds inline previews
  providers/                one adapter per backend (openai_compat, a1111, comfyui, unsloth)
  gui/app.py                dashboard API (FastAPI)
  gui/static/index.html     dashboard UI (Vue 3 + Tailwind, no build step)
workflows/                  ComfyUI workflow templates
tests/
```

To add a backend, subclass `ImageProvider` in `imgswitch/providers/`, implement `generate()` and `_probe()`, register it in `providers/__init__.py`, and add its settings model and name to `config.py`. In the dashboard, add it to `PROVIDERS` and give it a settings tab in `index.html`; if its config has an `api_key`, add it to `SECRET_PROVIDERS` in `gui/app.py` so the key is masked.
