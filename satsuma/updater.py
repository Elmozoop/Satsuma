"""Keeps Satsuma.exe up to date by itself.

A few times a day the exe asks GitHub for the latest release. When it's newer, the new
Satsuma.exe is downloaded in the background and checked against the SHA-256 GitHub lists for it;
anything that doesn't match is thrown away. When Satsuma is idle (no ring, cards, windows or jobs),
it renames itself to Satsuma.old.exe, puts the new file in its place, starts it and quits. The
new copy deletes the old one and says "Updated". Settings live in %LOCALAPPDATA%, so they stay.

Only the exe updates itself; a source checkout is updated with git. Switch it off in Settings → About.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from .config import GITHUB_REPO, VERSION, settings

log = logging.getLogger(__name__)

API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
ASSET_NAME = "Satsuma.exe"
DOWNLOAD_PREFIX = f"https://github.com/{GITHUB_REPO}/releases/download/"
FIRST_CHECK_MS = 2 * 60 * 1000          # not in the busy first minutes after sign-in
CHECK_MS = 6 * 60 * 60 * 1000
INSTALL_POLL_MS = 30 * 1000              # how often to look for an idle moment once it's ready
CHUNK = 1 << 16
# For testing a built exe end to end: a local file installed as if it were a verified download.
TEST_FILE = os.environ.get("SATSUMA_UPDATE_TEST", "")


def parse_version(text: str) -> tuple[int, int, int] | None:
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text or "")
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3) or 0)


def is_newer(tag: str, current: str = VERSION) -> bool:
    new, now = parse_version(tag), parse_version(current)
    return bool(new and now and new > now)


def highlights(notes: str, limit: int = 3) -> list[str]:
    """The release's headline features: its bold-only lines (**Like this**), else its first bullets."""
    def plain(text: str) -> str:
        return re.sub(r"[*_`]|\[([^\]]*)\]\([^)]*\)", lambda m: m.group(1) or "", text).strip()

    lines = [line.strip() for line in (notes or "").splitlines()]
    bold = [plain(m.group(1)) for line in lines if (m := re.fullmatch(r"\*\*(.+?)\*\*:?", line))]
    picked = [b for b in bold if b and b.lower().rstrip(":") not in ("also", "notes")]
    if not picked:
        picked = [plain(line[2:]) for line in lines if line.startswith(("- ", "* "))]
    return [p for p in picked if p][:limit]


def pick_asset(release: dict) -> dict | None:
    """The release's Satsuma.exe, only if it's a published, newer release with a SHA-256 to check."""
    if release.get("draft") or release.get("prerelease") or not is_newer(str(release.get("tag_name", ""))):
        return None
    for asset in release.get("assets") or []:
        if asset.get("name") != ASSET_NAME:
            continue
        url = str(asset.get("browser_download_url") or "")
        digest = str(asset.get("digest") or "")
        if not url.startswith(DOWNLOAD_PREFIX) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            return None
        return {"url": url, "sha256": digest.split(":", 1)[1], "size": int(asset.get("size") or 0),
                "version": ".".join(map(str, parse_version(release["tag_name"]))),
                "highlights": highlights(str(release.get("body") or "")),
                "notes_url": str(release.get("html_url") or f"https://github.com/{GITHUB_REPO}/releases/latest")}
    return None


def exe_path() -> Path | None:
    """The running Satsuma.exe, or None when running from source (which never self-updates)."""
    if not getattr(sys, "frozen", False):
        return None
    path = Path(sys.executable)
    return path if path.suffix.lower() == ".exe" else None


def old_path(exe: Path) -> Path:
    return exe.with_name(exe.stem + ".old.exe")


def download_path(exe: Path) -> Path:
    return exe.with_name(exe.stem + ".update")


def cleanup(exe: Path | None = None) -> bool:
    """Delete the previous version left behind by an update. True when nothing is left."""
    exe = exe or exe_path()
    if exe is None:
        return True
    done = True
    for leftover in (old_path(exe), download_path(exe)):
        try:
            leftover.unlink(missing_ok=True)
        except OSError:
            done = False          # the old process hasn't quite gone yet; try again later
    return done


def _get_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": f"Satsuma/{VERSION}",
                                                   "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def download(asset: dict, target: Path, stop: threading.Event | None = None) -> Path:
    """Fetch the new exe to `target`, checking size and SHA-256; a bad file is deleted."""
    digest = hashlib.sha256()
    written = 0
    request = urllib.request.Request(asset["url"], headers={"User-Agent": f"Satsuma/{VERSION}"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response, open(target, "wb") as out:
            while True:
                if stop is not None and stop.is_set():
                    raise InterruptedError("update download stopped")
                chunk = response.read(CHUNK)
                if not chunk:
                    break
                digest.update(chunk)
                out.write(chunk)
                written += len(chunk)
        if asset.get("size") and written != asset["size"]:
            raise ValueError(f"update is {written} bytes, expected {asset['size']}")
        if digest.hexdigest() != asset["sha256"]:
            raise ValueError("update doesn't match the SHA-256 GitHub lists for it")
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return target


def swap(exe: Path, new_file: Path) -> None:
    """Put `new_file` where `exe` is. Windows lets a running exe be renamed, not overwritten."""
    old = old_path(exe)
    old.unlink(missing_ok=True)
    exe.rename(old)
    try:
        new_file.rename(exe)
    except OSError:
        old.rename(exe)           # put things back as they were
        raise


def relaunch(exe: Path) -> None:
    """Start the new exe, which waits for this process to finish before it takes over."""
    env = dict(os.environ)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"   # a fresh copy, not a child of this one's unpacked files
    env.pop("SATSUMA_UPDATE_TEST", None)          # a test install happens once, not on every restart
    flags = 0x00000008 | 0x00000200 if sys.platform == "win32" else 0   # DETACHED_PROCESS | NEW_PROCESS_GROUP
    subprocess.Popen([str(exe), "--background", f"--after-update={os.getpid()}"], env=env,
                     creationflags=flags, close_fds=True, cwd=str(exe.parent))


def wait_for_exit(pid: int, timeout_ms: int = 30000) -> None:
    """Used by the new copy: let the old one quit first, so it doesn't just hand over to it."""
    if sys.platform != "win32":
        return
    import ctypes

    SYNCHRONIZE = 0x00100000
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if handle:
        kernel32.WaitForSingleObject(handle, timeout_ms)
        kernel32.CloseHandle(handle)


class Updater(QObject):
    """Checks, downloads in a background thread, then installs at the first idle moment."""
    ready = Signal(str, str)     # version, path of the verified download (emitted from the thread)

    def __init__(self, is_idle, quit_app, parent=None):
        super().__init__(parent)
        self._is_idle = is_idle
        self._quit_app = quit_app
        self._exe = exe_path()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._pending: tuple[str, Path] | None = None
        self._failed: set[str] = set()
        self._news: dict | None = None          # what the new version brings, shown after the restart      # versions that couldn't be installed: don't loop on them
        self.ready.connect(self._on_ready)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.check)
        self._install = QTimer(self)
        self._install.setInterval(INSTALL_POLL_MS)
        self._install.timeout.connect(self._try_install)
        self._first = QTimer(self)
        self._first.setSingleShot(True)
        self._first.timeout.connect(self._start)
        if self._exe is not None:
            self._first.start(5000 if TEST_FILE else FIRST_CHECK_MS)
        settings.subscribe(self._on_setting)

    @property
    def active(self) -> bool:
        return self._exe is not None and bool(settings.get("auto_update"))

    def _start(self) -> None:
        self.check()
        self._timer.start(CHECK_MS)

    def _on_setting(self, key: str) -> None:
        if key in ("auto_update", "*") and self.active and not self._timer.isActive():
            self._start()

    def check(self) -> bool:
        """Look for a new release (in a thread). False when updating is off or already busy."""
        if not self.active or self._pending or (self._thread and self._thread.is_alive()):
            return False
        self._thread = threading.Thread(target=self._work, name="satsuma-update", daemon=True)
        self._thread.start()
        return True

    def _work(self) -> None:
        try:
            if TEST_FILE:
                import shutil

                shutil.copyfile(TEST_FILE, download_path(self._exe))
                self.ready.emit("test", str(download_path(self._exe)))
                return
            asset = pick_asset(_get_json(API_URL))
            if asset is None or asset["version"] in self._failed:
                return
            log.info("downloading Satsuma %s", asset["version"])
            path = download(asset, download_path(self._exe), self._stop)
            log.info("Satsuma %s downloaded and verified", asset["version"])
            self._news = {"version": asset["version"], "highlights": asset["highlights"],
                          "url": asset["notes_url"]}
            self.ready.emit(asset["version"], str(path))
        except InterruptedError:
            pass
        except Exception as exc:      # offline, GitHub busy, bad file: try again next time
            log.info("update check failed: %s", exc)

    def _on_ready(self, version: str, path: str) -> None:
        self._pending = (version, Path(path))
        self._install.start()
        self._try_install()

    def _try_install(self) -> None:
        if self._pending is None or not self.active or not self._is_idle():
            return
        version, path = self._pending
        self._install.stop()
        self._pending = None
        try:
            if self._news:
                settings.set("whats_new", self._news)    # the new copy reads it and shows the card
            swap(self._exe, path)
            relaunch(self._exe)
        except OSError as exc:        # e.g. a folder Satsuma isn't allowed to write to
            log.warning("couldn't install Satsuma %s: %s", version, exc)
            settings.set("whats_new", {})
            self._failed.add(version)
            path.unlink(missing_ok=True)
            return
        log.info("installed Satsuma %s; restarting", version)
        self._quit_app()

    def stop(self) -> None:
        self._stop.set()
        for timer in (self._first, self._timer, self._install):
            timer.stop()
        settings.unsubscribe(self._on_setting)
