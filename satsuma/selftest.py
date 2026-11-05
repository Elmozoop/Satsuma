"""`Satsuma.exe --self-test`: exercise every engine inside the built app and report.

Packaging can quietly drop a plugin, a DLL or a data file that a normal run from source never
misses. This runs the real code paths on throwaway files and writes one line per check.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import traceback
from pathlib import Path


def run(report: Path | None = None) -> int:
    from PySide6.QtGui import QImageReader
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    work = Path(tempfile.mkdtemp(prefix="satsuma-selftest-"))
    results: list[tuple[str, bool, str]] = []

    def check(name, fn):
        try:
            detail = fn()
            results.append((name, True, str(detail or "ok")))
        except Exception as exc:  # report, keep going
            results.append((name, False, f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}"))

    from PIL import Image, ImageDraw, ImageFont

    photo = work / "photo.png"
    Image.new("RGBA", (640, 400), (255, 140, 0, 180)).save(photo)

    from .engine import archives, documents, images, ocr, pdfs

    for ext in (".jpg", ".webp", ".avif", ".heic", ".ico", ".pdf"):
        check(f"image → {ext}", lambda e=ext: images.convert(photo, e).name)
    check("image compress to size", lambda: images.compress_to(photo, 0.3).name)
    check("image clean / b&w / square", lambda: [images.strip_metadata(photo).name, images.grayscale(photo).name,
                                                 images.pad_square(photo).name])
    pdf = images.to_pdf([photo])
    check("pdf render pages (pdfium)", lambda: len(pdfs.to_images(pdf, ".png", dpi=40)))
    check("pdf lock + unlock (AES)", lambda: pdfs.unlock(pdfs.lock(pdf, "pw"), "pw").name)
    check("pdf page numbers (Qt text)", lambda: pdfs.add_page_numbers(pdf).name)
    check("pdf compress", lambda: pdfs.compress_to(pdf, 0.5).name)
    md = work / "notes.md"
    md.write_text("# Title\n\nSome **bold** text\n", encoding="utf-8")
    check("markdown → pdf / html", lambda: [documents.convert(md, ".pdf").name, documents.convert(md, ".html").name])
    check("office available", lambda: {k: documents.office_available(k) for k in ("word", "sheets", "slides")})
    check("zip + extract", lambda: archives.extract(archives.zip_files([photo])).name)

    note = work / "note.png"
    picture = Image.new("RGB", (900, 220), "white")
    ImageDraw.Draw(picture).text((30, 60), "Satsuma self test", fill="black",
                                 font=ImageFont.truetype(r"C:\Windows\Fonts\segoeui.ttf", 56))
    picture.save(note)

    def read() -> str:
        text = ocr.read_text(note)
        if "Satsuma" not in text:
            raise RuntimeError(f"read {text!r}")
        return text

    check("text from picture (Windows OCR)", read)
    check("svg icons (for themed dropdowns)", lambda: _need(b"svg" in [bytes(f) for f in QImageReader.supportedImageFormats()]))
    from .config import ASSETS_DIR

    check("bundled assets", lambda: _need((ASSETS_DIR / "icon.png").exists(), str(ASSETS_DIR)))

    def glass_blur() -> str:
        from PySide6.QtGui import QImage

        from .ui.glass import blur_image

        return _need(not blur_image(QImage(120, 80, QImage.Format_RGB32)).isNull())

    def tour() -> str:
        from .ui.tutorial import Tutorial

        window = Tutorial()
        pages = sum(window.page(i) is not None for i in range(window.stack.count()))   # build every page
        window.deleteLater()
        return _need(pages == 8, f"{pages} pages")

    check("glass blur", glass_blur)
    check("tour builds", tour)

    def explorer_access() -> str:
        from PySide6.QtAxContainer import QAxObject

        return _need(not QAxObject("Shell.Application").isNull(), "Shell.Application")

    if sys.platform == "win32":
        check("keyboard shortcut can read Explorer", explorer_access)

    lines = [f"{'PASS' if ok else 'FAIL'}  {name}: {detail.splitlines()[0] if ok else detail}"
             for name, ok, detail in results]
    text = "\n".join(lines)
    if report:
        report.write_text(text + "\n" + json.dumps({"passed": sum(ok for _n, ok, _d in results),
                                                     "failed": sum(not ok for _n, ok, _d in results)}),
                          encoding="utf-8")
    print(text)
    shutil.rmtree(work, ignore_errors=True)
    del app
    return 0 if all(ok for _n, ok, _d in results) else 1


def _need(condition: bool, detail: str = "") -> str:
    if not condition:
        raise RuntimeError("missing")
    return detail or "ok"
