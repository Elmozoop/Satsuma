"""Paths, persisted settings and shared constants."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP_NAME = "Satsuma"
APP_ID = "satsuma.win"
VERSION = "1.11.3"


def _base_dir() -> Path:
    """Per-user data directory (works the same frozen or from source)."""
    if sys.platform == "win32":
        root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    else:  # dev / testing on other platforms
        root = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    path = Path(root) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


DATA_DIR = _base_dir()
BIN_DIR = DATA_DIR / "bin"
LOG_FILE = DATA_DIR / "satsuma.log"
SETTINGS_FILE = DATA_DIR / "settings.json"

# Where the app itself lives, frozen (PyInstaller) or from source.
if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).parent
    # PyInstaller 6 unpacks bundled data into _internal (sys._MEIPASS), not next to the exe.
    ASSETS_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR)) / "assets"
else:
    APP_DIR = Path(__file__).resolve().parent.parent
    ASSETS_DIR = APP_DIR / "assets"

MODIFIERS = {
    "shift": 0x10,  # VK_SHIFT
    "ctrl": 0x11,   # VK_CONTROL
    "alt": 0x12,    # VK_MENU
}

OUTPUT_MODES = ("source", "subfolder", "custom")

DEFAULTS = {
    "modifier": "shift",
    "enabled": True,
    "output_mode": "source",      # alongside the original
    "output_subfolder": "Converted",
    "output_custom": "",
    "overwrite": False,           # False -> add " (1)", " (2)" ...
    "jpeg_quality": 88,
    "compress_quality": 70,
    "reveal_after": False,        # open Explorer at the result
    "scrim_opacity": 0.38,
    "drag_threshold": 12,         # px of movement before the menu arms
    "autostart": False,
    "theme": "system",       # system | dark | light
    "smart_detect": True,      # only reveal the menu once real files are dragged
    # ---- look & feel
    "accent": "#FF8A1F",
    "menu_scale": 1.0,         # 0.7 .. 1.5
    "glass_opacity": 0.86,     # how solid the ring is
    "anim_speed": "normal",    # off | fast | normal | relaxed
    "bounce": True,            # springy overshoot
    "show_icons": True,
    "type_colors": True,       # tint convert wedges by the kind of file they make
    "show_captions": True,     # describe the hovered action in the centre
    "explain_actions": True,   # a panel beside the hovered wedge says what it will do
    "hub_info": "size",        # size | name | type
    "wedges_per_ring": 8,      # 3 .. 10; more actions spill onto another ring
    "hub_switch_ms": 450,      # rest on the centre this long to swap rings
    "start_page": "convert",   # convert | tools
    # ---- actions
    "actions_hidden": [],      # action ids the user switched off
    "actions_shown": [],       # hidden-by-default action ids the user switched on
    # ---- watched folders: [{"folder": path, "action": action id, "enabled": bool}]
    "watch_rules": [],
    "actions_order": {},       # file category -> ordered action ids
}


class Settings:
    """Tiny JSON-backed settings store. Never raises on bad/missing files."""

    def __init__(self, path: Path = SETTINGS_FILE):
        self.path = path
        self._listeners: list = []
        self._data = {k: (type(v)() if isinstance(v, (list, dict)) else v) for k, v in DEFAULTS.items()}
        self.load()

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for key, value in raw.items():
                    if key in DEFAULTS:
                        self._data[key] = value
        except (OSError, ValueError):
            pass
        self._sanitise()

    def _sanitise(self) -> None:
        if self._data.get("modifier") not in MODIFIERS:
            self._data["modifier"] = DEFAULTS["modifier"]
        if self._data.get("output_mode") not in OUTPUT_MODES:
            self._data["output_mode"] = DEFAULTS["output_mode"]
        for key in ("jpeg_quality", "compress_quality"):
            try:
                self._data[key] = max(1, min(100, int(self._data[key])))
            except (TypeError, ValueError):
                self._data[key] = DEFAULTS[key]
        try:
            self._data["drag_threshold"] = max(2, min(80, int(self._data["drag_threshold"])))
        except (TypeError, ValueError):
            self._data["drag_threshold"] = DEFAULTS["drag_threshold"]
        try:
            self._data["menu_scale"] = max(0.7, min(1.5, float(self._data["menu_scale"])))
        except (TypeError, ValueError):
            self._data["menu_scale"] = DEFAULTS["menu_scale"]
        try:
            self._data["glass_opacity"] = max(0.35, min(1.0, float(self._data["glass_opacity"])))
        except (TypeError, ValueError):
            self._data["glass_opacity"] = DEFAULTS["glass_opacity"]
        try:
            self._data["wedges_per_ring"] = max(3, min(10, int(self._data["wedges_per_ring"])))
        except (TypeError, ValueError):
            self._data["wedges_per_ring"] = DEFAULTS["wedges_per_ring"]
        try:
            self._data["hub_switch_ms"] = max(150, min(2000, int(self._data["hub_switch_ms"])))
        except (TypeError, ValueError):
            self._data["hub_switch_ms"] = DEFAULTS["hub_switch_ms"]
        if self._data.get("anim_speed") not in ("off", "fast", "normal", "relaxed"):
            self._data["anim_speed"] = "normal"
        if self._data.get("hub_info") not in ("size", "name", "type"):
            self._data["hub_info"] = "size"
        if self._data.get("start_page") not in ("convert", "tools"):
            self._data["start_page"] = "convert"
        accent = str(self._data.get("accent") or "")
        if not (len(accent) == 7 and accent.startswith("#")
                and all(c in "0123456789abcdefABCDEF" for c in accent[1:])):
            self._data["accent"] = DEFAULTS["accent"]
        for key in ("actions_hidden", "actions_shown", "watch_rules"):
            if not isinstance(self._data.get(key), list):
                self._data[key] = []
        if not isinstance(self._data.get("actions_order"), dict):
            self._data["actions_order"] = {}
        try:
            self._data["scrim_opacity"] = max(0.05, min(0.85, float(self._data["scrim_opacity"])))
        except (TypeError, ValueError):
            self._data["scrim_opacity"] = DEFAULTS["scrim_opacity"]

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass

    def get(self, key: str, default=None):
        return self._data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value) -> None:
        self._data[key] = value
        self._sanitise()
        self.save()
        for listener in list(self._listeners):
            try:
                listener(key)
            except Exception:
                pass

    def subscribe(self, listener) -> None:
        self._listeners.append(listener)

    def unsubscribe(self, listener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def reset(self, keys) -> None:
        for key in keys:
            self._data[key] = DEFAULTS[key] if not isinstance(DEFAULTS[key], (list, dict)) else type(DEFAULTS[key])()
        self._sanitise()
        self.save()
        for listener in list(self._listeners):
            listener("*")

    @property
    def modifier_vk(self) -> int:
        return MODIFIERS[self._data["modifier"]]

    def as_dict(self) -> dict:
        return dict(self._data)


settings = Settings()
