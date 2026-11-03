"""Satsuma 1.6: new tools, Recent, clipboard, dragging results, watched folders."""
import time
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter

from conftest import pump
from satsuma import actions, history
from satsuma.config import settings
from satsuma.engine import ffmpeg_tool as ff
from satsuma.engine import images, media, pdfs


def _wait(qapp, condition, seconds=15.0):
    end = time.time() + seconds
    while time.time() < end and not condition():
        pump(qapp, 50)
    return condition()


# ----------------------------------------------------------------------------- image tools
def test_clean_removes_location_and_camera(tmp_path):
    photo = tmp_path / "trip.jpg"
    image = Image.new("RGB", (400, 300), (10, 120, 200))
    exif = image.getexif()
    exif[0x010F] = "PhoneMaker"
    exif[0x8825] = {1: "N", 2: (28.0, 36.0, 50.0), 3: "E", 4: (77.0, 12.0, 30.0)}
    image.save(photo, exif=exif)
    clean = images.strip_metadata(photo)
    with Image.open(clean) as out:
        assert len(out.getexif()) == 0 and out.size == (400, 300)

    sideways = tmp_path / "sideways.jpg"
    image = Image.new("RGB", (400, 200))
    exif = image.getexif()
    exif[0x0112] = 6                      # "rotate 90° to display"
    image.save(sideways, exif=exif)
    assert Image.open(images.strip_metadata(sideways)).size == (200, 400)   # baked in, still upright


def test_black_and_white_and_square(workdir):
    bw = images.grayscale(workdir / "alpha.png")
    assert Image.open(bw).mode == "LA"                                       # transparency kept
    square = Image.open(images.pad_square(workdir / "alpha.png"))
    assert square.size == (600, 600) and square.getpixel((0, 0))[3] == 0   # transparent border
    flat = Image.open(images.pad_square(workdir / "photo.jpg"))
    assert flat.size == (800, 800) and flat.getpixel((400, 0)) == (255, 255, 255)


# ----------------------------------------------------------------------------- pdf tools
@pytest.fixture()
def pdf(tmp_path):
    writer = PdfWriter()
    writer.add_blank_page(595, 842)
    writer.add_blank_page(842, 595)
    writer.add_blank_page(595, 842).rotate(90)
    path = tmp_path / "doc.pdf"
    writer.write(str(path))
    return path


def test_page_numbers(qapp, pdf):
    numbered = PdfReader(str(pdfs.add_page_numbers(pdf)))
    assert [" ".join(p.extract_text().split()) for p in numbered.pages] == ["1 / 3", "2 / 3", "3 / 3"]


def test_lock_and_unlock(pdf):
    locked = pdfs.lock(pdf, "s3cret")
    assert pdfs.is_encrypted(locked) and not pdfs.is_encrypted(pdf)
    with pytest.raises(pdfs.PdfLocked, match="isn't right"):
        pdfs.unlock(locked, "nope")
    opened = pdfs.unlock(locked, "s3cret")
    assert not PdfReader(str(opened)).is_encrypted and len(PdfReader(str(opened)).pages) == 3
    with pytest.raises(ValueError, match="no password"):
        pdfs.unlock(pdf, "x")


def test_ring_offers_lock_or_unlock(pdf):
    plain = {a.id for a in actions.actions_for([pdf], customise=False)}
    assert "pdf-lock" in plain and "pdf-unlock" not in plain
    locked = pdfs.lock(pdf, "pw")
    assert [a.id for a in actions.actions_for([locked], customise=False)] == ["pdf-unlock", "any-zip"]


# ----------------------------------------------------------------------------- video tools
def test_speed_keeps_audio_pitch_filter_in_range():
    assert media.atempo_chain(2.0) == "atempo=2"
    assert media.atempo_chain(0.25) == "atempo=0.5,atempo=0.5"
    assert media.atempo_chain(4.0) == "atempo=2,atempo=2"
    assert media.atempo_chain(1.5) == "atempo=1.5"


@pytest.mark.skipif(not ff.available(), reason="ffmpeg not installed")
def test_video_tools(tmp_path):
    clip = tmp_path / "clip.mp4"
    ff.run(["-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=15", "-f", "lavfi",
            "-i", "sine=duration=2", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)])
    fast = media.change_speed(clip, 2.0)
    assert 0.8 <= ff.duration_of(fast) <= 1.3
    turned = media.rotate_video(clip)
    video = next(s for s in ff.probe(turned)["streams"] if s["codec_type"] == "video")
    assert (video["width"], video["height"]) == (240, 320)
    gif = media.boomerang(clip, seconds=1)
    assert Image.open(gif).n_frames > 15


# ----------------------------------------------------------------------------- recent
def test_recent_history(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "HISTORY_FILE", tmp_path / "recent.json")
    kept, gone = tmp_path / "a.webp", tmp_path / "b.webp"
    kept.write_text("x")
    gone.write_text("x")
    history.add("WEBP", [gone])
    history.add("WEBP", [kept])
    gone.unlink()
    assert [e["outputs"] for e in history.entries()] == [[str(kept)]]   # deleted results drop out
    for i in range(15):
        f = tmp_path / f"f{i}.png"
        f.write_text("x")
        history.add("PNG", [f])
    assert len(history.entries()) == history.KEEP
    history.clear()
    assert history.entries() == []
    assert history.ago(1000, now=1030) == "just now" and history.ago(0, now=7200) == "2 h ago"


# ----------------------------------------------------------------------------- dragging results
def test_finished_card_is_draggable_but_not_its_buttons(qapp, tmp_path):
    from satsuma.ui.toast import Toasts

    (tmp_path / "a.png").write_text("original")
    made = tmp_path / "a.webp"
    made.write_text("x")
    toasts = Toasts()
    toasts.started(1, "WEBP", "a.png")
    toasts.finished(1, [str(made)])
    toasts.repaint()
    pump(qapp, 600)
    card = toasts._card(1)
    body = card.rect.topLeft() + type(card.rect.topLeft())(40, 20)
    assert toasts._draggable(body) is card
    assert toasts._draggable(card.buttons[0][0].center()) is None
    toasts.hide()


# ----------------------------------------------------------------------------- clipboard
def test_convert_copied_picture(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QStandardPaths
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication

    import satsuma.app as app_module

    monkeypatch.setattr(QStandardPaths, "writableLocation", staticmethod(lambda _kind: str(tmp_path)))
    monkeypatch.setattr(app_module, "setup_logging", lambda: None)
    satsuma = app_module.Satsuma(qapp)
    opened = []
    monkeypatch.setattr(satsuma.menu, "open_for", lambda paths, _pos=None: opened.append(paths))
    picture = QImage(120, 80, QImage.Format_ARGB32)
    picture.fill(0xFF3366CC)
    QApplication.clipboard().setImage(picture)
    assert satsuma._clipboard_contents() == "image"
    satsuma.convert_clipboard()
    assert len(opened) == 1 and opened[0][0].parent == tmp_path / "Satsuma clipboard"
    assert Image.open(opened[0][0]).size == (120, 80)
    satsuma.detector.stop()
    satsuma.watcher.stop()
    satsuma.tray.hide()


# ----------------------------------------------------------------------------- watched folders
def test_watched_folder_converts_only_new_files_and_never_loops(qapp, tmp_path):
    from satsuma.jobs import JobRunner
    from satsuma.watcher import FolderWatcher

    folder = tmp_path / "Screenshots"
    folder.mkdir()
    Image.new("RGB", (64, 64), (200, 0, 0)).save(folder / "old.png")      # there before: left alone
    settings.set("watch_rules", [{"folder": str(folder), "action": "img-compress", "enabled": True}])
    runner = JobRunner()
    watcher = FolderWatcher(runner)
    try:
        Image.new("RGB", (64, 64), (0, 200, 0)).save(folder / "new.png")
        assert _wait(qapp, lambda: (folder / "new-compressed.jpg").exists())
        pump(qapp, 4000)    # long enough for a loop to show: "new-compressed.jpg" must not be compressed again
        assert sorted(p.name for p in folder.iterdir()) == ["new-compressed.jpg", "new.png", "old.png"]
    finally:
        watcher.stop()
        settings.set("watch_rules", [])


def test_watch_rules_only_offer_unattended_actions():
    from satsuma.watcher import describe, watchable_actions

    ids = {action.id for _label, _cat, action in watchable_actions()}
    assert "img-webp" in ids and "pdf-numbers" in ids
    assert not ids & {"img-resize", "vid-trim", "pdf-lock", "vid-speed", "pdf-merge"}   # need answers or 2+ files
    assert describe("img-webp").startswith("Images: WEBP")


def test_settings_watch_page_add_and_remove(qapp, tmp_path):
    from satsuma.ui.settings_window import WATCH_PAGE, SettingsWindow

    settings.set("watch_rules", [{"folder": str(tmp_path), "action": "img-webp", "enabled": True}])
    window = SettingsWindow()
    try:
        window._edit_rule(0, enabled=False)
        assert settings.get("watch_rules")[0]["enabled"] is False
        window._edit_rule(0, remove=True)
        assert settings.get("watch_rules") == []
        assert window.stack.currentIndex() == WATCH_PAGE
    finally:
        settings.set("watch_rules", [])
        window.close()


def test_dragging_a_card_hands_over_the_file(qapp, workdir, monkeypatch):
    """The drag itself must start (1.6 failed silently here: an error while making the drag image)."""
    from PySide6.QtGui import QDrag

    from satsuma.engine import images as image_engine
    from satsuma.ui.toast import Toasts

    out = image_engine.convert(workdir / "photo.jpg", ".webp")
    toasts = Toasts()
    toasts.started(1, "WEBP", "photo.jpg")
    toasts.finished(1, [str(out)])
    handed = {}

    def fake_exec(drag, action=None):
        handed["files"] = [Path(u.toLocalFile()) for u in drag.mimeData().urls()]
        handed["image"] = not drag.pixmap().isNull()
        return action

    monkeypatch.setattr(QDrag, "exec", fake_exec)
    toasts._start_drag(toasts._card(1))
    assert handed == {"files": [out], "image": True}
    toasts.hide()
