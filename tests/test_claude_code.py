import json
import os

import pytest

from imgswitch import claude_code
from imgswitch.claude_code import MAIN_PY, TOOLS


@pytest.fixture
def claude_files(tmp_path, monkeypatch):
    cj, settings = tmp_path / "claude.json", tmp_path / "claude" / "settings.json"
    monkeypatch.setenv("IMGSWITCH_CLAUDE_JSON", str(cj))
    monkeypatch.setenv("IMGSWITCH_CLAUDE_SETTINGS", str(settings))
    return cj, settings


def test_registrations_user_and_local(claude_files):
    cj, _ = claude_files
    cj.write_text(json.dumps({
        "mcpServers": {"imgswitch": {"type": "stdio", "command": "/no/such/python", "args": [str(MAIN_PY)]}},
        "projects": {"/home/x/proj": {"mcpServers": {"imgswitch": {"command": "uv", "args": ["run", "other/main.py"]}}},
                     "/home/x/other": {"mcpServers": {}}},
    }))
    user, local = claude_code.registrations()
    assert (user["scope"], user["points_here"], user["command_exists"]) == ("user", True, False)
    assert (local["scope"], local["project"], local["points_here"]) == ("local", "/home/x/proj", False)


def test_register_skips_when_already_registered(claude_files):
    cj, _ = claude_files
    cj.write_text(json.dumps({"mcpServers": {"imgswitch": {"command": "python", "args": [str(MAIN_PY)]}}}))
    assert claude_code.register() == {"ok": True, "output": "ImgSwitch is already registered in user scope."}


def test_allow_tools_keeps_other_settings_and_backs_up(claude_files):
    _, settings = claude_files
    settings.parent.mkdir()
    original = {"model": "opus", "permissions": {"allow": ["Bash(ls:*)"], "deny": ["Read(.env)"]}}
    settings.write_text(json.dumps(original))
    assert claude_code.permissions()["allowed"] == {tool: False for tool in TOOLS}

    result = claude_code.allow_tools()

    assert result["added"] == list(TOOLS) and all(result["allowed"].values())
    saved = json.loads(settings.read_text())
    assert saved["model"] == "opus" and saved["permissions"]["deny"] == ["Read(.env)"]
    assert saved["permissions"]["allow"] == ["Bash(ls:*)", *TOOLS]
    assert json.loads((settings.parent / "settings.json.bak").read_text()) == original
    assert claude_code.allow_tools()["added"] == []  # idempotent


def test_allow_tools_creates_missing_settings(claude_files):
    _, settings = claude_files
    claude_code.allow_tools()
    assert json.loads(settings.read_text()) == {"permissions": {"allow": list(TOOLS)}}


def _fake_proc(root, pid, args, cwd, start_ticks):
    d = root / str(pid)
    d.mkdir()
    (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in args) + b"\0")
    # Field 22 (starttime) comes 20 fields after "(comm) ", and comm may contain spaces.
    (d / "stat").write_text(f"{pid} (py thon) S " + " ".join(["0"] * 18) + f" {start_ticks} 0 0\n")
    os.symlink(cwd, d / "cwd")


def test_running_servers(tmp_path, monkeypatch):
    proc = tmp_path / "proc"
    proc.mkdir()
    (proc / "stat").write_text("cpu 1 2 3\nbtime 1000\n")
    ticks = os.sysconf("SC_CLK_TCK")
    monkeypatch.setattr(claude_code, "code_updated_at", lambda: 1000 + 50)
    _fake_proc(proc, 11, ["/venv/bin/python", str(MAIN_PY)], "/home/x/a", 10 * ticks)  # started at 1010: outdated
    _fake_proc(proc, 12, ["/venv/bin/python", str(MAIN_PY)], "/home/x/b", 90 * ticks)  # 1090: current
    _fake_proc(proc, 13, ["/venv/bin/python", "main.py", "--gui"], str(MAIN_PY.parent), 5 * ticks)  # dashboard
    _fake_proc(proc, 14, ["uv", "run", "main.py"], str(MAIN_PY.parent), 5 * ticks)  # uv wrapper, not python
    _fake_proc(proc, 15, ["/usr/bin/python3", "other/main.py"], "/home/x/c", 5 * ticks)  # someone else's main.py
    _fake_proc(proc, 16, ["python", "main.py", "--transport", "sse"], str(MAIN_PY.parent), 95 * ticks)

    servers = claude_code.running_servers(proc)

    assert [(s["pid"], s["cwd"], s["outdated"], s["transport"]) for s in servers] == [
        (11, "/home/x/a", True, "stdio"),
        (12, "/home/x/b", False, "stdio"),
        (16, str(MAIN_PY.parent), False, "sse"),
    ]
    assert servers[0]["started_at"] == pytest.approx(1010)
