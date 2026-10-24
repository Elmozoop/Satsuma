"""Spring physics and a frame clock tied to the display's refresh rate.

Springs give the natural, interruptible motion seen in macOS menus: retargeting
mid-flight keeps the current velocity instead of restarting a fixed-length tween.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QElapsedTimer, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication

from ..config import settings

# (stiffness, damping ratio when bouncy, damping ratio when not)
SPEEDS = {
    "fast": (720.0, 0.72, 1.0),
    "normal": (420.0, 0.66, 1.0),
    "relaxed": (210.0, 0.62, 1.0),
}


def spring_params(kind: str = "main") -> tuple[float, float] | None:
    """(stiffness, damping) for the user's speed setting, or None when animations are off."""
    speed = settings.get("anim_speed")
    if speed == "off":
        return None
    stiffness, bouncy, calm = SPEEDS.get(speed, SPEEDS["normal"])
    ratio = bouncy if settings.get("bounce") else calm
    if kind == "hover":        # hover feedback should feel immediate
        stiffness *= 1.6
        ratio = max(ratio, 0.8)
    elif kind == "close":      # closing never bounces
        stiffness *= 1.5
        ratio = 1.0
    return stiffness, 2.0 * ratio * math.sqrt(stiffness)


class Spring:
    __slots__ = ("value", "target", "velocity", "kind", "delay")

    def __init__(self, value: float = 0.0, kind: str = "main"):
        self.value = float(value)
        self.target = float(value)
        self.velocity = 0.0
        self.kind = kind
        self.delay = 0.0   # seconds to wait before moving toward target

    def to(self, target: float, delay: float = 0.0) -> None:
        self.target = float(target)
        self.delay = max(0.0, delay)

    def snap(self, value: float) -> None:
        self.value = self.target = float(value)
        self.velocity = 0.0
        self.delay = 0.0

    def step(self, dt: float) -> bool:
        """Advance; returns True while still moving."""
        params = spring_params(self.kind)
        if params is None:          # animations off: jump straight there, delays included
            self.snap(self.target)
            return False
        if self.delay > 0:
            self.delay -= dt
            return True
        stiffness, damping = params
        # Semi-implicit Euler in small sub-steps: stable at any frame rate.
        remaining = dt
        while remaining > 0:
            h = min(remaining, 1 / 240)
            force = -stiffness * (self.value - self.target) - damping * self.velocity
            self.velocity += force * h
            self.value += self.velocity * h
            remaining -= h
        if abs(self.value - self.target) < 0.0005 and abs(self.velocity) < 0.005:
            self.snap(self.target)
            return False
        return True

    @property
    def settled(self) -> bool:
        return self.delay <= 0 and self.value == self.target and self.velocity == 0.0


class FrameClock(QObject):
    """Emits `frame(dt)` at the screen's refresh rate while something is animating."""

    frame = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._elapsed = QElapsedTimer()

    def _interval(self) -> int:
        screen = QGuiApplication.primaryScreen()
        rate = screen.refreshRate() if screen else 60.0
        rate = rate if 30 <= rate <= 360 else 60.0
        return max(3, int(1000 / rate))

    def start(self) -> None:
        if not self._timer.isActive():
            self._elapsed.start()
            self._timer.start(self._interval())

    def stop(self) -> None:
        self._timer.stop()

    @property
    def running(self) -> bool:
        return self._timer.isActive()

    def _tick(self) -> None:
        dt = self._elapsed.nsecsElapsed() / 1e9
        self._elapsed.restart()
        self.frame.emit(min(max(dt, 0.0), 1 / 30))  # never jump more than a frame at 30 Hz


def ease_out_cubic(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def mix(a: float, b: float, t: float) -> float:
    return a + (b - a) * t
