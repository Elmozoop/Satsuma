"""The radial action menu window.

Modes
-----
* sense   – armed by Shift-drag. Invisible (alpha 1/255 so it is still hit-testable)
            and parked under the cursor. Reveals itself only when Windows reports
            an actual file drag entering it.
* drop    – revealed: wedges are drop targets for the drag in progress.
* click   – opened with files already known (Send To, command line). Wedges are buttons.
* pinned  – the "drop window" from the tray: stays open, any drag of files lights it up.
"""
from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..actions import Action
from ..config import settings
from .anim import FrameClock
from .icons import draw_icon
from .radial import RadialView, Wedge
from .theme import palette

SENSE_SIZE = 120  # invisible sensor square, centred on the cursor


def local_paths(mime) -> list[Path]:
    if mime is None or not mime.hasUrls():
        return []
    paths = []
    for url in mime.urls():
        if url.isLocalFile():
            path = Path(url.toLocalFile())
            if path.exists():
                paths.append(path)
    return paths


class ActionMenu(QWidget):
    """Emits `chosen(action, paths)` once the user picks an action."""

    chosen = Signal(object, list)
    closed = Signal()

    def __init__(self):
        super().__init__(None)
        self.setWindowTitle("Satsuma")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)

        self.view = RadialView()
        self.clock = FrameClock(self)
        self.clock.frame.connect(self._frame)

        self.mode = "hidden"
        self.paths: list[Path] = []
        self._dropped = False
        self._focusable: bool | None = None
        self._was_active = False
        self._press: tuple[QPoint, object] | None = None   # (global pos, hit) of a mouse press
        self._moving_window = False

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._hide_if_idle)
        settings.subscribe(self._on_setting)

    # ------------------------------------------------------------------ helpers
    @property
    def center(self) -> QPointF:
        return QPointF(self.width() / 2, self.height() / 2)

    def point_for(self, action_id: str) -> QPoint:
        """Local point at the middle of an action's wedge on the current ring (tests, a11y)."""
        for wedge in self.view.page_wedges():
            if wedge.action.id == action_id:
                return self.view.wedge_center(wedge, self.center).toPoint()
        raise KeyError(action_id)

    def hub_point(self) -> QPoint:
        return self.center.toPoint()

    def close_point(self) -> QPointF:
        r = self.view.radius + 4 * self.view.scale
        return QPointF(self.center.x() + r * math.cos(-math.pi / 4),
                       self.center.y() + r * math.sin(-math.pi / 4))

    def _on_setting(self, key: str) -> None:
        if self.mode in ("click", "pinned", "drop") and key in ("menu_scale", "wedges_per_ring",
                                                                "start_page", "*"):
            self.view.set_paths(self.paths, animate=False)
            self._resize_keep_center()
        self.update()

    def _apply_flags(self, focusable: bool) -> None:
        if self._focusable == focusable:
            return
        self._focusable = focusable
        flags = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        if not focusable:
            flags |= Qt.WindowDoesNotAcceptFocus
        was_visible = self.isVisible()
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_ShowWithoutActivating, not focusable)
        if was_visible:
            self.show()

    # ------------------------------------------------------------------ entry points
    def arm(self, cursor: QPoint, smart: bool = True) -> None:
        """Called by the detector when a modifier-drag starts."""
        if self.mode in ("drop", "click", "pinned", "confirming"):
            return
        self._hide_timer.stop()
        self._dropped = False
        self.paths = []
        self._apply_flags(focusable=False)
        if smart:
            self.mode = "sense"
            self.view.opening.snap(0.0)
            self._place_sensor(cursor)
        else:
            self.mode = "drop"
            self.view.empty_text = "Drop here"
            self.view.set_paths([])
            self._open_at(cursor)
        self.show()
        self.raise_()

    def follow(self, cursor: QPoint) -> None:
        if self.mode == "sense":
            self._place_sensor(cursor)

    def released(self) -> None:
        if self.mode in ("sense", "drop"):
            self._hide_timer.start(120)  # grace period: the drop event may still be on its way

    def disarm(self) -> None:
        if self.mode == "sense":
            self.dismiss(animate=False)

    def open_for(self, paths, cursor: QPoint | None = None) -> None:
        """Click mode: files already known (Send To / command line)."""
        self.paths = [Path(p) for p in paths]
        self.mode = "click"
        self._was_active = False
        self._apply_flags(focusable=True)
        self.view.dwell_enabled = False
        self.view.set_paths(self.paths)
        self._open_at(cursor or QCursor.pos())
        self.show()
        self.raise_()
        self.activateWindow()

    def open_pinned(self) -> None:
        self.paths = []
        self.mode = "pinned"
        self._apply_flags(focusable=True)
        self.view.dwell_enabled = True
        self.view.empty_text = "Drop files here"
        self.view.set_paths([])
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self._open_at(screen.center())
        self.show()
        self.raise_()
        self.activateWindow()

    def dismiss(self, animate: bool = True) -> None:
        self._hide_timer.stop()
        if animate and self.isVisible() and self.mode not in ("sense", "hidden"):
            self.mode = "closing"
            self.view.close()
            self.clock.start()
            return
        self._finish_close()

    def _finish_close(self) -> None:
        self.clock.stop()
        self.mode = "hidden"
        self.view.set_hover(None)
        self.view.opening.snap(0.0)
        self.view.glow.snap(0.0)
        self.view.release()
        self.hide()
        self.closed.emit()

    # ------------------------------------------------------------------ geometry
    def _place_sensor(self, cursor: QPoint) -> None:
        self.setFixedSize(SENSE_SIZE, SENSE_SIZE)
        self.move(cursor.x() - SENSE_SIZE // 2, cursor.y() - SENSE_SIZE // 2)

    def _open_at(self, cursor: QPoint) -> None:
        side = self.view.side
        self.setFixedSize(side, side)
        screen = QGuiApplication.screenAt(cursor) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        reach = int(self.view.radius + 12 * self.view.scale)   # keep the ring itself on screen
        cx = max(area.left() + reach, min(cursor.x(), area.right() - reach))
        cy = max(area.top() + reach, min(cursor.y(), area.bottom() - reach))
        self.move(cx - side // 2, cy - side // 2)
        self.view.open(animate=True)
        self.clock.start()
        self.update()

    def _resize_keep_center(self) -> None:
        if self.mode in ("hidden", "sense"):
            return
        middle = self.geometry().center()
        side = self.view.side
        self.setFixedSize(side, side)
        self.move(middle.x() - side // 2, middle.y() - side // 2)

    # ------------------------------------------------------------------ animation
    def _frame(self, dt: float) -> None:
        moving, _switched = self.view.tick(dt)
        if self.mode == "closing" and self.view.closed:
            self._finish_close()
            return
        self.update()
        if not moving:
            self.clock.stop()

    def _set_hover(self, target) -> None:
        before = self.view.hover
        self.view.set_hover(target)
        if self.view.hover is not before:
            self.clock.start()

    def _hide_if_idle(self) -> None:
        if not self._dropped and self.mode in ("sense", "drop"):
            self.dismiss(animate=self.mode == "drop")

    # ------------------------------------------------------------------ drag & drop
    def dragEnterEvent(self, event) -> None:
        paths = local_paths(event.mimeData())
        if not paths or self.mode == "confirming":
            event.ignore()
            return
        self._hide_timer.stop()
        self.view.glow.to(1.0)
        self.clock.start()
        if self.mode == "sense":
            self.mode = "drop"
            self.paths = paths
            self.view.dwell_enabled = True
            self.view.set_paths(paths)
            self._open_at(QCursor.pos())
        elif self.mode in ("drop", "pinned") and paths != self.paths:
            self.paths = paths
            self.view.dwell_enabled = True
            self.view.set_paths(paths)
            self.clock.start()
        event.setDropAction(Qt.CopyAction)
        event.accept()

    def dragMoveEvent(self, event) -> None:
        target = self.view.hit(event.position(), self.center)
        self._set_hover(target)
        # Always COPY: with Shift held Explorer proposes MOVE, which would delete the original.
        event.setDropAction(Qt.CopyAction)
        if isinstance(target, Wedge):
            event.accept()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self.view.glow.to(0.0)
        self.clock.start()
        self._set_hover(None)
        event.accept()

    def dropEvent(self, event) -> None:
        self.view.glow.to(0.0)
        target = self.view.hit(event.position(), self.center)
        paths = local_paths(event.mimeData()) or self.paths
        event.setDropAction(Qt.CopyAction)
        if not isinstance(target, Wedge) or not paths:
            event.ignore()
            return
        event.accept()
        self._dropped = True
        # Return to the drag source first; never block inside a drop callback.
        QTimer.singleShot(0, lambda: self._choose(target, paths))

    def _choose(self, wedge: Wedge, paths: list[Path]) -> None:
        animate = settings.get("anim_speed") != "off"
        if animate:
            self.view.confirm_choice(wedge)    # a short tick on the chosen wedge first
            self.clock.start()
        if self.mode != "pinned":
            self.mode = "confirming"
            QTimer.singleShot(280 if animate else 0, lambda: self.dismiss(animate=True))
        else:
            self._set_hover(None)
            QTimer.singleShot(650, self._clear_confirm)   # the drop window stays open: tidy up
        self.chosen.emit(wedge.action, paths)

    def _clear_confirm(self) -> None:
        self.view.chosen = None
        self.view.confirm.snap(0.0)
        self.update()

    # ------------------------------------------------------------------ mouse (click / pinned)
    def mouseMoveEvent(self, event) -> None:
        if self._press and self.mode == "pinned" and event.buttons() & Qt.LeftButton:
            origin, hit = self._press
            delta = event.globalPosition().toPoint() - origin
            if not isinstance(hit, Wedge) and (self._moving_window or delta.manhattanLength() > 4):
                self._moving_window = True
                self.move(self.pos() + delta)
                self._press = (event.globalPosition().toPoint(), hit)
                return
        if self.mode in ("click", "pinned"):
            target = self.view.hit(event.position(), self.center)
            self._set_hover(target)
            interactive = isinstance(target, Wedge) or (target == "hub" and len(self.view.pages) > 1)
            self.setCursor(Qt.PointingHandCursor if interactive else Qt.ArrowCursor)

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        if self.mode in ("pinned", "click") and self._near_close(event.position()):
            self.dismiss()
            return
        self._press = (event.globalPosition().toPoint(), self.view.hit(event.position(), self.center))
        self._moving_window = False

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.LeftButton or self._press is None:
            return
        _origin, pressed = self._press
        self._press = None
        if self._moving_window:
            self._moving_window = False
            return
        target = self.view.hit(event.position(), self.center)
        if self.mode not in ("click", "pinned"):
            return
        if isinstance(target, Wedge) and target is pressed and self.paths:
            self._choose(target, list(self.paths))
        elif target == "hub" and pressed == "hub":
            self.view.switch_page()
            self.clock.start()
        elif target is None and pressed is None and self.mode == "click":
            self.dismiss()   # clicked the empty corner outside the ring

    def leaveEvent(self, event) -> None:
        if self.mode in ("click", "pinned"):
            self._set_hover(None)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.dismiss()
        elif event.key() in (Qt.Key_Tab, Qt.Key_Space):
            self.view.switch_page()
            self.clock.start()

    def changeEvent(self, event) -> None:
        # Click mode behaves like a popup: lose focus, close.
        if event.type() == event.Type.ActivationChange and self.mode == "click":
            if self.isActiveWindow():
                self._was_active = True
            elif self._was_active:
                QTimer.singleShot(0, self._dismiss_if_inactive)
        super().changeEvent(event)

    def _dismiss_if_inactive(self) -> None:
        if self.mode == "click" and not self.isActiveWindow():
            self.dismiss()

    def _near_close(self, pos: QPointF) -> bool:
        c = self.close_point()
        return math.hypot(pos.x() - c.x(), pos.y() - c.y()) <= 13 * self.view.scale

    # ------------------------------------------------------------------ painting
    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        # Alpha 1 everywhere: invisible, but Windows still routes the drag to us.
        painter.fillRect(self.rect(), QColor(0, 0, 0, 1))
        if self.mode in ("sense", "hidden"):
            return
        self.view.paint(painter, self.center)
        if self.mode in ("pinned", "click") and self.view.opening.value > 0.5:
            pal = palette()
            c = self.close_point()
            s = self.view.scale
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setOpacity(min(1.0, (self.view.opening.value - 0.5) * 2))
            painter.setPen(QPen(pal.border, 1))
            painter.setBrush(pal.panel)
            painter.drawEllipse(c, 12 * s, 12 * s)
            draw_icon(painter, "close", c, 13 * s, pal.muted, 1.6 * s)
