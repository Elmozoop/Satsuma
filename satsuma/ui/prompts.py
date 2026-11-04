"""Small dialogs for actions that need a value (resize, trim, pages, passwords, speed).
They follow Satsuma's theme and show a preview of the file they're about."""
from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QButtonGroup, QDialog, QDialogButtonBox, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QRadioButton, QSpinBox, QVBoxLayout)

from ..engine import ffmpeg_tool as ff
from .controls import stylesheet
from .thumbs import file_icon, thumbnail

THUMB = 64


def parse_time(text: str) -> float | None:
    """Accept '83', '83.5', '1:23', '1:23.5', '01:02:03'."""
    text = text.strip().replace(",", ".")
    if not text:
        return None
    if not re.fullmatch(r"\d+(:\d{1,2}){0,2}(\.\d+)?", text):
        return None
    parts = text.split(":")
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + float(part)
    return seconds


def format_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours >= 1:
        return f"{int(hours)}:{int(minutes):02d}:{secs:05.2f}".rstrip("0").rstrip(".")
    return f"{int(minutes)}:{secs:05.2f}".rstrip("0").rstrip(".")


def _preview(paths: list[Path] | None) -> QLabel:
    label = QLabel()
    label.setObjectName("thumb")
    label.setFixedSize(THUMB, THUMB)
    label.setAlignment(Qt.AlignCenter)
    if paths:
        ratio = label.devicePixelRatioF() or 1.0
        image = thumbnail(paths[0], int(THUMB * ratio))
        if image is not None:
            pixmap = QPixmap.fromImage(image).scaled(int((THUMB - 8) * ratio), int((THUMB - 8) * ratio),
                                                      Qt.KeepAspectRatio, Qt.SmoothTransformation)
            pixmap.setDevicePixelRatio(ratio)
        else:
            pixmap = file_icon(paths[0], 40)
        label.setPixmap(pixmap)
    return label


class _Base(QDialog):
    ok_text = "OK"

    def __init__(self, title: str, subtitle: str, paths: list[Path] | None = None):
        super().__init__(None)
        self.setWindowTitle(f"Satsuma — {title}")
        self.setWindowFlags(Qt.Dialog | Qt.WindowStaysOnTopHint | Qt.WindowCloseButtonHint)
        self.setMinimumWidth(400)
        self.setStyleSheet(stylesheet())
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(22, 20, 22, 18)
        self.layout_.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(14)
        header.addWidget(_preview(paths))
        text = QVBoxLayout()
        text.setSpacing(2)
        heading = QLabel(title)
        heading.setObjectName("promptTitle")
        text.addWidget(heading)
        sub = QLabel(subtitle)
        sub.setObjectName("hint")
        sub.setWordWrap(True)
        text.addWidget(sub)
        text.addStretch(1)
        header.addLayout(text, 1)
        self.layout_.addLayout(header)

        body = QFrame()
        body.setObjectName("card")
        self.grid = QGridLayout(body)
        self.grid.setContentsMargins(16, 14, 16, 14)
        self.grid.setHorizontalSpacing(14)
        self.grid.setVerticalSpacing(10)
        self.grid.setColumnStretch(1, 1)
        self.layout_.addWidget(body)

        self.error = QLabel("")
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        self.layout_.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        ok = buttons.button(QDialogButtonBox.Ok)
        ok.setObjectName("primary")
        ok.setText(self.ok_text)
        ok.setDefault(True)
        buttons.accepted.connect(self._try_accept)
        buttons.rejected.connect(self.reject)
        self.layout_.addWidget(buttons)
        self.result_params: dict = {}

    def _try_accept(self) -> None:
        message = self.validate()
        if message:
            self.error.setText(message)
            return
        self.accept()

    def validate(self) -> str | None:  # pragma: no cover - overridden
        return None


class ResizePrompt(_Base):
    ok_text = "Resize"
    def __init__(self, paths: list[Path]):
        subtitle = paths[0].name if len(paths) == 1 else f"{len(paths)} images"
        try:
            from ..engine import images  # loaded on demand: Pillow is large

            meta = images.info(paths[0])
            self.size = (meta["width"], meta["height"])
            subtitle += f" · {meta['width']}×{meta['height']}"
        except Exception:
            self.size = None
        super().__init__("Resize", subtitle, paths)

        self.group = QButtonGroup(self)
        self.by_scale = QRadioButton("Scale")
        self.by_width = QRadioButton("Width")
        self.by_height = QRadioButton("Height")
        for button in (self.by_scale, self.by_width, self.by_height):
            self.group.addButton(button)
        self.scale = QSpinBox(suffix=" %", minimum=1, maximum=1000, value=50)
        self.width = QSpinBox(suffix=" px", minimum=1, maximum=50000,
                              value=(self.size[0] // 2 if self.size else 1280))
        self.height = QSpinBox(suffix=" px", minimum=1, maximum=50000,
                               value=(self.size[1] // 2 if self.size else 720))
        for row, (button, box) in enumerate(((self.by_scale, self.scale),
                                             (self.by_width, self.width),
                                             (self.by_height, self.height))):
            self.grid.addWidget(button, row, 0)
            self.grid.addWidget(box, row, 1)
            box.valueChanged.connect(lambda _v, b=button: b.setChecked(True))
        self.by_scale.setChecked(True)
        self.scale.setFocus()
        self.scale.selectAll()

    def validate(self) -> str | None:
        if self.by_scale.isChecked():
            self.result_params = {"scale": self.scale.value() / 100.0}
        elif self.by_width.isChecked():
            self.result_params = {"width": self.width.value()}
        else:
            self.result_params = {"height": self.height.value()}
        return None


class TrimPrompt(_Base):
    ok_text = "Trim"
    def __init__(self, paths: list[Path]):
        self.duration = ff.duration_of(paths[0]) if ff.ffprobe_path() else 0.0
        subtitle = paths[0].name if len(paths) == 1 else f"{len(paths)} files (same cut for each)"
        if self.duration:
            subtitle += f" · {format_time(self.duration)} long"
        super().__init__("Trim", subtitle, paths)
        self.start = QLineEdit("0:00")
        self.end = QLineEdit(format_time(self.duration) if self.duration else "")
        self.end.setPlaceholderText("e.g. 1:30")
        self.grid.addWidget(QLabel("Start"), 0, 0)
        self.grid.addWidget(self.start, 0, 1)
        self.grid.addWidget(QLabel("End"), 1, 0)
        self.grid.addWidget(self.end, 1, 1)
        hint = QLabel("Seconds or m:ss — e.g. 75, 1:15, 1:02:03")
        hint.setObjectName("hint")
        self.grid.addWidget(hint, 2, 1)
        self.start.setFocus()
        self.start.selectAll()

    def validate(self) -> str | None:
        start = parse_time(self.start.text())
        end = parse_time(self.end.text())
        if start is None:
            return "Start time isn't a valid time."
        if end is None:
            return "End time isn't a valid time."
        if end <= start:
            return "End must be after start."
        if self.duration and start >= self.duration:
            return f"Start is past the end of the file ({format_time(self.duration)})."
        if self.duration:
            end = min(end, self.duration)
        self.result_params = {"start": start, "end": end}
        return None


class PagesPrompt(_Base):
    ok_text = "Extract"
    def __init__(self, paths: list[Path]):
        try:
            from ..engine import pdfs  # loaded on demand: the PDF libraries are large

            self.count = min(pdfs.page_count(p) for p in paths)
        except Exception:
            self.count = 9999
        subtitle = paths[0].name if len(paths) == 1 else f"{len(paths)} PDFs"
        if self.count != 9999:
            subtitle += f" · {self.count} page{'s' if self.count != 1 else ''}"
        super().__init__("Extract pages", subtitle, paths)
        self.first = QSpinBox(minimum=1, maximum=self.count, value=1)
        self.last = QSpinBox(minimum=1, maximum=self.count, value=self.count if self.count != 9999 else 1)
        self.grid.addWidget(QLabel("From page"), 0, 0)
        self.grid.addWidget(self.first, 0, 1)
        self.grid.addWidget(QLabel("To page"), 1, 0)
        self.grid.addWidget(self.last, 1, 1)
        self.first.setFocus()

    def validate(self) -> str | None:
        if self.last.value() < self.first.value():
            return "'To' must be the same as or after 'From'."
        self.result_params = {"first": self.first.value(), "last": self.last.value()}
        return None


def _password_field() -> QLineEdit:
    field = QLineEdit()
    field.setEchoMode(QLineEdit.Password)
    field.setMinimumWidth(220)
    return field


class LockPrompt(_Base):
    ok_text = "Lock PDF"
    def __init__(self, paths: list[Path]):
        subtitle = paths[0].name if len(paths) == 1 else f"{len(paths)} PDFs (same password)"
        super().__init__("Add a password", subtitle, paths)
        self.password = _password_field()
        self.again = _password_field()
        self.grid.addWidget(QLabel("Password"), 0, 0)
        self.grid.addWidget(self.password, 0, 1)
        self.grid.addWidget(QLabel("Again"), 1, 0)
        self.grid.addWidget(self.again, 1, 1)
        note = QLabel("Satsuma doesn't keep it. If you forget it, the copy can't be opened.")
        note.setObjectName("hint")
        note.setWordWrap(True)
        self.grid.addWidget(note, 2, 0, 1, 2)
        self.password.setFocus()

    def validate(self) -> str | None:
        if not self.password.text():
            return "Type a password."
        if self.password.text() != self.again.text():
            return "The two passwords don't match."
        self.result_params = {"password": self.password.text()}
        return None


class UnlockPrompt(_Base):
    ok_text = "Unlock"
    def __init__(self, paths: list[Path]):
        super().__init__("Remove the password", paths[0].name if len(paths) == 1 else f"{len(paths)} PDFs", paths)
        self.password = _password_field()
        self.grid.addWidget(QLabel("Current password"), 0, 0)
        self.grid.addWidget(self.password, 0, 1)
        self.password.setFocus()

    def validate(self) -> str | None:
        if not self.password.text():
            return "Type the PDF's password."
        self.result_params = {"password": self.password.text()}
        return None


SPEEDS = [(0.25, "¼× slow motion"), (0.5, "½× slower"), (1.5, "1.5× faster"), (2.0, "2× faster"),
          (4.0, "4× time-lapse")]


class SpeedPrompt(_Base):
    ok_text = "Change speed"
    def __init__(self, paths: list[Path]):
        super().__init__("Change speed", paths[0].name if len(paths) == 1 else f"{len(paths)} files", paths)
        self.group = QButtonGroup(self)
        for row, (factor, label) in enumerate(SPEEDS):
            button = QRadioButton(label)
            button.setProperty("factor", factor)
            self.group.addButton(button)
            self.grid.addWidget(button, row, 0, 1, 2)
            if factor == 2.0:
                button.setChecked(True)
                button.setFocus()

    def validate(self) -> str | None:
        self.result_params = {"factor": float(self.group.checkedButton().property("factor"))}
        return None


COMPRESS_PRESETS = [("Light", 75), ("Balanced", 50), ("Strong", 25), ("Tiny", 10)]
NOTICEABLE, DAMAGING = 25, 12      # % of the original size where warnings start


def _human(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            return f"{num:.0f} {unit}" if unit in ("B", "KB") else f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} GB"


class CompressPrompt(_Base):
    """Shows the current size and lets you pick how small, warning before it gets destructive."""
    ok_text = "Compress"

    def __init__(self, paths: list[Path]):
        self.total = sum(p.stat().st_size for p in paths if p.is_file())
        suffix = paths[0].suffix.lower()
        self.thing = ("the video" if suffix in {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".wmv"}
                      else "the pictures inside" if suffix == ".pdf" else "the picture")
        who = paths[0].name if len(paths) == 1 else f"{len(paths)} files"
        super().__init__("Compress", f"{who} · now {_human(self.total)}", paths)
        from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSlider

        self.now = QLabel(f"Now: <b>{_human(self.total)}</b>")
        self.now.setTextFormat(Qt.RichText)
        self.grid.addWidget(self.now, 0, 0, 1, 2)

        presets = QHBoxLayout()
        self.preset_buttons = []
        for name, percent in COMPRESS_PRESETS:
            button = QPushButton(f"{name}\n{percent}%")
            button.setCheckable(True)
            button.setObjectName("segment")
            button.clicked.connect(lambda _c=False, p=percent: self.slider.setValue(p))
            presets.addWidget(button)
            self.preset_buttons.append((percent, button))
        self.grid.addLayout(presets, 1, 0, 1, 2)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(3, 95)
        self.slider.valueChanged.connect(self._changed)
        self.grid.addWidget(QLabel("Keep"), 2, 0)
        self.grid.addWidget(self.slider, 2, 1)
        self.target = QLabel()
        self.target.setObjectName("promptTitle")
        self.grid.addWidget(self.target, 3, 0, 1, 2)
        self.warning = QLabel()
        self.warning.setWordWrap(True)
        self.grid.addWidget(self.warning, 4, 0, 1, 2)
        self.slider.setValue(50)
        self._changed(50)

    def _changed(self, percent: int) -> None:
        target = self.total * percent / 100
        self.target.setText(f"→ about {_human(target)}   (−{100 - percent}%)")
        for value, button in self.preset_buttons:
            button.setChecked(value == percent)
        if percent <= DAMAGING:
            self.warning.setObjectName("error")
            self.warning.setText(f"⚠ Very strong. {self.thing.capitalize()} may become unreadable or badly "
                                 "damaged: text and fine detail can turn into blocks or blur.")
        elif percent <= NOTICEABLE:
            self.warning.setObjectName("warn")
            self.warning.setText(f"Strong. Quality of {self.thing} will drop noticeably. "
                                 "Small text may be hard to read.")
        else:
            self.warning.setObjectName("hint")
            self.warning.setText("Satsuma aims for this size and keeps as much quality as fits. "
                                 "Your original isn't changed.")
        self.warning.style().unpolish(self.warning)
        self.warning.style().polish(self.warning)

    def validate(self) -> str | None:
        self.result_params = {"ratio": self.slider.value() / 100}
        return None


PROMPTS = {"resize": ResizePrompt, "trim": TrimPrompt, "pages": PagesPrompt, "lock": LockPrompt,
           "unlock": UnlockPrompt, "speed": SpeedPrompt, "compress": CompressPrompt}


def ask(kind: str, paths: list[Path]) -> dict | None:
    """Show the prompt for `kind`; return params, or None if cancelled."""
    dialog = PROMPTS[kind](paths)
    dialog.raise_()
    dialog.activateWindow()
    if dialog.exec() == QDialog.Accepted:
        return dialog.result_params
    return None
