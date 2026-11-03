"""The last few conversions, kept across restarts for the tray's Recent menu."""
from __future__ import annotations

import json
import time
from pathlib import Path

from .config import DATA_DIR

HISTORY_FILE = DATA_DIR / "recent.json"
KEEP = 10


def _load() -> list[dict]:
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        return [e for e in data if isinstance(e, dict) and isinstance(e.get("outputs"), list)]
    except (OSError, ValueError):
        return []


def _save(entries: list[dict]) -> None:
    try:
        HISTORY_FILE.write_text(json.dumps(entries[:KEEP], indent=1), encoding="utf-8")
    except OSError:
        pass


def add(title: str, outputs) -> None:
    outputs = [str(o) for o in outputs]
    if not outputs:
        return
    entries = [e for e in _load() if e["outputs"] != outputs]
    entries.insert(0, {"title": title, "outputs": outputs, "time": time.time()})
    _save(entries)


def entries() -> list[dict]:
    """Newest first; only results that still exist (a file deleted or undone drops out)."""
    found = []
    for entry in _load():
        alive = [o for o in entry["outputs"] if Path(o).exists()]
        if alive:
            found.append({**entry, "outputs": alive})
    return found


def clear() -> None:
    _save([])


def ago(timestamp: float, now: float | None = None) -> str:
    seconds = max(0, int((now or time.time()) - timestamp))
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60} min ago"
    if seconds < 86400:
        return f"{seconds // 3600} h ago"
    days = seconds // 86400
    return "yesterday" if days == 1 else f"{days} days ago"
