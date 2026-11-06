"""Application wiring: tray icon, single instance, detector → menu → jobs → toasts."""
from __future__ import annotations

import gc
import getpass
import json
import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QPointF, QRectF, QStandardPaths, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QCursor, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import history, winutil
from .actions import Action
from .config import APP_ID, ASSETS_DIR, LOG_FILE, VERSION, settings
from .detector import DragDetector
from .engine import documents
from .engine import ffmpeg_tool
from .engine.paths import open_file, reveal, undo_targets
from .jobs import JobRunner
from .ui import prompts
from .ui.menu import ActionMenu
from .ui.settings_window import SettingsWindow
from .ui.controls import message, stylesheet
from .ui.glass import glass_window
from .ui.toast import Toasts
from .ui.tray_badge import TrayActivity
from .telemetry import Pinger
from . import updater
from .updater import Updater
from .hotkey import Hotkey, label as hotkey_label
from .watcher import FolderWatcher

log = logging.getLogger("satsuma")
SERVER_NAME = f"satsuma-{getpass.getuser()}".replace(" ", "_")
IDLE_TRIM_MS = 20_000  # quiet this long (nothing on screen, no jobs) → give memory back


def setup_logging() -> None:
    handler = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    def hook(exc_type, exc, tb):
        logging.getLogger("satsuma").critical("uncaught", exc_info=(exc_type, exc, tb))

    sys.excepthook = hook
    try:  # a crash inside Qt or Windows itself never reaches excepthook: write its trace to the log
        import faulthandler

        global _CRASH_LOG
        _CRASH_LOG = open(LOG_FILE, "a", encoding="utf-8")
        faulthandler.enable(file=_CRASH_LOG, all_threads=True)
    except (OSError, ValueError):
        pass


_CRASH_LOG = None
WAKE_CHECK_MS = 15_000


def app_icon() -> QIcon:
    for name in ("icon.ico", "icon.png"):
        candidate = ASSETS_DIR / name
        if candidate.exists():
            return QIcon(str(candidate))
    # Drawn fallback so the tray never shows a blank square.
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(255, 138, 31))
    painter.drawEllipse(QRectF(6, 12, 50, 50))
    leaf = QPainterPath()
    leaf.moveTo(QPointF(32, 14))
    leaf.cubicTo(QPointF(36, 2), QPointF(52, 2), QPointF(58, 8))
    leaf.cubicTo(QPointF(50, 16), QPointF(40, 18), QPointF(32, 14))
    painter.setBrush(QColor(86, 170, 76))
    painter.drawPath(leaf)
    painter.end()
    return QIcon(pixmap)


# ----------------------------------------------------------------------------- single instance
def forward_to_running_instance(payload: dict) -> bool:
    """True if another instance received the payload (so this one should exit)."""
    socket = QLocalSocket()
    socket.connectToServer(SERVER_NAME)
    if not socket.waitForConnected(400):
        return False
    winutil.allow_foreground_for_others()
    socket.write(json.dumps(payload).encode("utf-8"))
    socket.flush()
    socket.waitForBytesWritten(1000)
    socket.disconnectFromServer()
    return True


class Satsuma(QObject):
    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        documents.install_gui_runner()
        self.menu = ActionMenu()
        self.toasts = Toasts()
        self.runner = JobRunner(self)
        self.watcher = FolderWatcher(self.runner, self)
        self.pinger = Pinger(self)
        self.updater = Updater(self._idle_for_update, self.quit, self)
        self.hotkey = Hotkey(self)
        self.hotkey.pressed.connect(self.open_for_selection)
        self.hotkey.taken.connect(self._shortcut_taken)
        if settings.get("hotkey") and not self.hotkey.registered:
            QTimer.singleShot(3000, lambda: self._shortcut_taken(hotkey_label()))
        self.detector = DragDetector(self)
        self.settings_window: SettingsWindow | None = None
        self.tutorial_window = None
        self._last_outputs: list[Path] = []   # for "Undo" in the tray menu
        self._titles: dict[int, str] = {}      # job id -> title, for Recent
        self.server: QLocalServer | None = None

        self.menu.chosen.connect(self.on_chosen)
        self.detector.is_revealed = lambda: self.menu.mode not in ("sense", "hidden")

        s = self.runner.signals
        s.started.connect(self.toasts.started)
        s.started.connect(lambda job_id, title, _sub: self._titles.__setitem__(job_id, title))
        s.sources.connect(self.toasts.sources)
        s.progress.connect(self.toasts.progress)
        s.finished.connect(self.toasts.finished)
        s.failed.connect(self.toasts.failed)
        s.cancelled.connect(self.toasts.cancelled)
        s.finished.connect(self.on_finished)
        self.toasts.cancel_requested.connect(self.runner.cancel)
        self.toasts.report_requested.connect(lambda what, error: self.report_problem(what, error))

        self.detector.armed.connect(lambda pos: self.menu.arm(pos, smart=bool(settings.get("smart_detect"))))
        self.detector.moved.connect(self.on_moved)
        self.detector.released.connect(self.menu.released)
        self.detector.disarmed.connect(self.menu.disarm)

        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.setInterval(IDLE_TRIM_MS)
        self._idle.timeout.connect(self._trim_if_idle)
        for signal in (self.menu.closed, s.finished, s.failed, s.cancelled):
            signal.connect(self._idle.start)

        self._build_tray()
        self._wall = time.time()
        self._wake = QTimer(self)
        self._wake.setInterval(WAKE_CHECK_MS)
        self._wake.timeout.connect(self._check_wake)
        self._wake.start()
        self.detector.start()
        self._idle.start()

    # ------------------------------------------------------------------ tray
    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip(self._idle_tooltip())
        self.activity = TrayActivity(self.tray, app_icon(), self._idle_tooltip, self.runner.signals, self)
        menu = QMenu()
        glass_window(menu, menu=True, always=True)
        menu.setStyleSheet(stylesheet())
        header = QAction(f"Satsuma {VERSION}", menu)
        header.setEnabled(False)
        menu.addAction(header)
        menu.addSeparator()
        self.enabled_action = QAction("Enabled", menu, checkable=True)
        self.enabled_action.setChecked(bool(settings.get("enabled")))
        self.enabled_action.toggled.connect(lambda v: settings.set("enabled", v))
        menu.addAction(self.enabled_action)
        self.info_action = QAction("Info panel beside wedges", menu, checkable=True)
        self.info_action.setChecked(bool(settings.get("explain_actions")))
        self.info_action.toggled.connect(lambda v: settings.set("explain_actions", v))
        menu.addAction(self.info_action)
        menu.addAction("Open drop window", self.menu.open_pinned)
        self.clipboard_action = QAction("Convert clipboard", menu)
        self.clipboard_action.triggered.connect(self.convert_clipboard)
        menu.addAction(self.clipboard_action)
        menu.addSeparator()
        self.recent_menu = menu.addMenu("Recent")
        self.undo_action = QAction("Undo last conversion", menu)
        self.undo_action.triggered.connect(self.undo_last)
        menu.addAction(self.undo_action)
        menu.addSeparator()
        menu.addAction("Settings…", self.show_settings)
        menu.addAction("Tour…", self.show_tutorial)
        self.stats_action = menu.addAction("Stats…", self.show_stats)    # only on the author's PC
        self.stats_action.setVisible(False)
        menu.addSeparator()
        menu.addAction("Report a problem…", lambda: self.report_problem())
        menu.addAction("Open log", lambda: open_file(LOG_FILE))
        menu.addAction("Quit", self.quit)
        menu.aboutToShow.connect(self._tray_menu_opening)
        self.tray.setContextMenu(menu)
        self._tray_menu = menu
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    @staticmethod
    def _idle_tooltip() -> str:
        return "Satsuma"   # just the name: Windows shows one on hover, and nothing else pops up

    def _tray_menu_opening(self) -> None:
        self._tray_menu.setStyleSheet(stylesheet())          # theme, accent and style may have changed
        from .ui.stats_window import owner_config

        self.stats_action.setVisible(owner_config() is not None)
        self.enabled_action.setChecked(bool(settings.get("enabled")))
        self.info_action.setChecked(bool(settings.get("explain_actions")))   # may have changed in Settings
        targets = [p for p in undo_targets(self._last_outputs) if p.exists()]
        self.undo_action.setEnabled(bool(targets))
        if len(targets) == 1:
            self.undo_action.setText(f"Undo “{targets[0].name}”")
        elif targets:
            self.undo_action.setText(f"Undo last conversion ({len(targets)} files)")
        else:
            self.undo_action.setText("Undo last conversion")
        self._fill_recent()
        what = self._clipboard_contents()
        self.clipboard_action.setEnabled(what is not None)
        self.clipboard_action.setText({"image": "Convert copied image",
                                       "files": "Convert copied files"}.get(what, "Convert clipboard (nothing copied)"))

    # ------------------------------------------------------------------ recent
    def _fill_recent(self) -> None:
        self.recent_menu.clear()
        entries = history.entries()
        if not entries:
            empty = self.recent_menu.addAction("Nothing converted yet")
            empty.setEnabled(False)
            return
        now = time.time()
        for entry in entries:
            outputs = [Path(o) for o in entry["outputs"]]
            name = outputs[0].name if len(outputs) == 1 else f"{outputs[0].name} +{len(outputs) - 1} more"
            label = f"{name}   ·   {history.ago(entry['time'], now)}"
            self.recent_menu.addAction(label, lambda o=outputs[0]: reveal(o))
        self.recent_menu.addSeparator()
        self.recent_menu.addAction("Clear this list", history.clear)

    # ------------------------------------------------------------------ clipboard
    @staticmethod
    def _clipboard_paths() -> list[Path]:
        data = QApplication.clipboard().mimeData()
        if data is None or not data.hasUrls():
            return []
        return [Path(u.toLocalFile()) for u in data.urls() if u.isLocalFile() and Path(u.toLocalFile()).exists()]

    def _clipboard_contents(self) -> str | None:
        if self._clipboard_paths():
            return "files"
        data = QApplication.clipboard().mimeData()
        return "image" if data is not None and data.hasImage() else None

    def convert_clipboard(self) -> None:
        """Open the ring for copied files, or for a copied picture saved as a PNG first."""
        paths = self._clipboard_paths()
        if not paths:
            image = QApplication.clipboard().image()
            if image.isNull():
                return
            pictures = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation) or str(Path.home())
            folder = Path(pictures) / "Satsuma clipboard"
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / time.strftime("Clipboard %Y-%m-%d %H.%M.%S.png")
            if not image.save(str(path), "PNG"):
                self.tray.showMessage("Satsuma", "Couldn't save the copied picture.", app_icon(), 5000)
                return
            paths = [path]
        self.menu.open_for(paths, QCursor.pos())

    def undo_last(self) -> None:
        """Undo the last job, like Undo on its card: renames get their old names back, anything
        else goes to the Recycle Bin."""
        from .engine import rename

        if rename.can_undo(self._last_outputs):
            rename.undo(self._last_outputs)
            self._last_outputs = []
            return
        targets = [p for p in undo_targets(self._last_outputs) if p.exists()]
        if not targets:
            return
        if winutil.recycle(targets):
            self._last_outputs = []
            self.tray.showMessage("Satsuma", "Moved to the Recycle Bin. Restore it from there if needed.",
                                  app_icon(), 4000)
        else:
            self.tray.showMessage("Satsuma", "Couldn't move it to the Recycle Bin. Is it open in another app?",
                                  app_icon(), 6000)

    def _tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.menu.open_pinned()

    def greet(self) -> None:
        if not self.detector.supported:
            message = "Shift-drag detection needs Windows. Use the drop window from the tray icon."
        else:
            message = (f"Hold {settings.get('modifier').title()} while dragging a file "
                       "to open the Satsuma menu.")
        if QSystemTrayIcon.supportsMessages():
            self.tray.showMessage("Satsuma is running", message, app_icon(), 6000)

    # ------------------------------------------------------------------ single instance
    def listen(self) -> None:
        QLocalServer.removeServer(SERVER_NAME)
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.UserAccessOption)
        if not self.server.listen(SERVER_NAME):
            log.warning("single-instance server failed: %s", self.server.errorString())
            return
        self.server.newConnection.connect(self._on_connection)

    def _on_connection(self) -> None:
        while self.server and self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            buffer = bytearray()

            def read(sock=socket, buf=buffer):
                buf.extend(bytes(sock.readAll()))

            def done(sock=socket, buf=buffer):
                buf.extend(bytes(sock.readAll()))
                sock.deleteLater()
                try:
                    payload = json.loads(buf.decode("utf-8") or "{}")
                except ValueError:
                    return
                self.handle_request(payload)

            socket.readyRead.connect(read)
            socket.disconnected.connect(done)

    def handle_request(self, payload: dict) -> None:
        log.info("request from another launch: %s", payload)
        if payload.get("cmd") == "noop":
            return
        paths = [Path(p) for p in payload.get("paths", []) if Path(p).exists()]
        if paths:
            self.menu.open_for(paths, QCursor.pos())
        elif payload.get("cmd") == "settings":
            self.show_settings()
        else:
            self.menu.open_pinned()

    # ------------------------------------------------------------------ flow
    def on_moved(self, pos: QPoint) -> None:
        self.menu.follow(pos)  # no-op unless the invisible sensor is out

    def on_chosen(self, action: Action, paths: list) -> None:
        params: dict = {}
        if action.prompt:
            # Defer so the drag source (Explorer) has fully finished its drop.
            QTimer.singleShot(30, lambda: self._prompt_then_run(action, paths))
            return
        self.runner.submit(action, paths, params)

    def _prompt_then_run(self, action: Action, paths: list) -> None:
        try:
            params = prompts.ask(action.prompt, [Path(p) for p in paths])
        except Exception as exc:
            log.exception("prompt failed")
            message(None, "Couldn't read the file", str(exc))
            return
        if params is not None:
            self.runner.submit(action, paths, params)

    def on_finished(self, job_id: int, outputs: list) -> None:
        self._last_outputs = [Path(o) for o in outputs]
        history.add(self._titles.pop(job_id, ""), outputs)
        if settings.get("reveal_after") and outputs:
            reveal(outputs[0])

    def show_settings(self) -> None:
        if self.settings_window is None:
            self.settings_window = SettingsWindow()
            self.settings_window.finished.connect(self._settings_closed)
            self.settings_window.restyle_requested.connect(self._reopen_settings)
            self.settings_window.tour_requested.connect(self.show_tutorial)
        self.settings_window.show()
        self.settings_window.raise_()
        self.settings_window.activateWindow()

    def show_tutorial(self) -> None:
        from .ui.tutorial import Tutorial

        if self.tutorial_window is None:
            self.tutorial_window = Tutorial()
            self.tutorial_window.open_drop_window.connect(self.menu.open_pinned)
            self.tutorial_window.finished.connect(self._tutorial_closed)
        self.tutorial_window.show()
        self.tutorial_window.raise_()
        self.tutorial_window.activateWindow()

    def show_stats(self) -> None:
        from .ui.stats_window import StatsWindow, owner_config

        owner = owner_config()
        if owner is None:
            return
        if getattr(self, "stats_window", None) is None:
            self.stats_window = StatsWindow(owner)
            self.stats_window.finished.connect(self._stats_closed)
        self.stats_window.show()
        self.stats_window.raise_()
        self.stats_window.activateWindow()

    def _stats_closed(self) -> None:
        window, self.stats_window = self.stats_window, None
        if window is not None:
            window.deleteLater()

    def _tutorial_closed(self) -> None:
        window, self.tutorial_window = self.tutorial_window, None
        if window is not None:
            window.deleteLater()
        self._idle.start()
        QTimer.singleShot(400, self.ask_autostart)

    def ask_autostart(self) -> None:
        """Once, after the first tour: should Satsuma start by itself when the PC starts?"""
        if settings.get("autostart_asked") or not self.detector.supported:
            return
        settings.set("autostart_asked", True)
        if winutil.autostart_enabled():          # already switched on in the tour
            return
        from .ui import controls

        answer = controls._dialog(
            None, "Start Satsuma with Windows?",
            "Satsuma can start by itself when you turn on your PC, so the ring is always ready when "
            "you Shift-drag a file. It waits quietly in the tray and uses very little memory.\n\n"
            "You can change this any time in Settings → Trigger.",
            [("yes", "Start with Windows", True), ("no", "Not now", False)])
        if answer == "yes":
            winutil.set_autostart(True)

    def _reopen_settings(self) -> None:
        """Solid ↔ Glass: make the window again in the new style, on the same page and spot."""
        old = self.settings_window
        if old is None or old.busy:
            return
        page, where = old.stack.currentIndex(), old.geometry()
        self.settings_window = None
        old.finished.disconnect(self._settings_closed)
        old.hide()
        old.deleteLater()
        self.show_settings()
        self.settings_window.setGeometry(where)
        self.settings_window.nav.setCurrentRow(page)

    def _settings_closed(self) -> None:
        # Settings is opened rarely: free it rather than keep ~10 MB of widgets around.
        window = self.settings_window
        if window is None or window.busy:   # an FFmpeg download still reports to it
            return
        self.settings_window = None
        window.deleteLater()
        self._idle.start()

    # ------------------------------------------------------------------ memory
    def _trim_if_idle(self) -> None:
        if self.settings_window is not None and not self.settings_window.isVisible():
            self._settings_closed()   # closed mid-download; free it once the download is over
        busy = (self.menu.isVisible() or self.toasts.isVisible() or self.settings_window is not None
                or self.tutorial_window is not None
                or self.runner.pool.activeThreadCount() > 0 or QApplication.activePopupWidget())
        if busy:
            self._idle.start()   # try again later
            return
        gc.collect()
        winutil.trim_working_set()

    def report_problem(self, what: str = "", error: str = "") -> None:
        from . import report

        report.report(what, error)
        if QSystemTrayIcon.supportsMessages():
            self.tray.showMessage("Report a problem",
                                  "Your browser opened a new GitHub issue. Satsuma's recent log is on your "
                                  "clipboard: paste it in if you like.", app_icon(), 6000)

    def _shortcut_taken(self, name: str) -> None:
        if not name or settings.get("hotkey_warned") == name:     # say it once per shortcut
            return
        settings.set("hotkey_warned", name)
        if QSystemTrayIcon.supportsMessages():
            self.tray.showMessage(f"{name} is taken",
                                  f"Another app already uses {name}. Pick a different shortcut in "
                                  "Settings → Trigger → Keyboard.", app_icon(), 8000)

    def open_for_selection(self) -> None:
        """The keyboard shortcut: the ring for whatever is selected in Explorer or on the desktop."""
        from .hotkey import foreground_window, selected_files

        if self.menu.isVisible() and self.menu.mode in ("click", "pinned"):
            self.menu.dismiss()                     # pressing it again closes the ring
            return
        paths = selected_files(foreground_window())
        if paths:
            self.menu.open_for(paths, QCursor.pos())
        else:
            self.menu.open_pinned()                 # nothing selected: the drop window instead

    def _check_wake(self) -> None:
        """After sleep or standby: make sure Satsuma is fully back (tray icon, shortcut, drag detection)."""
        now = time.time()
        gap, self._wall = now - self._wall, now
        if gap < WAKE_CHECK_MS / 1000 + 45:
            return
        log.info("woke up after %.0f min asleep; checking everything is running", gap / 60)
        self.resume()

    def resume(self) -> None:
        if not self.tray.isVisible():
            self.tray.show()
        self.hotkey.apply()
        self.detector.stop()
        self.detector.start()

    def _idle_for_update(self) -> bool:
        """Nothing on screen and nothing running: a restart now goes unnoticed."""
        return not (self.menu.isVisible() or self.toasts.isVisible() or self.settings_window is not None
                    or self.tutorial_window is not None or getattr(self, "stats_window", None) is not None
                    or self.runner.pool.activeThreadCount() > 0 or QApplication.activePopupWidget()
                    or QApplication.activeModalWidget())

    def announce_update(self) -> None:
        """After a self-update: the What's new card (or a plain notification if there's nothing to say)."""
        news = dict(settings.get("whats_new") or {})
        settings.set("whats_new", {})
        if news.get("version") == VERSION and news.get("highlights"):
            from .ui.whats_new import WhatsNew

            self.whats_new = WhatsNew(VERSION, list(news["highlights"]),
                                      str(news.get("url") or "https://github.com/Elmozoop/Satsuma/releases/latest"))
            self.whats_new.show()
            self.whats_new.raise_()
        elif QSystemTrayIcon.supportsMessages():
            self.tray.showMessage(f"Satsuma updated to {VERSION}",
                                  "It updated itself in the background. Your settings are just as they were.",
                                  app_icon(), 6000)
        self._clean_old()

    def _clean_old(self, tries: int = 10) -> None:
        if not updater.cleanup() and tries > 1:     # the old copy may take a moment to let go
            QTimer.singleShot(3000, lambda: self._clean_old(tries - 1))

    def quit(self) -> None:
        log.info("quitting")
        self.detector.stop()
        self.watcher.stop()
        self.pinger.stop()
        self.updater.stop()
        self.hotkey.stop()
        self.tray.hide()
        if self.server:
            self.server.close()
        self.runner.pool.clear()
        ffmpeg_tool.terminate_all()  # running conversions stop; their cards say why
        self.app.quit()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    args = argv[1:]
    if "--self-test" in args:
        # The exe has no console, so the report goes to a file (default: beside the log).
        from .config import DATA_DIR
        from .selftest import run

        target = next((a.split("=", 1)[1] for a in args if a.startswith("--report=")), None)
        return run(Path(target) if target else DATA_DIR / "selftest.txt")
    background = "--background" in args
    after_update = next((a.split("=", 1)[1] for a in args if a.startswith("--after-update=")), None)
    if after_update and after_update.isdigit():
        updater.wait_for_exit(int(after_update))     # the old version is still closing
    want_settings = "--settings" in args
    files = [a for a in args if not a.startswith("--")]

    if sys.platform == "win32":
        try:  # own taskbar identity instead of python.exe's
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:
            pass

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(argv)
    app.setApplicationName("Satsuma")
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(app_icon())

    payload = {"paths": [str(Path(f).resolve()) for f in files]} if files else (
        {"cmd": "settings"} if want_settings else {"cmd": "show"})
    if forward_to_running_instance(payload if (files or want_settings or not background) else {"cmd": "noop"}):
        return 0

    setup_logging()
    log.info("starting Satsuma %s (args=%s)", VERSION, args)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        log.warning("no system tray available")

    satsuma = Satsuma(app)
    satsuma.listen()
    if files:
        QTimer.singleShot(0, lambda: satsuma.handle_request(payload))
    elif want_settings:
        QTimer.singleShot(0, satsuma.show_settings)
    elif not settings.get("tutorial_done"):
        QTimer.singleShot(0, satsuma.show_tutorial)       # first run: the tour instead of a balloon
    elif not background:
        QTimer.singleShot(400, satsuma.greet)
    if after_update:
        QTimer.singleShot(1500, satsuma.announce_update)
    else:
        QTimer.singleShot(5000, satsuma._clean_old)
    app._satsuma = satsuma  # keep a strong reference for the lifetime of the app
    code = app.exec()
    satsuma.runner.pool.waitForDone(3000)
    logging.shutdown()
    # Don't let a worker stuck in an external tool (LibreOffice, Office) keep the process alive.
    os._exit(code)
