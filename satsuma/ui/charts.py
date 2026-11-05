"""Small charts for the Stats window, drawn with QPainter in Satsuma's colours (no chart library)."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from .theme import palette, ui_font

# Colours for the versions chart after the accent: distinct, readable in light and dark.
SERIES = ("#3b82f6", "#22c55e", "#a855f7", "#eab308", "#ec4899")


class Chart(QWidget):
    """Day-by-day data as bars (one value, or several stacked) or as a line."""

    def __init__(self, kind: str = "bars", parent=None):
        super().__init__(parent)
        self.kind = kind                 # "bars", "stacked" or "line"
        self.days: list[str] = []
        self.values: list[float] = []    # bars / line
        self.stacks: list[dict] = []     # stacked: {name: value} per day
        self.names: list[str] = []       # stacked: the series, in drawing order
        self.empty_text = "No data yet"
        self.setMinimumHeight(150)
        self.setMouseTracking(True)

    # ------------------------------------------------------------------ data
    def set_series(self, days: list[str], values: list[float]) -> None:
        self.days, self.values = list(days), [float(v or 0) for v in values]
        self.update()

    def set_stacked(self, days: list[str], stacks: list[dict], top: int = 4) -> None:
        totals: dict[str, float] = {}
        for stack in stacks:
            for name, value in stack.items():
                totals[name] = totals.get(name, 0) + value
        keep = sorted(totals, key=lambda n: (-totals[n], n))[:top]
        self.names = keep + (["other"] if len(totals) > top else [])
        self.days = list(days)
        self.stacks = [{**{n: stack.get(n, 0) for n in keep},
                        **({"other": sum(v for n, v in stack.items() if n not in keep)} if len(totals) > top else {})}
                       for stack in stacks]
        self.update()

    def colour(self, index: int) -> QColor:
        return palette().accent if index == 0 else QColor(SERIES[(index - 1) % len(SERIES)])

    def _has_data(self) -> bool:
        if self.kind == "stacked":
            return any(sum(s.values()) for s in self.stacks)
        return any(self.values)

    def _plot(self) -> QRectF:
        legend = 18 if self.kind == "stacked" and self.names else 0
        return QRectF(36, 6 + legend, self.width() - 44, self.height() - 26 - legend)

    # ------------------------------------------------------------------ drawing
    def paintEvent(self, _event) -> None:
        pal = palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setFont(ui_font(8))
        plot = self._plot()
        if not self.days or not self._has_data():
            painter.setPen(pal.muted)
            painter.drawText(QRectF(self.rect()), Qt.AlignCenter, self.empty_text)
            return

        if self.kind == "stacked":
            peak = max(sum(s.values()) for s in self.stacks)
        else:
            peak = max(self.values)
        peak = max(1.0, peak)

        # Grid lines with their values.
        for frac in (0.0, 0.5, 1.0):
            y = plot.bottom() - frac * plot.height()
            painter.setPen(QPen(pal.muted.lighter(100), 1, Qt.DotLine) if frac else QPen(pal.tile_border, 1))
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(pal.muted)
            value = peak * frac
            painter.drawText(QRectF(0, y - 8, plot.left() - 6, 16), Qt.AlignRight | Qt.AlignVCenter,
                             f"{value:,.0f}" if value >= 10 or value == int(value) else f"{value:.1f}")

        step = plot.width() / len(self.days)
        if self.kind == "line":
            path = QPainterPath()
            for i, value in enumerate(self.values):
                point = QPointF(plot.left() + step * (i + 0.5), plot.bottom() - value / peak * plot.height())
                path.lineTo(point) if i else path.moveTo(point)
            painter.setPen(QPen(pal.accent, 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)
        else:
            painter.setPen(Qt.NoPen)
            width = max(1.5, step * 0.7)
            for i in range(len(self.days)):
                x = plot.left() + step * i + (step - width) / 2
                bottom = plot.bottom()
                parts = ([(0, self.values[i])] if self.kind == "bars"
                         else [(k, self.stacks[i].get(n, 0)) for k, n in enumerate(self.names)])
                for index, value in parts:
                    height = value / peak * plot.height()
                    if height <= 0:
                        continue
                    painter.setBrush(self.colour(index))
                    painter.drawRoundedRect(QRectF(x, bottom - height, width, height), 1.5, 1.5)
                    bottom -= height

        # Day labels: first and last.
        painter.setPen(pal.muted)
        painter.drawText(QRectF(plot.left(), plot.bottom() + 4, 120, 16), Qt.AlignLeft, self.days[0][5:])
        painter.drawText(QRectF(plot.right() - 120, plot.bottom() + 4, 120, 16), Qt.AlignRight, self.days[-1][5:])

        if self.kind == "stacked":            # legend
            x = plot.left()
            for index, name in enumerate(self.names):
                painter.setPen(Qt.NoPen)
                painter.setBrush(self.colour(index))
                painter.drawRoundedRect(QRectF(x, 5, 9, 9), 2, 2)
                painter.setPen(pal.text)
                painter.setFont(ui_font(8, QFont.DemiBold))
                width = painter.fontMetrics().horizontalAdvance(name) + 22
                painter.drawText(QRectF(x + 13, 0, width, 18), Qt.AlignLeft | Qt.AlignVCenter, name)
                x += width

    def _day_at(self, x: float) -> int | None:
        plot = self._plot()
        if not self.days or not plot.left() <= x <= plot.right():
            return None
        return min(len(self.days) - 1, int((x - plot.left()) / (plot.width() / len(self.days))))

    def mouseMoveEvent(self, event) -> None:
        index = self._day_at(event.position().x())
        if index is None or not self._has_data():
            QToolTip.hideText()
            return
        if self.kind == "stacked":
            parts = [f"{n}: {self.stacks[index].get(n, 0):,.0f}" for n in self.names if self.stacks[index].get(n)]
            text = f"{self.days[index]}\n" + ("\n".join(parts) or "nobody")
        else:
            text = f"{self.days[index]}: {self.values[index]:,.0f}"
        QToolTip.showText(event.globalPosition().toPoint(), text, self)
