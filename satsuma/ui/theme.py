"""Colours and fonts shared by every window."""
from __future__ import annotations

import sys
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication

from ..config import settings


@dataclass(frozen=True)
class Palette:
    panel: QColor
    border: QColor
    text: QColor
    muted: QColor
    tile: QColor
    tile_border: QColor
    accent: QColor
    on_accent: QColor
    danger: QColor
    success: QColor
    shadow: QColor


DARK = Palette(
    panel=QColor(28, 29, 33, 246), border=QColor(255, 255, 255, 22),
    text=QColor(242, 242, 244), muted=QColor(154, 156, 166),
    tile=QColor(255, 255, 255, 14), tile_border=QColor(255, 255, 255, 18),
    accent=QColor(255, 138, 31), on_accent=QColor(30, 18, 6),
    danger=QColor(255, 99, 88), success=QColor(76, 201, 128), shadow=QColor(0, 0, 0, 90),
)
LIGHT = Palette(
    panel=QColor(250, 250, 251, 248), border=QColor(0, 0, 0, 26),
    text=QColor(24, 24, 28), muted=QColor(104, 106, 116),
    tile=QColor(0, 0, 0, 10), tile_border=QColor(0, 0, 0, 16),
    accent=QColor(244, 120, 10), on_accent=QColor(255, 255, 255),
    danger=QColor(214, 52, 44), success=QColor(28, 150, 80), shadow=QColor(0, 0, 0, 55),
)


ACCENT_PRESETS = [
    ("Tangerine", "#FF8A1F"), ("Blood orange", "#F0502E"), ("Rose", "#F2467E"),
    ("Grape", "#9B5CF6"), ("Ocean", "#2F7BF6"), ("Lagoon", "#14B8A6"),
    ("Lime", "#7CC42B"), ("Graphite", "#8A8F98"),
]


def is_dark() -> bool:
    choice = settings.get("theme")
    if choice in ("light", "dark"):
        return choice == "dark"
    try:
        return QGuiApplication.styleHints().colorScheme() != Qt.ColorScheme.Light
    except Exception:
        return True


def readable_on(color: QColor) -> QColor:
    """White or near-black text, whichever contrasts more with `color`."""
    def channel(c: float) -> float:
        c /= 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    lum = 0.2126 * channel(color.red()) + 0.7152 * channel(color.green()) + 0.0722 * channel(color.blue())
    return QColor(255, 255, 255) if lum < 0.42 else QColor(28, 18, 8)


def palette() -> Palette:
    base = DARK if is_dark() else LIGHT
    accent = QColor(str(settings.get("accent") or "#FF8A1F"))
    if not accent.isValid():
        accent = QColor("#FF8A1F")
    panel = QColor(base.panel)
    panel.setAlphaF(float(settings.get("glass_opacity")))
    return Palette(
        panel=panel, border=base.border, text=base.text, muted=base.muted, tile=base.tile,
        tile_border=base.tile_border, accent=accent, on_accent=readable_on(accent),
        danger=base.danger, success=base.success, shadow=base.shadow,
    )


def ui_font(size: float, weight=QFont.Normal) -> QFont:
    family = "Segoe UI Variable Text" if sys.platform == "win32" else "Segoe UI"
    font = QFont(family)
    font.setFamilies([family, "Segoe UI", "Inter", "Helvetica Neue", "Arial"])
    font.setPointSizeF(size)
    font.setWeight(weight)
    font.setHintingPreference(QFont.PreferNoHinting)
    return font
