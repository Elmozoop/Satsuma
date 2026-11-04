"""A small explanation bubble shown just outside the ring, beside the hovered wedge.

It never takes focus or input: clicks and file drops pass straight through it.
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPoint, QPointF, QRect, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from .glass import frosted, is_glass, paint_pane
from .theme import palette, ui_font

TEXT_W = 250       # widest line of text
PAD = 12
SHADOW = 10
GAP = 6            # between the ring and the bubble


class Bubble(QWidget):
    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
                            | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.title = self.body = self.footer = ""
        self.backdrop = None
        self._fade = QVariantAnimation(self)
        self._fade.setDuration(130)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        self._fade.valueChanged.connect(lambda v: self.setWindowOpacity(float(v)))

    # ------------------------------------------------------------------ layout
    @staticmethod
    def _fonts() -> tuple[QFont, QFont, QFont]:
        return ui_font(9.4, QFont.DemiBold), ui_font(9.0), ui_font(8.2)

    def _blocks(self) -> list[tuple[QFont, str, QRect]]:
        title_font, body_font, foot_font = self._fonts()
        blocks, y = [], PAD
        for font, text, after in ((title_font, self.title, 4), (body_font, self.body, 6), (foot_font, self.footer, 0)):
            if not text:
                continue
            rect = QFontMetrics(font).boundingRect(QRect(0, 0, TEXT_W, 1000), Qt.TextWordWrap, text)
            blocks.append((font, text, QRect(PAD, y, TEXT_W, rect.height())))
            y += rect.height() + after
        return blocks

    def show_for(self, title: str, body: str, footer: str, anchor: QPoint, direction: QPointF) -> None:
        """Show beside `anchor` (a point just outside the ring), extending away from the ring
        in `direction` (a unit vector from the ring's centre towards the wedge)."""
        fresh = not self.isVisible()
        self.title, self.body, self.footer = title, body, footer
        blocks = self._blocks()
        inner_w = PAD * 2 + max(QFontMetrics(f).boundingRect(QRect(0, 0, TEXT_W, 1000), Qt.TextWordWrap, t).width()
                                for f, t, _r in blocks)
        inner_h = blocks[-1][2].bottom() + PAD
        self.setFixedSize(inner_w + 2 * SHADOW, inner_h + 2 * SHADOW)

        dx, dy = direction.x(), direction.y()
        x = anchor.x() - inner_w / 2 if abs(dx) < 0.35 else (anchor.x() + GAP if dx > 0 else anchor.x() - GAP - inner_w)
        y = anchor.y() - inner_h / 2 if abs(dy) < 0.35 else (anchor.y() + GAP if dy > 0 else anchor.y() - GAP - inner_h)
        screen = QGuiApplication.screenAt(anchor) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        x = max(area.left() + 4, min(x, area.right() - inner_w - 4))
        y = max(area.top() + 4, min(y, area.bottom() - inner_h - 4))
        self.move(int(x) - SHADOW, int(y) - SHADOW)
        self.backdrop = frosted(self.frameGeometry(), owner=self) if is_glass() else None
        self.update()
        if fresh:
            self.setWindowOpacity(0.0)
            self.show()
            self._fade.stop()
            self._fade.setStartValue(0.0)
            self._fade.setEndValue(1.0)
            self._fade.start()

    def hide_now(self) -> None:
        self._fade.stop()
        self.hide()

    # ------------------------------------------------------------------ painting
    def paintEvent(self, _event) -> None:
        pal = palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        box = QRectF(self.rect()).adjusted(SHADOW, SHADOW, -SHADOW, -SHADOW)
        for i in range(SHADOW, 0, -2):
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(0, 0, 0, int(pal.shadow.alpha() * (1 - i / SHADOW) ** 2 * 0.5)))
            painter.drawRoundedRect(box.adjusted(-i, -i + 2, i, i + 2), 10 + i, 10 + i)
        path = QPainterPath()
        path.addRoundedRect(box, 10, 10)
        if is_glass():
            paint_pane(painter, path, self.backdrop, pal.panel, pal.text.lightness() > 128)
        else:
            panel = QColor(pal.panel)
            panel.setAlpha(250)                       # solid enough to read over anything
            painter.fillPath(path, panel)
            painter.setPen(QPen(pal.border, 1))
            painter.drawPath(path)
        colours = [pal.accent, pal.text, pal.muted]
        painter.translate(box.topLeft())
        for (font, text, rect), colour in zip(self._blocks(), colours[-len(self._blocks()):] if not self.title else colours):
            painter.setFont(font)
            painter.setPen(colour)
            painter.drawText(rect, Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop, text)
