"""ZIP creation; extraction of zip, tar (.gz/.bz2/.xz), single compressed files, 7z and rar."""
from __future__ import annotations

import bz2
import gzip
import lzma
import os
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

from .ffmpeg_tool import NO_WINDOW, ConversionError
from .paths import output_dir_for, target_path, unique

TAR_SUFFIXES = (".tar.gz", ".tar.bz2", ".tar.xz", ".tgz", ".tar")
SINGLE_FILE = {".gz": gzip.open, ".bz2": bz2.open, ".xz": lzma.open}   # one compressed file, not a tar
NEEDS_BSDTAR = {".7z", ".rar"}


def zip_files(sources) -> Path:
    sources = [Path(p) for p in sources]
    if not sources:
        raise ValueError("Nothing to zip.")
    stem = sources[0].stem if len(sources) == 1 else f"{sources[0].stem}-and-{len(sources) - 1}-more"
    destination = target_path(sources[0], ".zip", stem=stem)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for source in sources:
            if source.is_dir():
                for root, _dirs, files in os.walk(source):
                    for name in files:
                        full = Path(root) / name
                        if full.resolve() == destination.resolve():
                            continue
                        zf.write(full, full.relative_to(source.parent))
            else:
                zf.write(source, source.name)
    return destination


def _bsdtar() -> Path | None:
    """Windows 10+ ships bsdtar (libarchive), which reads 7z and rar. Not Git's GNU tar."""
    tar = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "tar.exe"
    return tar if tar.is_file() else None


def can_extract(path) -> bool:
    name = Path(path).name.lower()
    suffix = Path(path).suffix.lower()
    if suffix == ".zip" or name.endswith(TAR_SUFFIXES) or suffix in SINGLE_FILE:
        return True
    return suffix in NEEDS_BSDTAR and _bsdtar() is not None


def _folder_name(source: Path) -> str:
    lower = source.name.lower()
    for suffix in TAR_SUFFIXES:
        if lower.endswith(suffix):
            return source.name[: -len(suffix)] or source.stem
    return source.stem


def extract(source) -> Path:
    """Unpack next to the archive into a folder named after it. Blocks path traversal."""
    source = Path(source)
    suffix = source.suffix.lower()
    if suffix in SINGLE_FILE and not tarfile.is_tarfile(source):
        # "notes.txt.gz" -> "notes.txt" beside it.
        destination = target_path(source, "", stem=source.stem)
        with SINGLE_FILE[suffix](source, "rb") as packed, open(destination, "wb") as out:
            shutil.copyfileobj(packed, out)
        return destination

    folder = unique(output_dir_for(source) / _folder_name(source))
    folder.mkdir(parents=True, exist_ok=True)
    try:
        if suffix == ".zip":
            _extract_zip(source, folder)
        elif tarfile.is_tarfile(source):
            with tarfile.open(source) as tf:
                tf.extractall(folder, filter="data")   # refuses absolute paths, "..", odd links
        elif suffix in NEEDS_BSDTAR:
            _extract_bsdtar(source, folder)
        else:
            raise ConversionError("This doesn't look like an archive Satsuma can open.")
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)   # no half-filled folder left behind
        raise
    return folder


def _extract_zip(source: Path, folder: Path) -> None:
    root = folder.resolve()
    with zipfile.ZipFile(source) as zf:
        for member in zf.infolist():
            target = (folder / member.filename).resolve()
            if root != target and root not in target.parents:
                raise ValueError(f"Unsafe path inside archive: {member.filename}")
        zf.extractall(folder)


def _extract_bsdtar(source: Path, folder: Path) -> None:
    tar = _bsdtar()
    if tar is None:
        raise ConversionError("Opening .7z and .rar needs Windows 10 or newer.")
    # bsdtar refuses absolute paths and ".." entries unless told otherwise (-P).
    completed = subprocess.run([str(tar), "-xf", str(source), "-C", str(folder)],
                               capture_output=True, stdin=subprocess.DEVNULL, encoding="utf-8",
                               errors="replace", timeout=1800, creationflags=NO_WINDOW)
    if completed.returncode != 0:
        detail = (completed.stderr or "").strip().splitlines()
        message = detail[-1] if detail else f"exit code {completed.returncode}"
        if "passphrase" in message.lower() or "encrypt" in message.lower():
            message = "This archive is password protected."
        raise ConversionError(f"Couldn't extract it: {message}")
