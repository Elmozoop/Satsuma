"""The first-run tour: eight short steps, each with a live illustration, and a practice ring
where you can try a drag without touching any real file.

Opens by itself the first time Satsuma starts; replay it from the tray menu or Settings → About.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QMimeData, QPoint, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QDrag, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget)

from .. import winutil
from ..config import settings
from ..explain import explain
from .controls import Segmented, Toggle, stylesheet
from .glass import glass_window, refresh_backdrop
from .icons import draw_icon
from .preview import RadialPreview
from .radial import Wedge
from .theme import palette, ui_font

PRACTICE_MIME = "application/x-satsuma-practice"


# ----------------------------------------------------------------------------- little pieces
def _label(text: str, name: str, wrap: bool = True) -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(wrap)
    label.setTextFormat(Qt.RichText)
    return label


def _sample_photo() -> Path:
    """A made-up sunset for the practice step (no one's real photo)."""
    from PIL import Image, ImageDraw

    path = Path(tempfile.mkdtemp(prefix="satsuma-tour-")) / "Holiday.jpg"
    image = Image.new("RGB", (480, 320))
    draw = ImageDraw.Draw(image)
    for y in range(320):
        draw.line((0, y, 480, y), fill=(int(40 + 190 * y / 320), int(80 + 60 * y / 320), int(160 - 70 * y / 320)))
    draw.ellipse((180, 90, 300, 210), fill=(255, 196, 90))
    draw.polygon([(0, 320), (170, 170), (330, 320)], fill=(34, 40, 66))
    image.save(path, quality=90)
    return path


class DragTile(QLabel):
    """The sample photo you drag onto the practice ring."""

    def __init__(self, photo: Path):
        super().__init__()
        self.photo = photo
        picture = QPixmap(str(photo)).scaled(132, 88, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.setPixmap(picture)
        self.setFixedSize(picture.width() + 8, picture.height() + 8)
        self.setAlignment(Qt.AlignCenter)
        self.setCursor(Qt.OpenHandCursor)
        self.setObjectName("thumb")
        self._press: QPoint | None = None

    def mousePressEvent(self, event) -> None:
        self._press = event.position().toPoint()

    def mouseMoveEvent(self, event) -> None:
        if self._press is None or (event.position().toPoint() - self._press).manhattanLength() < 4:
            return
        self._press = None
        mime = QMimeData()
        mime.setData(PRACTICE_MIME, str(self.photo).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(self.pixmap())
        drag.setHotSpot(QPoint(self.pixmap().width() // 2, self.pixmap().height() // 2))
        drag.exec(Qt.CopyAction)


class PracticeRing(RadialPreview):
    """A real ring that accepts the practice photo: hover to read what each wedge does, drop for
    a tick. Nothing is converted."""

    hovered = Signal(object)    # Action or None
    dropped = Signal(object)    # Action

    def __init__(self, photo: Path):
        super().__init__()
        self.setAcceptDrops(True)
        self.view.set_paths([photo])
        self.replay()

    def _wedge_at(self, pos) -> Wedge | None:
        target = self.view.hit(self._to_view(pos), QPointF(self.width() / 2, self.height() / 2))
        return target if isinstance(target, Wedge) else None

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(PRACTICE_MIME):
            self._user_hover = True
            self.view.glow.to(1.0)
            self.clock.start()
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        wedge = self._wedge_at(event.position())
        if wedge is not self.view.hover:
            self.view.set_hover(wedge)
            self.hovered.emit(wedge.action if wedge else None)
            self.clock.start()
        event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self.view.glow.to(0.0)
        self.view.set_hover(None)
        self.hovered.emit(None)
        self._user_hover = False
        self.clock.start()

    def dropEvent(self, event) -> None:
        self.view.glow.to(0.0)
        wedge = self._wedge_at(event.position())
        if wedge is None:
            event.ignore()
            return
        event.acceptProposedAction()
        self.view.confirm_choice(wedge)
        self.clock.start()
        self.dropped.emit(wedge.action)
        QTimer.singleShot(1400, self._settle)

    def _settle(self) -> None:
        self.view.chosen = None
        self.view.confirm.snap(0.0)
        self._user_hover = False
        self.view.set_hover(None)
        self.clock.start()


class KeyCap(QWidget):
    """A keyboard key drawn in the current style, with a drag arrow: "hold Shift while dragging"."""

    def sizeHint(self) -> QSize:
        return QSize(300, 90)

    def paintEvent(self, _event) -> None:
        pal = palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        key = QRectF(10, 14, 120, 62)
        painter.setPen(QPen(pal.border, 1.2))
        painter.setBrush(QColor(255, 255, 255, 30) if pal.text.lightness() > 128 else QColor(255, 255, 255, 230))
        painter.drawRoundedRect(key, 12, 12)
        painter.setPen(pal.text)
        painter.setFont(ui_font(15, QFont.DemiBold))
        painter.drawText(key, Qt.AlignCenter, "⇧ Shift")
        painter.setPen(pal.muted)
        painter.setFont(ui_font(20, QFont.DemiBold))
        painter.drawText(QRectF(130, 14, 40, 62), Qt.AlignCenter, "+")
        draw_icon(painter, "pointer", QPointF(200, 45), 34, pal.accent, 2.0)
        painter.setPen(QPen(pal.accent, 2.2, Qt.DashLine, Qt.RoundCap))
        painter.drawLine(QPointF(222, 45), QPointF(282, 45))
        draw_icon(painter, "ring", QPointF(282, 45), 30, pal.accent, 2.0)


def _card_picture(photo: Path) -> QPixmap:
    """A real result card, drawn by the card code itself."""
    from ..engine import images
    from .toast import Toasts

    out = images.convert(photo, ".webp")
    toasts = Toasts()
    toasts.started(1, "WEBP · small", photo.name)
    toasts.sources(1, [str(photo)])
    toasts.finished(1, [str(out)])
    for card in toasts.cards:
        card.appear.snap(1.0)
        card.slot.snap(0.0)
    toasts.resize(toasts.size())
    image = QImage(toasts.size(), QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    toasts.render(image)
    toasts.hide()
    toasts.deleteLater()
    return QPixmap.fromImage(image)


# ----------------------------------------------------------------------------- the tour
class Tutorial(QDialog):
    open_drop_window = Signal()

    def __init__(self):
        super().__init__(None)
        self.setWindowTitle("Welcome to Satsuma")
        self.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint | Qt.WindowStaysOnTopHint)
        glass_window(self, always=True)          # follows Glass/Solid live, even from step 7
        self.setFixedSize(820, 560)
        self.photo = _sample_photo()

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 20)
        root.setSpacing(14)
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        footer = QHBoxLayout()
        self.skip = QPushButton("Skip tour")
        self.skip.clicked.connect(self.finish)
        footer.addWidget(self.skip)
        footer.addStretch(1)
        self.dots = QLabel()
        self.dots.setObjectName("hint")
        footer.addWidget(self.dots)
        footer.addStretch(1)
        self.back = QPushButton("Back")
        self.back.clicked.connect(lambda: self.go(self.stack.currentIndex() - 1))
        self.next = QPushButton("Next")
        self.next.setObjectName("primary")
        self.next.setDefault(True)
        self.next.clicked.connect(self._next)
        footer.addWidget(self.back)
        footer.addWidget(self.next)
        root.addLayout(footer)

        for build in (self._welcome, self._shift, self._practice, self._rings, self._cards, self._tray,
                      self._yours, self._done):
            self.stack.addWidget(build())
        self.setStyleSheet(stylesheet())
        listener = self._on_setting
        settings.subscribe(listener)
        self.destroyed.connect(lambda *_a: settings.unsubscribe(listener))
        self.go(0)

    # ------------------------------------------------------------------ navigation
    def go(self, index: int) -> None:
        index = max(0, min(self.stack.count() - 1, index))
        self.stack.setCurrentIndex(index)
        last = index == self.stack.count() - 1
        self.back.setVisible(index > 0)
        self.skip.setVisible(not last)
        self.next.setText("Finish" if last else ("Show me" if index == 0 else "Next"))
        self.dots.setText("  ".join("●" if i == index else "○" for i in range(self.stack.count())))

    def _next(self) -> None:
        if self.stack.currentIndex() == self.stack.count() - 1:
            self.finish()
        else:
            self.go(self.stack.currentIndex() + 1)

    def finish(self) -> None:
        settings.set("tutorial_done", True)
        self.accept()

    def closeEvent(self, event) -> None:
        settings.set("tutorial_done", True)     # closing counts as "seen"; it's in the tray menu anyway
        super().closeEvent(event)

    def _on_setting(self, key: str) -> None:
        if key in ("style", "theme", "accent", "*"):
            self.setStyleSheet(stylesheet())
            refresh_backdrop(self)
            self.update()

    # ------------------------------------------------------------------ page scaffolding
    @staticmethod
    def _page(title: str, body: str, art: QWidget | None) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(26)
        text = QVBoxLayout()
        text.setSpacing(10)
        text.addStretch(1)
        text.addWidget(_label(title, "pageTitle"))
        text.addWidget(_label(body, "tourBody"))
        text.addStretch(2)
        layout.addLayout(text, 5)
        if isinstance(art, QFrame):        # a panel of rows: its natural height, centred
            layout.addWidget(art, 6, Qt.AlignVCenter)
        elif art is not None:
            layout.addWidget(art, 6)
        page.text_layout = text
        return page

    # ------------------------------------------------------------------ the eight steps
    def _welcome(self) -> QWidget:
        ring = RadialPreview()
        ring.setMinimumSize(340, 340)
        return self._page(
            "Welcome to Satsuma 🍊",
            "Satsuma turns files into the files you need with <b>one drag</b>: convert, compress, trim, "
            "merge, rename and more, without opening an app.<br><br>"
            "Everything happens <b>on your PC</b>. Your files are never uploaded, and your originals are "
            "never changed.<br><br>This tour takes about a minute.", ring)

    def _shift(self) -> QWidget:
        art = QWidget()
        column = QVBoxLayout(art)
        column.addStretch(1)
        column.addWidget(KeyCap(), alignment=Qt.AlignCenter)
        column.addWidget(_label("Drag a file from File Explorer or your desktop, then press <b>Shift</b> "
                                "while you're still dragging.", "hint"), alignment=Qt.AlignCenter)
        column.addStretch(1)
        return self._page(
            "Hold Shift while you drag",
            "Start dragging any file, then hold <b>Shift</b>. A ring of actions springs open right under "
            "your pointer. Let go on the one you want.<br><br>"
            "Prefer clicking?<br>• Right-click files → <b>Send to → Satsuma</b> (switch it on in Settings)<br>"
            "• Click the 🍊 by the clock for a <b>drop window</b> you can drag files onto, no Shift needed",
            art)

    def _practice(self) -> QWidget:
        art = QWidget()
        column = QVBoxLayout(art)
        column.setSpacing(8)
        self.practice = PracticeRing(self.photo)
        self.practice.setMinimumSize(330, 300)
        column.addWidget(self.practice, 1)
        self.practice_note = _label("Hover a wedge to see what it does.", "hint")
        self.practice_note.setAlignment(Qt.AlignCenter)
        self.practice_note.setMinimumHeight(54)
        column.addWidget(self.practice_note)
        page = self._page(
            "Try it here",
            "Drag this photo onto a wedge of the ring. (No Shift needed in here, and no file is changed.)",
            art)
        page.text_layout.insertWidget(page.text_layout.count() - 1, DragTile(self.photo),
                                      alignment=Qt.AlignLeft)
        self.practice.hovered.connect(self._practice_hover)
        self.practice.dropped.connect(self._practice_drop)
        return page

    def _practice_hover(self, action) -> None:
        if action is None:
            self.practice_note.setText("Hover a wedge to see what it does.")
            return
        title, body, _where = explain(action)
        self.practice_note.setText(f"<b>{title}</b><br>{body}")

    def _practice_drop(self, action) -> None:
        self.practice_note.setText(f"<b>✓ Nice!</b> For real, Satsuma would now make "
                                   f"<b>{action.label}</b> from your file and show a card in the corner.")

    def _rings(self) -> QWidget:
        ring = RadialPreview()
        ring.setMinimumSize(340, 340)
        return self._page(
            "Two rings: Convert and Tools",
            "<b>Convert</b> holds formats (PNG, PDF, MP4…). <b>Tools</b> holds actions like Compress, "
            "Resize, Trim, Lock or Text.<br><br>"
            "To swap, <b>rest your pointer on the centre</b> for a moment. The dots in the middle show "
            "which ring you're on.<br><br>Click the centre of this ring to try.<br><br>"
            "Rest on a wedge and an <b>info panel</b> says exactly what it will do.", ring)

    def _cards(self) -> QWidget:
        art = QLabel()
        art.setAlignment(Qt.AlignCenter)
        try:
            art.setPixmap(_card_picture(self.photo))
        except Exception:
            art.setText("")
        return self._page(
            "Your result, in the corner",
            "Each job shows a card in the bottom-right corner:<br><br>"
            "• <b>Cancel</b> while it's running<br>"
            "• <b>Open</b> or <b>Show in folder</b> when it's done, with how much smaller it got<br>"
            "• <b>Undo</b> sends the new file to the Recycle Bin<br>"
            "• <b>Drag the card</b> straight into WhatsApp, Discord, an email or a folder", art)

    def _tray(self) -> QWidget:
        art = QFrame()
        art.setObjectName("card")
        rows = QVBoxLayout(art)
        rows.setContentsMargins(18, 14, 18, 14)
        rows.setSpacing(10)
        colour = palette().text
        for icon, line in (("save", "Open drop window: drag files on, no Shift"),
                           ("pages", "Convert clipboard: copied files or pictures"),
                           ("folder", "Recent: your last 10 results"),
                           ("rotate", "Undo the last conversion"),
                           ("info", "Info panel beside wedges: on or off"),
                           ("gear", "Settings…  and this tour again")):
            row = QHBoxLayout()
            picture = QPixmap(48, 48)
            picture.setDevicePixelRatio(2.0)
            picture.fill(Qt.transparent)
            painter = QPainter(picture)
            painter.setRenderHint(QPainter.Antialiasing)
            draw_icon(painter, icon, QPointF(12, 12), 20, colour, 1.7)
            painter.end()
            glyph = QLabel()
            glyph.setPixmap(picture)
            row.addWidget(glyph)
            row.addWidget(_label(line, "rowTitle"), 1)
            rows.addLayout(row)
        return self._page(
            "The 🍊 in your tray",
            "Satsuma waits quietly by the clock. <b>Right-click</b> the orange for its menu, or "
            "<b>click</b> it to open the drop window.<br><br>"
            "If you don't see it, click the <b>^</b> arrow by the clock and drag the 🍊 onto the taskbar "
            "to keep it in view.", art)

    def _yours(self) -> QWidget:
        art = QFrame()
        art.setObjectName("card")
        rows = QVBoxLayout(art)
        rows.setContentsMargins(18, 16, 18, 16)
        rows.setSpacing(14)
        for title, control in (
                ("Style", self._bound(Segmented((("glass", "Glass"), ("solid", "Solid")), settings.get("style")),
                                      "style")),
                ("Theme", self._bound(Segmented((("system", "System"), ("light", "Light"), ("dark", "Dark")),
                                                settings.get("theme")), "theme")),
                ("Info panel beside wedges", self._bound(Toggle(bool(settings.get("explain_actions"))),
                                                         "explain_actions"))):
            row = QHBoxLayout()
            row.addWidget(_label(title, "rowTitle"), 1)
            row.addWidget(control)
            rows.addLayout(row)
        rows.addWidget(_label("More in <b>Settings</b>: accent colour, size and animation; <b>click any "
                              "wedge</b> in Ring actions to swap it for another; <b>Watched folders</b> that "
                              "convert new files automatically; where results are saved.", "hint"))
        return self._page(
            "Make it yours",
            "Try the styles: <b>Glass</b> is frosted and see-through, <b>Solid</b> is plain. "
            "Changes apply right away.", art)

    @staticmethod
    def _bound(control, key: str):
        if isinstance(control, Segmented):
            control.changed.connect(lambda v: settings.set(key, v))
        else:
            control.toggled.connect(lambda v: settings.set(key, v))
        return control

    def _done(self) -> QWidget:
        art = QFrame()
        art.setObjectName("card")
        rows = QVBoxLayout(art)
        rows.setContentsMargins(18, 16, 18, 16)
        rows.setSpacing(14)
        start = Toggle(winutil.autostart_enabled())
        start.toggled.connect(winutil.set_autostart)
        start.setEnabled(winutil.IS_WINDOWS)
        row = QHBoxLayout()
        row.addWidget(_label("Start Satsuma when I sign in", "rowTitle"), 1)
        row.addWidget(start)
        rows.addLayout(row)
        drop = QPushButton("Open the drop window and try it")
        drop.setObjectName("primary")
        drop.clicked.connect(lambda: (self.finish(), self.open_drop_window.emit()))
        rows.addWidget(drop)
        rows.addWidget(_label("You can replay this tour any time from the 🍊 menu → <b>Tour</b>.", "hint"))
        return self._page(
            "You're all set",
            "Next time you drag a file, hold <b>Shift</b>.<br><br>"
            "Your originals are never changed: new files are saved next to them, and <b>Undo</b> is "
            "always one click away.", art)
