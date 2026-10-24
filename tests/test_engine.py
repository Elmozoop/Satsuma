import subprocess
import zipfile

import pytest
from PIL import Image
from pypdf import PdfReader

from satsuma.engine import archives, documents, images, pdfs
from satsuma.engine import ffmpeg_tool as ff

needs_ffmpeg = pytest.mark.skipif(not ff.available(), reason="ffmpeg not installed")


@pytest.mark.parametrize("ext", [".png", ".jpg", ".webp", ".bmp", ".tiff", ".gif", ".ico", ".pdf"])
def test_image_convert(workdir, ext):
    out = images.convert(workdir / "alpha.png", ext)
    assert out.exists() and out.suffix == ext and out.stat().st_size > 0


def test_image_tools(workdir):
    assert Image.open(images.resize(workdir / "photo.jpg", scale=0.5)).size == (400, 300)
    assert Image.open(images.resize(workdir / "photo.jpg", width=320)).size == (320, 240)
    assert Image.open(images.rotate(workdir / "photo.jpg", 90)).size == (600, 800)
    assert images.compress(workdir / "alpha.png").suffix == ".webp"  # keeps transparency
    pdf = images.to_pdf([workdir / "alpha.png", workdir / "photo.jpg"])
    assert len(PdfReader(str(pdf)).pages) == 2


def test_never_overwrites_by_default(workdir):
    a = images.convert(workdir / "photo.jpg", ".png")
    b = images.convert(workdir / "photo.jpg", ".png")
    assert a != b and a.exists() and b.exists()


def test_pdf_ops(workdir):
    pages = [Image.effect_noise((1600, 1200), 60).convert("RGB") for _ in range(3)]
    src = workdir / "doc.pdf"
    pages[0].save(src, "PDF", save_all=True, append_images=pages[1:])
    assert len(PdfReader(str(pdfs.merge([src, workdir / "photo.jpg", src]))).pages) == 7
    assert len(pdfs.split_pages(src)) == 3
    assert len(PdfReader(str(pdfs.extract_range(src, 2, 3))).pages) == 2
    assert PdfReader(str(pdfs.rotate(src, 90))).pages[0].rotation == 90
    assert len(pdfs.to_images(src, ".png", dpi=50)) == 3
    small = pdfs.compress(src)
    assert small.stat().st_size < src.stat().st_size


def test_text_to_pdf(qapp, tmp_path):
    (tmp_path / "n.md").write_text("# Title\n\nBody **bold**\n", encoding="utf-8")
    (tmp_path / "u.txt").write_text("hello world\n" * 50, encoding="utf-16")
    md = PdfReader(str(documents.convert(tmp_path / "n.md", ".pdf"))).pages[0].extract_text()
    assert "Title" in md and "**" not in md
    txt = PdfReader(str(documents.convert(tmp_path / "u.txt", ".pdf"))).pages[0].extract_text()
    assert "hello world" in " ".join(txt.split())


@pytest.mark.skipif(documents.libreoffice_path() is None, reason="LibreOffice not installed")
def test_libreoffice(qapp, tmp_path):
    (tmp_path / "p.html").write_text("<h1>Hi</h1>", encoding="utf-8")
    docx = documents.convert(tmp_path / "p.html", ".docx")
    assert zipfile.is_zipfile(docx)
    assert "Hi" in PdfReader(str(documents.convert(docx, ".pdf"))).pages[0].extract_text()


def test_zip_roundtrip_and_traversal(workdir):
    z = archives.zip_files([workdir / "alpha.png", workdir / "photo.jpg"])
    assert sorted(zipfile.ZipFile(z).namelist()) == ["alpha.png", "photo.jpg"]
    assert (archives.extract(z) / "photo.jpg").exists()
    evil = workdir / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../../escape.txt", "x")
    with pytest.raises(ValueError):
        archives.extract(evil)


@needs_ffmpeg
def test_media(tmp_path):
    from satsuma.engine import media

    exe = str(ff.ffmpeg_path())
    clip = tmp_path / "clip.mkv"
    subprocess.run([exe, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=641x361:rate=25:duration=3",
                    "-f", "lavfi", "-i", "sine=f=440:duration=3", "-c:v", "libx264", "-pix_fmt", "yuv444p",
                    "-c:a", "aac", "-shortest", str(clip)], check=True)
    for ext in (".mp4", ".webm"):
        assert media.convert_video(clip, ext).exists()
    assert abs(ff.duration_of(media.trim(clip, 1.0, 2.0)) - 1.0) < 0.2
    assert not ff.has_audio(media.mute(clip))
    assert media.extract_audio(clip, ".mp3").exists()
    assert media.to_gif(clip, width=160).exists()
    assert media.concat([clip, clip]).exists()
