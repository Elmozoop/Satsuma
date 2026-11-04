"""The tray icon reflects what Satsuma is doing: a progress ring while jobs run, then a brief tick."""
from __future__ import annotations

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

from .icons import draw_icon

SIZE = 64          # drawn large; Windows scales it down crisply
DONE_MS = 2500     # how long the tick stays after the last job


def badge_icon(base: QIcon, fraction: float | None, done: bool = False, failed: bool = False) -> QIcon:
    """`base` with a progress ring (fraction 0..1, or None for "busy, unknown") or a result badge."""
    pixmap = QPixmap(SIZE, SIZE)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    inset = 9 if fraction is not None or not (done or failed) else 0
    art = base.pixmap(SIZE, SIZE)   # may come back larger on a scaled display: draw all of it
    painter.drawPixmap(QRectF(inset, inset, SIZE - 2 * inset, SIZE - 2 * inset), art, QRectF(art.rect()))
    if not (done or failed):
        ring = QRectF(3, 3, SIZE - 6, SIZE - 6)
        painter.setPen(QPen(QColor(128, 128, 128, 120), 6))   # visible on dark and light taskbars
        painter.drawEllipse(ring)
        painter.setPen(QPen(QColor(255, 138, 31), 6, Qt.SolidLine, Qt.RoundCap))
        span = 0.25 if fraction is None else max(0.04, min(1.0, fraction))
        painter.drawArc(ring, 90 * 16, int(-360 * 16 * span))
    else:
        centre = QPointF(SIZE - 15, SIZE - 15)
        painter.setPen(QPen(QColor(20, 20, 24), 3))
        painter.setBrush(QColor(255, 99, 88) if failed else QColor(76, 201, 128))
        painter.drawEllipse(centre, 14, 14)
        draw_icon(painter, "close" if failed else "tick", centre, 18, QColor(255, 255, 255), 3.2)
    painter.end()
    return QIcon(pixmap)


class TrayActivity(QObject):
    """Listens to the job runner and keeps the tray icon and tooltip up to date."""

    def __init__(self, tray, base_icon: QIcon, idle_tooltip, signals, parent=None):
        super().__init__(parent)
        self.tray = tray
        self.base = base_icon
        self.idle_tooltip = idle_tooltip          # a callable: the modifier key can change
        self.jobs: dict[int, float] = {}
        self._failed = False
        self._dirty = False
        self._redraw = QTimer(self)
        self._redraw.setInterval(200)            # progress arrives often: redraw at most 5×/s
        self._redraw.timeout.connect(self._refresh)
        self._rest = QTimer(self)
        self._rest.setSingleShot(True)
        self._rest.timeout.connect(self._idle)
        signals.started.connect(self._started)
        signals.progress.connect(self._progress)
        signals.finished.connect(lambda job_id, _o: self._ended(job_id, False))
        signals.failed.connect(lambda job_id, _m: self._ended(job_id, True))
        signals.cancelled.connect(lambda job_id: self._ended(job_id, False))

    def _started(self, job_id: int, *_args) -> None:
        self._rest.stop()
        if not self.jobs:
            self._failed = False
        self.jobs[job_id] = 0.0
        self._dirty = True
        self._refresh()
        self._redraw.start()

    def _progress(self, job_id: int, fraction: float, _message: str) -> None:
        if job_id in self.jobs:
            self.jobs[job_id] = fraction
            self._dirty = True

    def _ended(self, job_id: int, failed: bool) -> None:
        if self.jobs.pop(job_id, None) is None:
            return
        self._failed |= failed
        if self.jobs:
            self._dirty = True
            return
        self._redraw.stop()
        self.tray.setIcon(badge_icon(self.base, None, done=not self._failed, failed=self._failed))

        self._rest.start(DONE_MS)

    def _refresh(self) -> None:
        if not self._dirty or not self.jobs:
            return
        self._dirty = False
        fraction = sum(self.jobs.values()) / len(self.jobs)
        self.tray.setIcon(badge_icon(self.base, fraction))


    def _idle(self) -> None:
        self.tray.setIcon(self.base)
        self.tray.setToolTip(self.idle_tooltip())
