"""Satsuma 1.7: thumbnails, card sizes, wedge tints, the finish tick, tray activity, prompts."""
import time
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfWriter

from PySide6.QtCore import Qt

from conftest import pump
from satsuma import actions
from satsuma.config import settings


def _wait(qapp, condition, seconds=5.0):
    end = time.time() + seconds
    while time.time() < end and not condition():
        pump(qapp, 20)
    return condition()


def test_size_change_wording():
    from satsuma.ui.toast import size_change

    assert size_change(2_400_000, 380_000) == "2.3 MB → 371.1 KB (−84%)"
    assert size_change(1000, 1500) == "1000 B → 1.5 KB (+50%)"
    assert size_change(1000, 1004) == "1000 B → 1004 B"            # no percentage for a tiny change
    assert size_change(None, 2048) == "2.0 KB" and size_change(1000, None) == ""


def test_convert_wedges_share_one_tint(qapp, workdir):
    """Every convert wedge in a ring shares one tint (none looks greyed out); tools stay neutral."""
    from satsuma.ui.radial import RadialView, ring_tint
    from satsuma.ui.theme import palette

    assert ring_tint([workdir / "photo.jpg"]) != ring_tint([workdir / "clip.mp4"])
    assert ring_tint([workdir / "report.pdf"]) is None and ring_tint([workdir / "notes.docx"]) is None   # plain
    view = RadialView()
    view.set_paths([workdir / "photo.jpg"], animate=False)
    pal = palette()

    def centre_colour(action_id):
        wedge = next(w for w in view.wedges if w.action.id == action_id)
        count = len(view.page_wedges(wedge.page))
        image = view._wedge_sprite(wedge, count, False, pal, True, 1.0, label=False)[0].toImage()
        return image.pixelColor(image.rect().center())

    assert centre_colour("img-pdf") == centre_colour("img-png") == centre_colour("img-webp")
    assert centre_colour("img-compress") != centre_colour("img-png")


def test_thumbnails(qapp, workdir, tmp_path):
    from satsuma.engine import images
    from satsuma.ui.thumbs import thumbnail

    big = thumbnail(workdir / "photo.jpg", 64)
    assert big is not None and max(big.width(), big.height()) <= 64
    heic = thumbnail(images.convert(workdir / "photo.jpg", ".heic"), 64)
    assert heic is not None                                          # through Pillow
    pdf = tmp_path / "one.pdf"
    writer = PdfWriter()
    writer.add_blank_page(200, 300)
    writer.write(str(pdf))
    page = thumbnail(pdf, 90)
    assert page is not None and page.height() == 90
    assert thumbnail(tmp_path / "missing.png", 64) is None
    assert thumbnail(tmp_path, 64) is None                           # folders have no preview


def test_card_shows_result_thumbnail_and_sizes(qapp, workdir):
    from satsuma.engine import images
    from satsuma.ui.toast import Toasts

    out = images.convert(workdir / "photo.jpg", ".webp")
    toasts = Toasts()
    toasts.started(7, "WEBP", "photo.jpg")
    toasts.sources(7, [str(workdir / "photo.jpg")])
    toasts.finished(7, [str(out)])
    card = toasts._card(7)
    assert card.thumb is not None and "→" in card.message and card.message.startswith("photo.webp · ")
    toasts.hide()


def test_tray_activity_states(qapp):
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtGui import QIcon, QPixmap

    from satsuma.ui.tray_badge import TrayActivity, badge_icon

    class Signals(QObject):
        started = Signal(int, str, str)
        progress = Signal(int, float, str)
        finished = Signal(int, list)
        failed = Signal(int, str)
        cancelled = Signal(int)

    class Tray:
        def __init__(self):
            self.icon, self.tip = None, ""

        def setIcon(self, icon):
            self.icon = icon

        def setToolTip(self, tip):
            self.tip = tip

    base = QIcon(QPixmap(32, 32))
    assert not badge_icon(base, 0.5).isNull() and not badge_icon(base, None, done=True).isNull()
    tray, signals = Tray(), Signals()
    activity = TrayActivity(tray, base, lambda: "idle", signals)
    signals.started.emit(1, "PNG", "a.jpg")
    signals.progress.emit(1, 0.5, "")
    activity._refresh()
    busy = tray.icon
    assert busy is not None and busy is not base and tray.tip == ""      # progress shows on the icon only
    signals.finished.emit(1, [])
    assert tray.icon is not busy and activity._rest.isActive()
    activity._idle()
    assert tray.tip == "idle" and tray.icon is base


def test_choosing_plays_the_tick_then_closes(qapp, workdir):
    from satsuma.ui.menu import ActionMenu

    menu = ActionMenu()
    menu.open_for([workdir / "photo.jpg"])
    pump(qapp, 300)
    chosen = []
    menu.chosen.connect(lambda action, paths: chosen.append(action.id))
    wedge = menu.view.page_wedges()[0]
    menu._choose(wedge, [workdir / "photo.jpg"])
    assert chosen == [wedge.action.id]                               # the job starts straight away
    assert menu.mode == "confirming" and menu.view.chosen is wedge
    assert _wait(qapp, lambda: menu.mode == "hidden")


@pytest.mark.parametrize("kind", ["resize", "trim", "pages", "lock", "unlock", "speed"])
def test_every_prompt_builds_with_a_preview(qapp, workdir, tmp_path, kind):
    from satsuma.ui import prompts

    if kind in ("pages", "lock", "unlock"):
        target = tmp_path / "doc.pdf"
        writer = PdfWriter()
        writer.add_blank_page(100, 100)
        writer.write(str(target))
    else:
        target = workdir / "photo.jpg"
    dialog = prompts.PROMPTS[kind]([target])
    thumb = dialog.findChild(type(dialog.error), "thumb")
    assert thumb is not None and thumb.pixmap() is not None and not thumb.pixmap().isNull()
    dialog.close()


def test_type_colours_can_be_switched_off(qapp, workdir):
    from satsuma.ui.radial import RadialView

    view = RadialView()
    view.set_paths([workdir / "photo.jpg"], animate=False)
    from satsuma.ui.theme import palette

    pal = palette()
    wedge = view.page_wedges()[0]
    on = view._wedge_sprite(wedge, len(view.page_wedges()), False, pal, True, 1.0)[0].toImage()
    settings.set("type_colors", False)
    try:
        view._check_style(pal, 1.0)
        off = view._wedge_sprite(wedge, len(view.page_wedges()), False, pal, True, 1.0)[0].toImage()
        centre = on.rect().center()
        assert on.pixelColor(centre) != off.pixelColor(centre)
    finally:
        settings.set("type_colors", True)


# ----------------------------------------------------------------------------- editing the ring from the preview
@pytest.fixture()
def actions_page(qapp):
    from satsuma.ui.settings_window import SettingsWindow

    for key in ("actions_hidden", "actions_shown", "actions_order"):
        settings.reset([key])
    window = SettingsWindow()
    window.action_kind.setCurrentIndex(0)        # Images
    yield window
    for key in ("actions_hidden", "actions_shown", "actions_order"):
        settings.reset([key])
    window.close()


def _ring(window):
    return [w.action.id for w in window.actions_preview.view.wedges if w.action.group == "convert"]


def test_replacing_a_wedge_with_one_not_on_the_ring(actions_page):
    assert "img-bmp" not in _ring(actions_page)
    spot = _ring(actions_page).index("img-gif")
    actions_page._replace_action("img-gif", "img-bmp")
    ring = _ring(actions_page)
    assert ring.index("img-bmp") == spot and "img-gif" not in ring          # same spot, GIF off the ring


def test_replacing_with_one_already_on_the_ring_swaps_them(actions_page):
    before = _ring(actions_page)                  # the sample is a PNG, so JPG and TIFF are both showing
    actions_page._replace_action("img-jpg", "img-tiff")
    after = _ring(actions_page)
    assert after.index("img-tiff") == before.index("img-jpg")
    assert after.index("img-jpg") == before.index("img-tiff") and len(after) == len(before)


def test_removing_a_wedge(actions_page):
    actions_page._remove_action("img-ico")
    assert "img-ico" not in _ring(actions_page)
    row = next(i for i in range(actions_page.action_list.count())
               if actions_page.action_list.item(i).data(Qt.UserRole) == "img-ico")
    assert actions_page.action_list.item(row).checkState() == Qt.Unchecked   # the list agrees


def test_clicking_a_wedge_in_the_preview_asks_what_to_put_there(actions_page, monkeypatch):
    shown = {}

    def fake_run(menu, _pos=None):
        shown["items"] = [a.text() for a in menu.actions() if a.text()]
        shown["held"] = actions_page.actions_preview.held

    monkeypatch.setattr(actions_page, "_run_menu", fake_run)
    wedge = next(w for w in actions_page.actions_preview.view.wedges if w.action.id == "img-gif")
    actions_page.actions_preview.wedge_clicked.emit(wedge, actions_page.mapToGlobal(actions_page.rect().center()))
    assert shown["items"][0] == "Replace “GIF” with" and shown["items"][-1] == "Remove from the ring"
    assert any(t.startswith("BMP") for t in shown["items"])                 # off-ring options are offered
    assert not any(t.startswith("Compress") for t in shown["items"])         # tools don't go on the Convert ring
    assert shown["held"] is wedge and actions_page.actions_preview.held is None
