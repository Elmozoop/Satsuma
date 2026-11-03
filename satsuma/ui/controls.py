"""Small custom controls and the stylesheet for the Settings window."""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QButtonGroup, QHBoxLayout, QPushButton, QWidget

from ..config import DATA_DIR
from .theme import is_dark, palette


class Toggle(QAbstractButton):
    """An on/off switch in the style of Windows 11, drawn in the accent colour."""

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self._pos = 1.0 if checked else 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._moved)
        self.toggled.connect(self._animate)

    def sizeHint(self) -> QSize:
        return QSize(44, 24)

    def _moved(self, value) -> None:
        self._pos = float(value)
        self.update()

    def _animate(self, on: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def paintEvent(self, _event) -> None:
        pal = palette()
        dark = is_dark()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(1, 1, 40, 22)
        rect.moveCenter(QPointF(self.width() / 2, self.height() / 2))
        off_border = QColor(255, 255, 255, 140) if dark else QColor(0, 0, 0, 120)
        knob_off = QColor(255, 255, 255, 200) if dark else QColor(0, 0, 0, 150)
        if not self.isEnabled():
            painter.setOpacity(0.4)
        t = self._pos
        track = QColor(pal.accent)
        track.setAlphaF(t)
        painter.setPen(QPen(off_border if t < 0.5 else pal.accent, 1.2))
        painter.setBrush(track)
        painter.drawRoundedRect(rect, 11, 11)
        radius = 6.5 + 1.0 * (1 if self.underMouse() else 0)
        x = rect.left() + 11 + t * (rect.width() - 22)
        knob = QColor(
            round(knob_off.red() + (pal.on_accent.red() - knob_off.red()) * t),
            round(knob_off.green() + (pal.on_accent.green() - knob_off.green()) * t),
            round(knob_off.blue() + (pal.on_accent.blue() - knob_off.blue()) * t),
            round(knob_off.alpha() + (255 - knob_off.alpha()) * t),
        )
        painter.setPen(Qt.NoPen)
        painter.setBrush(knob)
        painter.drawEllipse(QPointF(x, rect.center().y()), radius, radius)
        if self.hasFocus():
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(pal.text, 1.2))
            painter.drawRoundedRect(rect.adjusted(-3, -3, 3, 3), 14, 14)

    def enterEvent(self, event) -> None:
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.update()
        super().leaveEvent(event)


class Segmented(QWidget):
    """A row of joined buttons for a short list of choices (like a radio group)."""

    changed = Signal(object)

    def __init__(self, options, current, parent=None):
        super().__init__(parent)
        self.setObjectName("segmented")
        self.setAttribute(Qt.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        for value, label in options:
            button = QPushButton(label)
            button.setObjectName("segment")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setProperty("value", value)
            button.setChecked(value == current)
            button.clicked.connect(lambda _c=False, v=value: self.changed.emit(v))
            self.group.addButton(button)
            layout.addWidget(button)

    def value(self):
        button = self.group.checkedButton()
        return button.property("value") if button else None

    def set_value(self, value) -> None:
        for button in self.group.buttons():
            button.setChecked(button.property("value") == value)


def _chevron(color: str) -> str:
    """Path to a small down-chevron SVG in `color` (stylesheets can only load images from files)."""
    folder = DATA_DIR / "ui"
    path = folder / f"chevron-{color.strip('#')}.svg"
    if not path.exists():
        try:
            folder.mkdir(parents=True, exist_ok=True)
            path.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
                            f'<path d="M2 3.5l3 3 3-3" fill="none" stroke="{color}" stroke-width="1.4" '
                            'stroke-linecap="round" stroke-linejoin="round"/></svg>', encoding="utf-8")
        except OSError:
            return ""
    return path.as_posix()


def _rgba(color: QColor, alpha: float | None = None) -> str:
    a = color.alphaF() if alpha is None else alpha
    return f"rgba({color.red()},{color.green()},{color.blue()},{a:.3f})"


def stylesheet() -> str:
    """QSS for the Settings window, from the current theme and accent."""
    pal = palette()
    dark = is_dark()
    accent, on_accent = pal.accent, pal.on_accent
    if dark:
        window, sidebar, card, field = "#1b1c20", "#16171a", "#25262b", "#2e2f35"
        text, muted, line = "#f2f2f4", "#9a9ca6", "rgba(255,255,255,0.08)"
        hover, field_border = "rgba(255,255,255,0.06)", "rgba(255,255,255,0.10)"
    else:
        window, sidebar, card, field = "#f4f4f6", "#ebebee", "#ffffff", "#ffffff"
        text, muted, line = "#18181c", "#686a74", "rgba(0,0,0,0.08)"
        hover, field_border = "rgba(0,0,0,0.05)", "rgba(0,0,0,0.14)"
    acc, acc_soft = accent.name(), _rgba(accent, 0.18)
    return f"""
    QDialog {{ background: {window}; }}
    QWidget {{ color: {text}; font-family: "Segoe UI Variable Text", "Segoe UI"; font-size: 10pt; }}
    QLabel {{ background: transparent; }}
    QLabel#pageTitle {{ font-size: 20pt; font-weight: 600; padding: 2px 0 6px 2px; }}
    QLabel#cardTitle {{ font-size: 10.5pt; font-weight: 600; padding: 10px 2px 2px 2px; }}
    QLabel#rowTitle {{ font-size: 10pt; }}
    QLabel#rowHint, QLabel#hint {{ color: {muted}; font-size: 9pt; }}
    QLabel#value {{ color: {muted}; }}
    QLabel#example {{ color: {muted}; font-family: "Cascadia Mono", Consolas, monospace; font-size: 9pt; }}
    QLabel#dotOk {{ color: {pal.success.name()}; font-size: 14pt; }}
    QLabel#dotWarn {{ color: {acc}; font-size: 14pt; }}

    QWidget#sidebar {{ background: {sidebar}; border-right: 1px solid {line}; }}
    QLabel#brand {{ font-size: 13pt; font-weight: 600; padding: 4px 6px 12px 6px; }}
    QListWidget#nav {{ background: transparent; border: none; outline: none; }}
    QListWidget#nav::item {{ padding: 8px 10px; margin: 1px 0; border-radius: 6px; }}
    QListWidget#nav::item:hover {{ background: {hover}; }}
    QListWidget#nav::item:selected {{ background: {acc_soft}; color: {text}; }}

    QScrollArea, QScrollArea > QWidget > QWidget#page {{ background: transparent; border: none; }}
    QFrame#card {{ background: {card}; border: 1px solid {line}; border-radius: 10px; }}
    QFrame#sep {{ background: {line}; max-height: 1px; min-height: 1px; border: none; }}

    QPushButton {{ background: {field}; border: 1px solid {field_border}; border-radius: 6px;
                   padding: 5px 14px; }}
    QPushButton:hover {{ background: {hover}; }}
    QPushButton:pressed {{ background: {acc_soft}; }}
    QPushButton:disabled {{ color: {muted}; }}
    QPushButton#primary {{ background: {acc}; color: {on_accent.name()}; border: none; font-weight: 600; }}
    QPushButton#primary:hover {{ background: {accent.lighter(110).name()}; }}
    QPushButton#danger {{ color: {pal.danger.name()}; }}

    QWidget#segmented {{ background: {_rgba(QColor(text), 0.06)}; border: 1px solid {line}; border-radius: 7px; }}
    QPushButton#segment {{ background: transparent; border: none; border-radius: 5px; padding: 4px 12px; }}
    QPushButton#segment:hover {{ background: {hover}; }}
    QPushButton#segment:checked {{ background: {acc}; color: {on_accent.name()}; }}

    QComboBox, QLineEdit, QSpinBox {{ background: {field}; border: 1px solid {field_border};
                                      border-radius: 6px; padding: 4px 8px; min-height: 20px;
                                      selection-background-color: {acc}; selection-color: {on_accent.name()}; }}
    QComboBox:focus, QLineEdit:focus, QSpinBox:focus {{ border: 1px solid {acc}; }}
    QLineEdit:disabled {{ color: {muted}; }}
    QComboBox::drop-down {{ border: none; width: 26px; }}
    QComboBox::down-arrow {{ image: url("{_chevron(muted)}"); width: 10px; height: 10px; }}
    QComboBox QAbstractItemView {{ background: {card}; border: 1px solid {field_border};
                                   selection-background-color: {acc_soft}; selection-color: {text};
                                   outline: none; padding: 4px; }}

    QSlider {{ min-height: 24px; background: transparent; }}
    QSlider::groove:horizontal {{ height: 4px; border-radius: 2px; background: {_rgba(QColor(text), 0.18)}; }}
    QSlider::sub-page:horizontal {{ height: 4px; border-radius: 2px; background: {acc}; }}
    /* 18 px handle inside a 24 px slider: never clipped. No hover change, so it can't flicker mid-drag. */
    QSlider::handle:horizontal {{ width: 12px; height: 12px; margin: -7px 0; border-radius: 9px;
                                  background: {field}; border: 3px solid {acc}; }}
    QSlider::handle:horizontal:pressed {{ border-width: 4px; width: 10px; height: 10px; }}

    QListWidget#actions {{ background: {card}; border: 1px solid {line}; border-radius: 10px;
                           padding: 4px; outline: none; }}
    QListWidget#actions::item {{ border-radius: 6px; padding: 2px 4px; }}
    QListWidget#actions::item:hover {{ background: {hover}; }}
    QListWidget#actions::item:selected {{ background: {acc_soft}; color: {text}; }}

    QProgressBar {{ background: {_rgba(QColor(text), 0.10)}; border: none; border-radius: 3px; max-height: 6px; }}
    QProgressBar::chunk {{ background: {acc}; border-radius: 3px; }}

    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {_rgba(QColor(text), 0.22)}; border-radius: 3px; min-height: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QToolTip {{ background: {card}; color: {text}; border: 1px solid {field_border}; padding: 4px; }}
    """
