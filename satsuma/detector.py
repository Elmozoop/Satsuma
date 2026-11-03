"""Notices a modifier-held drag anywhere on the desktop.

Polls the physical button and modifier state with GetAsyncKeyState: every 60 ms while
the mouse button is up, every 15 ms from the moment it goes down until it is released.
Polling (rather than a low-level mouse hook) cannot slow down the user's mouse and
cannot be silently unhooked by Windows when the app is busy.

State machine
    idle ──press──▶ pressed ──moved > threshold & modifier──▶ armed ──release──▶ idle
                       └──────────────release──────────────────────────────────▶ idle
"""
from __future__ import annotations

import math

from PySide6.QtCore import QObject, QPoint, QTimer, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication

from . import winutil
from .config import settings

POLL_MS = 15        # while a button is down: smooth tracking of the drag
IDLE_POLL_MS = 60   # while idle: a press is still caught long before a drag can arm


class DragDetector(QObject):
    armed = Signal(QPoint)      # modifier-drag started at this point
    moved = Signal(QPoint)      # cursor while armed
    released = Signal()         # button came up while armed
    disarmed = Signal()         # modifier let go before any file drag was seen

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = "idle"
        self.origin = QPoint()
        self.button_vk = winutil.VK_LBUTTON
        # The app replaces this so we can ask whether the menu has revealed itself.
        self.is_revealed = lambda: False
        self._timer = QTimer(self)
        self._timer.setInterval(IDLE_POLL_MS)
        self._timer.timeout.connect(self._poll)

    @property
    def supported(self) -> bool:
        return winutil.IS_WINDOWS

    def start(self) -> None:
        if self.supported:
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self.state = "idle"

    def _over_own_window(self, pos: QPoint) -> bool:
        widget = QApplication.widgetAt(pos)
        return widget is not None

    def _poll(self) -> None:
        self._step()
        # Poll fast only while something may be happening; idle checks cost far less CPU.
        interval = IDLE_POLL_MS if self.state == "idle" else POLL_MS
        if self._timer.interval() != interval:
            self._timer.setInterval(interval)

    def _step(self) -> None:
        if not settings.get("enabled"):
            if self.state == "armed":
                self.released.emit()
            self.state = "idle"
            return

        if self.state == "idle":
            # Read the swap setting at each new press, so changing it needs no restart.
            self.button_vk = winutil.primary_button_vk()

        down = winutil.key_down(self.button_vk)
        pos = QCursor.pos()

        if self.state == "idle":
            if down:
                self.origin = pos
                # Ignore drags that begin on our own windows (settings, drop window, toasts).
                self.state = "ignored" if self._over_own_window(pos) else "pressed"
            return

        if not down:
            if self.state == "armed":
                self.released.emit()
            self.state = "idle"
            return

        if self.state == "pressed":
            distance = math.hypot(pos.x() - self.origin.x(), pos.y() - self.origin.y())
            if distance >= settings.get("drag_threshold") and winutil.key_down(settings.modifier_vk):
                self.state = "armed"
                self.armed.emit(pos)
            return

        if self.state == "armed":
            if not self.is_revealed() and not winutil.key_down(settings.modifier_vk):
                # Let go of Shift before a file drag reached us: back to waiting,
                # so pressing it again during the same drag re-arms.
                self.state = "pressed"
                self.disarmed.emit()
                return
            self.moved.emit(pos)
