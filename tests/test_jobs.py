"""Cancel, undo and the detector's idle polling."""
import sys
import threading
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint

from conftest import pump
from satsuma.actions import Action
from satsuma.engine import ffmpeg_tool as ff
from satsuma.jobs import JobRunner


def test_detector_polls_slowly_until_a_button_goes_down(qapp, monkeypatch):
    from satsuma import detector as det_mod
    from satsuma import winutil

    state = {"btn": False}
    monkeypatch.setattr(winutil, "primary_button_vk", lambda: winutil.VK_LBUTTON)
    monkeypatch.setattr(winutil, "key_down", lambda vk: state["btn"] if vk == winutil.VK_LBUTTON else False)
    monkeypatch.setattr(det_mod.QCursor, "pos", staticmethod(lambda: QPoint(10, 10)))
    monkeypatch.setattr(det_mod.QApplication, "widgetAt", staticmethod(lambda p: None))
    d = det_mod.DragDetector()
    assert d._timer.interval() == det_mod.IDLE_POLL_MS
    state["btn"] = True
    d._poll()
    assert d._timer.interval() == det_mod.POLL_MS
    state["btn"] = False
    d._poll()
    assert d._timer.interval() == det_mod.IDLE_POLL_MS


def _wait(qapp, condition, seconds=10.0):
    end = time.time() + seconds
    while time.time() < end and not condition():
        pump(qapp, 20)
    return condition()


def test_cancel_stops_a_job_between_files(qapp, tmp_path):
    started = threading.Event()
    produced = []

    def run(paths, _params, progress):
        for i, path in enumerate(paths):
            progress(i / len(paths), path.name)      # where a cancel takes effect
            started.set()
            time.sleep(0.2)
            produced.append(path)
        return produced

    files = [tmp_path / f"f{i}.txt" for i in range(10)]
    for f in files:
        f.write_text("x")
    runner = JobRunner()
    seen = {"cancelled": [], "finished": [], "failed": []}
    runner.signals.cancelled.connect(lambda job_id: seen["cancelled"].append(job_id))
    runner.signals.finished.connect(lambda job_id, _o: seen["finished"].append(job_id))
    runner.signals.failed.connect(lambda job_id, _m: seen["failed"].append(job_id))
    job_id = runner.submit(Action("test-slow", "Slow", "", "tools", run), files)
    assert started.wait(5)
    runner.cancel(job_id)
    assert _wait(qapp, lambda: seen["cancelled"] or seen["finished"] or seen["failed"])
    assert seen == {"cancelled": [job_id], "finished": [], "failed": []}
    assert len(produced) < len(files)


@pytest.mark.skipif(not ff.available(), reason="ffmpeg not installed")
def test_cancel_kills_ffmpeg_and_removes_the_partial_file(tmp_path):
    out = tmp_path / "long.mp4"
    token = ff.CancelToken()
    threading.Timer(1.0, token.cancel).start()
    with ff.cancel_scope(token), pytest.raises(ff.Cancelled):
        ff.run(["-f", "lavfi", "-i", "testsrc=duration=600:size=1280x720:rate=30",
                "-c:v", "libx264", "-preset", "veryslow", str(out)])
    assert not out.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Recycle Bin is Windows only")
def test_undo_sends_results_to_the_recycle_bin(tmp_path):
    from satsuma import winutil

    result = tmp_path / "satsuma-undo-test.txt"
    result.write_text("made by the Satsuma test suite; safe to delete")
    folder = tmp_path / "satsuma-undo-test-folder"
    (folder / "inner").mkdir(parents=True)
    assert winutil.recycle([result, folder])
    assert not result.exists() and not folder.exists()
    assert winutil.recycle([tmp_path / "already-gone.txt"])   # nothing to do is not a failure


def test_toast_cancel_and_undo_flow(qapp, tmp_path, monkeypatch):
    from satsuma import winutil
    from satsuma.ui.toast import Toasts

    toasts = Toasts()
    asked = []
    toasts.cancel_requested.connect(asked.append)
    toasts.started(1, "Convert", "a.png")
    toasts._cancel(toasts._card(1))
    assert asked == [1] and toasts._card(1).state == "cancelling"
    toasts.cancelled(1)
    assert toasts._card(1).state == "cancelled"

    made = tmp_path / "a.webp"
    made.write_text("x")
    recycled = []
    monkeypatch.setattr(winutil, "recycle", lambda paths: recycled.extend(paths) or True)
    toasts.started(2, "Convert", "a.png")
    toasts.finished(2, [str(made)])
    toasts._undo(toasts._card(2))
    assert recycled == [Path(made)] and toasts._card(2).state == "undone"
    toasts.hide()
