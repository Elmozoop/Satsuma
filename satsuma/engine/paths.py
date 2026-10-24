"""Where results go, and how they are named."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from ..config import settings

_INVALID = '<>:"/\\|?*'


def sanitise_stem(stem: str) -> str:
    cleaned = "".join("_" if ch in _INVALID or ord(ch) < 32 else ch for ch in stem)
    cleaned = cleaned.rstrip(" .")
    return cleaned or "file"


def output_dir_for(source: Path) -> Path:
    """Resolve the destination folder from settings, falling back to the source folder."""
    source = Path(source)
    mode = settings.get("output_mode")
    base = source.parent
    if mode == "subfolder":
        base = source.parent / str(settings.get("output_subfolder") or "Converted")
    elif mode == "custom":
        custom = str(settings.get("output_custom") or "").strip()
        if custom:
            base = Path(custom)
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError:
        base = source.parent
    return base


def target_path(source, suffix: str, stem: str | None = None, folder: Path | None = None) -> Path:
    """Build a free output path. `suffix` includes the dot, e.g. '.png'."""
    source = Path(source)
    folder = Path(folder) if folder else output_dir_for(source)
    stem = sanitise_stem(stem if stem is not None else source.stem)
    candidate = folder / f"{stem}{suffix}"
    if settings.get("overwrite"):
        # Never silently clobber the file we are reading from.
        if candidate.resolve() != source.resolve():
            return candidate
    return unique(candidate)


def unique(path: Path) -> Path:
    path = Path(path)
    if not path.exists():
        return path
    stem, suffix, folder = path.stem, path.suffix, path.parent
    for index in range(1, 1000):
        candidate = folder / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
    import uuid

    return folder / f"{stem} ({uuid.uuid4().hex[:6]}){suffix}"


def reveal(path) -> None:
    """Open the containing folder with the file selected."""
    path = Path(path)
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(str(path))])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path.parent)])
    except OSError:
        pass


def open_file(path) -> None:
    try:
        if sys.platform == "win32":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except (OSError, AttributeError):
        pass


def human_size(num_bytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(num_bytes) < 1024 or unit == "GB":
            return f"{num_bytes:.0f} {unit}" if unit == "B" else f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} GB"
