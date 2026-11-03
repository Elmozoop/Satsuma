"""Document conversion.

Strategy, in order:
  * .txt / .md / .html  -> PDF with Qt's own renderer (no extra software).
  * Office formats       -> LibreOffice if installed, otherwise Microsoft Office
                            through COM (Word / PowerPoint / Excel), driven by a
                            short PowerShell script so no pywin32 is needed.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from ..config import DATA_DIR
from .ffmpeg_tool import NO_WINDOW, ConversionError
from .paths import target_path

# One LibreOffice at a time, with its own persistent profile: fast after the first run,
# and never collides with a LibreOffice window the user already has open.
_LO_LOCK = threading.Lock()
_LO_PROFILE = DATA_DIR / "libreoffice-profile"

TEXTISH = {".txt", ".md", ".markdown", ".html", ".htm", ".csv"}
WORD = {".doc", ".docx", ".odt", ".rtf"}
SLIDES = {".ppt", ".pptx", ".odp"}
SHEETS = {".xls", ".xlsx", ".ods"}
OFFICE = WORD | SLIDES | SHEETS | {".epub"}

# What LibreOffice can produce from each family.
LO_TARGETS = {
    "word": [".pdf", ".docx", ".odt", ".rtf", ".txt", ".html"],
    "slides": [".pdf", ".pptx", ".odp"],
    "sheets": [".pdf", ".xlsx", ".ods", ".csv"],
}
LO_FILTERS = {  # explicit export filters avoid LibreOffice guessing wrong
    ".pdf": None,
    ".docx": "docx:MS Word 2007 XML",
    ".odt": "odt",
    ".rtf": "rtf",
    ".txt": "txt:Text (encoded):UTF8",
    ".html": "html:XHTML Writer File:UTF8",
    ".pptx": "pptx:Impress MS PowerPoint 2007 XML",
    ".odp": "odp",
    ".xlsx": "xlsx:Calc MS Excel 2007 XML",
    ".ods": "ods",
    ".csv": "csv:Text - txt - csv (StarCalc):44,34,76",
}


def family(extension: str) -> str | None:
    extension = extension.lower()
    if extension in WORD or extension == ".epub":
        return "word"
    if extension in SLIDES:
        return "slides"
    if extension in SHEETS:
        return "sheets"
    return None


# --------------------------------------------------------------------------- LibreOffice
def libreoffice_path() -> Path | None:
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return Path(found)
    if sys.platform == "win32":
        roots = [os.environ.get("ProgramFiles", r"C:\Program Files"),
                 os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")]
        for root in roots:
            candidate = Path(root) / "LibreOffice" / "program" / "soffice.exe"
            if candidate.is_file():
                return candidate
    return None


def _libreoffice_convert(source: Path, extension: str) -> Path:
    binary = libreoffice_path()
    if binary is None:
        raise ConversionError("LibreOffice is not installed.")
    filter_spec = LO_FILTERS.get(extension)
    target = extension.lstrip(".") if filter_spec is None else filter_spec
    work = Path(tempfile.mkdtemp(prefix="satsuma-lo-"))
    profile = _LO_PROFILE.as_uri()
    try:
        with _LO_LOCK:
            completed = subprocess.run(
                [str(binary), f"-env:UserInstallation={profile}", "--headless", "--norestore",
                 "--convert-to", target, "--outdir", str(work / "out"), str(source)],
                capture_output=True, stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace",
                timeout=600, creationflags=NO_WINDOW,
            )
        produced = list((work / "out").glob(f"*{extension}")) if (work / "out").exists() else []
        if not produced:
            detail = (completed.stderr or completed.stdout or "").strip().splitlines()
            raise ConversionError(detail[-1] if detail else "LibreOffice produced no output.")
        destination = target_path(source, extension)
        shutil.move(str(produced[0]), destination)
        return destination
    except subprocess.TimeoutExpired as exc:
        raise ConversionError("LibreOffice timed out.") from exc
    finally:
        shutil.rmtree(work, ignore_errors=True)


# --------------------------------------------------------------------------- Microsoft Office
_PS_SCRIPT = r"""
param([string]$Kind, [string]$Src, [string]$Dst)
$ErrorActionPreference = 'Stop'
$app = $null
try {
  switch ($Kind) {
    'word' {
      $app = New-Object -ComObject Word.Application
      $app.Visible = $false
      $app.DisplayAlerts = 0
      $doc = $app.Documents.Open($Src, $false, $true)   # ConfirmConversions, ReadOnly
      $doc.ExportAsFixedFormat($Dst, 17)                # wdExportFormatPDF
      $doc.Close(0)
    }
    'slides' {
      $app = New-Object -ComObject PowerPoint.Application
      $pres = $app.Presentations.Open($Src, -1, 0, 0)    # ReadOnly, Untitled, WithWindow=false
      $pres.SaveAs($Dst, 32)                             # ppSaveAsPDF
      $pres.Close()
    }
    'sheets' {
      $app = New-Object -ComObject Excel.Application
      $app.Visible = $false
      $app.DisplayAlerts = $false
      $book = $app.Workbooks.Open($Src, 0, $true)       # UpdateLinks, ReadOnly
      $book.ExportAsFixedFormat(0, $Dst)                 # xlTypePDF
      $book.Close($false)
    }
  }
} finally {
  if ($app -ne $null) {
    try { $app.Quit() } catch {}
    [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($app)
  }
}
"""


def office_available(kind: str) -> bool:
    if sys.platform != "win32":
        return False
    import winreg  # type: ignore[import-not-found]

    prog_id = {"word": "Word.Application", "slides": "PowerPoint.Application",
               "sheets": "Excel.Application"}.get(kind)
    if not prog_id:
        return False
    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, prog_id + r"\CLSID"))
        return True
    except OSError:
        return False


def _office_to_pdf(source: Path, kind: str) -> Path:
    destination = target_path(source, ".pdf")
    work = Path(tempfile.mkdtemp(prefix="satsuma-ms-"))
    script = work / "convert.ps1"
    script.write_text(_PS_SCRIPT, encoding="utf-8-sig")
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(script), "-Kind", kind,
             "-Src", str(source.resolve()), "-Dst", str(destination.resolve())],
            capture_output=True, stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace", timeout=600, creationflags=NO_WINDOW,
        )
        if completed.returncode != 0 or not destination.exists():
            detail = (completed.stderr or completed.stdout or "").strip().splitlines()
            raise ConversionError(detail[0] if detail else "Microsoft Office could not convert this file.")
        return destination
    except subprocess.TimeoutExpired as exc:
        raise ConversionError("Microsoft Office timed out.") from exc
    finally:
        shutil.rmtree(work, ignore_errors=True)


# --------------------------------------------------------------------------- Qt text renderer
# Qt's text engine (QFont/QTextDocument) is only safe on the GUI thread, but jobs run on
# worker threads. A small QObject living on the GUI thread runs the render for them.
_gui_runner = None


def install_gui_runner() -> None:
    """Call once from the GUI thread at startup."""
    global _gui_runner
    from PySide6.QtCore import QObject, Qt, Signal, Slot

    class _GuiRunner(QObject):
        request = Signal(object)

        def __init__(self):
            super().__init__()
            self.request.connect(self._run, Qt.BlockingQueuedConnection)

        @Slot(object)
        def _run(self, box: dict) -> None:
            try:
                box["result"] = box["fn"]()
            except BaseException as exc:  # handed back to the worker
                box["error"] = exc

    _gui_runner = _GuiRunner()


def _on_gui_thread(fn):
    from PySide6.QtCore import QCoreApplication, QThread

    app = QCoreApplication.instance()
    if app is None or QThread.currentThread() is app.thread() or _gui_runner is None:
        return fn()
    box: dict = {"fn": fn}
    _gui_runner.request.emit(box)  # blocks until the GUI thread has run it
    if "error" in box:
        raise box["error"]
    return box["result"]


def _text_to_pdf(source: Path) -> Path:
    return _on_gui_thread(lambda: _render_text_pdf(source))


def _render_text_pdf(source: Path) -> Path:
    from PySide6.QtCore import QMarginsF, QSizeF
    from PySide6.QtGui import QFont, QFontDatabase, QPageLayout, QPageSize, QPdfWriter, QTextDocument

    if not QFontDatabase.families():
        # Qt would quietly write pages with no text on them.
        raise ConversionError("No fonts are available to lay out the text.")

    raw = source.read_bytes()
    text = None
    for encoding in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    text = text or raw.decode("utf-8", errors="replace")

    destination = target_path(source, ".pdf")
    writer = QPdfWriter(str(destination))
    writer.setResolution(300)
    writer.setPageLayout(QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait,
                                     QMarginsF(18, 18, 18, 18), QPageLayout.Millimeter))
    writer.setTitle(source.stem)

    document = QTextDocument()
    document.setDefaultFont(QFont("Segoe UI", 10))
    extension = source.suffix.lower()
    if extension in (".md", ".markdown"):
        document.setMarkdown(text)
    elif extension in (".html", ".htm"):
        document.setHtml(text)
    else:
        mono = QFont("Consolas", 9)
        mono.setStyleHint(QFont.Monospace)
        document.setDefaultFont(mono)
        document.setPlainText(text)

    layout = writer.pageLayout()
    paint_rect = layout.paintRectPixels(writer.resolution())
    document.setPageSize(QSizeF(paint_rect.width(), paint_rect.height()))
    document.print_(writer)
    del writer  # flushes the file
    if not destination.exists() or destination.stat().st_size == 0:
        raise ConversionError("Could not write the PDF.")
    return destination


# --------------------------------------------------------------------------- public API
def can_convert(extension: str) -> list[str]:
    """Target extensions available for a source on this machine."""
    extension = extension.lower()
    if extension in TEXTISH and extension != ".csv":
        targets = [".pdf"]
        if libreoffice_path() and extension in (".txt", ".html", ".htm"):
            targets.append(".docx")
        return targets
    kind = family(extension)
    if kind is None and extension == ".csv":
        kind = "sheets"
    if kind is None:
        return []
    if libreoffice_path():
        return [t for t in LO_TARGETS[kind] if t != extension]
    if extension != ".csv" and office_available(kind):
        return [".pdf"]
    return []


def convert(source, extension: str) -> Path:
    source = Path(source)
    extension = extension.lower()
    src_ext = source.suffix.lower()
    if extension == ".pdf" and src_ext in (".txt", ".md", ".markdown", ".html", ".htm"):
        return _text_to_pdf(source)
    if libreoffice_path():
        return _libreoffice_convert(source, extension)
    kind = family(src_ext)
    if extension == ".pdf" and kind and office_available(kind):
        return _office_to_pdf(source, kind)
    raise ConversionError(
        "Converting this document needs LibreOffice (free) or Microsoft Office. "
        "Install either one and try again."
    )
