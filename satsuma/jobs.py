"""Run actions off the UI thread and report back through Qt signals."""
from __future__ import annotations

import itertools
import logging
import traceback
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from .actions import Action, ensure_requirements
from .engine.ffmpeg_tool import Cancelled, ConversionError, FFmpegMissing
from .engine.pdfs import PdfLocked

log = logging.getLogger(__name__)
_ids = itertools.count(1)

# Errors whose message is already written for people.
FRIENDLY = (ConversionError, FFmpegMissing, Cancelled, PdfLocked, ValueError, PermissionError,
            FileNotFoundError)


def friendly_error(exc: BaseException) -> str:
    if isinstance(exc, PermissionError):
        return "Windows blocked access to the file. Is it open in another app?"
    if isinstance(exc, FileNotFoundError):
        return "The file no longer exists."
    if isinstance(exc, FRIENDLY):
        return str(exc) or exc.__class__.__name__
    if isinstance(exc, OSError) and getattr(exc, "winerror", None) == 112:
        return "The disk is full."
    return f"Something went wrong ({exc.__class__.__name__}: {exc}). Details are in the log."


class JobSignals(QObject):
    started = Signal(int, str, str)          # job id, title, subtitle
    progress = Signal(int, float, str)       # job id, fraction 0..1, message
    finished = Signal(int, list)             # job id, [output paths as str]
    failed = Signal(int, str)                # job id, message


class Job(QRunnable):
    def __init__(self, action: Action, paths: list[Path], params: dict, signals: JobSignals):
        super().__init__()
        self.id = next(_ids)
        self.action = action
        self.paths = [Path(p) for p in paths]
        self.params = params
        self.signals = signals
        self.setAutoDelete(True)

    def _progress(self, fraction: float, message: str) -> None:
        self.signals.progress.emit(self.id, max(0.0, min(1.0, float(fraction))), message)

    def run(self) -> None:  # noqa: D401 - Qt API
        title = f"{self.action.label} · {self.action.caption}" if self.action.caption else self.action.label
        subtitle = self.paths[0].name if len(self.paths) == 1 else f"{len(self.paths)} files"
        self.signals.started.emit(self.id, title, subtitle)
        try:
            missing = [p for p in self.paths if not p.exists()]
            if missing:
                raise FileNotFoundError(str(missing[0]))
            ensure_requirements(self.action, self._progress)
            outputs = self.action.run(self.paths, self.params, self._progress)
            log.info("job %s %s ok -> %s", self.id, self.action.id, [str(o) for o in outputs])
            self.signals.finished.emit(self.id, [str(o) for o in outputs])
        except BaseException as exc:  # never let a worker die silently
            log.error("job %s %s failed:\n%s", self.id, self.action.id, traceback.format_exc())
            self.signals.failed.emit(self.id, friendly_error(exc))


class JobRunner(QObject):
    """Owns the thread pool. Media jobs are heavy, so cap concurrency."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.signals = JobSignals()
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)

    def submit(self, action: Action, paths, params: dict | None = None) -> int:
        job = Job(action, list(paths), params or {}, self.signals)
        self.pool.start(job)
        return job.id
