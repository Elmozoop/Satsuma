from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QApplication

from conftest import pump

BOTH = Qt.CopyAction | Qt.MoveAction
SHIFT = Qt.ShiftModifier
LB = Qt.LeftButton


def _mime(paths):
    data = QMimeData()
    data.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    return data


def test_shift_drag_drop_converts_and_copies(qapp, workdir):
    from satsuma.app import Satsuma

    sat = Satsuma(qapp)
    menu = sat.menu
    try:
        menu.arm(QPoint(700, 400), smart=True)
        assert menu.mode == "sense"
        data = _mime([workdir / "alpha.png"])
        enter = QDragEnterEvent(QPoint(60, 60), BOTH, data, LB, SHIFT)
        QApplication.sendEvent(menu, enter)
        assert enter.isAccepted() and enter.dropAction() == Qt.CopyAction
        assert menu.mode == "drop" and menu.view.wedges
        point = menu.point_for("img-jpg")
        QApplication.sendEvent(menu, QDragMoveEvent(point, BOTH, data, LB, SHIFT))
        drop = QDropEvent(QPointF(point), BOTH, data, LB, SHIFT)
        QApplication.sendEvent(menu, drop)
        # COPY, never MOVE: Explorer must not delete the original after a Shift-drop.
        assert drop.isAccepted() and drop.dropAction() == Qt.CopyAction
        pump(qapp, 1500)
        assert (workdir / "alpha.jpg").exists()
        assert (workdir / "alpha.png").exists()
    finally:
        sat.quit()


def test_text_drag_is_ignored(qapp):
    from satsuma.ui.menu import ActionMenu

    menu = ActionMenu()
    menu.arm(QPoint(300, 300), smart=True)
    data = QMimeData()
    data.setText("selected text")
    enter = QDragEnterEvent(QPoint(40, 40), BOTH, data, LB, SHIFT)
    QApplication.sendEvent(menu, enter)
    assert not enter.isAccepted() and menu.mode == "sense"
    menu.dismiss()


def test_detector_state_machine(qapp, monkeypatch):
    from satsuma import detector as det_mod
    from satsuma import winutil

    state = {"btn": False, "shift": False, "pos": QPoint(100, 100)}
    monkeypatch.setattr(winutil, "primary_button_vk", lambda: winutil.VK_LBUTTON)
    monkeypatch.setattr(winutil, "key_down",
                        lambda vk: state["btn"] if vk == winutil.VK_LBUTTON else state["shift"] if vk == 0x10 else False)
    monkeypatch.setattr(det_mod.QCursor, "pos", staticmethod(lambda: state["pos"]))
    monkeypatch.setattr(det_mod.QApplication, "widgetAt", staticmethod(lambda p: None))
    d = det_mod.DragDetector()
    events = []
    d.armed.connect(lambda p: events.append("armed"))
    d.released.connect(lambda: events.append("released"))

    def step(**kw):
        state.update(kw)
        d._poll()

    step(btn=True)
    step(pos=QPoint(150, 100))
    step(btn=False)
    assert events == []  # no Shift
    step(btn=True, pos=QPoint(100, 100))
    step(shift=True, pos=QPoint(150, 100))
    step(btn=False, shift=False)
    assert events == ["armed", "released"]
