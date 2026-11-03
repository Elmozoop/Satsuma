"""Document conversion.

Strategy, in order:
  * .txt / .md / .html  -> PDF, and Markdown <-> HTML <-> text, with Qt (no extra software).
  * .csv <-> .json      -> plain Python.
  * Office formats       -> LibreOffice if installed, otherwise Microsoft Office
                            through COM (Word / PowerPoint / Excel), driven by a
                            short PowerShell script so no pywin32 is needed.
"""
from __future__ import annotations

import csv
import json
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
param([string]$Kind, [string]$Src, [string]$Dst, [string]$Fmt)
$ErrorActionPreference = 'Stop'
$app = $null
$m = [Type]::Missing
# A dummy password makes protected files fail at once instead of waiting on a hidden prompt.
$probe = 'satsuma-not-a-password'
try {
  switch ($Kind) {
    'word' {
      $app = New-Object -ComObject Word.Application
      $app.Visible = $false
      $app.DisplayAlerts = 0
      # Word guesses short HTML files are plain text unless told (wdOpenFormatWebPages = 7).
      $open = if ($Src -match '\.html?$') { 7 } else { 0 }
      $doc = $app.Documents.Open($Src, $false, $true, $false, $probe, $m, $m, $m, $m, $open)   # ..., Password, ..., Format
      if ($Fmt -eq 'pdf') { $doc.ExportAsFixedFormat($Dst, 17) }        # wdExportFormatPDF
      elseif ($Fmt -eq 'utf8') { $doc.SaveAs2($Dst, 2, $m, $m, $false, $m, $m, $m, $m, $m, $m, 65001) }   # plain text, UTF-8
      else { $doc.SaveAs2($Dst, [int]$Fmt, $m, $m, $false) }
      $doc.Close(0)
    }
    'slides' {
      $app = New-Object -ComObject PowerPoint.Application
      $pres = $app.Presentations.Open($Src, -1, 0, 0)    # ReadOnly, Untitled, WithWindow=false
      $pres.SaveAs($Dst, [int]$Fmt)
      $pres.Close()
    }
    'sheets' {
      $app = New-Object -ComObject Excel.Application
      $app.Visible = $false
      $app.DisplayAlerts = $false
      $book = $app.Workbooks.Open($Src, 0, $true, $m, $probe)   # UpdateLinks, ReadOnly, Format, Password
      if ($Fmt -eq 'pdf') { $book.ExportAsFixedFormat(0, $Dst) }   # xlTypePDF
      else { $book.SaveAs($Dst, [int]$Fmt) }
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

# File-format codes for SaveAs in each Office app ("pdf"/"utf8" are handled specially above).
OFFICE_TARGETS = {
    "word": {".pdf": "pdf", ".docx": "16", ".doc": "0", ".rtf": "6", ".odt": "23", ".txt": "utf8",
             ".html": "10"},
    "sheets": {".pdf": "pdf", ".xlsx": "51", ".xls": "56", ".csv": "62", ".ods": "60"},
    "slides": {".pdf": "32", ".pptx": "24", ".ppt": "1", ".odp": "35"},
}


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


def _office_convert(source: Path, kind: str, extension: str) -> Path:
    fmt = OFFICE_TARGETS[kind][extension]
    destination = target_path(source, extension)
    work = Path(tempfile.mkdtemp(prefix="satsuma-ms-"))
    script = work / "convert.ps1"
    script.write_text(_PS_SCRIPT, encoding="utf-8-sig")
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(script), "-Kind", kind,
             "-Src", str(source.resolve()), "-Dst", str(destination.resolve()), "-Fmt", fmt],
            capture_output=True, stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace", timeout=600, creationflags=NO_WINDOW,
        )
        if completed.returncode != 0 or not destination.exists():
            detail = (completed.stderr or completed.stdout or "").strip()
            if "password" in detail.lower():
                raise ConversionError("This file is password protected. Open it, remove the password, and try again.")
            lines = detail.splitlines()
            raise ConversionError(lines[0] if lines else "Microsoft Office could not convert this file.")
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


def _read_text(source: Path) -> str:
    raw = source.read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _render_text(source: Path, extension: str) -> Path:
    """Markdown / HTML to HTML, Markdown or plain text with Qt's text engine (GUI thread)."""
    from PySide6.QtGui import QTextDocument

    text = _read_text(source)
    document = QTextDocument()
    if source.suffix.lower() in (".md", ".markdown"):
        document.setMarkdown(text)
    else:
        document.setHtml(text)
    if extension == ".html":
        result = document.toHtml()
    elif extension == ".md":
        result = document.toMarkdown()
    else:
        result = document.toPlainText()
    destination = target_path(source, extension)
    destination.write_text(result, encoding="utf-8")
    return destination


# --------------------------------------------------------------------------- data
def _csv_to_json(source: Path) -> Path:
    text = _read_text(source)
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;	|")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.DictReader(text.splitlines(), dialect=dialect))
    destination = target_path(source, ".json")
    destination.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    return destination


def _json_to_csv(source: Path) -> Path:
    try:
        data = json.loads(_read_text(source))
    except ValueError as exc:
        raise ConversionError(f"This isn't valid JSON ({exc}).") from exc
    if isinstance(data, dict):
        # {"items": [...]} is common; a single object becomes one row.
        lists = [v for v in data.values() if isinstance(v, list)]
        data = lists[0] if len(lists) == 1 else [data]
    if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
        raise ConversionError("Only a list of objects (rows with named fields) can become a CSV.")
    columns: list[str] = []
    for row in data:
        columns += [key for key in row if key not in columns]
    destination = target_path(source, ".csv")
    with open(destination, "w", newline="", encoding="utf-8-sig") as handle:   # BOM: Excel reads UTF-8
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in data:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
                             for k, v in row.items()})
    return destination


def _render_text_pdf(source: Path) -> Path:
    from PySide6.QtCore import QMarginsF, QSizeF
    from PySide6.QtGui import QFont, QFontDatabase, QPageLayout, QPageSize, QPdfWriter, QTextDocument

    if not QFontDatabase.families():
        # Qt would quietly write pages with no text on them.
        raise ConversionError("No fonts are available to lay out the text.")

    text = _read_text(source)
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
# What Qt converts by itself, with no Office or LibreOffice.
QT_TEXT = {
    ".txt": [".pdf"],
    ".md": [".pdf", ".html", ".txt"], ".markdown": [".pdf", ".html", ".txt"],
    ".html": [".pdf", ".md", ".txt"], ".htm": [".pdf", ".md", ".txt"],
}


def _office_kind(src_ext: str, extension: str) -> str | None:
    """Which Office app can turn `src_ext` into `extension`, if it is installed."""
    if src_ext == ".csv":
        kind = "sheets"
    elif src_ext in (".html", ".htm") and extension == ".docx":
        kind = "word"
    else:
        kind = family(src_ext)
    if kind is None or src_ext == ".epub" or extension not in OFFICE_TARGETS[kind]:
        return None
    return kind if office_available(kind) else None


def can_convert(extension: str) -> list[str]:
    """Target extensions available for a source on this machine."""
    extension = extension.lower()
    if extension == ".json":
        return [".csv"]
    lo = libreoffice_path()
    if extension in QT_TEXT:
        targets = list(QT_TEXT[extension])
        if (lo and extension in (".txt", ".html", ".htm")) or _office_kind(extension, ".docx"):
            targets.append(".docx")
        return targets
    targets = [".json"] if extension == ".csv" else []
    kind = "sheets" if extension == ".csv" else family(extension)
    if kind is None:
        return targets
    if lo:
        more = LO_TARGETS[kind]
    else:
        more = [t for t in OFFICE_TARGETS[kind] if _office_kind(extension, t)]
    return targets + [t for t in more if t != extension and t not in targets]


def convert(source, extension: str) -> Path:
    source = Path(source)
    extension = extension.lower()
    src_ext = source.suffix.lower()
    if src_ext == ".json" and extension == ".csv":
        return _json_to_csv(source)
    if src_ext == ".csv" and extension == ".json":
        return _csv_to_json(source)
    if extension in QT_TEXT.get(src_ext, []):
        if extension == ".pdf":
            return _text_to_pdf(source)
        return _on_gui_thread(lambda: _render_text(source, extension))
    if libreoffice_path():
        return _libreoffice_convert(source, extension)
    kind = _office_kind(src_ext, extension)
    if kind:
        return _office_convert(source, kind, extension)
    raise ConversionError(
        "Converting this document needs LibreOffice (free) or Microsoft Office. "
        "Install either one and try again."
    )
