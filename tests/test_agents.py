import json
import os
import subprocess
import tomllib
from pathlib import Path

import pytest

from imgswitch import agents
from imgswitch.agents import CLAUDE_TOOLS, MAIN_PY


@pytest.fixture
def agent_files(tmp_path, monkeypatch):
    """Point every agent's config at a scratch file, so no test touches the real ones."""
    files = {
        "claude": tmp_path / "claude.json",
        "claude_settings": tmp_path / "claude" / "settings.json",
        "codex": tmp_path / "codex" / "config.toml",
        "opencode": tmp_path / "opencode" / "opencode.jsonc",
        "antigravity": tmp_path / "gemini" / "config" / "mcp_config.json",
    }
    monkeypatch.setenv("IMGSWITCH_CLAUDE_JSON", str(files["claude"]))
    monkeypatch.setenv("IMGSWITCH_CLAUDE_SETTINGS", str(files["claude_settings"]))
    monkeypatch.setenv("IMGSWITCH_CODEX_CONFIG", str(files["codex"]))
    monkeypatch.setenv("IMGSWITCH_OPENCODE_CONFIG", str(files["opencode"]))
    monkeypatch.setenv("IMGSWITCH_ANTIGRAVITY_CONFIG", str(files["antigravity"]))
    for f in files.values():
        f.parent.mkdir(parents=True, exist_ok=True)
    return files


# --- Who is calling, and from where ---------------------------------------------------------------


@pytest.mark.parametrize(
    "name,key",
    [("claude-code", "claude"), ("codex-mcp-client", "codex"), ("opencode", "opencode"), ("Antigravity", "antigravity"),
     ("jetski", "antigravity"), ("gemini-cli", "gemini"), ("My Agent 2", "my-agent-2")],
)
def test_agent_key(name, key):
    assert agents.agent_key(name) == key


def test_identify_agent_prefers_client_info():
    assert agents.identify_agent("codex-mcp-client", "0.130.0") == ("codex", "codex-mcp-client 0.130.0")


def _fake_proc(root: Path, pid: int, ppid: int, args: list[str], cwd: str = "/", start_ticks: int = 0) -> None:
    d = root / str(pid)
    d.mkdir()
    (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in args) + b"\0")
    # Field 22 (starttime) comes 20 fields after "(comm) ", and comm may contain spaces.
    (d / "stat").write_text(f"{pid} (some name) S {ppid} " + " ".join(["0"] * 17) + f" {start_ticks} 0 0\n")
    os.symlink(cwd, d / "cwd")


def test_process_agent_walks_up_the_parent_chain(tmp_path):
    proc = tmp_path / "proc"
    proc.mkdir()
    _fake_proc(proc, 10, 1, ["/home/x/.npm-global/bin/node", "/home/x/.npm-global/bin/codex"])
    _fake_proc(proc, 20, 10, ["/bin/sh", "-c", "python main.py"])  # a wrapper shell in between
    _fake_proc(proc, 30, 20, ["/venv/bin/python", str(MAIN_PY)])
    _fake_proc(proc, 40, 1, ["/usr/bin/bash"])
    _fake_proc(proc, 50, 40, ["/venv/bin/python", str(MAIN_PY)])
    assert agents.process_agent(30, proc) == "codex"
    assert agents.process_agent(50, proc) is None


def test_choose_workspace():
    project = Path("/home/x/project")
    assert agents.choose_workspace(project, []) == project
    assert agents.choose_workspace(project / "src", [project]) == project / "src"  # already inside: keep the cwd
    assert agents.choose_workspace(Path("/home/x"), [project, Path("/other")]) == project


# --- Claude Code -----------------------------------------------------------------------------------


def test_claude_registrations_and_status(agent_files):
    agent_files["claude"].write_text(json.dumps({
        "mcpServers": {"imgswitch": {"type": "stdio", "command": "/no/such/python", "args": [str(MAIN_PY)]}},
        "projects": {"/home/x/proj": {"mcpServers": {"imgswitch": {"command": "uv", "args": ["run", "other/main.py"]}}}},
    }))
    user, local = agents.claude_registrations()
    assert (user["where"], user["points_here"], user["command_exists"]) == ("user", True, False)
    assert (local["where"], local["points_here"]) == ("local:/home/x/proj", False)
    status = agents.agent_status("claude")
    assert status["label"] == "Claude Code" and not status["registered"]  # its command doesn't exist
    assert "mcp add --scope user imgswitch" in status["snippet"]
    assert status["permissions"]["allowed"] == {tool: False for tool in CLAUDE_TOOLS}


def test_claude_allow_tools_keeps_other_settings_and_backs_up(agent_files):
    settings = agent_files["claude_settings"]
    original = {"model": "opus", "permissions": {"allow": ["Bash(ls:*)"], "deny": ["Read(.env)"]}}
    settings.write_text(json.dumps(original))

    result = agents.claude_allow_tools()

    assert result["added"] == list(CLAUDE_TOOLS) and all(result["allowed"].values())
    saved = json.loads(settings.read_text())
    assert saved["model"] == "opus" and saved["permissions"]["deny"] == ["Read(.env)"]
    assert saved["permissions"]["allow"] == ["Bash(ls:*)", *CLAUDE_TOOLS]
    assert json.loads((settings.parent / "settings.json.bak").read_text()) == original
    assert agents.claude_allow_tools()["added"] == []  # idempotent


# --- Codex -----------------------------------------------------------------------------------------


def test_codex_register_appends_and_keeps_the_rest(agent_files):
    config = agent_files["codex"]
    original = 'model = "gpt-5"\n\n[mcp_servers.other]\ncommand = "npx"\nargs = ["-y", "other"]\n'
    config.write_text(original)
    assert agents.codex_registrations() == []

    assert agents.register("codex")["ok"]

    data = tomllib.loads(config.read_text())
    assert data["model"] == "gpt-5" and data["mcp_servers"]["other"]["command"] == "npx"
    entry = data["mcp_servers"]["imgswitch"]
    assert entry["args"] == [str(MAIN_PY)] and entry["tool_timeout_sec"] == 600
    assert (config.parent / "config.toml.bak").read_text() == original
    assert agents.agent_status("codex")["registered"]
    assert agents.register("codex")["output"].startswith("ImgSwitch is already registered")


def test_codex_register_refuses_to_break_the_config(agent_files):
    config = agent_files["codex"]
    config.write_text('mcp_servers = { other = { command = "npx" } }\n')  # an inline table can't take a new header
    result = agents.register("codex")
    assert not result["ok"] and "valid TOML" in result["output"]
    assert config.read_text() == 'mcp_servers = { other = { command = "npx" } }\n'


def test_codex_register_creates_a_missing_config(agent_files):
    agents.register("codex")
    assert tomllib.loads(agent_files["codex"].read_text())["mcp_servers"]["imgswitch"]["startup_timeout_sec"] == 30


# --- OpenCode --------------------------------------------------------------------------------------


def test_strip_jsonc():
    text = '{\n  // a comment\n  "url": "http://x//y", /* block */ "list": [1, 2,],\n  "s": "a\\"b",\n}'
    assert json.loads(agents.strip_jsonc(text)) == {"url": "http://x//y", "list": [1, 2], "s": 'a"b'}


@pytest.mark.parametrize(
    "mcp",
    [
        {"servers": {"imgswitch": {"type": "local", "command": ["PYTHON", str(MAIN_PY)]}}},  # v2
        {"imgswitch": {"type": "local", "command": ["PYTHON", str(MAIN_PY)], "enabled": True}},  # v1
    ],
)
def test_opencode_registrations(agent_files, mcp):
    python = agents.server_command()[0]
    body = json.dumps({"$schema": "https://opencode.ai/config.json", "mcp": mcp}).replace("PYTHON", python)
    agent_files["opencode"].write_text("// my opencode config\n" + body)
    [entry] = agents.opencode_registrations()
    assert entry["command"] == python and entry["args"] == [str(MAIN_PY)] and entry["points_here"]
    assert agents.agent_status("opencode")["registered"]


def test_opencode_register_uses_its_cli(agent_files, monkeypatch):
    calls = []
    monkeypatch.setattr(agents, "opencode_cli", lambda: "/opt/opencode")
    monkeypatch.setattr(
        agents.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, "added", "")
    )
    assert agents.register("opencode") == {"ok": True, "output": "added"}
    assert calls == [["/opt/opencode", "mcp", "add", "imgswitch", "--global", "--", *agents.server_command()]]


# --- Antigravity -----------------------------------------------------------------------------------


def test_antigravity_register_into_an_empty_file(agent_files):
    config = agent_files["antigravity"]
    config.write_text("")  # how Antigravity leaves it before any server is added
    assert agents.antigravity_registrations() == []
    assert agents.register("antigravity")["ok"]
    assert json.loads(config.read_text()) == {"mcpServers": {"imgswitch": {"command": agents.server_command()[0], "args": [str(MAIN_PY)]}}}
    assert agents.agent_status("antigravity")["registered"]


def test_antigravity_register_keeps_other_servers(agent_files):
    config = agent_files["antigravity"]
    config.write_text(json.dumps({"mcpServers": {"gws": {"serverUrl": "https://example.com/mcp"}}}))
    agents.register("antigravity")
    servers = json.loads(config.read_text())["mcpServers"]
    assert set(servers) == {"gws", "imgswitch"} and (config.parent / "mcp_config.json.bak").exists()


def test_antigravity_falls_back_to_the_pre_2_config(tmp_path, monkeypatch):
    monkeypatch.delenv("IMGSWITCH_ANTIGRAVITY_CONFIG", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    legacy = tmp_path / ".gemini" / "antigravity" / "mcp_config.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("{}")
    assert agents.antigravity_config_path() == legacy
    (tmp_path / ".gemini" / "config").mkdir()
    assert agents.antigravity_config_path() == tmp_path / ".gemini" / "config" / "mcp_config.json"


# --- Overview and running servers ------------------------------------------------------------------


def test_status_lists_every_agent(agent_files):
    status = agents.status()
    assert [a["key"] for a in status["agents"]] == ["claude", "codex", "opencode", "antigravity"]
    assert all({"installed", "registered", "snippet", "config_path"} <= a.keys() for a in status["agents"])


def test_running_servers_tagged_with_their_agent(tmp_path, monkeypatch):
    proc = tmp_path / "proc"
    proc.mkdir()
    (proc / "stat").write_text("cpu 1 2 3\nbtime 1000\n")
    ticks = os.sysconf("SC_CLK_TCK")
    monkeypatch.setattr(agents, "code_updated_at", lambda: 1000 + 50)
    _fake_proc(proc, 5, 1, ["/home/x/.local/share/claude/versions/2.1.310"])
    _fake_proc(proc, 6, 1, ["/home/x/.opencode/bin/opencode"])
    _fake_proc(proc, 11, 5, ["/venv/bin/python", str(MAIN_PY)], "/home/x/a", 10 * ticks)  # outdated
    _fake_proc(proc, 12, 6, ["/venv/bin/python", str(MAIN_PY)], "/home/x/b", 90 * ticks)
    _fake_proc(proc, 13, 1, ["/venv/bin/python", "main.py", "--gui"], str(MAIN_PY.parent), 5 * ticks)  # the app
    _fake_proc(proc, 14, 1, ["uv", "run", "main.py"], str(MAIN_PY.parent), 5 * ticks)  # not python
    _fake_proc(proc, 15, 1, ["/usr/bin/python3", "other/main.py"], "/home/x/c", 5 * ticks)  # someone else's
    _fake_proc(proc, 16, 1, ["python", "main.py", "--transport", "sse"], str(MAIN_PY.parent), 95 * ticks)

    servers = agents.running_servers(proc)

    assert [(s["pid"], s["agent"], s["cwd"], s["outdated"], s["transport"]) for s in servers] == [
        (11, "claude", "/home/x/a", True, "stdio"),
        (12, "opencode", "/home/x/b", False, "stdio"),
        (16, None, str(MAIN_PY.parent), False, "sse"),
    ]
    assert servers[0]["started_at"] == pytest.approx(1010)
