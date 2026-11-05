"""Satsuma 1.14: the anonymous user count and the owner's Stats window."""
import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from conftest import pump
from satsuma import telemetry
from satsuma.config import settings


@pytest.fixture()
def counter():
    """A local stand-in for the Cloudflare counter that records what it receives."""
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            received.append((self.path, self.headers.get("Content-Type"), json.loads(body)))
            self.send_response(204)
            self.end_headers()

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", received
    server.shutdown()


def _wait(qapp, condition, seconds=5.0):
    end = time.time() + seconds
    while time.time() < end and not condition():
        pump(qapp, 20)
    return condition()


def test_ping_sends_only_a_random_id_and_the_version(qapp, counter, monkeypatch):
    url, received = counter
    monkeypatch.setattr(telemetry, "STATS_URL", url)
    settings.set("count_me", True)
    pinger = telemetry.Pinger()
    try:
        assert pinger.ping()
        assert _wait(qapp, lambda: received)
        path, kind, body = received[0]
        assert path == "/ping" and kind == "application/json"
        assert set(body) == {"id", "v"}                          # nothing else, ever
        uuid.UUID(body["id"])
        from satsuma.config import VERSION

        assert body["v"] == VERSION
        assert telemetry.install_id() == body["id"]            # the same id every time
    finally:
        pinger.stop()


def test_nothing_is_sent_when_switched_off_or_not_set_up(qapp, counter, monkeypatch):
    url, received = counter
    pinger = telemetry.Pinger()
    try:
        monkeypatch.setattr(telemetry, "STATS_URL", "")
        settings.set("count_me", True)
        assert not pinger.ping()                                 # no counter configured yet
        monkeypatch.setattr(telemetry, "STATS_URL", url)
        settings.set("count_me", False)
        assert not pinger.ping()                                 # the user said no
        pump(qapp, 300)
        assert received == []
    finally:
        settings.set("count_me", True)
        pinger.stop()


def test_counting_is_on_by_default():
    from satsuma.config import DEFAULTS

    assert DEFAULTS["count_me"] is True


def test_stats_window_shows_users_and_downloads(qapp, tmp_path, monkeypatch):
    from satsuma.ui import stats_window

    monkeypatch.setattr(stats_window, "DATA_DIR", tmp_path)
    assert stats_window.owner_config() is None                   # not the owner's PC
    (tmp_path / "owner.json").write_text(json.dumps({"stats_url": "", "key": "k"}))
    owner = stats_window.owner_config()
    assert owner == {"stats_url": "", "key": "k"}
    window = stats_window.StatsWindow(owner)
    try:
        window.show_users({"online": 3, "today": 12, "month": 40, "installs": 1234,
                           "versions": {"1.14.0": 30, "1.13.0": 10}})
        assert window.online.value.text() == "3" and window.installs.value.text() == "1,234"
        assert "1.14.0 × 30" in window.versions.text()
        window.show_downloads([{"tag_name": "v1.14.0", "assets": [{"download_count": 7}, {"download_count": 5}]},
                               {"tag_name": "v1.13.0", "assets": [{"download_count": 30}]}])
        assert window.total_downloads.value.text() == "42"
        assert "v1.14.0: 12" in window.per_release.text() and "v1.13.0: 30" in window.per_release.text()
    finally:
        window.done(0)


def test_stats_menu_item_only_on_the_owners_pc(qapp, tmp_path, monkeypatch):
    import satsuma.app as app_module
    from satsuma.ui import stats_window

    monkeypatch.setattr(app_module, "setup_logging", lambda: None)
    monkeypatch.setattr(stats_window, "DATA_DIR", tmp_path)
    satsuma = app_module.Satsuma(qapp)
    try:
        satsuma._tray_menu_opening()
        assert not satsuma.stats_action.isVisible()
        (tmp_path / "owner.json").write_text(json.dumps({"key": "k"}))
        satsuma._tray_menu_opening()
        assert satsuma.stats_action.isVisible()
    finally:
        satsuma.detector.stop()
        satsuma.watcher.stop()
        satsuma.pinger.stop()
        satsuma.tray.hide()
