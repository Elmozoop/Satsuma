"""Watched folders: run an action on every new file that lands in a folder.

Only files that arrive after watching starts are touched. A file is handled once its size has
stopped changing and it can be opened (a download or copy has finished). Results Satsuma writes
into a watched folder are never picked up again, so a rule can't feed on its own output.
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer

from .actions import Action, actions_for, catalogue
from .config import settings

log = logging.getLogger(__name__)
SETTLE_MS = 1500   # a new file must look the same this long before we touch it
SKIP_SUFFIXES = {".tmp", ".crdownload", ".part", ".partial", ".download", ".opdownload"}


def watchable_actions() -> list[tuple[str, str, Action]]:
    """(category label, category, action) for every action that can run unattended on one file."""
    found, seen = [], set()
    for category, label, actions in catalogue():
        for action in actions:
            if (action.prompt and not action.unattended) or action.min_files > 1 or (category, action.id) in seen:
                continue
            seen.add((category, action.id))
            found.append((label, category, action))
    return found


def describe(action_id: str) -> str:
    for label, _category, action in watchable_actions():
        if action.id == action_id:
            caption = f" ({action.caption})" if action.caption else ""
            return f"{label}: {action.label}{caption}"
    return action_id


def rules() -> list[dict]:
    return [r for r in (settings.get("watch_rules") or [])
            if isinstance(r, dict) and r.get("folder") and r.get("action")]


class FolderWatcher(QObject):
    def __init__(self, runner, parent=None):
        super().__init__(parent)
        self.runner = runner
        self._fs = QFileSystemWatcher(self)
        self._fs.directoryChanged.connect(self._changed)
        self._known: dict[str, set[str]] = {}            # folder -> names already seen or made
        self._sizes: dict[str, int] = {}                 # file -> size at the last look
        self._jobs: dict[int, str] = {}                  # job id -> folder it came from
        self._timers: dict[str, QTimer] = {}
        s = runner.signals
        s.finished.connect(self._job_finished)
        for signal in (s.failed, s.cancelled):
            signal.connect(lambda job_id, *_: self._job_done(job_id))
        settings.subscribe(self._on_setting)
        self.reload()

    # ------------------------------------------------------------------ setup
    def _on_setting(self, key: str) -> None:
        if key in ("watch_rules", "*"):
            self.reload()

    def reload(self) -> None:
        wanted = {str(Path(r["folder"])) for r in rules() if r.get("enabled", True)}
        wanted = {f for f in wanted if Path(f).is_dir()}
        current = set(self._fs.directories())
        if current - wanted:
            self._fs.removePaths(list(current - wanted))
        for folder in wanted - current:
            self._known[folder] = self._names(folder)    # what's there now is never touched
            self._fs.addPath(folder)
            log.info("watching %s", folder)
        for folder in set(self._known) - wanted:
            self._known.pop(folder, None)

    @property
    def folders(self) -> list[str]:
        return list(self._fs.directories())

    @staticmethod
    def _names(folder: str) -> set[str]:
        try:
            return {p.name for p in Path(folder).iterdir()}
        except OSError:
            return set()

    # ------------------------------------------------------------------ scanning
    def _changed(self, folder: str) -> None:
        timer = self._timers.get(folder)
        if timer is None:
            timer = self._timers[folder] = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(SETTLE_MS)
            timer.timeout.connect(lambda f=folder: self.scan(f))
        timer.start()   # restart: wait until the folder has been quiet for a moment

    def _busy(self) -> bool:
        # Any job (a watched-folder one or one the user started) may be writing a result into a
        # watched folder: wait until it finishes, so that result is recognised as ours.
        return self.runner.pool.activeThreadCount() > 0

    def scan(self, folder: str) -> None:
        known = self._known.get(folder)
        if known is None:
            return
        if self._busy():
            self._changed(folder)
            return
        waiting = False
        for path in sorted(Path(folder).iterdir() if Path(folder).is_dir() else []):
            if path.name in known or not path.is_file():
                continue
            if path.name.startswith(("~$", ".")) or path.suffix.lower() in SKIP_SUFFIXES:
                continue
            if not self._settled(path):
                waiting = True
                continue
            known.add(path.name)
            self._sizes.pop(str(path), None)
            self._run_rules(folder, path)
        if waiting:
            self._changed(folder)

    def _settled(self, path: Path) -> bool:
        try:
            size = path.stat().st_size
            with open(path, "rb"):
                pass                       # still being written: Windows refuses the open
        except OSError:
            return False
        previous = self._sizes.get(str(path))
        self._sizes[str(path)] = size
        return previous == size and size > 0

    def _run_rules(self, folder: str, path: Path) -> None:
        offered = {a.id: a for a in actions_for([path], customise=False)}
        for rule in rules():
            if not rule.get("enabled", True) or str(Path(rule["folder"])) != folder:
                continue
            action = offered.get(rule["action"])
            if action is None:
                continue                   # this rule isn't for this kind of file
            log.info("watched folder: %s on %s", action.id, path)
            job_id = self.runner.submit(action, [path])
            self._jobs[job_id] = folder

    # ------------------------------------------------------------------ results
    def _job_finished(self, job_id: int, outputs: list) -> None:
        for out in outputs:
            out = Path(out)
            for folder, known in self._known.items():
                if str(out.parent) == folder or str(out) == folder:
                    known.add(out.name)
        self._job_done(job_id)

    def _job_done(self, job_id: int) -> None:
        self._jobs.pop(job_id, None)
        for folder in self._known:
            self._changed(folder)          # look again for files that arrived meanwhile

    def stop(self) -> None:
        if self._fs.directories():
            self._fs.removePaths(self._fs.directories())
        settings.unsubscribe(self._on_setting)
