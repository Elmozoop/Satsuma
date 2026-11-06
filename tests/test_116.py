"""Satsuma 1.16: keyboard shortcut, What's new card, Report a problem, Stats charts."""
import ctypes
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from conftest import pump
from satsuma import report, updater
from satsuma.config import VERSION, settings

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows hotkeys")


def _stop(satsuma):
    for part in (satsuma.detector, satsuma.watcher, satsuma.pinger, satsuma.updater, satsuma.hotkey):
        part.stop()
    satsuma.tray.hide()


# ----------------------------------------------------------------------------- keyboard shortcut
@windows_only
def test_shortcut_registers_fires_and_switches_off(qapp):
    from satsuma import hotkey

    key = hotkey.Hotkey()
    hits, taken = [], []
    key.pressed.connect(lambda: hits.append(1))
    key.taken.connect(taken.append)
    try:
        for choice in hotkey.SHORTCUTS:            # whichever one no other app on this PC uses
            settings.set("hotkey", choice)
            if key.registered:
                break
        else:
            pytest.skip("every shortcut is taken by other apps on this PC")
        assert all(name in [s[2] for s in hotkey.SHORTCUTS.values()] for name in taken)
        ctypes.windll.user32.PostThreadMessageW(ctypes.windll.kernel32.GetCurrentThreadId(),
                                                hotkey.WM_HOTKEY, hotkey.HOTKEY_ID, 0)
        pump(qapp, 100)
        assert hits == [1]
        settings.set("hotkey", "")
        assert not key.registered
    finally:
        key.stop()
        settings.set("hotkey", "")


def test_shortcut_opens_the_ring_for_the_selection_or_the_drop_window(qapp, tmp_path, monkeypatch):
    import satsuma.app as app_module
    from satsuma import hotkey

    monkeypatch.setattr(app_module, "setup_logging", lambda: None)
    picked = tmp_path / "photo.png"
    picked.write_bytes(b"x")
    satsuma = app_module.Satsuma(qapp)
    opened = []
    monkeypatch.setattr(satsuma.menu, "open_for", lambda paths, pos=None: opened.append(("ring", paths)))
    monkeypatch.setattr(satsuma.menu, "open_pinned", lambda: opened.append(("drop", None)))
    try:
        monkeypatch.setattr(hotkey, "selected_files", lambda _hwnd: [picked])
        satsuma.open_for_selection()
        monkeypatch.setattr(hotkey, "selected_files", lambda _hwnd: [])
        satsuma.open_for_selection()
        assert opened == [("ring", [picked]), ("drop", None)]
    finally:
        _stop(satsuma)


def test_shortcut_label_and_nothing_outside_explorer():
    from satsuma import hotkey

    assert hotkey.label("ctrl+shift+space") == "Ctrl+Shift+Space" and hotkey.label("") == ""
    assert hotkey.selected_files(0) == []


# ----------------------------------------------------------------------------- What's new
def test_highlights_come_from_the_release_notes():
    notes = ("## Satsuma 2\n\n**Download `Satsuma.exe` below.** No install.\n\n"
             "**A `faster` ring**\n- details\n\n**Charts**\n\n**Also**\n- more\n\n**Fourth thing**")
    assert updater.highlights(notes) == ["A faster ring", "Charts", "Fourth thing"]
    assert updater.highlights("- Fixed a crash\n- Faster [PDF](http://x) merge") == ["Fixed a crash",
                                                                                     "Faster PDF merge"]


def test_whats_new_is_saved_before_installing_and_shown_once_after(qapp, tmp_path, monkeypatch):
    import satsuma.app as app_module

    exe = tmp_path / "Satsuma.exe"
    exe.write_bytes(b"old")
    new = tmp_path / "Satsuma.update"
    new.write_bytes(b"new")
    monkeypatch.setattr(updater, "exe_path", lambda: exe)
    monkeypatch.setattr(updater, "relaunch", lambda _p: None)
    u = updater.Updater(lambda: True, lambda: None)
    try:
        u._news = {"version": VERSION, "highlights": ["Charts", "Shortcut"], "url": "https://example.com/r"}
        u._on_ready(VERSION, str(new))
        assert exe.read_bytes() == b"new"
        assert settings.get("whats_new")["highlights"] == ["Charts", "Shortcut"]
    finally:
        u.stop()

    monkeypatch.setattr(app_module, "setup_logging", lambda: None)
    satsuma = app_module.Satsuma(qapp)
    try:
        satsuma.announce_update()
        card = satsuma.whats_new
        assert card.isVisible() and [p.text() for p in card.points] == ["•  Charts", "•  Shortcut"]
        assert card.url == "https://example.com/r" and settings.get("whats_new") == {}
        card.accept()
    finally:
        _stop(satsuma)


# ----------------------------------------------------------------------------- Report a problem
def test_report_opens_a_prefilled_issue_and_hides_the_home_folder(qapp, monkeypatch):
    from PySide6.QtGui import QDesktopServices, QGuiApplication

    home = str(Path.home())
    report.LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    report.LOG_FILE.write_text(f"line one\nfailed on {home}\\Desktop\\photo.heic\n", encoding="utf-8")
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))
    url = report.report("Convert to PDF", "file is locked")
    query = parse_qs(urlparse(url).query)
    assert url.startswith("https://github.com/Elmozoop/Satsuma/issues/new?") and opened
    assert query["title"] == ["Problem: Convert to PDF"]
    assert "file is locked" in query["body"][0] and f"Satsuma {VERSION}" in query["body"][0]
    clip = QGuiApplication.clipboard().text()
    assert "photo.heic" in clip and home not in clip and "%USERPROFILE%" in clip


def test_failed_card_has_a_report_button(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QMouseEvent

    from satsuma.ui.toast import Toasts

    toasts = Toasts()
    reported = []
    toasts.report_requested.connect(lambda what, err: reported.append((what, err)))
    toasts.started(1, "PDF", "photo.png")
    toasts.failed(1, "file is locked")
    toasts.show()
    pump(qapp, 600)
    card = toasts.cards[0]
    rect = next(r for r, name in card.buttons if name == "report")
    toasts.mouseReleaseEvent(QMouseEvent(QMouseEvent.MouseButtonRelease, rect.center(), rect.center(),
                                         Qt.LeftButton, Qt.NoButton, Qt.NoModifier))
    assert reported == [("PDF", "file is locked")]
    toasts.hide()


# ----------------------------------------------------------------------------- charts
def test_stats_window_draws_day_by_day_charts(qapp, tmp_path, monkeypatch):
    from satsuma.ui import stats_window

    monkeypatch.setattr(stats_window, "DATA_DIR", tmp_path)
    window = stats_window.StatsWindow({"key": "k", "stats_url": ""})
    try:
        days = [{"day": f"2026-11-0{i}", "active": i, "new": 1,
                 "versions": {"1.16.0": i, "1.15.1": 1, "1.14.0": 1, "1.13.0": 1, "1.12.0": 1}}
                for i in range(1, 6)]
        window.show_users({"online": 1, "today": 2, "month": 3, "installs": 4, "versions": {},
                           "days": days, "downloads": [{"day": "2026-11-04", "total": 10},
                                                       {"day": "2026-11-05", "total": 25}]})
        assert window.users_chart.values == [1, 2, 3, 4, 5]
        assert window.versions_chart.names[0] == "1.16.0" and window.versions_chart.names[-1] == "other"
        assert window.downloads_chart.values == [10, 25]
        window.resize(780, 820)
        window.show()
        pump(qapp, 100)
        assert not window.grab().isNull()
    finally:
        window.done(0)


# ----------------------------------------------------------------------------- waking from sleep
def test_waking_from_sleep_brings_everything_back(qapp, monkeypatch):
    import time as clock

    import satsuma.app as app_module

    monkeypatch.setattr(app_module, "setup_logging", lambda: None)
    satsuma = app_module.Satsuma(qapp)
    resumed = []
    monkeypatch.setattr(satsuma, "resume", lambda: resumed.append(1))
    try:
        satsuma._wall = clock.time() - 5            # an ordinary tick: nothing to do
        satsuma._check_wake()
        assert resumed == []
        satsuma._wall = clock.time() - 8 * 3600     # the laptop slept overnight
        satsuma._check_wake()
        assert resumed == [1]
    finally:
        _stop(satsuma)


def test_resume_restores_the_tray_shortcut_and_detection(qapp, monkeypatch):
    import satsuma.app as app_module

    monkeypatch.setattr(app_module, "setup_logging", lambda: None)
    satsuma = app_module.Satsuma(qapp)
    applied = []
    monkeypatch.setattr(satsuma.hotkey, "apply", lambda: applied.append(1) or True)
    try:
        satsuma.tray.hide()
        satsuma.resume()
        assert applied == [1]
        assert satsuma.detector._timer.isActive() == satsuma.detector.supported
    finally:
        _stop(satsuma)
