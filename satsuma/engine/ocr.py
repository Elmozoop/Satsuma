"""Read the text in a picture with the OCR engine built into Windows 10/11 (offline).

Driven by a short PowerShell script through Windows' own WinRT APIs, so nothing extra is
installed. The picture is first re-saved as a moderate-size PNG, which Windows can always decode.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .ffmpeg_tool import NO_WINDOW, ConversionError
from .paths import target_path

MAX_EDGE = 4000    # Windows OCR rejects very large images; this keeps small text readable

_PS_SCRIPT = r"""
param([string]$Src)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($operation, [Type]$type) {
    $task = $asTask.MakeGenericMethod($type).Invoke($null, @($operation))
    $null = $task.Wait(-1)
    $task.Result
}
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($engine -eq $null) { Write-Error 'NO-OCR-LANGUAGE'; exit 3 }
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($Src)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
foreach ($line in $result.Lines) { [Console]::WriteLine($line.Text) }
"""


def read_text(source) -> str:
    """The text Windows finds in the picture, one line per line of text."""
    if sys.platform != "win32":
        raise ConversionError("Reading text from pictures needs Windows 10 or 11.")
    from PIL import Image, ImageOps

    from . import images   # registers HEIC/AVIF

    _ = images
    work = Path(tempfile.mkdtemp(prefix="satsuma-ocr-"))
    try:
        picture = work / "page.png"
        with Image.open(source) as original:
            image = ImageOps.exif_transpose(original) or original
            image.thumbnail((MAX_EDGE, MAX_EDGE))
            if min(image.size) < 400:          # small screenshots read better a little bigger
                factor = 400 / min(image.size)
                image = image.resize((round(image.size[0] * factor), round(image.size[1] * factor)),
                                     Image.LANCZOS)
            image.convert("RGB").save(picture)
        script = work / "ocr.ps1"
        script.write_text(_PS_SCRIPT, encoding="utf-8-sig")
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(script), "-Src", str(picture.resolve())],
            capture_output=True, stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace",
            timeout=120, creationflags=NO_WINDOW)
        if completed.returncode != 0:
            detail = (completed.stderr or "").strip()
            if "NO-OCR-LANGUAGE" in detail:
                raise ConversionError("Windows has no text-recognition language installed. Add one in "
                                      "Settings → Time & language → Language (English includes it).")
            raise ConversionError("Windows couldn't read this picture." +
                                  (f" ({detail.splitlines()[-1]})" if detail else ""))
        return completed.stdout.strip()
    except subprocess.TimeoutExpired as exc:
        raise ConversionError("Reading the text took too long.") from exc
    finally:
        shutil.rmtree(work, ignore_errors=True)


def to_text(source) -> Path:
    """Save the picture's text as a .txt beside it and put it on the clipboard."""
    source = Path(source)
    text = read_text(source)
    if not text:
        raise ConversionError("No text found in this picture.")
    destination = target_path(source, ".txt")
    destination.write_text(text + "\n", encoding="utf-8")
    _copy_to_clipboard(text)
    return destination


def _copy_to_clipboard(text: str) -> None:
    from PySide6.QtWidgets import QApplication

    from .documents import _on_gui_thread

    if QApplication.instance() is not None:
        _on_gui_thread(lambda: QApplication.clipboard().setText(text))   # the clipboard lives on the GUI thread
