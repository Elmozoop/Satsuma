"""Small previews of files: for the ring's centre, prompts and result cards.

Images are decoded at reduced size (a 50 MB photo stays quick), PDFs show their first page, and
anything else falls back to the file's Windows icon. Results are cached per file version.
"""
from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QFileInfo, QSize, Qt
from PySide6.QtGui import QImage, QImageReader, QPixmap
from PySide6.QtWidgets import QFileIconProvider

from .. import filetypes as ft

PILLOW_ONLY = {".heic", ".heif", ".avif", ".tga", ".ppm", ".pgm"}


def thumbnail(path, size: int) -> QImage | None:
    """A preview at most `size` px on its longest side, or None if there's nothing to show."""
    path = Path(path)
    try:
        stat = path.stat()
    except OSError:
        return None
    if path.is_dir():
        return None
    return _cached(str(path), stat.st_mtime_ns, stat.st_size, size)


@lru_cache(maxsize=48)
def _cached(path: str, _mtime: int, _size: int, size: int) -> QImage | None:
    suffix = Path(path).suffix.lower()
    try:
        if suffix == ".pdf":
            return _pdf_page(path, size)
        if ft.category_of(Path(path)) == ft.IMAGE:
            return _pillow(path, size) if suffix in PILLOW_ONLY else (_qt(path, size) or _pillow(path, size))
    except Exception:
        return None
    return None


def _qt(path: str, size: int) -> QImage | None:
    reader = QImageReader(path)
    reader.setAutoTransform(True)          # honour the camera's rotation
    original = reader.size()
    if not original.isValid():
        return None
    scaled = original.scaled(QSize(size, size), Qt.KeepAspectRatio)
    if original.width() > scaled.width():
        reader.setScaledSize(scaled)       # decode small: much faster and lighter than decoding all
    image = reader.read()
    return None if image.isNull() else image


def _pillow(path: str, size: int) -> QImage | None:
    from PIL import Image, ImageOps

    from ..engine import images        # registers HEIC/AVIF support

    _ = images
    with Image.open(path) as picture:
        picture.draft("RGB", (size, size))
        picture = ImageOps.exif_transpose(picture) or picture
        picture.thumbnail((size, size))
        buffer = io.BytesIO()
        picture.convert("RGBA").save(buffer, "PNG")
    image = QImage()
    image.loadFromData(buffer.getvalue(), "PNG")
    return None if image.isNull() else image


def _pdf_page(path: str, size: int) -> QImage | None:
    from ..engine import pdfs

    if not pdfs.RENDER_OK or pdfs.is_encrypted(path):
        return None
    with pdfs._PDFIUM_LOCK:   # noqa: SLF001 - pdfium must never run on two threads at once
        document = pdfs.pdfium.PdfDocument(path)
        try:
            page = document[0]
            width, height = page.get_size()
            bitmap = page.render(scale=size / max(width, height, 1))
            picture = bitmap.to_pil()
        finally:
            document.close()
    buffer = io.BytesIO()
    picture.save(buffer, "PNG")
    image = QImage()
    image.loadFromData(buffer.getvalue(), "PNG")
    return None if image.isNull() else image


def file_icon(path, size: int) -> QPixmap:
    """The icon Windows shows for this file (or folder)."""
    return QFileIconProvider().icon(QFileInfo(str(path))).pixmap(size, size)
