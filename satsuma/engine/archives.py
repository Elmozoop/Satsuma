"""ZIP creation and extraction (stdlib only)."""
from __future__ import annotations

import os
import zipfile
from pathlib import Path

from .paths import output_dir_for, target_path, unique


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


def extract(source) -> Path:
    """Extract next to the archive into a folder named after it. Blocks path traversal."""
    source = Path(source)
    folder = unique(output_dir_for(source) / source.stem)
    folder.mkdir(parents=True, exist_ok=True)
    root = folder.resolve()
    with zipfile.ZipFile(source) as zf:
        for member in zf.infolist():
            target = (folder / member.filename).resolve()
            if root != target and root not in target.parents:
                raise ValueError(f"Unsafe path inside archive: {member.filename}")
        zf.extractall(folder)
    return folder
