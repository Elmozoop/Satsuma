"""PDF merge, split, rotate, render-to-image, extract text and compress."""
from __future__ import annotations

import io
import threading
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from .paths import target_path, unique

try:
    import pypdfium2 as pdfium

    RENDER_OK = True
except Exception:  # pragma: no cover - optional dependency
    RENDER_OK = False


_PDFIUM_LOCK = threading.Lock()  # pdfium must never run on two threads at once


class PdfLocked(RuntimeError):
    """The PDF is password protected."""


def _reader(path) -> PdfReader:
    reader = PdfReader(str(path))
    if reader.is_encrypted:
        # Many PDFs are "encrypted" with an empty owner password.
        try:
            if reader.decrypt("") == 0:
                raise PdfLocked("This PDF is password protected.")
        except PdfLocked:
            raise
        except Exception as exc:
            raise PdfLocked("This PDF is password protected.") from exc
    return reader


def page_count(path) -> int:
    return len(_reader(path).pages)


def _write(writer: PdfWriter, destination: Path) -> Path:
    with open(destination, "wb") as handle:
        writer.write(handle)
    return destination


def merge(sources, destination_hint=None) -> Path:
    """Merge PDFs (and any images among them) into one document, in order."""
    sources = [Path(p) for p in sources]
    if len(sources) < 2:
        raise ValueError("Merging needs at least two files.")
    writer = PdfWriter()
    for path in sources:
        if path.suffix.lower() == ".pdf":
            for page in _reader(path).pages:
                writer.add_page(page)
        else:
            from . import images as image_engine

            with image_engine._load(path) as image:  # noqa: SLF001 - internal helper by design
                prepared = image_engine._prepare(image, "PDF")  # noqa: SLF001
                buffer = io.BytesIO()
                prepared.save(buffer, "PDF", resolution=96.0)
            buffer.seek(0)
            for page in PdfReader(buffer).pages:
                writer.add_page(page)

    base = Path(destination_hint) if destination_hint else sources[0]
    destination = target_path(base, ".pdf", stem=f"{base.stem}-merged")
    return _write(writer, destination)


def split_pages(source) -> list[Path]:
    """One new PDF per page."""
    source = Path(source)
    reader = _reader(source)
    total = len(reader.pages)
    width = len(str(total))
    outputs: list[Path] = []
    folder = target_path(source, "", stem=f"{source.stem}-pages")
    folder.mkdir(parents=True, exist_ok=True)
    for index, page in enumerate(reader.pages, start=1):
        writer = PdfWriter()
        writer.add_page(page)
        outputs.append(_write(writer, unique(folder / f"{source.stem}-{index:0{width}d}.pdf")))
    return outputs


def extract_range(source, first: int, last: int) -> Path:
    """Pull pages `first`..`last` (1-based, inclusive) into a new PDF."""
    source = Path(source)
    reader = _reader(source)
    total = len(reader.pages)
    first = max(1, min(total, int(first)))
    last = max(first, min(total, int(last)))
    writer = PdfWriter()
    for index in range(first - 1, last):
        writer.add_page(reader.pages[index])
    label = f"p{first}" if first == last else f"p{first}-{last}"
    return _write(writer, target_path(source, ".pdf", stem=f"{source.stem}-{label}"))


def rotate(source, degrees: int) -> Path:
    """Rotate every page clockwise by a multiple of 90."""
    if degrees % 90 != 0:
        raise ValueError("Rotation must be a multiple of 90 degrees.")
    source = Path(source)
    reader = _reader(source)
    writer = PdfWriter()
    for page in reader.pages:
        page.rotate(degrees % 360)
        writer.add_page(page)
    return _write(writer, target_path(source, ".pdf", stem=f"{source.stem}-rotated"))


def to_images(source, extension: str = ".png", dpi: int = 150) -> list[Path]:
    """Render each page to an image file."""
    if not RENDER_OK:
        raise RuntimeError("PDF rendering needs pypdfium2 (pip install pypdfium2).")
    with _PDFIUM_LOCK:
        return _to_images_locked(Path(source), extension.lower(), dpi)


def _to_images_locked(source: Path, extension: str, dpi: int) -> list[Path]:
    document = pdfium.PdfDocument(str(source))
    try:
        total = len(document)
        width = len(str(total))
        folder = target_path(source, "", stem=f"{source.stem}-pages")
        folder.mkdir(parents=True, exist_ok=True)
        outputs: list[Path] = []
        scale = max(0.1, dpi / 72.0)
        for index in range(total):
            page = document[index]
            bitmap = page.render(scale=scale)
            image = bitmap.to_pil()
            if extension in (".jpg", ".jpeg") and image.mode != "RGB":
                image = image.convert("RGB")
            destination = unique(folder / f"{source.stem}-{index + 1:0{width}d}{extension}")
            if extension in (".jpg", ".jpeg"):
                image.save(destination, "JPEG", quality=90, optimize=True)
            else:
                image.save(destination)
            image.close()
            outputs.append(destination)
        return outputs
    finally:
        document.close()


def to_text(source) -> Path:
    """Extract the text layer to a .txt file."""
    source = Path(source)
    reader = _reader(source)
    chunks = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        chunks.append(f"--- Page {index} ---\n{text.strip()}\n")
    destination = target_path(source, ".txt")
    destination.write_text("\n".join(chunks), encoding="utf-8")
    return destination


def compress(source, max_image_edge: int = 1600, quality: int = 70) -> Path:
    """Shrink a PDF by downsampling embedded images and packing content streams.

    Text and vectors are preserved; only raster images are re-encoded.
    """
    source = Path(source)
    writer = _shrunk(source, max_image_edge, quality)
    destination = target_path(source, ".pdf", stem=f"{source.stem}-compressed")
    return _write(writer, destination)


# Gentlest first: the first level that reaches the chosen size wins.
PDF_LEVELS = [(2000, 80), (1600, 70), (1400, 55), (1200, 45), (1000, 35), (800, 28), (600, 22), (450, 15)]


def compress_to(source, ratio: float) -> Path:
    """Shrink towards `ratio` × the original size by stepping down picture quality and size.
    Text stays sharp at every level; only pictures get softer."""
    source = Path(source)
    target = int(source.stat().st_size * ratio)
    smallest = None
    for edge, quality in PDF_LEVELS:
        buffer = io.BytesIO()
        _shrunk(source, edge, quality).write(buffer)
        data = buffer.getvalue()
        if smallest is None or len(data) < len(smallest):
            smallest = data
        if len(data) <= target:
            break
    destination = target_path(source, ".pdf", stem=f"{source.stem}-compressed")
    destination.write_bytes(smallest)
    return destination


def _shrunk(source: Path, max_image_edge: int, quality: int) -> PdfWriter:
    reader = _reader(source)
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)

    from PIL import Image

    for page in writer.pages:
        try:
            embedded = list(page.images)
        except Exception:
            embedded = []
        for item in embedded:
            try:
                image = item.image
                if image is None:
                    continue
                if max(image.size) > max_image_edge:
                    ratio = max_image_edge / max(image.size)
                    new_size = (max(1, round(image.size[0] * ratio)),
                                max(1, round(image.size[1] * ratio)))
                    image = image.resize(new_size, Image.LANCZOS)
                if image.mode in ("RGBA", "LA", "P"):
                    image = image.convert("RGB")
                item.replace(image, quality=quality, optimize=True)
            except Exception:
                continue  # leave that image untouched rather than corrupt the page
        try:
            page.compress_content_streams()
        except Exception:
            pass
    return writer


# ----------------------------------------------------------------------------- passwords
def is_encrypted(path) -> bool:
    """True if opening the PDF needs a password (not just an empty owner password)."""
    try:
        reader = PdfReader(str(path))
        return bool(reader.is_encrypted) and reader.decrypt("") == 0
    except Exception:
        return False


def lock(source, password: str) -> Path:
    """A copy that asks for `password` to open (AES-256)."""
    source = Path(source)
    if not password:
        raise ValueError("Type a password first.")
    writer = PdfWriter()
    writer.append(_reader(source))
    writer.encrypt(user_password=password, owner_password=password, algorithm="AES-256")
    return _write(writer, target_path(source, ".pdf", stem=f"{source.stem}-locked"))


def unlock(source, password: str) -> Path:
    """A copy without the password, for someone who knows it."""
    source = Path(source)
    reader = PdfReader(str(source))
    if not reader.is_encrypted:
        raise ValueError("This PDF has no password.")
    try:
        ok = reader.decrypt(password)
    except Exception as exc:
        raise PdfLocked(f"Couldn't open it with that password ({exc}).") from exc
    if ok == 0:
        raise PdfLocked("That password isn't right.")
    writer = PdfWriter()
    writer.append(reader)
    return _write(writer, target_path(source, ".pdf", stem=f"{source.stem}-unlocked"))


# ----------------------------------------------------------------------------- page numbers
def add_page_numbers(source) -> Path:
    """Stamp "3 / 12" at the bottom centre of every page."""
    from .documents import _on_gui_thread

    source = Path(source)
    reader = _reader(source)
    writer = PdfWriter()
    writer.append(reader)
    sizes = []
    for page in writer.pages:
        page.transfer_rotation_to_content()     # so "bottom" is the bottom the reader sees
        box = page.mediabox
        sizes.append((float(box.width), float(box.height), float(box.left), float(box.bottom)))
    overlay = PdfReader(io.BytesIO(_on_gui_thread(lambda: _number_pages([s[:2] for s in sizes]))))
    for page, stamp, (_w, _h, left, bottom) in zip(writer.pages, overlay.pages, sizes):
        page.merge_translated_page(stamp, left, bottom)
    return _write(writer, target_path(source, ".pdf", stem=f"{source.stem}-numbered"))


def _number_pages(sizes: list[tuple[float, float]]) -> bytes:
    """A PDF of transparent pages, each the given size in points, with only its number on it.
    Qt's text engine has to run on the GUI thread."""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QMarginsF, QRectF, QSizeF, Qt
    from PySide6.QtGui import QColor, QFont, QPageLayout, QPageSize, QPainter, QPdfWriter

    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    writer = QPdfWriter(buffer)
    writer.setResolution(72)    # 1 unit = 1 point, the PDF's own unit

    def size_page(width: float, height: float) -> None:
        writer.setPageLayout(QPageLayout(QPageSize(QSizeF(width, height), QPageSize.Point),
                                         QPageLayout.Portrait, QMarginsF(0, 0, 0, 0)))

    size_page(*sizes[0])
    painter = QPainter(writer)
    font = QFont("Segoe UI")
    font.setPointSizeF(9)
    painter.setFont(font)
    painter.setPen(QColor(90, 90, 90))
    total = len(sizes)
    for index, (width, height) in enumerate(sizes):
        if index:
            size_page(width, height)
            writer.newPage()
        painter.drawText(QRectF(0, height - 30, width, 16), Qt.AlignCenter, f"{index + 1} / {total}")
    painter.end()
    buffer.close()
    return bytes(data)
