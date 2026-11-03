"""The conversions added in 1.5: image formats, text/data, archives."""
import gzip
import io
import json
import subprocess
import tarfile
import zipfile

import pytest
from PIL import Image

from satsuma import actions
from satsuma.engine import archives, documents, images


@pytest.mark.parametrize("ext, pil_format", [(".avif", "AVIF"), (".heic", "HEIF"), (".bmp", "BMP")])
def test_new_image_formats(workdir, ext, pil_format):
    out = images.convert(workdir / "alpha.png", ext)
    with Image.open(out) as image:
        assert image.format == pil_format and image.size == (600, 400)
    back = images.convert(out, ".png")            # and they open again
    assert Image.open(back).size == (600, 400)


def test_image_ring_offers_new_formats(workdir):
    ids = {a.id for a in actions.actions_for([workdir / "photo.jpg"], customise=False)}
    assert {"img-avif", "img-heic", "img-bmp"} <= ids
    heic = images.convert(workdir / "photo.jpg", ".heic")
    assert "img-heic" not in {a.id for a in actions.actions_for([heic], customise=False)}


def test_bmp_is_hidden_until_switched_on(workdir):
    from satsuma.config import settings

    def ids():
        return {a.id for a in actions.actions_for([workdir / "photo.jpg"])}

    assert "img-bmp" not in ids()
    settings.set("actions_shown", ["image:img-bmp"])
    try:
        assert "img-bmp" in ids()
    finally:
        settings.set("actions_shown", [])


def test_markdown_html_text(qapp, tmp_path):
    md = tmp_path / "notes.md"
    md.write_text("# Title\n\nSome **bold** text\n\n- one\n- two\n", encoding="utf-8")
    html = documents.convert(md, ".html")
    assert "<b>" in html.read_text(encoding="utf-8") or "font-weight" in html.read_text(encoding="utf-8")
    txt = documents.convert(md, ".txt").read_text(encoding="utf-8")
    assert "Title" in txt and "**" not in txt
    page = tmp_path / "page.html"
    page.write_text("<h1>Hello</h1><p>A <i>small</i> page</p>", encoding="utf-8")
    back = documents.convert(page, ".md").read_text(encoding="utf-8")
    assert "# Hello" in back and "*small*" in back


def test_csv_json_round_trip(tmp_path):
    src = tmp_path / "people.csv"
    src.write_text("name;age\nAsha;31\nRavi;27\n", encoding="utf-8")       # ; separated is sniffed
    data = json.loads(documents.convert(src, ".json").read_text(encoding="utf-8"))
    assert data == [{"name": "Asha", "age": "31"}, {"name": "Ravi", "age": "27"}]

    nested = tmp_path / "items.json"
    nested.write_text(json.dumps({"items": [{"id": 1, "tags": ["a"]}, {"id": 2, "note": "x"}]}))
    rows = documents.convert(nested, ".csv").read_text(encoding="utf-8-sig").splitlines()
    assert rows[0] == "id,tags,note" and rows[1] == '1,"[""a""]",' and rows[2] == "2,,x"

    bad = tmp_path / "bad.json"
    bad.write_text("[1, 2, 3]")
    with pytest.raises(Exception, match="list of objects"):
        documents.convert(bad, ".csv")


def test_targets_without_office(monkeypatch):
    monkeypatch.setattr(documents, "libreoffice_path", lambda: None)
    monkeypatch.setattr(documents, "office_available", lambda kind: False)
    assert documents.can_convert(".md") == [".pdf", ".html", ".txt"]
    assert documents.can_convert(".json") == [".csv"]
    assert documents.can_convert(".csv") == [".json"]
    assert documents.can_convert(".docx") == []


def test_targets_with_microsoft_office(monkeypatch):
    monkeypatch.setattr(documents, "libreoffice_path", lambda: None)
    monkeypatch.setattr(documents, "office_available", lambda kind: True)
    assert documents.can_convert(".docx") == [".pdf", ".doc", ".rtf", ".odt", ".txt", ".html"]
    assert documents.can_convert(".csv") == [".json", ".pdf", ".xlsx", ".xls", ".ods"]
    assert documents.can_convert(".pptx") == [".pdf", ".ppt", ".odp"]
    assert ".docx" in documents.can_convert(".html")
    assert documents.can_convert(".epub") == []          # Word can't open EPUB


def _tar_gz(path, files):
    with tarfile.open(path, "w:gz") as tf:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))


def test_extract_tar_gz_and_single_gz(tmp_path):
    archive = tmp_path / "photos.tar.gz"
    _tar_gz(archive, {"a.txt": b"one", "sub/b.txt": b"two"})
    assert archives.can_extract(archive)
    folder = archives.extract(archive)
    assert folder.name == "photos" and (folder / "sub" / "b.txt").read_bytes() == b"two"

    single = tmp_path / "log.txt.gz"
    single.write_bytes(gzip.compress(b"hello"))
    out = archives.extract(single)
    assert out.name == "log.txt" and out.read_bytes() == b"hello"


def test_extract_refuses_escaping_paths(tmp_path):
    evil = tmp_path / "evil.tar.gz"
    _tar_gz(evil, {"../outside.txt": b"x"})
    with pytest.raises(Exception):
        archives.extract(evil)
    assert not (tmp_path / "outside.txt").exists()
    assert not (tmp_path / "evil").exists()                 # no half-made folder left

    zipped = tmp_path / "evil.zip"
    with zipfile.ZipFile(zipped, "w") as zf:
        zf.writestr("../outside.txt", "x")
    with pytest.raises(ValueError):
        archives.extract(zipped)
    assert not (tmp_path / "outside.txt").exists()


@pytest.mark.skipif(archives._bsdtar() is None, reason="Windows bsdtar not available")
def test_extract_7z(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "hello.txt").write_text("hi")
    archive = tmp_path / "bundle.7z"
    subprocess.run([str(archives._bsdtar()), "--format", "7zip", "-cf", str(archive), "-C",
                    str(tmp_path / "src"), "hello.txt"], check=True, creationflags=0x08000000)
    assert archives.can_extract(archive)
    assert {a.id for a in actions.actions_for([archive], customise=False)} >= {"zip-extract"}
    folder = archives.extract(archive)
    assert (folder / "hello.txt").read_text() == "hi"
