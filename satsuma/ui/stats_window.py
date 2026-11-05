"""The owner's Stats window: people using Satsuma right now, and downloads per release.

Only on the author's PC: it appears when %LOCALAPPDATA%\\Satsuma\\owner.json exists, holding the
counter's address and its private key. Downloads come from GitHub's public release data.
"""
from __future__ import annotations

import json

from PySide6.QtCore import QTimer, QUrl, Qt
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ..config import DATA_DIR, GITHUB_REPO, OWNER_FILE_NAME, STATS_URL
from .controls import stylesheet
from .glass import glass_window

REFRESH_MS = 60 * 1000


def owner_config() -> dict | None:
    """The owner file's contents, or None when this isn't the author's PC."""
    try:
        data = json.loads((DATA_DIR / OWNER_FILE_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("key") else None


def _number(text: str, caption: str) -> QFrame:
    box = QFrame()
    box.setObjectName("card")
    layout = QVBoxLayout(box)
    layout.setContentsMargins(16, 12, 16, 12)
    value = QLabel(text)
    value.setObjectName("bigNumber")
    layout.addWidget(value)
    label = QLabel(caption)
    label.setObjectName("hint")
    layout.addWidget(label)
    box.value = value
    return box


class StatsWindow(QDialog):
    def __init__(self, owner: dict):
        super().__init__(None)
        self.owner = owner
        self.setWindowTitle("Satsuma Stats")
        self.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint)
        glass_window(self)
        self.setMinimumWidth(560)
        self._network = QNetworkAccessManager(self)
        self._network.finished.connect(self._reply_done)   # a bound slot: gone when the window is

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 18)
        root.setSpacing(12)
        title = QLabel("Satsuma Stats")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        root.addWidget(self._heading("People using Satsuma"))
        grid = QGridLayout()
        grid.setSpacing(10)
        self.online = _number("–", "online now")
        self.today = _number("–", "in the last 24 hours")
        self.month = _number("–", "in the last 30 days")
        self.installs = _number("–", "installs ever")
        for i, box in enumerate((self.online, self.today, self.month, self.installs)):
            grid.addWidget(box, 0, i)
        root.addLayout(grid)
        self.versions = QLabel("")
        self.versions.setObjectName("hint")
        self.versions.setWordWrap(True)
        root.addWidget(self.versions)

        root.addWidget(self._heading("Downloads"))
        downloads = QHBoxLayout()
        self.total_downloads = _number("–", "downloads, all releases")
        downloads.addWidget(self.total_downloads)
        self.per_release = QLabel("")
        self.per_release.setObjectName("rowTitle")
        self.per_release.setWordWrap(True)
        downloads.addWidget(self.per_release, 1)
        root.addLayout(downloads)

        footer = QHBoxLayout()
        self.status = QLabel("")
        self.status.setObjectName("hint")
        footer.addWidget(self.status, 1)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        footer.addWidget(refresh)
        root.addLayout(footer)

        self.setStyleSheet(stylesheet())
        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.refresh()

    @staticmethod
    def _heading(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("cardTitle")
        return label

    # ------------------------------------------------------------------ fetching
    def refresh(self) -> None:
        self.status.setText("Updating…")
        url = str(self.owner.get("stats_url") or STATS_URL).rstrip("/")
        if url:
            request = QNetworkRequest(QUrl(url + "/stats"))
            request.setRawHeader(b"Authorization", f"Bearer {self.owner['key']}".encode("utf-8"))
            request.setTransferTimeout(15000)
            self._network.get(request).setProperty("kind", "users")
        else:
            self.status.setText("The user counter isn't set up yet (see server/README.md).")
        request = QNetworkRequest(QUrl(f"https://api.github.com/repos/{GITHUB_REPO}/releases?per_page=100"))
        request.setRawHeader(b"Accept", b"application/vnd.github+json")
        request.setTransferTimeout(15000)
        self._network.get(request).setProperty("kind", "downloads")

    def _reply_done(self, reply: QNetworkReply) -> None:
        if reply.property("kind") == "users":
            self._got_users(reply)
        else:
            self._got_downloads(reply)

    def done(self, result: int) -> None:
        """Closing stops the refresh timer and drops any request still on its way."""
        self._timer.stop()
        try:
            self._network.finished.disconnect(self._reply_done)
        except (RuntimeError, TypeError):
            pass
        for reply in self._network.findChildren(QNetworkReply):
            reply.abort()
        super().done(result)

    def _got_users(self, reply: QNetworkReply) -> None:
        reply.deleteLater()
        status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        if status == 401:
            self.status.setText("The counter refused the key in owner.json.")
            return
        if reply.error() != QNetworkReply.NoError:
            self.status.setText(f"Couldn't reach the counter ({reply.errorString()}).")
            return
        try:
            data = json.loads(bytes(reply.readAll()).decode("utf-8"))
        except ValueError:
            self.status.setText("The counter sent something unexpected.")
            return
        self.show_users(data)

    def show_users(self, data: dict) -> None:
        for box, key in ((self.online, "online"), (self.today, "today"), (self.month, "month"),
                         (self.installs, "installs")):
            box.value.setText(f"{int(data.get(key, 0)):,}")
        versions = data.get("versions") or {}
        self.versions.setText("Versions in use (last 30 days): " +
                              ", ".join(f"{v} × {n}" for v, n in versions.items()) if versions else "")
        self.status.setText("Up to date. Refreshes every minute.")

    def _got_downloads(self, reply: QNetworkReply) -> None:
        reply.deleteLater()
        if reply.error() != QNetworkReply.NoError:
            self.per_release.setText("Couldn't reach GitHub.")
            return
        try:
            releases = json.loads(bytes(reply.readAll()).decode("utf-8"))
        except ValueError:
            return
        self.show_downloads(releases)

    def show_downloads(self, releases: list) -> None:
        lines, total = [], 0
        for release in releases if isinstance(releases, list) else []:
            count = sum(int(a.get("download_count", 0)) for a in release.get("assets", []))
            total += count
            lines.append(f"{release.get('tag_name') or release.get('name')}: {count:,}")
        self.total_downloads.value.setText(f"{total:,}")
        self.per_release.setText("\n".join(lines) if lines else "No releases published yet.")
