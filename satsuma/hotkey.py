"""The keyboard shortcut: select files in Explorer (or on the desktop), press Ctrl+Shift+Space,
and the ring opens at the pointer for them. No dragging needed, which helps on a trackpad.

The shortcut is a normal Windows hotkey (RegisterHotKey), so Satsuma doesn't watch the keyboard.
Explorer's selection is read through its own scripting interface (Shell.Application).
"""
from __future__ import annotations

import ctypes
import logging
import os
import sys
from pathlib import Path

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication, QObject, Signal

from .config import settings

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"
WM_HOTKEY = 0x0312
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x4000
VK_SPACE = 0x20
HOTKEY_ID = 0x5A75          # any id unique to this app

SHORTCUTS = {               # setting value -> (modifiers, key, label)
    "ctrl+shift+space": (MOD_CONTROL | MOD_SHIFT, VK_SPACE, "Ctrl+Shift+Space"),
    "ctrl+alt+space": (MOD_CONTROL | MOD_ALT, VK_SPACE, "Ctrl+Alt+Space"),
}
SWC_DESKTOP = 8
SWFO_NEEDDISPATCH = 1


def label(value: str | None = None) -> str:
    value = value if value is not None else str(settings.get("hotkey") or "")
    return SHORTCUTS[value][2] if value in SHORTCUTS else ""


# ----------------------------------------------------------------------------- Explorer's selection
def foreground_window() -> int:
    return int(ctypes.windll.user32.GetForegroundWindow() or 0) if IS_WINDOWS else 0


def _window_text(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(512)
    ctypes.windll.user32.GetWindowTextW(hwnd, buffer, 512)
    return buffer.value


def _class_name(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    ctypes.windll.user32.GetClassNameW(hwnd, buffer, 256)
    return buffer.value


def _selection(document) -> list[Path]:
    items = document.querySubObject("SelectedItems()") if document is not None else None
    if items is None:
        return []
    paths = []
    for index in range(int(items.property("Count") or 0)):
        item = items.querySubObject("Item(QVariant)", index)
        path = item.property("Path") if item is not None else None
        if path and os.path.exists(path):
            paths.append(Path(path))
    return paths


def selected_files(hwnd: int) -> list[Path]:
    """The files selected in the Explorer window (or desktop) `hwnd`; [] if there are none."""
    if not IS_WINDOWS or not hwnd:
        return []
    try:
        from PySide6.QtAxContainer import QAxObject
    except ImportError:
        return []
    root = ctypes.windll.user32.GetAncestor(hwnd, 2)       # GA_ROOT: the top-level window
    kind = _class_name(root)
    try:
        shell = QAxObject("Shell.Application")
        windows = shell.querySubObject("Windows()")
        if windows is None:
            return []
        if kind in ("Progman", "WorkerW"):                  # the desktop
            desktop = windows.querySubObject("FindWindowSW(QVariant,QVariant,int,int&,int)",
                                             0, 0, SWC_DESKTOP, 0, SWFO_NEEDDISPATCH)
            return _selection(desktop.querySubObject("Document")) if desktop is not None else []
        if kind != "CabinetWClass":
            return []
        # Windows 11 tabs share one window: the active tab is the one named in the title bar.
        title = _window_text(root)
        tabs = []
        for index in range(int(windows.property("Count") or 0)):
            window = windows.querySubObject("Item(QVariant)", index)
            if window is None or int(window.property("HWND") or 0) != root:
                continue
            tabs.append((str(window.property("LocationName") or ""), window.querySubObject("Document")))
        active = [doc for name, doc in tabs if name and title.startswith(name)] or [doc for _n, doc in tabs]
        for document in active:
            paths = _selection(document)
            if paths:
                return paths
    except Exception as exc:          # Explorer busy or restarting: just nothing selected
        log.info("couldn't read Explorer's selection: %s", exc)
    return []


# ----------------------------------------------------------------------------- the hotkey
class _Filter(QAbstractNativeEventFilter):
    def __init__(self, owner: "Hotkey"):
        super().__init__()
        self.owner = owner

    def nativeEventFilter(self, event_type, message):
        if event_type == b"windows_generic_MSG" or event_type == "windows_generic_MSG":
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                self.owner.pressed.emit()
                return True, 0
        return False, 0


class Hotkey(QObject):
    """Registers the shortcut chosen in Settings and emits `pressed`."""
    pressed = Signal()
    taken = Signal(str)          # the shortcut's name, when another app already uses it

    def __init__(self, parent=None):
        super().__init__(parent)
        self._registered = False
        self._filter = None
        if IS_WINDOWS:
            import ctypes.wintypes  # noqa: F401  (MSG)

            self._filter = _Filter(self)
            QCoreApplication.instance().installNativeEventFilter(self._filter)
        settings.subscribe(self._on_setting)
        self.apply()

    @property
    def registered(self) -> bool:
        return self._registered

    def apply(self) -> bool:
        """(Re-)register the shortcut from settings. False if Windows refused (taken by another app)."""
        self._unregister()
        value = str(settings.get("hotkey") or "")
        if not IS_WINDOWS or value not in SHORTCUTS:
            return False
        modifiers, key, name = SHORTCUTS[value]
        self._registered = bool(ctypes.windll.user32.RegisterHotKey(None, HOTKEY_ID, modifiers | MOD_NOREPEAT, key))
        if not self._registered:
            log.warning("%s is already used by another app", name)
            self.taken.emit(name)
        return self._registered

    def _unregister(self) -> None:
        if self._registered:
            ctypes.windll.user32.UnregisterHotKey(None, HOTKEY_ID)
            self._registered = False

    def _on_setting(self, key: str) -> None:
        if key in ("hotkey", "*"):
            self.apply()

    def stop(self) -> None:
        self._unregister()
        settings.unsubscribe(self._on_setting)
        if self._filter is not None:
            QCoreApplication.instance().removeNativeEventFilter(self._filter)
            self._filter = None
