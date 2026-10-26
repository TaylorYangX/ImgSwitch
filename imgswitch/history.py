"""Log of every generation, from Claude or the desktop app's Playground, for the History page.

One JSON object per line in history.jsonl next to config.json. Several MCP server processes may write
at once, so every access holds an flock on the file and appends with a single write.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from imgswitch.config import data_dir

logger = logging.getLogger(__name__)

HISTORY_FILE = "history.jsonl"


def history_path() -> Path:
    return data_dir() / HISTORY_FILE


@contextmanager
def _locked(mode: str) -> Iterator:
    path = history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | (os.O_APPEND if mode == "a" else 0), 0o600)
    with os.fdopen(fd, "r+" if mode != "a" else "a", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield f
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def record(entry: dict) -> dict | None:
    """Append one generation and return it with its id and time. Never raises: history is a convenience."""
    item = {"id": uuid.uuid4().hex[:12], "time": time.time(), **entry}
    try:
        with _locked("a") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    except OSError as e:
        logger.warning("Could not record history in %s: %s", history_path(), e)
        return None
    return item


def _parse(text: str) -> list[dict]:
    items = []
    for line in text.splitlines():
        try:
            items.append(json.loads(line))
        except ValueError:
            continue  # a hand-edited or truncated line shouldn't hide the rest
    return items


def _read_all() -> list[dict]:
    try:
        text = history_path().read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    return _parse(text)


def _matches(item: dict, query: str, source: str | None, backend: str | None) -> bool:
    if source and item.get("source") != source:
        return False
    if backend and item.get("backend") != backend:
        return False
    if query:
        haystack = " ".join(str(item.get(k, "")) for k in ("prompt", "model", "backend_label", "cwd")).lower()
        return query.lower() in haystack
    return True


def list_entries(
    offset: int = 0, limit: int = 60, query: str = "", source: str | None = None, backend: str | None = None
) -> tuple[list[dict], int]:
    """Newest first. Each returned entry gets `missing`: which of its output files no longer exist."""
    items = [i for i in reversed(_read_all()) if _matches(i, query, source, backend)]
    page = items[offset : offset + limit]
    for item in page:
        item["missing"] = [not Path(p).is_file() for p in item.get("outputs", [])]
    return page, len(items)


def get(entry_id: str) -> dict | None:
    return next((i for i in _read_all() if i.get("id") == entry_id), None)


def _rewrite(keep) -> int:
    """Rewrite the file under the lock, keeping entries for which keep(entry) is true; return how many went."""
    with _locked("rw") as f:
        items = _parse(f.read())
        kept = [i for i in items if keep(i)]
        f.seek(0)
        f.truncate()
        f.writelines(json.dumps(i, ensure_ascii=False) + "\n" for i in kept)
    return len(items) - len(kept)


def delete(entry_id: str) -> bool:
    """Remove one entry from the history. The image files themselves are kept."""
    return _rewrite(lambda i: i.get("id") != entry_id) > 0


def clear() -> int:
    return _rewrite(lambda i: False)
