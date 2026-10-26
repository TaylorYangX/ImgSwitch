"""What Claude Code knows about ImgSwitch: its registration, tool permissions, and running server processes.

Read from Claude Code's own files (~/.claude.json, ~/.claude/settings.json) and /proc, so the desktop app
can show and fix the usual problems without a terminal.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from imgswitch import PROJECT_ROOT

MAIN_PY = PROJECT_ROOT / "main.py"
TOOLS = ("mcp__imgswitch__generate_image", "mcp__imgswitch__list_backends")


def claude_json_path() -> Path:
    return Path(os.environ.get("IMGSWITCH_CLAUDE_JSON", "~/.claude.json")).expanduser()


def settings_path() -> Path:
    return Path(os.environ.get("IMGSWITCH_CLAUDE_SETTINGS", "~/.claude/settings.json")).expanduser()


def server_python() -> str:
    venv = PROJECT_ROOT / ".venv" / "bin" / "python"
    return str(venv) if venv.exists() else sys.executable


def claude_cli() -> str | None:
    """The claude CLI. The app may start with a minimal PATH (e.g. from the Start menu), so try the usual spots."""
    found = shutil.which("claude")
    if found:
        return found
    home = Path.home()
    candidates = [home / ".local/bin/claude", home / ".claude/local/claude", home / ".npm-global/bin/claude"]
    candidates += sorted(home.glob(".nvm/versions/node/*/bin/claude"), reverse=True)
    return next((str(c) for c in candidates if c.exists()), None)


def register_command() -> list[str]:
    return [claude_cli() or "claude", "mcp", "add", "--scope", "user", "imgswitch", "--", server_python(), str(MAIN_PY)]


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    return data if isinstance(data, dict) else {}


def _describe(scope: str, project: str | None, entry: dict) -> dict:
    command = entry.get("command", "")
    args = [str(a) for a in entry.get("args") or []]
    return {
        "scope": scope,
        "project": project,
        "type": entry.get("type", "stdio"),
        "command": command,
        "args": args,
        "url": entry.get("url"),
        "command_exists": bool(command) and (Path(command).exists() or shutil.which(command) is not None),
        "points_here": str(MAIN_PY) in args or str(entry.get("url", "")).startswith("http://127.0.0.1"),
    }


def registrations() -> list[dict]:
    """Every `imgswitch` entry Claude Code has: user scope, then local (per-folder) scope."""
    data = _read_json(claude_json_path())
    found = []
    if user := (data.get("mcpServers") or {}).get("imgswitch"):
        found.append(_describe("user", None, user))
    for project, cfg in (data.get("projects") or {}).items():
        if isinstance(cfg, dict) and (local := (cfg.get("mcpServers") or {}).get("imgswitch")):
            found.append(_describe("local", project, local))
    return found


def register() -> dict:
    """Register ImgSwitch in user scope with the claude CLI, which validates and writes ~/.claude.json itself."""
    if any(r["scope"] == "user" for r in registrations()):
        return {"ok": True, "output": "ImgSwitch is already registered in user scope."}
    if not claude_cli():
        return {"ok": False, "output": "The claude CLI wasn't found. Run the command below in a terminal instead."}
    try:
        proc = subprocess.run(register_command(), capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "output": str(e)}
    return {"ok": proc.returncode == 0, "output": (proc.stdout + proc.stderr).strip()}


def _is_allowed(tool: str, allow: list) -> bool:
    return tool in allow or "mcp__imgswitch" in allow or "mcp__imgswitch__*" in allow


def permissions() -> dict:
    allow = (_read_json(settings_path()).get("permissions") or {}).get("allow") or []
    return {"settings_path": str(settings_path()), "allowed": {tool: _is_allowed(tool, allow) for tool in TOOLS}}


def allow_tools() -> dict:
    """Add the ImgSwitch tools to permissions.allow, keeping everything else; the old file is kept as .bak."""
    path = settings_path()
    settings = _read_json(path)
    allow = settings.setdefault("permissions", {}).setdefault("allow", [])
    added = [tool for tool in TOOLS if not _is_allowed(tool, allow)]
    if added:
        allow.extend(added)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            shutil.copy2(path, path.with_name(path.name + ".bak"))
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
    return {"added": added, **permissions()}


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
    """ImgSwitch MCP server processes (one per Claude Code session), with their folder and whether they're outdated."""
    boot, ticks, updated = _boot_time(proc), os.sysconf("SC_CLK_TCK"), code_updated_at()
    servers = []
    for pid_dir in proc.iterdir():
        if not pid_dir.name.isdigit():
            continue
        try:
            args = [a.decode(errors="replace") for a in (pid_dir / "cmdline").read_bytes().split(b"\0") if a]
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
            "cwd": cwd,
            "transport": transport,
            "started_at": started,
            "outdated": started < updated,
        })
    return sorted(servers, key=lambda s: s["started_at"])


def status() -> dict:
    return {
        "registrations": registrations(),
        "register_command": register_command(),
        "cli": claude_cli(),
        "permissions": permissions(),
        "servers": running_servers(),
        "code_updated_at": code_updated_at(),
    }
