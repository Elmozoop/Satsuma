"""Regenerate the README images in docs/ (run from the project root):

    .venv\\Scripts\\python.exe tools\\make_screenshots.py

Everything is drawn by Satsuma's own code with throwaway settings, so the pictures always match
the app. Writes demo.webp, menu.png, cards.png, prompt.png, settings.png and watch.png.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["LOCALAPPDATA"] = tempfile.mkdtemp(prefix="satsuma-shots-")   # never the real settings
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw  # noqa: E402
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)

from satsuma.config import settings  # noqa: E402
from satsuma.engine import images  # noqa: E402
from satsuma.ui import prompts  # noqa: E402
from satsuma.ui.radial import RadialView, Wedge  # noqa: E402
from satsuma.ui.settings_window import WATCH_PAGE, SettingsWindow  # noqa: E402
from satsuma.ui.toast import Toasts  # noqa: E402

DOCS = ROOT / "docs"
WORK = Path(tempfile.mkdtemp(prefix="satsuma-shot-files-"))
FPS = 30           # an animated WebP keeps every frame's timing and full colour: smooth playback


def frames_for(seconds: float) -> int:
    return max(1, round(seconds * FPS))


def ease(t: float) -> float:
    """Ease in and out, the way a hand moves a mouse."""
    return t * t * (3 - 2 * t)


def spin(ms: int) -> None:
    QTimer.singleShot(ms, lambda: app.exit(0))
    app.exec()


def sample_photo() -> Path:
    """A made-up sunset, so the pictures carry no one's real photo."""
    image = Image.new("RGB", (1600, 1100))
    draw = ImageDraw.Draw(image)
    for y in range(1100):
        t = y / 1100
        draw.line((0, y, 1600, y), fill=(int(40 + 200 * t), int(70 + 60 * t), int(150 - 80 * t)))
    draw.ellipse((620, 330, 980, 690), fill=(255, 196, 90))
    draw.polygon([(0, 1100), (520, 640), (1000, 1100)], fill=(34, 40, 66))
    draw.polygon([(600, 1100), (1120, 560), (1600, 1100)], fill=(48, 50, 82))
    # Real photos have grain; without it the PNG is unrealistically small next to the WEBP.
    grain = Image.effect_noise((1600, 1100), 28).convert("RGB")
    image = Image.blend(image, grain, 0.12)
    path = WORK / "Holiday.png"
    image.save(path)
    return path


def backdrop(painter: QPainter, width: int, height: int, dark: bool = True) -> None:
    gradient = QLinearGradient(0, 0, width, height)
    gradient.setColorAt(0, QColor(46, 58, 92) if dark else QColor(214, 228, 248))
    gradient.setColorAt(1, QColor(24, 26, 38) if dark else QColor(240, 212, 196))
    painter.fillRect(QRectF(0, 0, width, height), gradient)


def draw_cursor(painter: QPainter, at: QPointF, carrying: Path | None) -> None:
    """An arrow pointer, with the dragged file's picture under it (as Explorer shows a drag)."""
    if carrying is not None:
        from satsuma.ui.thumbs import thumbnail

        tile = QRectF(at.x() + 10, at.y() + 14, 58, 40)
        clip = QPainterPath()
        clip.addRoundedRect(tile, 5, 5)
        painter.save()
        painter.setOpacity(0.9)
        painter.setClipPath(clip)
        picture = thumbnail(carrying, 120)
        if picture is not None:
            painter.drawImage(tile, picture)
        painter.restore()
        painter.setPen(QPen(QColor(255, 255, 255, 220), 1.5))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(clip)
    arrow = QPainterPath()
    for i, (x, y) in enumerate(((0, 0), (0, 17), (4.5, 13), (8, 20), (10.5, 19), (7, 12.5), (12.5, 12.5))):
        (arrow.moveTo if i == 0 else arrow.lineTo)(at.x() + x, at.y() + y)
    arrow.closeSubpath()
    painter.setPen(QPen(QColor(20, 20, 24), 1.3))
    painter.setBrush(QColor(255, 255, 255))
    painter.drawPath(arrow)


# ----------------------------------------------------------------------------- demo.webp
def demo_animation(photo: Path) -> None:
    width, height = 640, 480
    settings.set("menu_scale", 1.0)
    view = RadialView()
    view.set_paths([photo], animate=True)
    centre = QPointF(width / 2 - 50, height / 2 - 10)
    toasts = Toasts()
    out = images.convert(photo, ".webp")
    frames: list[QImage] = []
    cursor = QPointF(60, 430)
    dt = 1 / FPS

    def frame(carrying=True, card=False) -> None:
        image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        backdrop(painter, width, height)
        view.paint(painter, centre)
        if card:
            toasts._frame(dt)
            shot = QImage(toasts.size(), QImage.Format_ARGB32_Premultiplied)
            shot.fill(Qt.transparent)
            toasts.render(shot)
            painter.drawImage(QRectF(width - shot.width() - 4, height - shot.height() - 4,
                                     shot.width(), shot.height()), shot)
        draw_cursor(painter, cursor, photo if carrying else None)
        painter.end()
        frames.append(image)

    # 1. drag the file in (Shift held), the ring springs open under the cursor
    steps = frames_for(0.8)
    for i in range(steps):
        t = ease((i + 1) / steps)
        cursor = QPointF(60 + (centre.x() - 60) * t, 430 + (centre.y() - 430) * t)
        frame()
    view.open(animate=True)
    for _ in range(frames_for(0.7)):
        view.tick(dt)
        frame()
    # 2. glide across a few wedges
    wedges = view.page_wedges()
    route = [wedges[i % len(wedges)] for i in (6, 7, 0, 1)]
    for wedge in route:
        start, end = cursor, view.wedge_center(wedge, centre)
        steps = frames_for(0.42)
        for i in range(steps):
            t = ease((i + 1) / steps)
            cursor = QPointF(start.x() + (end.x() - start.x()) * t, start.y() + (end.y() - start.y()) * t)
            target = view.hit(cursor, centre)
            view.set_hover(target if isinstance(target, Wedge) else None)
            view.tick(dt)
            frame()
        for _ in range(frames_for(0.3)):
            view.tick(dt)
            frame()
    # 3. drop on WEBP: the tick, then the ring closes and the card arrives
    chosen = route[-1]
    view.confirm_choice(chosen)
    for _ in range(frames_for(0.3)):
        view.tick(dt)
        frame(carrying=False)
    view.close()
    toasts.started(1, f"{chosen.action.label} · {chosen.action.caption}", photo.name)
    toasts.sources(1, [str(photo)])
    toasts.progress(1, 0.6, "60%")
    for _ in range(frames_for(0.5)):
        view.tick(dt)
        frame(carrying=False, card=True)
    toasts.finished(1, [str(out)])
    for _ in range(frames_for(1.8)):
        view.tick(dt)
        frame(carrying=False, card=True)

    def to_pil(frame_image: QImage) -> Image.Image:
        rgba = frame_image.convertToFormat(QImage.Format_RGBA8888)   # keep it alive while copying its pixels
        return Image.frombytes("RGBA", (rgba.width(), rgba.height()), bytes(rgba.constBits()),
                               "raw", "RGBA", rgba.bytesPerLine()).convert("RGB")

    # Merge identical neighbours ourselves, adding up their time: left to the encoder, merged frames
    # lose their duration and the animation jumps.
    pil: list[Image.Image] = []
    durations: list[int] = []
    previous = None
    for f in frames:
        image = to_pil(f)
        data = image.tobytes()
        if data == previous:
            durations[-1] += round(1000 / FPS)
            continue
        pil.append(image)
        durations.append(round(1000 / FPS))
        previous = data
    durations[-1] += 1600                      # rest on the finished card before looping
    pil[0].save(DOCS / "demo.webp", save_all=True, append_images=pil[1:], duration=durations, loop=0,
                quality=82, method=6, minimize_size=False, allow_mixed=False)
    toasts.hide()
    settings.set("menu_scale", 1.0)


# ----------------------------------------------------------------------------- stills
def menu_png(photo: Path) -> None:
    """The ring in both themes, resting over a photo with one wedge lit."""
    halves = []
    for theme in ("dark", "light"):
        settings.set("theme", theme)
        view = RadialView()
        view.set_paths([photo], animate=False)
        view.open(animate=False)
        view.opening.snap(1.0)
        side = view.side
        image = QImage(side, side, QImage.Format_ARGB32_Premultiplied)
        painter = QPainter(image)
        backdrop(painter, side, side, dark=theme == "dark")
        view.set_hover(view.page_wedges()[1])
        for _ in range(40):
            view.tick(1 / 60)
            view.paint(painter, QPointF(side / 2, side / 2))      # also loads the centre preview
        backdrop(painter, side, side, dark=theme == "dark")
        view.paint(painter, QPointF(side / 2, side / 2))
        painter.end()
        halves.append(image)
    both = QImage(halves[0].width() * 2, halves[0].height(), QImage.Format_ARGB32_Premultiplied)
    painter = QPainter(both)
    painter.drawImage(0, 0, halves[0])
    painter.drawImage(halves[0].width(), 0, halves[1])
    painter.end()
    both.save(str(DOCS / "menu.png"))
    settings.set("theme", "dark")


def cards_png(photo: Path) -> None:
    toasts = Toasts()
    out = images.compress(photo)
    toasts.started(1, "Compress · smaller file", photo.name)
    toasts.sources(1, [str(photo)])
    toasts.finished(1, [str(out)])
    clip = WORK / "Lecture.mp4"
    clip.write_bytes(b"\0" * 180_000_000)
    toasts.started(2, "Compress · 1080p max", clip.name)
    toasts.sources(2, [str(clip)])
    toasts.progress(2, 0.42, "42%")
    spin(1400)
    image = QImage(toasts.size(), QImage.Format_ARGB32_Premultiplied)
    painter = QPainter(image)
    backdrop(painter, image.width(), image.height())
    painter.end()
    toasts.render(image)
    image.save(str(DOCS / "cards.png"))
    toasts.hide()


def window_png(widget, path: Path, wait: int = 900) -> None:
    widget.move(-4000, 0)
    widget.show()
    spin(wait)
    widget.grab().save(str(path))
    widget.close()
    widget.deleteLater()
    spin(100)


def main() -> None:
    settings.set("theme", "dark")
    photo = sample_photo()
    demo_animation(photo)
    menu_png(photo)
    cards_png(photo)
    window_png(prompts.ResizePrompt([photo]), DOCS / "prompt.png", 400)
    window_png(SettingsWindow(), DOCS / "settings.png", 1300)
    settings.set("watch_rules", [
        {"folder": str(Path.home() / "Pictures" / "Screenshots"), "action": "img-webp", "enabled": True},
        {"folder": str(Path.home() / "Documents" / "Scans"), "action": "pdf-compress", "enabled": True}])
    window = SettingsWindow()
    window.nav.setCurrentRow(WATCH_PAGE)
    window_png(window, DOCS / "watch.png", 400)
    for name in ("demo.webp", "menu.png", "cards.png", "prompt.png", "settings.png", "watch.png"):
        print(f"{name:<13} {(DOCS / name).stat().st_size / 1024:7.0f} KB")


if __name__ == "__main__":
    main()
