"""Batch rename: "Trip ###" → Trip 001.jpg, Trip 002.jpg … in file-name order.

The one Satsuma tool that changes the originals (renaming copies would defeat the point), so it
remembers what it did: Undo puts the old names back instead of recycling anything.
"""
from __future__ import annotations

import re
import threading
import uuid
from pathlib import Path

_LOCK = threading.Lock()
_UNDO: dict[str, str] = {}      # new path -> old path, for every rename this session
INVALID = '<>:"/\\|?*'


def plan(paths, pattern: str, start: int = 1) -> list[tuple[Path, Path]]:
    """[(old, new)] in natural file-name order. `#` marks where the number goes ("##" pads to two
    digits); without any, the number is added after a space. Extensions are kept."""
    from ..actions import natural_key

    paths = sorted((Path(p) for p in paths), key=natural_key)
    pattern = pattern.strip()
    if not pattern:
        raise ValueError("Type a name first.")
    if any(c in pattern for c in INVALID):
        raise ValueError(f"A file name can't contain any of  {INVALID}")
    hashes = re.search(r"#+", pattern)
    width = max(len(hashes.group()) if hashes else 0, len(str(start + len(paths) - 1)))
    result = []
    for offset, path in enumerate(paths):
        number = str(start + offset).zfill(width)
        stem = pattern[:hashes.start()] + number + pattern[hashes.end():] if hashes else f"{pattern} {number}"
        result.append((path, path.with_name(stem.strip() + path.suffix)))
    return result


def rename(paths, pattern: str, start: int = 1) -> list[Path]:
    steps = [(old, new) for old, new in plan(paths, pattern, start) if old != new]
    sources = {old.resolve() for old, _new in steps}
    for _old, new in steps:
        if new.exists() and new.resolve() not in sources:
            raise ValueError(f"“{new.name}” already exists in that folder. Pick another name.")
    # Two steps through temporary names, so A→B and B→A can't trip over each other.
    temporary = []
    for old, new in steps:
        hop = old.with_name(f".satsuma-rename-{uuid.uuid4().hex}{old.suffix}")
        old.rename(hop)
        temporary.append((hop, old, new))
    for hop, old, new in temporary:
        hop.rename(new)
        with _LOCK:
            _UNDO[str(new)] = str(old)
    return [new for _hop, _old, new in temporary]


def can_undo(outputs) -> bool:
    with _LOCK:
        return bool(outputs) and all(str(Path(o)) in _UNDO for o in outputs)


def undo(outputs) -> bool:
    """Put the old names back. True if every file got its name back."""
    ok = True
    for out in outputs:
        out = Path(out)
        with _LOCK:
            old = _UNDO.pop(str(out), None)
        if old is None or not out.exists() or Path(old).exists():
            ok = False
            continue
        out.rename(old)
    return ok
