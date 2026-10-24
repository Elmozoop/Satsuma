"""Bottom-right stack of job cards: progress, then Open / Show in folder."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from ..engine.paths import human_size, open_file, reveal
from .anim import FrameClock, Spring
from .theme import palette, ui_font

CARD_W = 340
CARD_H = 74
MARGIN = 14
SHADOW = 12
BTN_H = 22


class Card:
    def __init__(self, job_id: int, title: str, subtitle: str):
        self.id = job_id
        self.title = title
        self.subtitle = subtitle
        self.message = "Starting…"
        self.fraction = 0.0
        self.state = "running"   # running | done | failed
        self.outputs: list[Path] = []
        self.buttons: list[tuple[QRectF, str]] = []
        self.close_rect = QRectF()
        self.expire_ms = 0
        self.slot = Spring(0.0, "main")       # 0 = bottom of the stack
        self.appear = Spring(0.0, "main")     # slides in from the right
        self.shown = Spring(0.0, "hover")     # smoothed progress bar
        self.leaving = False


class Toasts(QWidget):
    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                            | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)
        self.cards: list[Card] = []
        self.hover_button: tuple[int, str] | None = None
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

    def finished(self, job_id: int, outputs: list[str]) -> None:
        card = self._card(job_id)
        if not card:
            return
        card.state = "done"
        card.fraction = 1.0
        card.shown.to(1.0)
        card.outputs = [Path(o) for o in outputs]
        if len(card.outputs) == 1:
            out = card.outputs[0]
            try:
                size = "" if out.is_dir() else f" · {human_size(out.stat().st_size)}"
            except OSError:
                size = ""
            card.message = f"{out.name}{size}"
        else:
            card.message = f"{len(card.outputs)} files created"
        card.expire_ms = 8000
        self._relayout()

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
            if card.state != "running" and not card.leaving:
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

    def mouseMoveEvent(self, event) -> None:
        found = None
        for card in self.cards:
            for rect, name in card.buttons:
                if rect.contains(event.position()):
                    found = (card.id, name)
            if card.close_rect.contains(event.position()):
                found = (card.id, "close")
        if found != self.hover_button:
            self.hover_button = found
            self.setCursor(Qt.PointingHandCursor if found else Qt.ArrowCursor)
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        for card in list(self.cards):
            if card.close_rect.contains(event.position()) and not card.leaving:
                self._remove(card)
                return
            for rect, name in card.buttons:
                if rect.contains(event.position()) and card.outputs:
                    if name == "open":
                        open_file(card.outputs[0])
                    else:
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

        status_color = {"running": pal.accent, "done": pal.success, "failed": pal.danger}[card.state]
        painter.setPen(Qt.NoPen)
        painter.setBrush(status_color)
        painter.drawEllipse(QRectF(rect.left() + 14, rect.top() + 17, 8, 8))

        painter.setPen(pal.text)
        painter.setFont(ui_font(9.6, QFont.DemiBold))
        metrics = QFontMetrics(painter.font())
        title = metrics.elidedText(f"{card.title}", Qt.ElideRight, int(rect.width() - 70))
        painter.drawText(QRectF(rect.left() + 30, rect.top() + 10, rect.width() - 64, 20),
                         Qt.AlignLeft | Qt.AlignVCenter, title)

        painter.setFont(ui_font(8.4))
        painter.setPen(pal.danger if card.state == "failed" else pal.muted)
        line = card.message if card.state != "running" else f"{card.subtitle} — {card.message}"
        line = QFontMetrics(painter.font()).elidedText(line, Qt.ElideMiddle, int(rect.width() - 44))
        painter.drawText(QRectF(rect.left() + 30, rect.top() + 30, rect.width() - 44, 18),
                         Qt.AlignLeft | Qt.AlignVCenter, line)

        card.close_rect = QRectF(rect.right() - 30, rect.top() + 8, 22, 22)
        close_hover = self.hover_button == (card.id, "close")
        painter.setPen(QPen(pal.text if close_hover else pal.muted, 1.4, Qt.SolidLine, Qt.RoundCap))
        c = card.close_rect.center()
        painter.drawLine(QPointF(c.x() - 4, c.y() - 4), QPointF(c.x() + 4, c.y() + 4))
        painter.drawLine(QPointF(c.x() + 4, c.y() - 4), QPointF(c.x() - 4, c.y() + 4))

        card.buttons = []
        bottom = rect.bottom() - 14
        if card.state == "running":
            track = QRectF(rect.left() + 30, bottom - 2, rect.width() - 50, 4)
            painter.setPen(Qt.NoPen)
            painter.setBrush(pal.tile)
            painter.drawRoundedRect(track, 2, 2)
            painter.setBrush(pal.accent)
            shown = max(0.0, min(1.0, card.shown.value))
            filled = QRectF(track.left(), track.top(), max(6.0, track.width() * shown), track.height())
            painter.drawRoundedRect(filled, 2, 2)
        elif card.state == "done" and card.outputs:
            x = rect.left() + 30
            labels = [("open", "Open"), ("reveal", "Show in folder")]
            if card.outputs[0].is_dir():
                labels = [("open", "Open folder")]
            painter.setFont(ui_font(8.2, QFont.DemiBold))
            for name, text in labels:
                width = QFontMetrics(painter.font()).horizontalAdvance(text) + 18
                button = QRectF(x, bottom - BTN_H + 6, width, BTN_H)
                hovered = self.hover_button == (card.id, name)
                fill = QColor(pal.accent)
                fill.setAlpha(255 if hovered else 34)
                painter.setPen(Qt.NoPen)
                painter.setBrush(fill)
                painter.drawRoundedRect(button, 6, 6)
                painter.setPen(pal.on_accent if hovered else pal.accent)
                painter.drawText(button, Qt.AlignCenter, text)
                card.buttons.append((button, name))
                x += width + 6
