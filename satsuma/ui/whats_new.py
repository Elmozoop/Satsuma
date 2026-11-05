"""The card shown once after Satsuma updated itself: the version, its highlights, and a link."""
from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .controls import stylesheet
from .glass import glass_window


class WhatsNew(QDialog):
    def __init__(self, version: str, highlights: list[str], url: str):
        super().__init__(None)
        self.url = url
        glass_window(self)
        self.setWindowTitle("Satsuma updated")
        self.setWindowFlags(Qt.Dialog | Qt.WindowStaysOnTopHint | Qt.WindowCloseButtonHint)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setMinimumWidth(400)
        self.setStyleSheet(stylesheet())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(8)
        title = QLabel(f"Satsuma updated to {version} 🍊")
        title.setObjectName("promptTitle")
        layout.addWidget(title)
        intro = QLabel("It updated itself in the background; your settings are just as they were."
                       + (" What's new:" if highlights else ""))
        intro.setObjectName("hint")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.points = []
        for text in highlights:
            point = QLabel(f"•  {text}")
            point.setWordWrap(True)
            point.setTextFormat(Qt.PlainText)
            layout.addWidget(point)
            self.points.append(point)
        layout.addSpacing(10)

        row = QHBoxLayout()
        self.notes = QPushButton("See all release notes")
        self.notes.clicked.connect(self.open_notes)
        row.addWidget(self.notes)
        row.addStretch(1)
        done = QPushButton("Got it")
        done.setObjectName("primary")
        done.setDefault(True)
        done.clicked.connect(self.accept)
        row.addWidget(done)
        layout.addLayout(row)

    def open_notes(self) -> None:
        QDesktopServices.openUrl(QUrl(self.url))
        self.accept()
