"""End-to-end: launch `python main.py` the way Claude Code does."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters

ROOT = Path(__file__).resolve().parent.parent


def _listening_inodes() -> set[str]:
    inodes = set()
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            lines = Path(table).read_text().splitlines()[1:]
        except FileNotFoundError:
            continue
        for line in lines:
            fields = line.split()
            if fields[3] == "0A":  # TCP_LISTEN
                inodes.add(fields[9])
    return inodes


def _socket_inodes(pid: int) -> set[str]:
    inodes = set()
    for fd in Path(f"/proc/{pid}/fd").iterdir():
        try:
            target = os.readlink(fd)
        except OSError:
            continue
        if target.startswith("socket:["):
            inodes.add(target[8:-1])
    return inodes


async def test_stdio_lists_tools(config_file, tmp_path):
    # Launched from an unrelated cwd: config must come from IMGSWITCH_CONFIG, not the cwd.
    params = StdioServerParameters(
        command=sys.executable, args=[str(ROOT / "main.py")], cwd=str(tmp_path), env={**os.environ}
    )
    async with Client(params) as client:
        tools = (await client.list_tools()).tools
    assert [t.name for t in tools] == ["generate_image", "list_backends"]


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="uses /proc")
def test_stdio_mode_binds_no_port(config_file):
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "main.py")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        init = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}},
        }
        proc.stdin.write(json.dumps(init) + "\n")
        proc.stdin.flush()
        reply = json.loads(proc.stdout.readline())  # stdout carries only protocol messages
        assert reply["result"]["serverInfo"]["name"] == "imgswitch"

        assert not (_socket_inodes(proc.pid) & _listening_inodes())
    finally:
        proc.kill()
        proc.wait()
