"""Satsuma 1.11: copy text from pictures, even out volume, batch rename."""
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from satsuma import actions
from satsuma.engine import media, rename


# ----------------------------------------------------------------------------- text from pictures
@pytest.mark.skipif(sys.platform != "win32", reason="Windows OCR")
def test_copy_text_from_a_picture(tmp_path):
    from satsuma.engine import ocr

    picture = tmp_path / "note.png"
    image = Image.new("RGB", (1100, 300), "white")
    font = ImageFont.truetype(r"C:\Windows\Fonts\segoeui.ttf", 54)
    draw = ImageDraw.Draw(image)
    draw.text((30, 30), "Invoice 4471", fill="black", font=font)
    draw.text((30, 140), "Due on Friday", fill="black", font=font)
    image.save(picture)
    out = ocr.to_text(picture)
    text = out.read_text(encoding="utf-8")
    assert out.name == "note.txt" and "Invoice 4471" in text and "Friday" in text


@pytest.mark.skipif(sys.platform != "win32", reason="Windows OCR")
def test_a_picture_without_text_says_so(tmp_path):
    from satsuma.engine import ocr
    from satsuma.engine.ffmpeg_tool import ConversionError

    blank = tmp_path / "sky.png"
    Image.new("RGB", (600, 400), (90, 160, 230)).save(blank)
    with pytest.raises(ConversionError, match="No text"):
        ocr.to_text(blank)


# ----------------------------------------------------------------------------- even out volume
def test_level_builds_the_right_command(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(media.ff, "run", lambda args, **_k: calls.append(args))
    monkeypatch.setattr(media.ff, "has_audio", lambda _p: True)
    song = tmp_path / "talk.mp3"
    song.write_bytes(b"x")
    out = media.normalize_volume(song)
    assert out.name == "talk-levelled.mp3" and media.LOUDNORM in calls[-1] and "-vn" in calls[-1]
    clip = tmp_path / "lecture.mp4"
    clip.write_bytes(b"x")
    out = media.normalize_volume(clip)
    args = calls[-1]
    assert out.name == "lecture-levelled.mp4"
    assert args[args.index("-c:v") + 1] == "copy"            # the picture is untouched


def test_level_refuses_a_silent_video(tmp_path, monkeypatch):
    monkeypatch.setattr(media.ff, "has_audio", lambda _p: False)
    clip = tmp_path / "silent.mp4"
    clip.write_bytes(b"x")
    with pytest.raises(ValueError, match="no sound"):
        media.normalize_volume(clip)


# ----------------------------------------------------------------------------- batch rename
def _files(folder: Path, names):
    for name in names:
        (folder / name).write_text(name)
    return [folder / n for n in names]


def test_rename_plan_numbers_in_file_name_order(tmp_path):
    files = _files(tmp_path, ["IMG_10.jpg", "IMG_2.jpg", "IMG_1.png"])
    steps = rename.plan(files, "Trip ##")
    assert [(a.name, b.name) for a, b in steps] == [("IMG_1.png", "Trip 01.png"), ("IMG_2.jpg", "Trip 02.jpg"),
                                                     ("IMG_10.jpg", "Trip 03.jpg")]
    assert [b.name for _a, b in rename.plan(files, "Beach", start=9)] == ["Beach 09.png", "Beach 10.jpg",
                                                                          "Beach 11.jpg"]
    with pytest.raises(ValueError, match="can't contain"):
        rename.plan(files, "a/b")


def test_rename_and_undo(tmp_path):
    files = _files(tmp_path, ["a.txt", "b.txt"])
    out = rename.rename(files, "Note #")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["Note 1.txt", "Note 2.txt"]
    assert (tmp_path / "Note 1.txt").read_text() == "a.txt"              # contents follow their file
    assert rename.can_undo(out) and rename.undo(out)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.txt", "b.txt"]


def test_rename_handles_names_swapping_within_the_batch(tmp_path):
    files = _files(tmp_path, ["File 2.txt", "File 1.txt"])
    rename.rename(files, "File #", start=2)          # File 1 -> File 2 while File 2 -> File 3
    assert {p.name: p.read_text() for p in tmp_path.iterdir()} == {"File 2.txt": "File 1.txt",
                                                                   "File 3.txt": "File 2.txt"}


def test_rename_wont_overwrite_another_file(tmp_path):
    files = _files(tmp_path, ["a.txt", "b.txt"])
    (tmp_path / "Doc 1.txt").write_text("keep me")
    with pytest.raises(ValueError, match="already exists"):
        rename.rename(files, "Doc #")
    assert (tmp_path / "Doc 1.txt").read_text() == "keep me" and (tmp_path / "a.txt").exists()


def test_rename_prompt_previews_the_new_names(qapp, tmp_path):
    from satsuma.ui.prompts import RenamePrompt

    files = _files(tmp_path, ["IMG_001.jpg", "IMG_002.jpg"])
    dialog = RenamePrompt(files)
    assert dialog.name.text() == "IMG ##"
    dialog.name.setText("Holiday ##")
    assert "IMG_001.jpg  →  Holiday 01.jpg" in dialog.preview.text()
    assert dialog.validate() is None and dialog.result_params == {"pattern": "Holiday ##", "start": 1}
    dialog.name.setText("bad:name")
    assert dialog.validate() and "can't contain" in dialog.preview.text()
    dialog.close()


def test_card_undo_puts_names_back(qapp, tmp_path):
    from satsuma.ui.toast import Toasts

    files = _files(tmp_path, ["x.txt", "y.txt"])
    out = rename.rename(files, "Renamed #")
    toasts = Toasts()
    toasts.started(1, "Rename", "2 files")
    toasts.finished(1, [str(o) for o in out])
    toasts._undo(toasts._card(1))
    assert toasts._card(1).message == "Old names put back"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["x.txt", "y.txt"]   # nothing went to the bin
    toasts.hide()


# ----------------------------------------------------------------------------- the rings
def test_new_tools_appear_and_rings_still_fit(workdir, tmp_path):
    from satsuma.config import settings

    per_ring = int(settings.get("wedges_per_ring"))
    photo = {a.id: a.group for a in actions.actions_for([workdir / "photo.jpg"])}
    assert "img-text" in photo and "img-flip" not in photo                # Flip is off by default now
    assert sum(g == "tools" for g in photo.values()) <= per_ring
    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"x")
    video = {a.id: a.group for a in actions.actions_for([clip])}
    assert "vid-level" in video and "vid-rotate" not in video
    assert sum(g == "tools" for g in video.values()) <= per_ring
    assert "any-rename" not in {a.id for a in actions.actions_for([workdir / "photo.jpg"])}   # needs 2+
    both = [workdir / "photo.jpg", workdir / "alpha.png"]
    assert "any-rename" in {a.id for a in actions.actions_for(both)}


def test_self_test_passes_from_source(qapp, tmp_path):
    """The same checks the built exe runs with --self-test."""
    from satsuma.selftest import run

    report = tmp_path / "selftest.txt"
    assert run(report) == 0, report.read_text(encoding="utf-8")
    assert '"failed": 0' in report.read_text(encoding="utf-8")
