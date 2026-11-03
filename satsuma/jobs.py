"""Run actions off the UI thread and report back through Qt signals."""
from __future__ import annotations

import itertools
import logging
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from .actions import Action, ensure_requirements
from .engine.ffmpeg_tool import Cancelled, CancelToken, ConversionError, FFmpegMissing, cancel_scope

log = logging.getLogger(__name__)
_ids = itertools.count(1)

# Errors whose message is already written for people.
FRIENDLY = (ConversionError, FFmpegMissing, Cancelled, ValueError, PermissionError,
            FileNotFoundError)


def _pdf_locked(exc: BaseException) -> bool:
    # Only look if the PDF engine was loaded; importing it here would cost memory for nothing.
    pdfs = sys.modules.get("satsuma.engine.pdfs")
    return pdfs is not None and isinstance(exc, pdfs.PdfLocked)


def friendly_error(exc: BaseException) -> str:
    if isinstance(exc, PermissionError):
        return "Windows blocked access to the file. Is it open in another app?"
    if isinstance(exc, FileNotFoundError):
        return "The file no longer exists."
    if isinstance(exc, FRIENDLY) or _pdf_locked(exc):
        return str(exc) or exc.__class__.__name__
    if isinstance(exc, OSError) and getattr(exc, "winerror", None) == 112:
        return "The disk is full."
    return f"Something went wrong ({exc.__class__.__name__}: {exc}). Details are in the log."


class JobSignals(QObject):
    started = Signal(int, str, str)          # job id, title, subtitle
    sources = Signal(int, list)              # job id, [input paths as str]: for before -> after sizes
    progress = Signal(int, float, str)       # job id, fraction 0..1, message
    finished = Signal(int, list)             # job id, [output paths as str]
    failed = Signal(int, str)                # job id, message
    cancelled = Signal(int)                  # job id: stopped because the user asked


class Job(QRunnable):
    def __init__(self, action: Action, paths: list[Path], params: dict, signals: JobSignals):
        super().__init__()
        self.id = next(_ids)
        self.action = action
        self.paths = [Path(p) for p in paths]
        self.params = params
        self.signals = signals
        self.token = CancelToken()
        self.setAutoDelete(True)

    def _progress(self, fraction: float, message: str) -> None:
        # Every action reports progress between files, so this is where a cancel takes effect.
        self.token.check()
        self.signals.progress.emit(self.id, max(0.0, min(1.0, float(fraction))), message)

    def run(self) -> None:  # noqa: D401 - Qt API
        title = f"{self.action.label} · {self.action.caption}" if self.action.caption else self.action.label
        subtitle = self.paths[0].name if len(self.paths) == 1 else f"{len(self.paths)} files"
        self.signals.started.emit(self.id, title, subtitle)
        self.signals.sources.emit(self.id, [str(p) for p in self.paths])
        try:
            self.token.check()
            missing = [p for p in self.paths if not p.exists()]
            if missing:
                raise FileNotFoundError(str(missing[0]))
            with cancel_scope(self.token):
                ensure_requirements(self.action, self._progress)
                outputs = self.action.run(self.paths, self.params, self._progress)
            log.info("job %s %s ok -> %s", self.id, self.action.id, [str(o) for o in outputs])
            self.signals.finished.emit(self.id, [str(o) for o in outputs])
        except Cancelled as exc:
            if self.token.cancelled:
                log.info("job %s %s cancelled", self.id, self.action.id)
                self.signals.cancelled.emit(self.id)
            else:   # stopped for another reason, e.g. Satsuma quitting
                self.signals.failed.emit(self.id, friendly_error(exc))
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
        self._tokens: dict[int, CancelToken] = {}
        for signal in (self.signals.finished, self.signals.failed):
            signal.connect(lambda job_id, *_: self._tokens.pop(job_id, None))
        self.signals.cancelled.connect(lambda job_id: self._tokens.pop(job_id, None))

    def submit(self, action: Action, paths, params: dict | None = None) -> int:
        job = Job(action, list(paths), params or {}, self.signals)
        self._tokens[job.id] = job.token
        self.pool.start(job)
        return job.id

    def cancel(self, job_id: int) -> None:
        token = self._tokens.get(job_id)
        if token:
            token.cancel()
