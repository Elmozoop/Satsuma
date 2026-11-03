"""Live, interactive preview of the radial menu for the Settings window."""
from __future__ import annotations

import shutil
import tempfile
from functools import partial
from pathlib import Path

from PySide6.QtCore import QPointF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..config import settings
from .anim import FrameClock
from .radial import RadialView, Wedge
from .theme import is_dark

SAMPLES = {"image": ("Holiday photo.png", 2_400_000), "video": ("Screen recording.mp4", 48_000_000),
           "audio": ("Voice note.wav", 5_300_000), "pdf": ("Lab report.pdf", 1_250_000),
           "document": ("Notes.md", 12_000)}
LAYOUT_KEYS = {"menu_scale", "wedges_per_ring", "start_page", "actions_hidden", "actions_order",
               "show_icons", "hub_info", "show_captions", "*"}
REPLAY_KEYS = {"anim_speed", "bounce", "menu_scale", "*"}


def _release(listener, folder: Path, *_args) -> None:
    settings.unsubscribe(listener)
    shutil.rmtree(folder, ignore_errors=True)


class RadialPreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumSize(300, 300)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.view = RadialView()
        self.view.dwell_enabled = False   # click the centre to swap rings here
        self.clock = FrameClock(self)
        self.clock.frame.connect(self._frame)
        self._dir = Path(tempfile.mkdtemp(prefix="satsuma-preview-"))
        self.kind = "image"
        self._user_hover = False
        self._demo_index = -1
        self._demo = QTimer(self)
        self._demo.setInterval(1100)
        self._demo.timeout.connect(self._demo_step)
        settings.subscribe(self._on_setting)
        # The settings window is freed when closed: stop listening and drop the sample files.
        self.destroyed.connect(partial(_release, self._on_setting, self._dir))
        self.set_kind("image")
        self._demo.start()

    def sizeHint(self) -> QSize:
        return QSize(380, 380)

    # ------------------------------------------------------------------ content
    def set_kind(self, kind: str) -> None:
        self.kind = kind if kind in SAMPLES else "image"
        name, size = SAMPLES[self.kind]
        path = self._dir / name
        if not path.exists():
            with open(path, "wb") as handle:   # sparse: reports the size without using disk
                handle.truncate(size)
        self.view.set_paths([path])
        self.replay()

    def replay(self) -> None:
        self._demo_index = -1
        self.view.set_hover(None)
        self.view.open(animate=True)
        self.clock.start()

    def _on_setting(self, key: str) -> None:
        if key in LAYOUT_KEYS:
            page = self.view.page
            self.view.set_paths(self.view.paths, animate=False)
            if page < len(self.view.pages):
                self.view.switch_page(page) if page else None
                self.view.page_pos.snap(float(self.view.page))
        if key in REPLAY_KEYS:
            self.replay()
        self.clock.start()
        self.update()

    # ------------------------------------------------------------------ demo hover
    def _demo_step(self) -> None:
        if self._user_hover or not self.isVisible():
            return
        wedges = self.view.page_wedges()
        if not wedges:
            return
        self._demo_index = (self._demo_index + 1) % (len(wedges) + 1)
        self.view.set_hover(wedges[self._demo_index] if self._demo_index < len(wedges) else None)
        self.clock.start()

    # ------------------------------------------------------------------ geometry
    def _fit(self) -> float:
        side = self.view.side
        return min(1.0, min(self.width(), self.height()) / side)

    def _to_view(self, pos) -> QPointF:
        fit = self._fit()
        c = QPointF(self.width() / 2, self.height() / 2)
        return QPointF(c.x() + (pos.x() - c.x()) / fit, c.y() + (pos.y() - c.y()) / fit)

    # ------------------------------------------------------------------ events
    def _frame(self, dt: float) -> None:
        moving, _ = self.view.tick(dt)
        self.update()
        if not moving:
            self.clock.stop()

    def mouseMoveEvent(self, event) -> None:
        self._user_hover = True
        c = QPointF(self.width() / 2, self.height() / 2)
        target = self.view.hit(self._to_view(event.position()), c)
        self.view.set_hover(target)
        self.setCursor(Qt.PointingHandCursor if isinstance(target, Wedge) or target == "hub" else Qt.ArrowCursor)
        self.clock.start()

    def leaveEvent(self, _event) -> None:
        self._user_hover = False
        self.view.set_hover(None)
        self.clock.start()

    def mouseReleaseEvent(self, event) -> None:
        c = QPointF(self.width() / 2, self.height() / 2)
        if self.view.hit(self._to_view(event.position()), c) == "hub":
            self.view.switch_page()
            self.clock.start()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        # A desktop-like backdrop so glass and shadows read as they will on screen.
        path = QPainterPath()
        path.addRoundedRect(self.rect().adjusted(0, 0, -1, -1), 12, 12)
        backdrop = QLinearGradient(0, 0, self.width(), self.height())
        if is_dark():
            backdrop.setColorAt(0, QColor(46, 58, 92))
            backdrop.setColorAt(1, QColor(24, 26, 38))
        else:
            backdrop.setColorAt(0, QColor(214, 228, 248))
            backdrop.setColorAt(1, QColor(240, 212, 196))
        painter.fillPath(path, backdrop)
        painter.setClipPath(path)
        fit = self._fit()
        c = QPointF(self.width() / 2, self.height() / 2)
        painter.translate(c)
        painter.scale(fit, fit)
        painter.translate(-c)
        self.view.paint(painter, c)
        if fit < 0.999:
            painter.resetTransform()
            painter.setPen(QColor(255, 255, 255, 170) if is_dark() else QColor(0, 0, 0, 140))
            painter.drawText(self.rect().adjusted(0, 0, -10, -8), Qt.AlignRight | Qt.AlignBottom,
                             f"shown at {round(fit * 100)}%")
