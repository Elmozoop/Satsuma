"""Application wiring: tray icon, single instance, detector → menu → jobs → toasts."""
from __future__ import annotations

import gc
import getpass
import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QCursor, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from . import winutil
from .actions import Action
from .config import APP_ID, ASSETS_DIR, LOG_FILE, VERSION, settings
from .detector import DragDetector
from .engine import documents
from .engine import ffmpeg_tool
from .engine.paths import open_file, reveal
from .jobs import JobRunner
from .ui import prompts
from .ui.menu import ActionMenu
from .ui.settings_window import SettingsWindow
from .ui.toast import Toasts

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
        self.detector = DragDetector(self)
        self.settings_window: SettingsWindow | None = None
        self.server: QLocalServer | None = None

        self.menu.chosen.connect(self.on_chosen)
        self.detector.is_revealed = lambda: self.menu.mode not in ("sense", "hidden")

        s = self.runner.signals
        s.started.connect(self.toasts.started)
        s.progress.connect(self.toasts.progress)
        s.finished.connect(self.toasts.finished)
        s.failed.connect(self.toasts.failed)
        s.cancelled.connect(self.toasts.cancelled)
        s.finished.connect(self.on_finished)
        self.toasts.cancel_requested.connect(self.runner.cancel)

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
        self.detector.start()
        self._idle.start()

    # ------------------------------------------------------------------ tray
    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip(f"Satsuma — hold {settings.get('modifier').title()} while dragging a file")
        menu = QMenu()
        header = QAction(f"Satsuma {VERSION}", menu)
        header.setEnabled(False)
        menu.addAction(header)
        menu.addSeparator()
        self.enabled_action = QAction("Enabled", menu, checkable=True)
        self.enabled_action.setChecked(bool(settings.get("enabled")))
        self.enabled_action.toggled.connect(lambda v: settings.set("enabled", v))
        menu.addAction(self.enabled_action)
        menu.addAction("Open drop window", self.menu.open_pinned)
        menu.addAction("Settings…", self.show_settings)
        menu.addSeparator()
        menu.addAction("Open log", lambda: open_file(LOG_FILE))
        menu.addAction("Quit", self.quit)
        menu.aboutToShow.connect(lambda: self.enabled_action.setChecked(bool(settings.get("enabled"))))
        self.tray.setContextMenu(menu)
        self._tray_menu = menu
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

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
            QMessageBox.warning(None, "Satsuma", f"Could not read the file: {exc}")
            return
        if params is not None:
            self.runner.submit(action, paths, params)

    def on_finished(self, _job_id: int, outputs: list) -> None:
        if settings.get("reveal_after") and outputs:
            reveal(outputs[0])

    def show_settings(self) -> None:
        if self.settings_window is None:
            self.settings_window = SettingsWindow()
            self.settings_window.finished.connect(self._settings_closed)
        self.settings_window.show()
        self.settings_window.raise_()
        self.settings_window.activateWindow()

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
                or self.runner.pool.activeThreadCount() > 0 or QApplication.activePopupWidget())
        if busy:
            self._idle.start()   # try again later
            return
        gc.collect()
        winutil.trim_working_set()

    def quit(self) -> None:
        self.detector.stop()
        self.tray.hide()
        if self.server:
            self.server.close()
        self.runner.pool.clear()
        ffmpeg_tool.terminate_all()  # running conversions stop; their cards say why
        self.app.quit()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    args = argv[1:]
    background = "--background" in args
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
    elif not background:
        QTimer.singleShot(400, satsuma.greet)
    app._satsuma = satsuma  # keep a strong reference for the lifetime of the app
    code = app.exec()
    satsuma.runner.pool.waitForDone(3000)
    logging.shutdown()
    # Don't let a worker stuck in an external tool (LibreOffice, Office) keep the process alive.
    os._exit(code)
