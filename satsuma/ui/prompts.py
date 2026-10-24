"""Small dialogs for actions that need a value (resize, trim, page range)."""
from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QDialog, QDialogButtonBox, QGridLayout, QLabel,
                               QLineEdit, QRadioButton, QSpinBox, QVBoxLayout)

from ..engine import ffmpeg_tool as ff
from ..engine import images, pdfs


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


class _Base(QDialog):
    def __init__(self, title: str, subtitle: str):
        super().__init__(None)
        self.setWindowTitle(f"Satsuma — {title}")
        self.setWindowFlags(Qt.Dialog | Qt.WindowStaysOnTopHint | Qt.WindowCloseButtonHint)
        self.setMinimumWidth(340)
        self.layout_ = QVBoxLayout(self)
        heading = QLabel(f"<b>{title}</b><br><span style='color:gray'>{subtitle}</span>")
        heading.setTextFormat(Qt.RichText)
        self.layout_.addWidget(heading)
        self.grid = QGridLayout()
        self.grid.setColumnStretch(1, 1)
        self.layout_.addLayout(self.grid)
        self.error = QLabel("")
        self.error.setStyleSheet("color:#d6342c")
        self.layout_.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
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
    def __init__(self, paths: list[Path]):
        subtitle = paths[0].name if len(paths) == 1 else f"{len(paths)} images"
        try:
            meta = images.info(paths[0])
            self.size = (meta["width"], meta["height"])
            subtitle += f" · {meta['width']}×{meta['height']}"
        except Exception:
            self.size = None
        super().__init__("Resize", subtitle)

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
    def __init__(self, paths: list[Path]):
        self.duration = ff.duration_of(paths[0]) if ff.ffprobe_path() else 0.0
        subtitle = paths[0].name if len(paths) == 1 else f"{len(paths)} files (same cut for each)"
        if self.duration:
            subtitle += f" · {format_time(self.duration)} long"
        super().__init__("Trim", subtitle)
        self.start = QLineEdit("0:00")
        self.end = QLineEdit(format_time(self.duration) if self.duration else "")
        self.end.setPlaceholderText("e.g. 1:30")
        self.grid.addWidget(QLabel("Start"), 0, 0)
        self.grid.addWidget(self.start, 0, 1)
        self.grid.addWidget(QLabel("End"), 1, 0)
        self.grid.addWidget(self.end, 1, 1)
        hint = QLabel("Seconds or m:ss — e.g. 75, 1:15, 1:02:03")
        hint.setStyleSheet("color:gray")
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
    def __init__(self, paths: list[Path]):
        try:
            self.count = min(pdfs.page_count(p) for p in paths)
        except Exception:
            self.count = 9999
        subtitle = paths[0].name if len(paths) == 1 else f"{len(paths)} PDFs"
        if self.count != 9999:
            subtitle += f" · {self.count} page{'s' if self.count != 1 else ''}"
        super().__init__("Extract pages", subtitle)
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


PROMPTS = {"resize": ResizePrompt, "trim": TrimPrompt, "pages": PagesPrompt}


def ask(kind: str, paths: list[Path]) -> dict | None:
    """Show the prompt for `kind`; return params, or None if cancelled."""
    dialog = PROMPTS[kind](paths)
    dialog.raise_()
    dialog.activateWindow()
    if dialog.exec() == QDialog.Accepted:
        return dialog.result_params
    return None
