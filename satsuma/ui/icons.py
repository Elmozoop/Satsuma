"""Small line icons drawn with QPainterPath on a 24×24 grid (crisp at any size/DPI)."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPen


def _arrow_head(path: QPainterPath, tip: QPointF, angle: float, size: float = 3.2) -> None:
    for side in (-1, 1):
        a = angle + math.pi + side * 0.55
        path.moveTo(tip)
        path.lineTo(tip.x() + size * math.cos(a), tip.y() + size * math.sin(a))


def _icon_path(name: str) -> QPainterPath:
    p = QPainterPath()
    P = QPointF
    if name == "compress":
        for y0, y1 in ((3, 9.5), (21, 14.5)):
            p.moveTo(12, y0)
            p.lineTo(12, y1)
            _arrow_head(p, P(12, y1), math.pi / 2 if y1 > y0 else -math.pi / 2)
        p.moveTo(5, 12)
        p.lineTo(19, 12)
    elif name == "resize":
        p.addRoundedRect(QRectF(3, 3, 18, 18), 3, 3)
        p.moveTo(8, 16)
        p.lineTo(16, 8)
        _arrow_head(p, P(16, 8), -math.pi / 4)
        _arrow_head(p, P(8, 16), 3 * math.pi / 4)
    elif name == "rotate":
        p.arcMoveTo(QRectF(4, 4, 16, 16), 30)
        p.arcTo(QRectF(4, 4, 16, 16), 30, -300)   # clockwise, ends at the top
        _arrow_head(p, P(12, 4), 0.0, 3.6)
    elif name == "flip":
        p.moveTo(12, 3)
        p.lineTo(12, 21)
        p.moveTo(9, 6)
        p.lineTo(3, 18)
        p.lineTo(9, 18)
        p.closeSubpath()
        p.moveTo(15, 6)
        p.lineTo(21, 18)
        p.lineTo(15, 18)
        p.closeSubpath()
    elif name == "trim":
        p.addEllipse(QRectF(3, 14, 6, 6))
        p.addEllipse(QRectF(15, 14, 6, 6))
        p.moveTo(7.5, 14.5)
        p.lineTo(17, 3)
        p.moveTo(16.5, 14.5)
        p.lineTo(7, 3)
    elif name == "mute":
        p.moveTo(3, 9)
        p.lineTo(7, 9)
        p.lineTo(12, 4.5)
        p.lineTo(12, 19.5)
        p.lineTo(7, 15)
        p.lineTo(3, 15)
        p.closeSubpath()
        p.moveTo(16, 9)
        p.lineTo(21, 15)
        p.moveTo(21, 9)
        p.lineTo(16, 15)
    elif name == "frame":
        p.addRoundedRect(QRectF(3, 6, 18, 14), 3, 3)
        p.addEllipse(QRectF(8.5, 9.5, 7, 7))
        p.moveTo(8, 6)
        p.lineTo(9.5, 3.5)
        p.lineTo(14.5, 3.5)
        p.lineTo(16, 6)
    elif name == "join":
        p.addRoundedRect(QRectF(2.5, 8, 11, 8), 4, 4)
        p.addRoundedRect(QRectF(10.5, 8, 11, 8), 4, 4)
    elif name == "merge":
        p.moveTo(4, 4)
        p.lineTo(12, 12)
        p.moveTo(20, 4)
        p.lineTo(12, 12)
        p.lineTo(12, 21)
        _arrow_head(p, P(12, 21), math.pi / 2)
    elif name == "split":
        p.moveTo(12, 21)
        p.lineTo(12, 12)
        p.lineTo(5, 4)
        p.moveTo(12, 12)
        p.lineTo(19, 4)
        _arrow_head(p, P(5, 4), math.radians(-131))
        _arrow_head(p, P(19, 4), math.radians(-49))
    elif name == "pages":
        p.addRoundedRect(QRectF(7, 3, 13, 16), 2, 2)
        p.moveTo(4, 7)
        p.lineTo(4, 21)
        p.lineTo(16, 21)
        for y in (8, 11.5, 15):
            p.moveTo(10, y)
            p.lineTo(17, y)
    elif name == "zip":
        p.addRoundedRect(QRectF(4, 3, 16, 18), 2.5, 2.5)
        for i, y in enumerate((5, 7.5, 10, 12.5)):
            x = 11 if i % 2 == 0 else 13
            p.moveTo(x, y)
            p.lineTo(x, y + 1.3)
        p.addRoundedRect(QRectF(10, 14, 4, 4), 1, 1)
    elif name == "extract":
        p.moveTo(4, 12)
        p.lineTo(4, 20)
        p.lineTo(20, 20)
        p.lineTo(20, 12)
        p.moveTo(12, 15)
        p.lineTo(12, 3.5)
        _arrow_head(p, P(12, 3.5), -math.pi / 2)
    elif name == "text":
        p.moveTo(5, 5)
        p.lineTo(19, 5)
        p.moveTo(12, 5)
        p.lineTo(12, 19)
        p.moveTo(9, 19)
        p.lineTo(15, 19)
    elif name == "image":
        p.addRoundedRect(QRectF(3, 4, 18, 16), 3, 3)
        p.addEllipse(QRectF(6.5, 7.5, 4, 4))
        p.moveTo(3.5, 17)
        p.lineTo(9, 12.5)
        p.lineTo(13, 16)
        p.lineTo(16, 13.5)
        p.lineTo(20.5, 17.5)
    elif name == "music":
        p.addEllipse(QRectF(3.5, 15, 6, 5))
        p.addEllipse(QRectF(14, 13, 6, 5))
        p.moveTo(9.5, 17.5)
        p.lineTo(9.5, 5)
        p.lineTo(20, 3)
        p.lineTo(20, 15.5)
    elif name == "doc":
        p.moveTo(6, 3)
        p.lineTo(14, 3)
        p.lineTo(19, 8)
        p.lineTo(19, 21)
        p.lineTo(6, 21)
        p.closeSubpath()
        p.moveTo(14, 3)
        p.lineTo(14, 8)
        p.lineTo(19, 8)
    elif name == "close":
        p.moveTo(6, 6)
        p.lineTo(18, 18)
        p.moveTo(18, 6)
        p.lineTo(6, 18)
    return p


_CACHE: dict[str, QPainterPath] = {}
NAMES = ("compress", "resize", "rotate", "flip", "trim", "mute", "frame", "join", "merge",
         "split", "pages", "zip", "extract", "text", "image", "music", "doc", "close")


def draw_icon(painter: QPainter, name: str, center: QPointF, size: float, color, width: float = 1.7) -> None:
    path = _CACHE.get(name)
    if path is None:
        path = _CACHE[name] = _icon_path(name)
    if path.isEmpty():
        return
    painter.save()
    painter.translate(center.x() - size / 2, center.y() - size / 2)
    painter.scale(size / 24.0, size / 24.0)
    pen = QPen(color, width * 24.0 / size)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(path)
    painter.restore()
