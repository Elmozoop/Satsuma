"""Satsuma 1.14: Satsuma.exe updates itself from GitHub Releases."""
import hashlib
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from conftest import pump
from satsuma import updater
from satsuma.config import VERSION, settings

NEW_EXE = b"MZ pretend this is Satsuma 99" * 1000


def _release(digest=None, url=None, tag="v99.0.0", **extra):
    if digest is None:
        digest = "sha256:" + hashlib.sha256(NEW_EXE).hexdigest()
    return {"tag_name": tag, "draft": False, "prerelease": False, **extra,
            "assets": [{"name": "Satsuma.exe", "size": len(NEW_EXE),
                        "browser_download_url": url or updater.DOWNLOAD_PREFIX + f"{tag}/Satsuma.exe",
                        "digest": digest}]}


@pytest.fixture()
def file_server():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(NEW_EXE)))
            self.end_headers()
            self.wfile.write(NEW_EXE)

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/Satsuma.exe"
    server.shutdown()


def test_versions_compare_as_numbers():
    assert updater.parse_version("v1.14.0") == (1, 14, 0)
    assert updater.parse_version("Satsuma 1.9") == (1, 9, 0)
    assert updater.is_newer("v1.10.0", "1.9.5")             # not compared as text
    assert not updater.is_newer("v1.13.0", "1.13.0")
    assert not updater.is_newer("v1.12.0", "1.13.0")
    assert not updater.is_newer("latest", "1.13.0")


def test_only_a_newer_published_exe_with_a_checksum_is_taken():
    asset = updater.pick_asset(_release())
    assert asset["version"] == "99.0.0" and asset["size"] == len(NEW_EXE)
    assert updater.pick_asset(_release(tag="v" + VERSION)) is None                    # not newer
    assert updater.pick_asset(_release(prerelease=True)) is None
    assert updater.pick_asset(_release(draft=True)) is None
    assert updater.pick_asset(_release(digest="")) is None                            # nothing to check it with
    assert updater.pick_asset(_release(url="https://example.com/Satsuma.exe")) is None  # not from this repo


def test_download_is_checked_and_a_bad_file_is_thrown_away(tmp_path, file_server):
    target = tmp_path / "Satsuma.update"
    good = dict(updater.pick_asset(_release()), url=file_server)
    assert updater.download(good, target).read_bytes() == NEW_EXE
    bad = dict(good, sha256="0" * 64)
    with pytest.raises(ValueError):
        updater.download(bad, target)
    assert not target.exists()


def test_swap_replaces_the_exe_and_cleanup_removes_the_old_one(tmp_path):
    exe = tmp_path / "Satsuma.exe"
    exe.write_bytes(b"old")
    new = tmp_path / "Satsuma.update"
    new.write_bytes(b"new")
    updater.swap(exe, new)
    assert exe.read_bytes() == b"new" and updater.old_path(exe).read_bytes() == b"old"
    assert updater.cleanup(exe) and not updater.old_path(exe).exists()


def test_a_failed_swap_puts_the_old_exe_back(tmp_path):
    exe = tmp_path / "Satsuma.exe"
    exe.write_bytes(b"old")
    with pytest.raises(OSError):
        updater.swap(exe, tmp_path / "missing.update")
    assert exe.read_bytes() == b"old"


def test_running_from_source_never_updates(qapp):
    u = updater.Updater(lambda: True, lambda: None)
    try:
        assert updater.exe_path() is None and not u.check()
    finally:
        u.stop()


def test_it_waits_for_an_idle_moment_then_installs_and_restarts(qapp, tmp_path, file_server, monkeypatch):
    exe = tmp_path / "Satsuma.exe"
    exe.write_bytes(b"old")
    monkeypatch.setattr(updater, "exe_path", lambda: exe)
    monkeypatch.setattr(updater, "_get_json", lambda _url: _release(url=updater.DOWNLOAD_PREFIX + "x"))
    real_download = updater.download
    monkeypatch.setattr(updater, "download", lambda asset, target, stop=None:
                        real_download(dict(asset, url=file_server), target, stop))
    launched, quit_calls = [], []
    monkeypatch.setattr(updater, "relaunch", lambda path: launched.append(path))
    idle = {"now": False}
    settings.set("auto_update", True)
    u = updater.Updater(lambda: idle["now"], lambda: quit_calls.append(1))
    try:
        assert u.check()
        end = time.time() + 10
        while time.time() < end and u._pending is None:
            pump(qapp, 20)
        assert u._pending is not None and exe.read_bytes() == b"old"     # busy: not yet
        idle["now"] = True
        u._try_install()
        assert exe.read_bytes() == NEW_EXE and launched == [exe] and quit_calls == [1]
    finally:
        u.stop()


def test_switched_off_means_no_check(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "exe_path", lambda: tmp_path / "Satsuma.exe")
    settings.set("auto_update", False)
    u = updater.Updater(lambda: True, lambda: None)
    try:
        assert not u.check()
    finally:
        settings.set("auto_update", True)
        u.stop()


def test_updates_are_on_by_default():
    from satsuma.config import DEFAULTS

    assert DEFAULTS["auto_update"] is True
