"""Which actions appear for which files, and how each one runs.

An action's `run(paths, params, progress)` returns a list of output paths.
Actions with `prompt` set ask the user for parameters after the drop.
"""
from __future__ import annotations

import importlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import filetypes as ft
from .engine import archives, documents, media
from .engine import ffmpeg_tool as ff

Progress = Callable[[float, str], None]


class _Lazy:
    """Imports an engine module on first use. Pillow and the PDF libraries cost ~30 MB,
    which a tray app idling in the background shouldn't carry until a job needs them."""

    def __init__(self, name: str):
        self._name = name

    def __getattr__(self, attr: str):
        return getattr(importlib.import_module(self._name), attr)


images = _Lazy("satsuma.engine.images")
pdfs = _Lazy("satsuma.engine.pdfs")


@dataclass(frozen=True)
class Action:
    id: str
    label: str            # big text on the tile
    caption: str          # small text under it
    group: str            # "convert" or "tools"
    run: Callable[[list[Path], dict, Progress], list[Path]]
    min_files: int = 1
    needs_ffmpeg: bool = False
    prompt: str | None = None  # "resize" | "trim" | "pages"
    skip_ext: tuple[str, ...] = field(default_factory=tuple)  # hide if every source has one of these
    icon: str | None = None    # name from ui/icons.py; None = big text label


def _each(fn) -> Callable[[list[Path], dict, Progress], list[Path]]:
    """Adapt a single-file function into a batch runner with progress."""

    def runner(paths: list[Path], params: dict, progress: Progress) -> list[Path]:
        outputs: list[Path] = []
        total = len(paths)
        for index, path in enumerate(paths):
            label = f"{path.name}  ({index + 1}/{total})" if total > 1 else path.name
            progress(index / total, label)
            with ff.progress_scope(lambda f, i=index, lb=label: progress((i + f) / total, lb)):
                result = fn(path, params)
            outputs.extend(result if isinstance(result, list) else [result])
        progress(1.0, "Done")
        return outputs

    return runner


def natural_key(path: Path):
    """'img2' before 'img10' — the order people expect for merge and join."""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", path.name)]


def _all(fn) -> Callable[[list[Path], dict, Progress], list[Path]]:
    def runner(paths: list[Path], params: dict, progress: Progress) -> list[Path]:
        paths = sorted(paths, key=natural_key)
        progress(0.0, f"{len(paths)} files")
        with ff.progress_scope(lambda f: progress(f, f"{len(paths)} files")):
            result = fn(paths, params)
        progress(1.0, "Done")
        return result if isinstance(result, list) else [result]

    return runner


# ----------------------------------------------------------------------------- images
def _image_actions() -> list[Action]:
    convert = [
        (".png", "PNG", "lossless"), (".jpg", "JPG", "photo"), (".webp", "WEBP", "small"),
        (".gif", "GIF", "palette"), (".tiff", "TIFF", "print"), (".ico", "ICO", "icon"),
    ]
    skips = {".jpg": (".jpg", ".jpeg", ".jpe", ".jfif"), ".tiff": (".tif", ".tiff")}
    actions = [
        Action(f"img-{ext[1:]}", label, caption, "convert",
               _each(lambda p, _params, e=ext: images.convert(p, e)),
               skip_ext=skips.get(ext, (ext,)))
        for ext, label, caption in convert
    ]
    actions += [
        Action("img-pdf", "PDF", "one document", "convert",
               _all(lambda ps, _params: images.to_pdf(ps))),
        Action("img-compress", "Compress", "smaller file", "tools",
               _each(lambda p, _params: images.compress(p)), icon="compress"),
        Action("img-resize", "Resize", "scale or width", "tools",
               _each(lambda p, params: images.resize(p, scale=params.get("scale"),
                                                     width=params.get("width"),
                                                     height=params.get("height"))),
               prompt="resize", icon="resize"),
        Action("img-rotate", "Rotate", "90° clockwise", "tools",
               _each(lambda p, _params: images.rotate(p, 90)), icon="rotate"),
        Action("img-flip", "Flip", "mirror", "tools",
               _each(lambda p, _params: images.flip(p, horizontal=True)), icon="flip"),
    ]
    return actions


# ----------------------------------------------------------------------------- video
def _video_actions() -> list[Action]:
    actions = [
        Action(f"vid-{ext[1:]}", ext[1:].upper(), caption, "convert",
               _each(lambda p, _params, e=ext: media.convert_video(p, e)),
               needs_ffmpeg=True, skip_ext=(ext,))
        for ext, caption in ((".mp4", "H.264"), (".mov", "QuickTime"), (".mkv", "Matroska"),
                             (".webm", "VP9"))
    ]
    actions += [
        Action("vid-gif", "GIF", "first 15 s", "convert",
               _each(lambda p, _params: media.to_gif(p)), needs_ffmpeg=True),
        Action("vid-mp3", "MP3", "audio only", "convert",
               _each(lambda p, _params: media.extract_audio(p, ".mp3")), needs_ffmpeg=True),
        Action("vid-compress", "Compress", "1080p max", "tools",
               _each(lambda p, _params: media.compress_video(p)), needs_ffmpeg=True, icon="compress"),
        Action("vid-trim", "Trim", "start → end", "tools",
               _each(lambda p, params: media.trim(p, params["start"], params["end"])),
               needs_ffmpeg=True, prompt="trim", icon="trim"),
        Action("vid-mute", "Mute", "drop audio", "tools",
               _each(lambda p, _params: media.mute(p)), needs_ffmpeg=True, icon="mute"),
        Action("vid-frame", "Frame", "still as PNG", "tools",
               _each(lambda p, _params: media.snapshot(p)), needs_ffmpeg=True, icon="frame"),
        Action("vid-join", "Join", "end to end", "tools",
               _all(lambda ps, _params: media.concat(ps)), min_files=2, needs_ffmpeg=True, icon="join"),
    ]
    return actions


# ----------------------------------------------------------------------------- audio
def _audio_actions() -> list[Action]:
    actions = [
        Action(f"aud-{ext[1:]}", ext[1:].upper(), caption, "convert",
               _each(lambda p, _params, e=ext: media.convert_audio(p, e)),
               needs_ffmpeg=True, skip_ext=(ext,))
        for ext, caption in ((".mp3", "universal"), (".m4a", "AAC"), (".wav", "uncompressed"),
                             (".flac", "lossless"), (".ogg", "Vorbis"), (".opus", "tiny"))
    ]
    actions += [
        Action("aud-trim", "Trim", "start → end", "tools",
               _each(lambda p, params: media.trim(p, params["start"], params["end"])),
               needs_ffmpeg=True, prompt="trim", icon="trim"),
        Action("aud-join", "Join", "end to end", "tools",
               _all(lambda ps, _params: media.concat(ps)), min_files=2, needs_ffmpeg=True, icon="join"),
    ]
    return actions


# ----------------------------------------------------------------------------- pdf
def _pdf_actions() -> list[Action]:
    return [
        Action("pdf-merge", "Merge", "one PDF", "convert",
               _all(lambda ps, _params: pdfs.merge(ps)), min_files=2, icon="merge"),
        Action("pdf-png", "PNG", "page images", "convert",
               _each(lambda p, _params: pdfs.to_images(p, ".png"))),
        Action("pdf-jpg", "JPG", "page images", "convert",
               _each(lambda p, _params: pdfs.to_images(p, ".jpg"))),
        Action("pdf-txt", "TXT", "extract text", "convert",
               _each(lambda p, _params: pdfs.to_text(p))),
        Action("pdf-compress", "Compress", "shrink images", "tools",
               _each(lambda p, _params: pdfs.compress(p)), icon="compress"),
        Action("pdf-split", "Split", "file per page", "tools",
               _each(lambda p, _params: pdfs.split_pages(p)), icon="split"),
        Action("pdf-pages", "Pages", "extract range", "tools",
               _each(lambda p, params: pdfs.extract_range(p, params["first"], params["last"])),
               prompt="pages", icon="pages"),
        Action("pdf-rotate", "Rotate", "90° clockwise", "tools",
               _each(lambda p, _params: pdfs.rotate(p, 90)), icon="rotate"),
    ]


# ----------------------------------------------------------------------------- documents
DOC_CAPTIONS = {".pdf": "document", ".docx": "Word", ".odt": "OpenDocument", ".rtf": "rich text",
                ".txt": "plain text", ".html": "web page", ".pptx": "PowerPoint",
                ".odp": "OpenDocument", ".xlsx": "Excel", ".ods": "OpenDocument", ".csv": "values"}


def _doc_action(ext: str) -> Action:
    return Action(f"doc-{ext[1:]}", ext[1:].upper(), DOC_CAPTIONS.get(ext, ""), "convert",
                  _each(lambda p, _params, e=ext: documents.convert(p, e)))


def _document_actions(paths: list[Path]) -> list[Action]:
    # Offer only targets every dropped document supports on this machine.
    common: list[str] | None = None
    for path in paths:
        targets = documents.can_convert(path.suffix)
        common = targets if common is None else [t for t in common if t in targets]
    return [_doc_action(ext) for ext in (common or [])]


# ----------------------------------------------------------------------------- shared
ZIP = Action("any-zip", "ZIP", "compress to zip", "tools",
             _all(lambda ps, _params: archives.zip_files(ps)), icon="zip")
EXTRACT = Action("zip-extract", "Extract", "unzip here", "tools",
                 _each(lambda p, _params: archives.extract(p)), icon="extract")
MIXED_PDF = Action("mix-pdf", "PDF", "merge all", "convert",
                   _all(lambda ps, _params: pdfs.merge(ps) if len(ps) > 1 else images.to_pdf(ps)), icon="merge")


def actions_for(paths, customise: bool = True) -> list[Action]:
    paths = [Path(p) for p in paths]
    category = ft.category_for(paths)
    if category == ft.IMAGE:
        candidates = _image_actions()
    elif category == ft.VIDEO:
        candidates = _video_actions()
    elif category == ft.AUDIO:
        candidates = _audio_actions()
    elif category == ft.PDF:
        candidates = _pdf_actions()
    elif category == ft.DOCUMENT:
        candidates = _document_actions(paths)
    elif category == ft.ARCHIVE:
        candidates = [EXTRACT] if all(p.suffix.lower() == ".zip" for p in paths) else []
    elif category == ft.MIXED and {ft.category_of(p) for p in paths} <= {ft.IMAGE, ft.PDF}:
        candidates = [MIXED_PDF]
    else:
        candidates = []

    if any(p.is_dir() for p in paths):
        candidates = []  # folders: only zipping makes sense

    extensions = {p.suffix.lower() for p in paths}
    visible = [
        action for action in candidates
        if len(paths) >= action.min_files
        and not (action.skip_ext and extensions <= set(action.skip_ext))
    ]
    if category != ft.ARCHIVE or not all(p.suffix.lower() == ".zip" for p in paths):
        visible.append(ZIP)
    return customised(category, visible) if customise else visible


# ----------------------------------------------------------------------------- customisation
def customised(category: str, actions: list[Action]) -> list[Action]:
    """Apply the user's hidden list and ordering for this file category."""
    from .config import settings

    hidden = set(settings.get("actions_hidden") or [])
    order = (settings.get("actions_order") or {}).get(category) or []
    rank = {action_id: index for index, action_id in enumerate(order)}
    shown = [a for a in actions if f"{category}:{a.id}" not in hidden]
    # Stable sort: known ids by the user's order, new ones keep their default place after.
    return sorted(shown, key=lambda a: (0, rank[a.id]) if a.id in rank else (1, actions.index(a)))


def catalogue() -> list[tuple[str, str, list[Action]]]:
    """Every action Satsuma can offer, per file category, in default order (for Settings)."""
    docs = [_doc_action(e) for e in (".pdf", ".docx", ".odt", ".rtf", ".txt", ".html",
                                     ".pptx", ".odp", ".xlsx", ".ods", ".csv")]
    return [
        (ft.IMAGE, "Images", _image_actions() + [ZIP]),
        (ft.VIDEO, "Videos", _video_actions() + [ZIP]),
        (ft.AUDIO, "Audio", _audio_actions() + [ZIP]),
        (ft.PDF, "PDFs", _pdf_actions() + [ZIP]),
        (ft.DOCUMENT, "Documents", docs + [ZIP]),
        (ft.ARCHIVE, "Archives", [EXTRACT, ZIP]),
        (ft.MIXED, "Mixed files", [MIXED_PDF, ZIP]),
        (ft.OTHER, "Other files", [ZIP]),
    ]


def ensure_requirements(action: Action, progress: Progress) -> None:
    if action.needs_ffmpeg and not ff.available():
        ff.ensure(lambda fraction, message: progress(fraction * 0.99, message))
