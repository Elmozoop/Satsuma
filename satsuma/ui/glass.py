"""The Glass style: frosted, see-through surfaces with what's behind them softly blurred.

Two techniques, because Windows only blurs whole rectangular windows:
  * ordinary windows (Settings, prompts, dialogs, menus) get Windows' own acrylic backdrop;
  * the ring, result cards and info panel are round or floating shapes, so Satsuma captures the
    screen behind them, blurs it, and paints that inside their shape.
"""
from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import QEvent, QObject, QRect, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPixmap

from ..config import settings

IS_WINDOWS = sys.platform == "win32"
WIN11_BACKDROP = IS_WINDOWS and sys.getwindowsversion().build >= 22621   # DWMWA_SYSTEMBACKDROP_TYPE


def is_glass() -> bool:
    return settings.get("style") == "glass"


# ----------------------------------------------------------------------------- blurred capture
def _hide_from_capture(widget, hidden: bool) -> None:
    if IS_WINDOWS and widget is not None and widget.isVisible():
        try:
            ctypes.windll.user32.SetWindowDisplayAffinity(ctypes.c_void_p(int(widget.winId())),
                                                          0x11 if hidden else 0)  # WDA_EXCLUDEFROMCAPTURE
        except Exception:
            pass


def frosted(rect: QRect, owner=None, blur: int = 9) -> QPixmap | None:
    """A blurred picture of the screen inside `rect` (global, logical px). If `owner` is already
    on screen it is left out of the capture for that instant, so it never sees itself."""
    screen = QGuiApplication.screenAt(rect.center()) or QGuiApplication.primaryScreen()
    if screen is None or rect.isEmpty():
        return None
    _hide_from_capture(owner, True)
    try:
        local = rect.translated(-screen.geometry().topLeft())
        shot = screen.grabWindow(0, local.x(), local.y(), local.width(), local.height())
    finally:
        _hide_from_capture(owner, False)
    if shot.isNull():
        return None
    return blur_image(shot.toImage(), blur, shot.devicePixelRatio())


def blur_image(image: QImage, blur: int = 9, ratio: float = 1.0) -> QPixmap:
    """Shrinking hard and growing back smoothly, twice, is a fast, soft blur."""
    image = image.convertToFormat(QImage.Format_RGB32)
    size = image.size()
    for _ in range(2):
        small = image.scaled(max(1, size.width() // blur), max(1, size.height() // blur),
                             Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        image = small.scaled(size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


def tint(base: QColor, dark: bool) -> QColor:
    """The frosted layer laid over the blur: enough colour to keep text readable."""
    colour = QColor(base)
    colour.setAlphaF(0.58 if dark else 0.52)
    return colour


def paint_pane(painter, path, backdrop: QPixmap | None, base: QColor, dark: bool) -> None:
    """A frosted pane in `path`: the blurred backdrop, a light tint, a top sheen, a bright edge."""
    from PySide6.QtGui import QBrush, QLinearGradient, QPen

    painter.save()
    painter.setClipPath(path)
    if backdrop is not None:
        painter.drawPixmap(0, 0, backdrop)
    painter.fillPath(path, tint(base, dark))
    box = path.boundingRect()
    sheen = QLinearGradient(box.topLeft(), box.bottomLeft())
    sheen.setColorAt(0.0, QColor(255, 255, 255, 34 if dark else 80))
    sheen.setColorAt(0.5, QColor(255, 255, 255, 0))
    painter.fillPath(path, QBrush(sheen))
    painter.restore()
    painter.setPen(QPen(QColor(255, 255, 255, 60 if dark else 190), 1.1))
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(path)


# ----------------------------------------------------------------------------- acrylic windows
class _DWMBackdrop(QObject):
    """Applies Windows' acrylic backdrop each time the window is shown (it needs a real handle)."""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Show and is_glass():
            apply_backdrop(obj)
        return False


_filter = _DWMBackdrop()


def glass_window(widget, menu: bool = False, always: bool = False) -> None:
    """Make a top-level window (dialog, menu) frosted in the Glass style. Call before it is shown.
    `always` prepares a long-lived window (the tray menu) so it can follow Solid/Glass changes."""
    if not IS_WINDOWS or not (always or is_glass()):
        return
    widget.setAttribute(Qt.WA_TranslucentBackground, True)
    if menu:
        widget.setWindowFlags(widget.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
    widget.installEventFilter(_filter)


def refresh_backdrop(widget) -> None:
    """For a window made with `always=True`: frosted in Glass, plain in Solid, switched live."""
    if not IS_WINDOWS or not widget.isVisible():
        return
    if is_glass():
        apply_backdrop(widget)
        return
    try:
        hwnd = ctypes.c_void_p(int(widget.winId()))
        if WIN11_BACKDROP:
            value = ctypes.c_int(1)                                             # no backdrop
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 38, ctypes.byref(value), 4)
    except Exception:
        pass


def apply_backdrop(widget) -> None:
    from .theme import is_dark

    try:
        hwnd = ctypes.c_void_p(int(widget.winId()))
        dwm = ctypes.windll.dwmapi
        value = ctypes.c_int(1 if is_dark() else 0)
        dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(value), 4)            # dark title bar
        value = ctypes.c_int(2)
        dwm.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(value), 4)            # rounded corners
        if WIN11_BACKDROP:
            class Margins(ctypes.Structure):
                _fields_ = [("l", ctypes.c_int), ("r", ctypes.c_int), ("t", ctypes.c_int), ("b", ctypes.c_int)]

            dwm.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(Margins(-1, -1, -1, -1)))
            value = ctypes.c_int(3)                                             # acrylic
            dwm.DwmSetWindowAttribute(hwnd, 38, ctypes.byref(value), 4)
        else:                                                                   # Windows 10: blur-behind
            class Accent(ctypes.Structure):
                _fields_ = [("state", ctypes.c_int), ("flags", ctypes.c_int), ("color", ctypes.c_uint),
                            ("anim", ctypes.c_int)]

            class Data(ctypes.Structure):
                _fields_ = [("attr", ctypes.c_int), ("data", ctypes.c_void_p), ("size", ctypes.c_size_t)]

            accent = Accent(4, 2, 0x401E1C1A if is_dark() else 0x40F3F3F3, 0)
            data = Data(19, ctypes.cast(ctypes.byref(accent), ctypes.c_void_p), ctypes.sizeof(accent))
            ctypes.windll.user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data))
    except Exception:
        pass
