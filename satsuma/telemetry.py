"""The anonymous "I'm running" signal, so the author can count how many people use Satsuma.

Every 10 minutes while Satsuma runs it sends one tiny message: a random id made on this PC (not
linked to anything about you) and the Satsuma version. Nothing about your files, names or what you
do. Switch it off in Settings → About; it is also silent until STATS_URL is set.
"""
from __future__ import annotations

import json
import uuid

from PySide6.QtCore import QObject, QTimer, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest

from .config import STATS_URL, VERSION, settings

PING_MS = 10 * 60 * 1000
FIRST_PING_MS = 30 * 1000      # not at the very start of sign-in, when the PC is busiest


def install_id() -> str:
    """This install's random id, made once."""
    value = str(settings.get("install_id") or "")
    try:
        uuid.UUID(value)
    except ValueError:
        value = str(uuid.uuid4())
        settings.set("install_id", value)
    return value


def payload() -> bytes:
    return json.dumps({"id": install_id(), "v": VERSION}).encode("utf-8")


def enabled() -> bool:
    return bool(STATS_URL) and bool(settings.get("count_me"))


class Pinger(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._network = QNetworkAccessManager(self)
        self._network.finished.connect(lambda reply: reply.deleteLater())   # answers aren't needed
        self._timer = QTimer(self)
        self._timer.setInterval(PING_MS)
        self._timer.timeout.connect(self.ping)
        self._first = QTimer(self)
        self._first.setSingleShot(True)
        self._first.timeout.connect(self._start)
        self._first.start(FIRST_PING_MS)
        settings.subscribe(self._on_setting)

    def _start(self) -> None:
        self.ping()
        self._timer.start()

    def _on_setting(self, key: str) -> None:
        if key in ("count_me", "*") and enabled() and not self._timer.isActive():
            self._start()

    def ping(self) -> bool:
        if not enabled():
            return False
        request = QNetworkRequest(QUrl(STATS_URL.rstrip("/") + "/ping"))
        request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
        request.setTransferTimeout(15000)
        self._network.post(request, payload())     # offline? it just fails quietly
        return True

    def stop(self) -> None:
        self._first.stop()
        self._timer.stop()
        settings.unsubscribe(self._on_setting)
