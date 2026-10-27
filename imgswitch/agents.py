"""The coding agents that can use ImgSwitch (Claude Code, Codex, OpenCode, Antigravity).

Covers which agent is calling, where each one keeps its MCP config, registering ImgSwitch there,
Claude Code's tool permissions, and the ImgSwitch servers the agents are running. Everything is
read from the agents' own files and /proc, so the desktop app can show and fix it without a terminal.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from pathlib import Path

from imgswitch import PROJECT_ROOT

MAIN_PY = PROJECT_ROOT / "main.py"
SERVER_NAME = "imgswitch"
CLAUDE_TOOLS = ("mcp__imgswitch__generate_image", "mcp__imgswitch__list_backends")
AGENTS = ("claude", "codex", "opencode", "antigravity")
LABELS = {"claude": "Claude Code", "codex": "Codex", "opencode": "OpenCode", "antigravity": "Antigravity"}

# Matched against an MCP client's name, or an ancestor process's command line.
AGENT_PATTERNS = [
    ("claude", re.compile(r"claude")),
    ("codex", re.compile(r"codex")),
    ("opencode", re.compile(r"opencode")),
    ("antigravity", re.compile(r"antigravity|jetski|agentapi")),
    ("gemini", re.compile(r"gemini")),
]


# ---- Who is calling, and from which folder ---------------------------------------------------


def agent_key(client_name: str) -> str:
    name = client_name.lower()
    for key, pattern in AGENT_PATTERNS:
        if pattern.search(name):
            return key
    return re.sub(r"[^a-z0-9]+", "-", name).strip("-") or "agent"


def _parent(pid: int, proc: Path) -> int:
    stat = (proc / str(pid) / "stat").read_text()
    return int(stat[stat.rindex(")") + 2 :].split()[1])  # fields after "(comm)": state, ppid, …


def _cmdline(pid: int, proc: Path) -> list[str]:
    return [a.decode(errors="replace") for a in (proc / str(pid) / "cmdline").read_bytes().split(b"\0") if a]


def process_agent(pid: int, proc: Path = Path("/proc"), depth: int = 4) -> str | None:
    """The agent that started process `pid`, judged by its ancestors' command lines (a stdio server's parent)."""
    try:
        for _ in range(depth):
            pid = _parent(pid, proc)
            if pid <= 1:
                return None
            args = _cmdline(pid, proc)
            if not args:
                continue
            # The program's full path counts: Claude Code's CLI runs as …/claude/versions/2.1.310.
            words = " ".join([args[0], *(Path(a).name for a in args[1:2])]).lower()
            for key, pattern in AGENT_PATTERNS:
                if pattern.search(words):
                    return key
    except (OSError, ValueError, IndexError):
        pass
    return None


def identify_agent(client_name: str | None, client_version: str | None = None) -> tuple[str, str | None]:
    """(agent key, "name version" as the client reported it). Falls back to this process's ancestry."""
    if client_name:
        return agent_key(client_name), " ".join(filter(None, [client_name, client_version]))
    return process_agent(os.getpid()) or "agent", None


def choose_workspace(cwd: Path, roots: list[Path]) -> Path:
    """The folder relative paths resolve against: the cwd, unless the client's workspace roots say it's elsewhere."""
    if not roots or any(cwd == r or r in cwd.parents for r in roots):
        return cwd
    return roots[0]


# ---- Shared helpers ---------------------------------------------------------------------------


def server_command() -> list[str]:
    venv = PROJECT_ROOT / ".venv" / "bin" / "python"
    return [str(venv) if venv.exists() else sys.executable, str(MAIN_PY)]


def _find_cli(name: str, *candidates: Path) -> str | None:
    """The app may start with a minimal PATH (e.g. from the Start menu), so also try the usual install spots."""
    found = shutil.which(name)
    if found:
        return found
    return next((str(c) for c in candidates if c.exists()), None)


def _read_json(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    data = json.loads(text) if text.strip() else {}
    return data if isinstance(data, dict) else {}


def _write_with_backup(path: Path, text: str) -> None:
    """Replace a config file atomically, keeping the previous version next to it as .bak."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + ".bak"))
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        if path.exists():
            shutil.copymode(path, tmp)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _describe(where: str, command: str, args: list[str], url: str | None = None) -> dict:
    return {
        "where": where,
        "command": command,
        "args": args,
        "url": url,
        "command_exists": bool(command) and (Path(command).exists() or shutil.which(command) is not None),
        "points_here": str(MAIN_PY) in args,
    }


def _env_path(var: str, default: str) -> Path:
    return Path(os.environ.get(var, default)).expanduser()


# ---- Claude Code ------------------------------------------------------------------------------


def claude_json_path() -> Path:
    return _env_path("IMGSWITCH_CLAUDE_JSON", "~/.claude.json")


def claude_settings_path() -> Path:
    return _env_path("IMGSWITCH_CLAUDE_SETTINGS", "~/.claude/settings.json")


def claude_cli() -> str | None:
    home = Path.home()
    return _find_cli(
        "claude",
        home / ".local/bin/claude",
        home / ".claude/local/claude",
        home / ".npm-global/bin/claude",
        *sorted(home.glob(".nvm/versions/node/*/bin/claude"), reverse=True),
    )


def claude_register_command() -> list[str]:
    return [claude_cli() or "claude", "mcp", "add", "--scope", "user", SERVER_NAME, "--", *server_command()]


def claude_registrations() -> list[dict]:
    """Every `imgswitch` entry Claude Code has: user scope, then local (per-folder) scope."""
    data = _read_json(claude_json_path())
    found = []

    def add(where: str, entry: dict) -> None:
        found.append(_describe(where, entry.get("command", ""), [str(a) for a in entry.get("args") or []], entry.get("url")))

    if user := (data.get("mcpServers") or {}).get(SERVER_NAME):
        add("user", user)
    for project, cfg in (data.get("projects") or {}).items():
        if isinstance(cfg, dict) and (local := (cfg.get("mcpServers") or {}).get(SERVER_NAME)):
            add(f"local:{project}", local)
    return found


def _claude_register() -> dict:
    if not claude_cli():
        return {"ok": False, "output": "The claude CLI wasn't found. Run the command shown instead."}
    try:
        proc = subprocess.run(claude_register_command(), capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "output": str(e)}
    return {"ok": proc.returncode == 0, "output": (proc.stdout + proc.stderr).strip()}


def _is_allowed(tool: str, allow: list) -> bool:
    return tool in allow or "mcp__imgswitch" in allow or "mcp__imgswitch__*" in allow


def claude_permissions() -> dict:
    allow = (_read_json(claude_settings_path()).get("permissions") or {}).get("allow") or []
    return {"settings_path": str(claude_settings_path()), "allowed": {t: _is_allowed(t, allow) for t in CLAUDE_TOOLS}}


def claude_allow_tools() -> dict:
    """Add the ImgSwitch tools to Claude Code's permissions.allow, keeping everything else."""
    path = claude_settings_path()
    settings = _read_json(path)
    allow = settings.setdefault("permissions", {}).setdefault("allow", [])
    added = [tool for tool in CLAUDE_TOOLS if not _is_allowed(tool, allow)]
    if added:
        allow.extend(added)
        _write_with_backup(path, json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
    return {"added": added, **claude_permissions()}


# ---- Codex ------------------------------------------------------------------------------------


def codex_config_path() -> Path:
    return _env_path("IMGSWITCH_CODEX_CONFIG", "~/.codex/config.toml")


def codex_snippet() -> str:
    python, main = server_command()
    # Local generation often takes minutes; Codex's default tool timeout is 60 s.
    return (
        f"[mcp_servers.{SERVER_NAME}]\n"
        f"command = {json.dumps(python)}\n"
        f"args = [{json.dumps(main)}]\n"
        "startup_timeout_sec = 30\n"
        "tool_timeout_sec = 600\n"
    )


def codex_registrations() -> list[dict]:
    path = codex_config_path()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        return []
    entry = (data.get("mcp_servers") or {}).get(SERVER_NAME)
    if not isinstance(entry, dict):
        return []
    return [_describe(str(path), entry.get("command", ""), [str(a) for a in entry.get("args") or []], entry.get("url"))]


def _codex_register() -> dict:
    path = codex_config_path()
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    updated = text + ("\n" if text and not text.endswith("\n") else "") + ("\n" if text else "") + codex_snippet()
    try:
        tomllib.loads(updated)  # never write a config Codex can't read
    except tomllib.TOMLDecodeError as e:
        return {"ok": False, "output": f"{path} would not stay valid TOML ({e}); add the snippet by hand."}
    _write_with_backup(path, updated)
    return {"ok": True, "output": f"Added [mcp_servers.{SERVER_NAME}] to {path}"}


# ---- OpenCode ---------------------------------------------------------------------------------


def opencode_cli() -> str | None:
    return _find_cli("opencode", Path.home() / ".opencode/bin/opencode", Path.home() / ".npm-global/bin/opencode")


def opencode_config_paths() -> list[Path]:
    if env := os.environ.get("IMGSWITCH_OPENCODE_CONFIG"):
        return [Path(env).expanduser()]
    folder = Path.home() / ".config" / "opencode"
    return [folder / "opencode.jsonc", folder / "opencode.json"]


def strip_jsonc(text: str) -> str:
    """JSON with comments and trailing commas → plain JSON, leaving string contents alone."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i : j + 1])
            i = j + 1
        elif text.startswith("//", i):
            i = text.find("\n", i) if "\n" in text[i:] else n
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
        else:
            out.append(c)
            i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def opencode_snippet() -> str:
    server = {"type": "local", "command": server_command()}
    return json.dumps({"mcp": {"servers": {SERVER_NAME: server}}}, indent=2)


def opencode_registrations() -> list[dict]:
    found = []
    for path in opencode_config_paths():
        try:
            data = json.loads(strip_jsonc(path.read_text(encoding="utf-8")) or "{}")
        except (FileNotFoundError, ValueError):
            continue
        mcp = data.get("mcp") or {}
        entry = (mcp.get("servers") or {}).get(SERVER_NAME) or mcp.get(SERVER_NAME)  # v2, then v1 schema
        if isinstance(entry, dict):
            command = entry.get("command") or []
            command = command if isinstance(command, list) else [command]
            found.append(_describe(str(path), str(command[0]) if command else "", [str(a) for a in command[1:]], entry.get("url")))
    return found


def _opencode_register() -> dict:
    cli = opencode_cli()
    if not cli:
        return {"ok": False, "output": "The opencode CLI wasn't found. Add the snippet to its config by hand."}
    try:
        proc = subprocess.run(
            [cli, "mcp", "add", SERVER_NAME, "--global", "--", *server_command()], capture_output=True, text=True, timeout=60
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "output": str(e)}
    return {"ok": proc.returncode == 0, "output": (proc.stdout + proc.stderr).strip()}


# ---- Antigravity ------------------------------------------------------------------------------


def antigravity_config_path() -> Path:
    """Antigravity 2.0, its IDE and CLI share ~/.gemini/config/mcp_config.json; older builds used ~/.gemini/antigravity/."""
    if env := os.environ.get("IMGSWITCH_ANTIGRAVITY_CONFIG"):
        return Path(env).expanduser()
    gemini = Path.home() / ".gemini"
    legacy = gemini / "antigravity" / "mcp_config.json"
    if not (gemini / "config").is_dir() and legacy.exists():
        return legacy
    return gemini / "config" / "mcp_config.json"


def antigravity_snippet() -> str:
    python, main = server_command()
    return json.dumps({"mcpServers": {SERVER_NAME: {"command": python, "args": [main]}}}, indent=2)


def antigravity_registrations() -> list[dict]:
    path = antigravity_config_path()
    try:
        entry = (_read_json(path).get("mcpServers") or {}).get(SERVER_NAME)
    except ValueError:
        return []
    if not isinstance(entry, dict):
        return []
    return [_describe(str(path), entry.get("command", ""), [str(a) for a in entry.get("args") or []], entry.get("serverUrl"))]


def _antigravity_register() -> dict:
    path = antigravity_config_path()
    try:
        data = _read_json(path)
    except ValueError as e:
        return {"ok": False, "output": f"{path} isn't valid JSON ({e}); add the snippet by hand."}
    python, main = server_command()
    data.setdefault("mcpServers", {})[SERVER_NAME] = {"command": python, "args": [main]}
    _write_with_backup(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return {"ok": True, "output": f"Added {SERVER_NAME} to {path}"}


# ---- Per-agent overview -----------------------------------------------------------------------


def _installed(key: str) -> bool:
    home = Path.home()
    if key == "claude":
        return bool(claude_cli()) or (home / ".claude").is_dir()
    if key == "codex":
        return bool(_find_cli("codex", home / ".npm-global/bin/codex")) or (home / ".codex").is_dir()
    if key == "opencode":
        return bool(opencode_cli()) or (home / ".config/opencode").is_dir()
    return any((home / ".gemini" / d).is_dir() for d in ("antigravity", "antigravity-cli", "config"))


def agent_status(key: str) -> dict:
    registrations, config_path, snippet = {
        "claude": lambda: (claude_registrations(), claude_json_path(), " ".join(claude_register_command())),
        "codex": lambda: (codex_registrations(), codex_config_path(), codex_snippet()),
        "opencode": lambda: (opencode_registrations(), opencode_config_paths()[0], opencode_snippet()),
        "antigravity": lambda: (antigravity_registrations(), antigravity_config_path(), antigravity_snippet()),
    }[key]()
    status = {
        "key": key,
        "label": LABELS[key],
        "installed": _installed(key),
        "config_path": str(config_path),
        "registrations": registrations,
        "registered": any(r["points_here"] and r["command_exists"] for r in registrations),
        "snippet": snippet,
    }
    if key == "claude":
        status["permissions"] = claude_permissions()
    return status


def register(key: str) -> dict:
    """Register ImgSwitch with an agent, unless it already is."""
    if agent_status(key)["registered"]:
        return {"ok": True, "output": f"ImgSwitch is already registered with {LABELS[key]}."}
    return {"claude": _claude_register, "codex": _codex_register, "opencode": _opencode_register,
            "antigravity": _antigravity_register}[key]()


# ---- Running servers --------------------------------------------------------------------------


def code_updated_at() -> float:
    """When ImgSwitch's code last changed; a server started before that runs outdated code."""
    files = [MAIN_PY, *(PROJECT_ROOT / "imgswitch").rglob("*.py")]
    return max((f.stat().st_mtime for f in files if f.exists()), default=0.0)


def _boot_time(proc: Path) -> float:
    for line in (proc / "stat").read_text().splitlines():
        if line.startswith("btime "):
            return float(line.split()[1])
    return time.time() - time.monotonic()


def running_servers(proc: Path = Path("/proc")) -> list[dict]:
    """ImgSwitch MCP server processes (one per agent session), with their agent, folder and whether they're outdated."""
    boot, ticks, updated = _boot_time(proc), os.sysconf("SC_CLK_TCK"), code_updated_at()
    servers = []
    for pid_dir in proc.iterdir():
        if not pid_dir.name.isdigit():
            continue
        try:
            args = _cmdline(int(pid_dir.name), proc)
            if not args or "python" not in Path(args[0]).name or "--gui" in args:
                continue
            cwd = os.readlink(pid_dir / "cwd")
            if not any(a.endswith("main.py") and (Path(cwd) / a).resolve() == MAIN_PY for a in args[1:]):
                continue
            # Field 22 of stat is the start time in clock ticks after boot; skip past the "(comm)" field first.
            stat = (pid_dir / "stat").read_text()
            started = boot + int(stat[stat.rindex(")") + 2 :].split()[19]) / ticks
        except (OSError, ValueError, IndexError):
            continue  # the process ended meanwhile, or it isn't ours to read
        transport = args[args.index("--transport") + 1] if "--transport" in args[:-1] else "stdio"
        servers.append({
            "pid": int(pid_dir.name),
            "agent": process_agent(int(pid_dir.name), proc),
            "cwd": cwd,
            "transport": transport,
            "started_at": started,
            "outdated": started < updated,
        })
    return sorted(servers, key=lambda s: s["started_at"])


def status() -> dict:
    return {
        "agents": [agent_status(key) for key in AGENTS],
        "servers": running_servers(),
        "code_updated_at": code_updated_at(),
    }
