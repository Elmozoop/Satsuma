"""Satsuma 1.13: the Glass style and the first-run tour."""
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent

from conftest import pump
from satsuma.config import settings


def _style(value):
    settings.set("style", value)


def test_glass_and_solid_style_sheets_differ(qapp):
    from satsuma.ui import glass
    from satsuma.ui.controls import stylesheet

    try:
        _style("solid")
        solid = stylesheet()
        _style("glass")
        frosted = stylesheet()
        assert glass.is_glass()
        if glass.IS_WINDOWS:
            assert "rgba(" in frosted.split("QDialog {")[1].split("}")[0]     # see-through window
            assert solid != frosted
    finally:
        _style("glass")


def test_glass_is_the_default_and_survives_bad_values(qapp):
    from satsuma.config import DEFAULTS

    assert DEFAULTS["style"] == "glass"
    settings._data["style"] = "neon"
    settings._sanitise()
    assert settings.get("style") == "glass"


def test_switching_style_asks_settings_to_reopen(qapp):
    from satsuma.ui.settings_window import SettingsWindow

    _style("glass")
    window = SettingsWindow()
    asked = []
    window.restyle_requested.connect(lambda: asked.append(True))
    try:
        _style("solid")
        assert asked == [True]
    finally:
        _style("glass")
        window.close()


def test_ring_draws_a_frosted_plate_in_glass(qapp, workdir):
    from PySide6.QtGui import QColor, QImage, QPainter, QPixmap

    from satsuma.ui.radial import RadialView

    def centre_pixel(style):
        _style(style)
        view = RadialView()
        view.set_paths([workdir / "photo.jpg"], animate=False)
        view.open(animate=False)
        view.opening.snap(1.0)
        backdrop = QPixmap(view.side, view.side)
        backdrop.fill(QColor(255, 0, 0))                       # a loud "screen behind"
        view.backdrop = backdrop
        image = QImage(view.side, view.side, QImage.Format_ARGB32_Premultiplied)
        image.fill(QColor(0, 0, 0))
        painter = QPainter(image)
        view.paint(painter, QPointF(view.side / 2, view.side / 2))
        painter.end()
        return image.pixelColor(view.side // 2, int(view.side * 0.12))   # on the plate, above the wedges

    try:
        glass_px, solid_px = centre_pixel("glass"), centre_pixel("solid")
        assert glass_px.red() > glass_px.blue() + 15        # the red "screen" shows through glass…
        assert glass_px != solid_px                         # …and not through solid
    finally:
        _style("glass")


# ----------------------------------------------------------------------------- the tour
def test_tour_walks_through_and_remembers(qapp):
    from satsuma.ui.tutorial import Tutorial

    settings.set("tutorial_done", False)
    tour = Tutorial()
    try:
        assert tour.stack.count() == 8 and tour.next.text() == "Show me" and not tour.back.isVisible()
        for _ in range(7):
            tour._next()
        assert tour.next.text() == "Finish" and not tour.skip.isVisible()
        tour._next()
        assert settings.get("tutorial_done") is True
    finally:
        tour.close()


def test_practice_ring_explains_and_accepts_the_sample(qapp):
    from satsuma.ui.tutorial import PRACTICE_MIME, Tutorial

    tour = Tutorial()
    tour.go(2)
    tour.show()
    pump(qapp, 500)
    ring = tour.practice
    mime = QMimeData()
    mime.setData(PRACTICE_MIME, b"photo")
    wedge = next(w for w in ring.view.page_wedges() if w.action.id == "img-webp")
    centre = QPointF(ring.width() / 2, ring.height() / 2)
    point = (centre + (ring.view.wedge_center(wedge, centre) - centre) * ring._fit()).toPoint()
    ring.dragEnterEvent(QDragEnterEvent(point, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))
    ring.dragMoveEvent(QDragMoveEvent(point, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))
    assert "WEBP" in tour.practice_note.text()
    ring.dropEvent(QDropEvent(QPointF(point), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))
    assert "Nice" in tour.practice_note.text() and ring.view.chosen is wedge
    tour.close()


def test_tour_opens_on_first_launch_only(qapp, monkeypatch):
    import satsuma.app as app_module

    monkeypatch.setattr(app_module, "setup_logging", lambda: None)
    satsuma = app_module.Satsuma(qapp)
    try:
        assert any(a.text() == "Tour…" for a in satsuma._tray_menu.actions())
        satsuma.show_tutorial()
        assert satsuma.tutorial_window is not None and satsuma.tutorial_window.isVisible()
        satsuma.tutorial_window.finish()
        pump(qapp, 100)
        assert satsuma.tutorial_window is None and settings.get("tutorial_done") is True
    finally:
        satsuma.detector.stop()
        satsuma.watcher.stop()
        satsuma.tray.hide()


def test_asks_once_about_starting_with_windows_after_the_tour(qapp, monkeypatch):
    import satsuma.app as app_module
    from satsuma import winutil
    from satsuma.ui import controls

    monkeypatch.setattr(app_module, "setup_logging", lambda: None)
    asked, switched = [], []
    monkeypatch.setattr(controls, "_dialog", lambda *a, **k: asked.append(a[1]) or "yes")
    monkeypatch.setattr(winutil, "autostart_enabled", lambda: False)
    monkeypatch.setattr(winutil, "set_autostart", lambda on: switched.append(on) or True)
    satsuma = app_module.Satsuma(qapp)
    try:
        settings.set("autostart_asked", False)
        satsuma.show_tutorial()
        satsuma.tutorial_window.finish()
        pump(qapp, 700)
        assert asked == ["Start Satsuma with Windows?"] and switched == [True]
        satsuma.ask_autostart()                               # only ever once
        assert len(asked) == 1
        settings.set("autostart_asked", False)
        monkeypatch.setattr(winutil, "autostart_enabled", lambda: True)
        satsuma.ask_autostart()                               # already on (from the tour): no question
        assert len(asked) == 1
    finally:
        satsuma.detector.stop()
        satsuma.watcher.stop()
        satsuma.pinger.stop()
        satsuma.updater.stop()
        satsuma.tray.hide()
