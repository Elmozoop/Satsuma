"""Bottom-right stack of job cards: progress and Cancel, then Open / Show in folder / Undo.
A finished card can also be dragged, carrying its files into any app that accepts a file drop."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMimeData, QPoint, QPointF, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (QColor, QDrag, QFont, QFontMetrics, QGuiApplication, QPainter, QPainterPath, QPen,
                           QPixmap)
from PySide6.QtWidgets import QApplication, QWidget

from .. import winutil
from ..engine.paths import human_size, open_file, reveal, undo_targets
from . import thumbs
from .anim import FrameClock, Spring
from .icons import draw_icon
from .theme import palette, ui_font

CARD_W = 340
CARD_H = 74
MARGIN = 14
SHADOW = 12
BTN_H = 22
THUMB = 48


def _total_size(paths) -> int | None:
    """Combined size of files, or None if any is a folder or can't be read."""
    total = 0
    for path in paths:
        path = Path(path)
        try:
            if not path.is_file():
                return None
            total += path.stat().st_size
        except OSError:
            return None
    return total


def size_change(before: int | None, after: int | None) -> str:
    """'2.4 MB → 380 KB (−84%)', or just the new size when there's nothing to compare."""
    if after is None:
        return ""
    if not before:
        return human_size(after)
    change = round((after - before) / before * 100)
    note = f" (−{-change}%)" if change <= -1 else f" (+{change}%)" if change >= 1 else ""
    return f"{human_size(before)} → {human_size(after)}{note}"


class Card:
    def __init__(self, job_id: int, title: str, subtitle: str):
        self.id = job_id
        self.title = title
        self.subtitle = subtitle
        self.message = "Starting…"
        self.fraction = 0.0
        self.state = "running"   # running | cancelling | done | failed | cancelled | undone
        self.outputs: list[Path] = []
        self.before: int | None = None     # size of the sources, for "before → after"
        self.thumb: QPixmap | None = None
        self.buttons: list[tuple[QRectF, str]] = []
        self.close_rect = QRectF()
        self.rect = QRectF()
        self.expire_ms = 0
        self.slot = Spring(0.0, "main")       # 0 = bottom of the stack
        self.appear = Spring(0.0, "main")     # slides in from the right
        self.shown = Spring(0.0, "hover")     # smoothed progress bar
        self.leaving = False


class Toasts(QWidget):
    cancel_requested = Signal(int)   # job id

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                            | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)
        self.cards: list[Card] = []
        self.hover_button: tuple[int, str] | None = None
        self._drag_from: tuple[QPointF, Card] | None = None   # press on a finished card's body
        self._tick = QTimer(self)
        self._tick.setInterval(250)
        self._tick.timeout.connect(self._expire)
        self._tick.start()
        self._hovered = False
        self.clock = FrameClock(self)
        self.clock.frame.connect(self._frame)

    # ----------------------------------------------------------------- job events
    def _card(self, job_id: int) -> Card | None:
        return next((c for c in self.cards if c.id == job_id), None)

    def started(self, job_id: int, title: str, subtitle: str) -> None:
        card = Card(job_id, title, subtitle)
        card.appear.to(1.0)
        self.cards.append(card)
        active = [c for c in self.cards if not c.leaving]
        for old in active[:-5]:            # keep at most five
            self._remove(old)
        self._restack()
        self._relayout()

    def _remove(self, card: Card) -> None:
        if not card.leaving:
            card.leaving = True
            card.appear.to(0.0)
            self._restack()
            self.clock.start()

    def _restack(self) -> None:
        active = [c for c in self.cards if not c.leaving]
        for i, card in enumerate(active):
            target = float(len(active) - 1 - i)   # newest at the bottom
            if card.slot.value == 0.0 and card.slot.target == 0.0 and card is active[-1]:
                card.slot.snap(target)
            card.slot.to(target)
        self.clock.start()

    def _frame(self, dt: float) -> None:
        moving = False
        for card in self.cards:
            moving |= card.slot.step(dt)
            moving |= card.appear.step(dt)
            moving |= card.shown.step(dt)
        gone = [c for c in self.cards if c.leaving and c.appear.value <= 0.02]
        if gone:
            self.cards = [c for c in self.cards if c not in gone]
            self._relayout()
        self.update()
        if not moving:
            self.clock.stop()

    def progress(self, job_id: int, fraction: float, message: str) -> None:
        card = self._card(job_id)
        if card:
            card.fraction, card.message = fraction, message
            card.shown.to(fraction)
            self.clock.start()

    def sources(self, job_id: int, paths: list[str]) -> None:
        card = self._card(job_id)
        if card:
            card.before = _total_size(paths)

    def finished(self, job_id: int, outputs: list[str]) -> None:
        card = self._card(job_id)
        if not card:
            return
        card.state = "done"
        card.fraction = 1.0
        card.shown.to(1.0)
        card.outputs = [Path(o) for o in outputs]
        sizes = size_change(card.before, _total_size(card.outputs))
        name = card.outputs[0].name if len(card.outputs) == 1 else f"{len(card.outputs)} files"
        card.message = f"{name} · {sizes}" if sizes else name
        first = next((o for o in card.outputs if o.is_file()), None)
        image = thumbs.thumbnail(first, THUMB * 2) if first else None
        if image is not None:
            card.thumb = QPixmap.fromImage(image)
        card.expire_ms = 15000   # long enough to notice Undo
        self._relayout()

    def cancelled(self, job_id: int) -> None:
        card = self._card(job_id)
        if not card:
            return
        card.state = "cancelled"
        card.message = "Cancelled"
        card.expire_ms = 4000
        self._relayout()

    def _cancel(self, card: Card) -> None:
        card.state = "cancelling"
        card.message = "Cancelling…"
        self.cancel_requested.emit(card.id)
        self.update()

    def _undo(self, card: Card) -> None:
        if winutil.recycle(undo_targets(card.outputs)):
            card.state = "undone"
            card.message = "Moved to the Recycle Bin"
        else:
            card.message = "Couldn't move it to the Recycle Bin"
        card.expire_ms = 4000
        self.update()

    def failed(self, job_id: int, message: str) -> None:
        card = self._card(job_id)
        if not card:
            return
        card.state = "failed"
        card.message = message
        card.expire_ms = 25000
        self._relayout()

    # ----------------------------------------------------------------- layout
    def _relayout(self) -> None:
        if not self.cards:
            self.hide()
            return
        height = len(self.cards) * (CARD_H + 8) - 8 + SHADOW * 2
        self.setFixedSize(CARD_W + SHADOW * 2, height)
        area = QGuiApplication.primaryScreen().availableGeometry()
        self.move(QPoint(area.right() - self.width() - MARGIN + SHADOW,
                         area.bottom() - self.height() - MARGIN + SHADOW))
        if not self.isVisible():
            self.show()
        self.update()

    def _expire(self) -> None:
        if self._hovered:
            return
        for card in list(self.cards):
            if card.state not in ("running", "cancelling") and not card.leaving:
                card.expire_ms -= self._tick.interval()
                if card.expire_ms <= 0:
                    self._remove(card)

    # ----------------------------------------------------------------- input
    def enterEvent(self, _event) -> None:
        self._hovered = True

    def leaveEvent(self, _event) -> None:
        self._hovered = False
        self.hover_button = None
        self.update()

    def _draggable(self, pos: QPointF) -> Card | None:
        """The finished card under `pos`, unless the point is on one of its buttons."""
        for card in self.cards:
            if card.state != "done" or card.leaving or not card.rect.contains(pos):
                continue
            if card.close_rect.contains(pos) or any(r.contains(pos) for r, _n in card.buttons):
                return None
            return card if any(o.exists() for o in card.outputs) else None
        return None

    def mousePressEvent(self, event) -> None:
        card = self._draggable(event.position()) if event.button() == Qt.LeftButton else None
        self._drag_from = (event.position(), card) if card else None

    def _start_drag(self, card: Card) -> None:
        files = [o for o in card.outputs if o.exists()]
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(f)) for f in files])
        drag = QDrag(self)
        drag.setMimeData(mime)
        if card.thumb is not None:     # the result itself follows the pointer
            picture = card.thumb.scaled(72, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        else:
            picture = thumbs.file_icon(files[0], 48)
        drag.setPixmap(picture)
        drag.setHotSpot(QPoint(picture.width() // 2, picture.height() // 2))
        drag.exec(Qt.CopyAction)   # always a copy: the result stays where it is

    def mouseMoveEvent(self, event) -> None:
        if self._drag_from and event.buttons() & Qt.LeftButton:
            origin, card = self._drag_from
            if (event.position() - origin).manhattanLength() >= QApplication.startDragDistance():
                self._drag_from = None
                self._start_drag(card)
                return
        found = None
        for card in self.cards:
            for rect, name in card.buttons:
                if rect.contains(event.position()):
                    found = (card.id, name)
            if card.close_rect.contains(event.position()):
                found = (card.id, "close")
        if found != self.hover_button:
            self.hover_button = found
            self.update()
        grab = found is None and self._draggable(event.position()) is not None
        self.setCursor(Qt.PointingHandCursor if found else Qt.OpenHandCursor if grab else Qt.ArrowCursor)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_from = None
        for card in list(self.cards):
            if card.close_rect.contains(event.position()) and not card.leaving:
                self._remove(card)
                return
            for rect, name in card.buttons:
                if not rect.contains(event.position()):
                    continue
                if name == "cancel" and card.state == "running":
                    self._cancel(card)
                elif name == "undo" and card.state == "done":
                    self._undo(card)
                elif name == "open" and card.outputs:
                    open_file(card.outputs[0])
                elif name == "reveal" and card.outputs:
                    reveal(card.outputs[0])
                return

    # ----------------------------------------------------------------- paint
    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        pal = palette()
        bottom = self.height() - SHADOW
        for card in self.cards:
            appear = max(0.0, min(1.0, card.appear.value))
            if appear <= 0.01:
                continue
            y = bottom - CARD_H - card.slot.value * (CARD_H + 8)
            rect = QRectF(SHADOW + (1.0 - appear) * 44, y, CARD_W, CARD_H)
            painter.save()
            painter.setOpacity(appear)
            self._paint_card(painter, card, rect, pal)
            painter.restore()

    def _paint_card(self, painter: QPainter, card: Card, rect: QRectF, pal) -> None:
        for i in range(SHADOW, 0, -2):
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(0, 0, 0, int(pal.shadow.alpha() * (1 - i / SHADOW) ** 2 * 0.45)))
            painter.drawRoundedRect(rect.adjusted(-i, -i + 3, i, i + 3), 12 + i, 12 + i)
        path = QPainterPath()
        path.addRoundedRect(rect, 12, 12)
        painter.fillPath(path, pal.panel)
        painter.setPen(QPen(pal.border, 1))
        painter.drawPath(path)

        status_color = {"running": pal.accent, "cancelling": pal.muted, "done": pal.success,
                        "failed": pal.danger, "cancelled": pal.muted, "undone": pal.muted}[card.state]
        thumb = card.thumb if card.state in ("done", "undone") else None
        indent = 14 + THUMB + 12 if thumb else 30
        if thumb:
            self._paint_thumb(painter, card, thumb, QRectF(rect.left() + 13, rect.top() + 13, THUMB, THUMB),
                              pal, status_color)
        else:
            painter.setPen(Qt.NoPen)
            painter.setBrush(status_color)
            painter.drawEllipse(QRectF(rect.left() + 14, rect.top() + 17, 8, 8))

        painter.setPen(pal.text)
        painter.setFont(ui_font(9.6, QFont.DemiBold))
        metrics = QFontMetrics(painter.font())
        title = metrics.elidedText(f"{card.title}", Qt.ElideRight, int(rect.width() - indent - 40))
        painter.drawText(QRectF(rect.left() + indent, rect.top() + 10, rect.width() - indent - 34, 20),
                         Qt.AlignLeft | Qt.AlignVCenter, title)

        painter.setFont(ui_font(8.4))
        painter.setPen(pal.danger if card.state == "failed" else pal.muted)
        line = f"{card.subtitle} — {card.message}" if card.state in ("running", "cancelling") else card.message
        line = QFontMetrics(painter.font()).elidedText(line, Qt.ElideMiddle, int(rect.width() - indent - 14))
        painter.drawText(QRectF(rect.left() + indent, rect.top() + 30, rect.width() - indent - 14, 18),
                         Qt.AlignLeft | Qt.AlignVCenter, line)

        card.rect = QRectF(rect)
        card.close_rect = QRectF(rect.right() - 30, rect.top() + 8, 22, 22)
        close_hover = self.hover_button == (card.id, "close")
        painter.setPen(QPen(pal.text if close_hover else pal.muted, 1.4, Qt.SolidLine, Qt.RoundCap))
        c = card.close_rect.center()
        painter.drawLine(QPointF(c.x() - 4, c.y() - 4), QPointF(c.x() + 4, c.y() + 4))
        painter.drawLine(QPointF(c.x() + 4, c.y() - 4), QPointF(c.x() - 4, c.y() + 4))

        card.buttons = []
        bottom = rect.bottom() - 14
        if card.state in ("running", "cancelling"):
            if card.state == "running":
                self._button(painter, card, "cancel", "Cancel", rect.right() - 14, bottom, pal, right=True)
            track = QRectF(rect.left() + 30, bottom - 2, rect.width() - 112, 4)
            painter.setPen(Qt.NoPen)
            painter.setBrush(pal.tile)
            painter.drawRoundedRect(track, 2, 2)
            painter.setBrush(pal.accent)
            shown = max(0.0, min(1.0, card.shown.value))
            filled = QRectF(track.left(), track.top(), max(6.0, track.width() * shown), track.height())
            painter.drawRoundedRect(filled, 2, 2)
        elif card.state == "done" and card.outputs:
            x = rect.left() + indent
            labels = [("open", "Open"), ("reveal", "Show in folder")]
            if card.outputs[0].is_dir():
                labels = [("open", "Open folder")]
            for name, text in labels:
                x = self._button(painter, card, name, text, x, bottom, pal) + 6
            self._button(painter, card, "undo", "Undo", rect.right() - 14, bottom, pal, right=True)

    @staticmethod
    def _paint_thumb(painter: QPainter, card: Card, thumb: QPixmap, box: QRectF, pal, status: QColor) -> None:
        """The result, cropped to a rounded square, with a small status badge in its corner."""
        clip = QPainterPath()
        clip.addRoundedRect(box, 8, 8)
        painter.save()
        painter.setClipPath(clip)
        painter.fillPath(clip, pal.tile)
        scaled = thumb.scaled(int(box.width() * 2), int(box.height() * 2), Qt.KeepAspectRatioByExpanding,
                              Qt.SmoothTransformation)
        source = QRectF((scaled.width() - box.width() * 2) / 2, (scaled.height() - box.height() * 2) / 2,
                        box.width() * 2, box.height() * 2)
        if card.state == "undone":
            painter.setOpacity(0.35)
        painter.drawPixmap(box, scaled, source)
        painter.restore()
        painter.setPen(QPen(pal.border, 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(clip)
        badge = QPointF(box.right() - 2, box.bottom() - 2)
        painter.setPen(QPen(pal.panel, 2))
        painter.setBrush(status)
        painter.drawEllipse(badge, 7.5, 7.5)
        if card.state == "done":
            draw_icon(painter, "tick", badge, 10, QColor(255, 255, 255), 1.8)

    def _button(self, painter: QPainter, card: Card, name: str, text: str, x: float, bottom: float, pal,
                right: bool = False, quiet: bool = False) -> float:
        """Draw a pill button starting at x (or ending at x when `right`); returns its right edge."""
        painter.setFont(ui_font(8.2, QFont.DemiBold))
        width = QFontMetrics(painter.font()).horizontalAdvance(text) + 18
        left = x - width if right else x
        button = QRectF(left, bottom - BTN_H + 6, width, BTN_H)
        hovered = self.hover_button == (card.id, name)
        tint = pal.muted if quiet else pal.accent
        fill = QColor(tint)
        fill.setAlpha(255 if hovered else 34)
        painter.setPen(Qt.NoPen)
        painter.setBrush(fill)
        painter.drawRoundedRect(button, 6, 6)
        painter.setPen((pal.on_accent if not quiet else pal.panel) if hovered else (pal.text if quiet else tint))
        painter.drawText(button, Qt.AlignCenter, text)
        card.buttons.append((button, name))
        return button.right()
