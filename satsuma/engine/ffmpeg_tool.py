"""Locating, fetching and running ffmpeg/ffprobe without flashing a console."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import zipfile
from contextlib import contextmanager
from pathlib import Path

from ..config import BIN_DIR

# Static Windows builds. Primary, then mirror.
DOWNLOAD_URLS = (
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
    "ffmpeg-master-latest-win64-gpl.zip",
)

_EXE = ".exe" if sys.platform == "win32" else ""
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW


class FFmpegMissing(RuntimeError):
    pass


class Cancelled(RuntimeError):
    pass


# Per-thread progress reporter, set by the job runner; ffmpeg runs report into it.
_local = threading.local()
_running: set = set()
_running_lock = threading.Lock()


@contextmanager
def progress_scope(callback):
    """Within this block, ffmpeg runs on this thread report fraction 0..1 to `callback`."""
    previous = getattr(_local, "callback", None)
    _local.callback = callback
    try:
        yield
    finally:
        _local.callback = previous


def terminate_all() -> None:
    """Kill any ffmpeg still running (used when the app quits)."""
    with _running_lock:
        processes = list(_running)
    for process in processes:
        try:
            process._satsuma_killed = True
            process.kill()
        except OSError:
            pass


def _expected_duration(args: list[str]) -> float:
    """Length of the output, to measure progress against."""
    inputs = [args[i + 1] for i, a in enumerate(args[:-1]) if a == "-i"]
    if not inputs:
        return 0.0
    joined = any("concat=" in a for a in args)
    total = sum(duration_of(p) for p in inputs) if joined else duration_of(inputs[0])
    if "-t" in args:
        try:
            limit = float(args[args.index("-t") + 1])
            total = min(total, limit) if total else limit
        except (ValueError, IndexError):
            pass
    return total


class ConversionError(RuntimeError):
    pass


def _bundled(name: str) -> Path | None:
    """Look next to the executable first, then in our data dir, then on PATH."""
    from ..config import APP_DIR

    for folder in (APP_DIR / "bin", APP_DIR, BIN_DIR):
        candidate = folder / f"{name}{_EXE}"
        if candidate.is_file():
            return candidate
    found = shutil.which(name)
    return Path(found) if found else None


def ffmpeg_path() -> Path | None:
    return _bundled("ffmpeg")


def ffprobe_path() -> Path | None:
    return _bundled("ffprobe")


def available() -> bool:
    return ffmpeg_path() is not None


def ensure(progress=None) -> Path:
    """Return a usable ffmpeg, downloading a static build if needed.

    `progress(fraction, message)` is called from the calling thread.
    """
    existing = ffmpeg_path()
    if existing:
        return existing
    if sys.platform != "win32":
        raise FFmpegMissing("ffmpeg was not found on PATH.")
    return download(progress)


def download(progress=None) -> Path:
    import urllib.error
    import urllib.request

    def report(fraction: float, message: str) -> None:
        if progress:
            try:
                progress(fraction, message)
            except Exception:
                pass

    BIN_DIR.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None

    for url in DOWNLOAD_URLS:
        tmp_dir = Path(tempfile.mkdtemp(prefix="satsuma-ffmpeg-"))
        archive = tmp_dir / "ffmpeg.zip"
        try:
            report(0.0, "Downloading FFmpeg…")
            request = urllib.request.Request(url, headers={"User-Agent": "Satsuma/1.0"})
            with urllib.request.urlopen(request, timeout=60) as response:
                total = int(response.headers.get("Content-Length") or 0)
                done = 0
                with open(archive, "wb") as handle:
                    while True:
                        chunk = response.read(262144)
                        if not chunk:
                            break
                        handle.write(chunk)
                        done += len(chunk)
                        if total:
                            report(min(done / total, 0.97), "Downloading FFmpeg…")

            report(0.98, "Extracting FFmpeg…")
            wanted = {f"ffmpeg{_EXE}", f"ffprobe{_EXE}"}
            extracted: dict[str, Path] = {}
            with zipfile.ZipFile(archive) as zf:
                for member in zf.infolist():
                    name = Path(member.filename).name.lower()
                    if name in wanted and not member.is_dir():
                        destination = BIN_DIR / name
                        with zf.open(member) as src, open(destination, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                        os.chmod(destination, 0o755)
                        extracted[name] = destination

            if f"ffmpeg{_EXE}" not in extracted:
                raise FFmpegMissing("The downloaded archive did not contain ffmpeg.")
            report(1.0, "FFmpeg ready")
            return extracted[f"ffmpeg{_EXE}"]

        except (urllib.error.URLError, OSError, zipfile.BadZipFile, FFmpegMissing) as exc:
            last_error = exc
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    raise FFmpegMissing(
        "Could not download FFmpeg. Check your connection, or drop ffmpeg.exe "
        f"into {BIN_DIR} yourself.\n({last_error})"
    )


def run(args: list[str], timeout: int = 3600) -> str:
    """Run ffmpeg with the given arguments. Raises ConversionError on failure."""
    binary = ffmpeg_path()
    if binary is None:
        raise FFmpegMissing("ffmpeg is not available.")
    callback = getattr(_local, "callback", None)
    total = _expected_duration(args) if callback else 0.0
    command = [str(binary), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
               "-progress", "pipe:1", "-nostats", *args]
    # stderr goes to a temp file so a chatty ffmpeg can never fill a pipe and stall.
    with tempfile.TemporaryFile() as errors:
        try:
            process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=errors, stdin=subprocess.DEVNULL,
                creationflags=NO_WINDOW,
            )
        except OSError as exc:
            raise ConversionError(f"Could not start FFmpeg: {exc}") from exc
        with _running_lock:
            _running.add(process)
        timed_out = threading.Event()

        def on_timeout(proc=process):
            timed_out.set()
            proc.kill()

        timer = threading.Timer(timeout, on_timeout)
        timer.daemon = True
        timer.start()
        try:
            for raw in process.stdout:
                line = raw.decode("utf-8", "replace").strip()
                if callback and total > 0 and line.startswith("out_time_us="):
                    try:
                        seconds = int(line.split("=", 1)[1]) / 1_000_000
                        callback(max(0.0, min(0.99, seconds / total)))
                    except ValueError:
                        pass
            process.wait()
        finally:
            timer.cancel()
            with _running_lock:
                _running.discard(process)
        if process.returncode != 0:
            if timed_out.is_set():
                raise ConversionError("FFmpeg timed out.")
            if getattr(process, "_satsuma_killed", False):
                raise Cancelled("Stopped because Satsuma was closed.")
            errors.seek(0)
            detail = errors.read().decode("utf-8", "replace").strip().splitlines()
            message = detail[-1] if detail else f"exit code {process.returncode}"
            raise ConversionError(message)
    return ""


def probe(path) -> dict:
    """Return the ffprobe JSON for a media file, or {} if unavailable."""
    binary = ffprobe_path()
    if binary is None:
        return {}
    command = [
        str(binary), "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace", timeout=60, creationflags=NO_WINDOW
        )
        if completed.returncode == 0:
            return json.loads(completed.stdout or "{}")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return {}


def duration_of(path) -> float:
    info = probe(path)
    try:
        return float(info.get("format", {}).get("duration", 0.0))
    except (TypeError, ValueError):
        return 0.0


def has_audio(path) -> bool:
    info = probe(path)
    return any(s.get("codec_type") == "audio" for s in info.get("streams", []))
