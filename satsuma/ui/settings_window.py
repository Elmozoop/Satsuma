"""Settings: Look & feel (with live preview), Actions, Trigger & saving, Converters."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QThread, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QColorDialog, QComboBox,
                               QDialog, QFileDialog, QFormLayout, QGridLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QProgressBar, QPushButton, QSlider, QSpinBox, QTabWidget,
                               QToolButton, QVBoxLayout, QWidget)

from .. import winutil
from ..actions import catalogue
from ..config import BIN_DIR, VERSION, settings
from ..engine import documents
from ..engine import ffmpeg_tool as ff
from .icons import draw_icon
from .preview import RadialPreview
from .theme import ACCENT_PRESETS, readable_on

LOOK_KEYS = ["theme", "accent", "menu_scale", "glass_opacity", "anim_speed", "bounce", "show_icons",
             "show_captions", "hub_info", "wedges_per_ring", "hub_switch_ms", "start_page"]


class _FFmpegFetcher(QThread):
    progressed = Signal(float, str)
    done = Signal(bool, str)

    def run(self) -> None:
        try:
            ff.ensure(lambda f, m: self.progressed.emit(f, m))
            self.done.emit(True, "FFmpeg is ready.")
        except Exception as exc:  # shown to the user
            self.done.emit(False, str(exc))


def _combo(options, key: str) -> QComboBox:
    box = QComboBox()
    for value, label in options:
        box.addItem(label, value)
    box.setCurrentIndex(max(0, box.findData(settings.get(key))))
    box.currentIndexChanged.connect(lambda _i: settings.set(key, box.currentData()))
    return box


def _check(text: str, key: str) -> QCheckBox:
    box = QCheckBox(text)
    box.setChecked(bool(settings.get(key)))
    box.toggled.connect(lambda v: settings.set(key, v))
    return box


def _slider(key: str, low: int, high: int, factor: float = 1.0, suffix: str = "",
            live: bool = True) -> QWidget:
    """Slider bound to a setting. `factor` maps slider ints to the stored value."""
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    slider = QSlider(Qt.Horizontal)
    slider.setRange(low, high)
    slider.setValue(round(float(settings.get(key)) / factor))
    value = QLabel()
    value.setMinimumWidth(48)
    value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def show(v: int) -> None:
        value.setText(f"{v}{suffix}")

    def store(v: int) -> None:
        stored = v * factor
        settings.set(key, int(stored) if factor == 1.0 else round(stored, 3))

    show(slider.value())
    slider.valueChanged.connect(show)
    if live:
        slider.valueChanged.connect(store)
    else:
        slider.sliderReleased.connect(lambda: store(slider.value()))
        slider.valueChanged.connect(lambda v: None if slider.isSliderDown() else store(v))
    layout.addWidget(slider, 1)
    layout.addWidget(value)
    row.slider = slider
    return row


def _swatch_icon(color: QColor, selected: bool) -> QIcon:
    """A colour dot; a tick marks the current accent."""
    pixmap = QPixmap(56, 56)
    pixmap.setDevicePixelRatio(2.0)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(color)
    painter.drawEllipse(QRectF(3, 3, 22, 22))
    if selected:
        tick = readable_on(color)
        painter.setPen(QPen(tick, 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.setBrush(Qt.NoBrush)
        painter.drawPolyline([QPointF(9, 14.5), QPointF(12.5, 18), QPointF(19, 10.5)])
    painter.end()
    return QIcon(pixmap)


class SettingsWindow(QDialog):
    def __init__(self):
        super().__init__(None)
        self.setWindowTitle("Satsuma Settings")
        self.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint | Qt.WindowMinimizeButtonHint)
        self.resize(860, 600)
        root = QVBoxLayout(self)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs)
        self.tabs.addTab(self._look_tab(), "Look && feel")
        self.tabs.addTab(self._actions_tab(), "Actions")
        self.tabs.addTab(self._trigger_tab(), "Trigger && saving")
        self.tabs.addTab(self._converters_tab(), "Converters")
        footer = QLabel(f"Satsuma {VERSION}")
        footer.setStyleSheet("color:gray")
        root.addWidget(footer, alignment=Qt.AlignRight)
        self._fetcher: _FFmpegFetcher | None = None

    # ================================================================== Look & feel
    def _look_tab(self) -> QWidget:
        tab = QWidget()
        layout = QHBoxLayout(tab)

        left = QVBoxLayout()
        self.preview = RadialPreview()
        left.addWidget(self.preview, 1)
        controls = QHBoxLayout()
        self.preview_kind = QComboBox()
        for kind, label in (("image", "Preview: image"), ("video", "Preview: video"),
                            ("audio", "Preview: audio"), ("pdf", "Preview: PDF"),
                            ("document", "Preview: document")):
            self.preview_kind.addItem(label, kind)
        self.preview_kind.currentIndexChanged.connect(
            lambda _i: self.preview.set_kind(self.preview_kind.currentData()))
        replay = QPushButton("Replay")
        replay.clicked.connect(self.preview.replay)
        controls.addWidget(self.preview_kind, 1)
        controls.addWidget(replay)
        left.addLayout(controls)
        hint = QLabel("Hover the preview to try it. Click the centre to swap rings.")
        hint.setStyleSheet("color:gray")
        hint.setWordWrap(True)
        left.addWidget(hint)
        layout.addLayout(left, 5)

        right = QVBoxLayout()
        colours = QGroupBox("Colour")
        form = QFormLayout(colours)
        form.addRow("Theme", _combo((("system", "Match Windows"), ("dark", "Dark"), ("light", "Light")), "theme"))
        form.addRow("Accent", self._accent_picker())
        form.addRow("Glass", _slider("glass_opacity", 35, 100, 0.01, "%"))
        right.addWidget(colours)

        shape = QGroupBox("Shape")
        form = QFormLayout(shape)
        form.addRow("Size", _slider("menu_scale", 70, 150, 0.01, "%", live=False))
        spin = QSpinBox()
        spin.setRange(3, 10)
        spin.setValue(int(settings.get("wedges_per_ring")))
        spin.valueChanged.connect(lambda v: settings.set("wedges_per_ring", v))
        form.addRow("Wedges per ring", spin)
        form.addRow("First ring", _combo((("convert", "Convert"), ("tools", "Tools")), "start_page"))
        form.addRow(_check("Show icons on tool wedges", "show_icons"))
        right.addWidget(shape)

        motion = QGroupBox("Motion")
        form = QFormLayout(motion)
        form.addRow("Animation", _combo((("fast", "Fast"), ("normal", "Normal"), ("relaxed", "Relaxed"),
                                         ("off", "Off")), "anim_speed"))
        form.addRow(_check("Springy bounce", "bounce"))
        form.addRow("Hold centre to swap", _slider("hub_switch_ms", 150, 1500, 1.0, " ms"))
        right.addWidget(motion)

        centre = QGroupBox("Centre")
        form = QFormLayout(centre)
        form.addRow("Shows", _combo((("size", "File size"), ("name", "File name"), ("type", "File type")),
                                    "hub_info"))
        form.addRow(_check("Describe the action under the cursor", "show_captions"))
        right.addWidget(centre)

        reset = QPushButton("Reset look to defaults")
        reset.clicked.connect(self._reset_look)
        right.addWidget(reset, alignment=Qt.AlignRight)
        right.addStretch(1)
        layout.addLayout(right, 4)
        return tab

    def _accent_picker(self) -> QWidget:
        row = QWidget()
        grid = QGridLayout(row)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(2)
        self._swatches = QButtonGroup(row)
        self._swatches.setExclusive(True)
        for i, (name, hex_) in enumerate(ACCENT_PRESETS):
            button = QToolButton()
            button.setToolTip(name)
            button.setCheckable(True)
            button.setAutoRaise(True)
            button.setIconSize(QSize(28, 28))
            button.setProperty("hex", hex_)
            button.clicked.connect(lambda _c=False, h=hex_: self._set_accent(h))
            self._swatches.addButton(button)
            grid.addWidget(button, 0, i)
        custom = QToolButton()
        custom.setText("Custom…")
        custom.clicked.connect(self._custom_accent)
        grid.addWidget(custom, 0, len(ACCENT_PRESETS))
        self._custom_button = custom
        self._refresh_swatches()
        return row

    def _refresh_swatches(self) -> None:
        current = str(settings.get("accent")).upper()
        for button in self._swatches.buttons():
            hex_ = button.property("hex")
            selected = hex_.upper() == current
            button.setChecked(selected)
            button.setIcon(_swatch_icon(QColor(hex_), selected))
        is_custom = all(h.upper() != current for _n, h in ACCENT_PRESETS)
        self._custom_button.setIcon(_swatch_icon(QColor(current), True) if is_custom else QIcon())
        self._custom_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon if is_custom else Qt.ToolButtonTextOnly)

    def _set_accent(self, hex_: str) -> None:
        settings.set("accent", hex_.upper())
        self._refresh_swatches()

    def _custom_accent(self) -> None:
        colour = QColorDialog.getColor(QColor(str(settings.get("accent"))), self, "Accent colour")
        if colour.isValid():
            self._set_accent(colour.name())

    def _reset_look(self) -> None:
        settings.reset(LOOK_KEYS)
        # Rebuild the tab so every control shows the defaults again.
        index = self.tabs.currentIndex()
        self.tabs.removeTab(0)
        self.tabs.insertTab(0, self._look_tab(), "Look && feel")
        self.tabs.setCurrentIndex(index)

    # ================================================================== Actions
    def _actions_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        top = QHBoxLayout()
        top.addWidget(QLabel("When I drag"))
        self.action_kind = QComboBox()
        self._catalogue = catalogue()
        for category, label, _actions in self._catalogue:
            self.action_kind.addItem(label, category)
        self.action_kind.currentIndexChanged.connect(self._load_action_list)
        top.addWidget(self.action_kind)
        top.addStretch(1)
        layout.addLayout(top)

        body = QHBoxLayout()
        self.action_list = QListWidget()
        self.action_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.action_list.setDefaultDropAction(Qt.MoveAction)
        self.action_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.action_list.setIconSize(QSize(18, 18))
        self.action_list.itemChanged.connect(lambda _i: self._save_action_list())
        self.action_list.model().rowsMoved.connect(lambda *_a: self._save_action_list())
        body.addWidget(self.action_list, 1)

        buttons = QVBoxLayout()
        up = QPushButton("Move up")
        down = QPushButton("Move down")
        up.clicked.connect(lambda: self._move_selected(-1))
        down.clicked.connect(lambda: self._move_selected(1))
        reset = QPushButton("Reset this type")
        reset.clicked.connect(self._reset_action_list)
        for button in (up, down):
            buttons.addWidget(button)
        buttons.addStretch(1)
        buttons.addWidget(reset)
        body.addLayout(buttons)
        layout.addLayout(body, 1)

        note = QLabel("Tick what appears in the ring, drag to change the order. Convert actions and "
                      "tools sit on separate rings; rest on the centre while dragging to swap between them.")
        note.setWordWrap(True)
        note.setStyleSheet("color:gray")
        layout.addWidget(note)
        self._load_action_list()
        return tab

    def _current_actions(self):
        category = self.action_kind.currentData()
        for cat, _label, actions in self._catalogue:
            if cat == category:
                return category, actions
        return category, []

    def _load_action_list(self) -> None:
        category, actions = self._current_actions()
        hidden = set(settings.get("actions_hidden") or [])
        order = (settings.get("actions_order") or {}).get(category) or []
        rank = {a: i for i, a in enumerate(order)}
        ordered = sorted(actions, key=lambda a: (0, rank[a.id]) if a.id in rank else (1, actions.index(a)))
        self.action_list.blockSignals(True)
        self.action_list.clear()
        for action in ordered:
            ring = "Convert" if action.group == "convert" else "Tools"
            item = QListWidgetItem(f"{action.label}   —   {action.caption}   ·   {ring} ring")
            item.setData(Qt.UserRole, action.id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsDragEnabled)
            item.setFlags(item.flags() & ~Qt.ItemIsDropEnabled)
            item.setCheckState(Qt.Unchecked if f"{category}:{action.id}" in hidden else Qt.Checked)
            # Every row gets an icon (blank for format wedges) so rows line up.
            pixmap = QPixmap(36, 36)
            pixmap.setDevicePixelRatio(2.0)
            pixmap.fill(Qt.transparent)
            if action.icon:
                painter = QPainter(pixmap)
                painter.setRenderHint(QPainter.Antialiasing)
                draw_icon(painter, action.icon, QPointF(9, 9), 16, self.palette().text().color(), 1.6)
                painter.end()
            item.setIcon(QIcon(pixmap))
            item.setSizeHint(QSize(0, 30))
            self.action_list.addItem(item)
        self.action_list.blockSignals(False)

    def _save_action_list(self) -> None:
        category, actions = self._current_actions()
        ids = [self.action_list.item(i).data(Qt.UserRole) for i in range(self.action_list.count())]
        unchecked = {self.action_list.item(i).data(Qt.UserRole) for i in range(self.action_list.count())
                     if self.action_list.item(i).checkState() != Qt.Checked}
        hidden = [h for h in (settings.get("actions_hidden") or []) if not h.startswith(f"{category}:")]
        hidden += [f"{category}:{a}" for a in ids if a in unchecked]
        order = dict(settings.get("actions_order") or {})
        order[category] = ids
        settings.set("actions_order", order)
        settings.set("actions_hidden", hidden)

    def _move_selected(self, step: int) -> None:
        row = self.action_list.currentRow()
        target = row + step
        if row < 0 or not 0 <= target < self.action_list.count():
            return
        item = self.action_list.takeItem(row)
        self.action_list.insertItem(target, item)
        self.action_list.setCurrentRow(target)
        self._save_action_list()

    def _reset_action_list(self) -> None:
        category, _ = self._current_actions()
        hidden = [h for h in (settings.get("actions_hidden") or []) if not h.startswith(f"{category}:")]
        order = dict(settings.get("actions_order") or {})
        order.pop(category, None)
        settings.set("actions_order", order)
        settings.set("actions_hidden", hidden)
        self._load_action_list()

    # ================================================================== Trigger & saving
    def _trigger_tab(self) -> QWidget:
        tab = QWidget()
        root = QVBoxLayout(tab)

        trigger = QGroupBox("Trigger")
        form = QFormLayout(trigger)
        form.addRow(_check("Open the menu when I drag files with a modifier key held", "enabled"))
        form.addRow("Modifier key", _combo((("shift", "Shift"), ("ctrl", "Ctrl"), ("alt", "Alt")), "modifier"))
        form.addRow(_check("Only for real file drags (ignore text selection, window moves)", "smart_detect"))
        root.addWidget(trigger)

        output = QGroupBox("Saving")
        out_form = QFormLayout(output)
        self.mode = QComboBox()
        self.mode.addItem("Next to the original", "source")
        self.mode.addItem("In a subfolder next to the original", "subfolder")
        self.mode.addItem("In one folder I choose", "custom")
        self.mode.setCurrentIndex(max(0, self.mode.findData(settings.get("output_mode"))))
        out_form.addRow("Save results", self.mode)
        self.subfolder = QLineEdit(str(settings.get("output_subfolder")))
        self.subfolder.editingFinished.connect(
            lambda: settings.set("output_subfolder", self.subfolder.text().strip() or "Converted"))
        out_form.addRow("Subfolder name", self.subfolder)
        custom_row = QWidget()
        custom_layout = QHBoxLayout(custom_row)
        custom_layout.setContentsMargins(0, 0, 0, 0)
        self.custom = QLineEdit(str(settings.get("output_custom")))
        self.custom.setPlaceholderText("Choose a folder…")
        self.custom.editingFinished.connect(lambda: settings.set("output_custom", self.custom.text().strip()))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        custom_layout.addWidget(self.custom, 1)
        custom_layout.addWidget(browse)
        out_form.addRow("Folder", custom_row)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self._mode_changed()
        out_form.addRow(_check("Overwrite files with the same name (otherwise add “(1)”)", "overwrite"))
        out_form.addRow(_check("Show the result in File Explorer when done", "reveal_after"))
        root.addWidget(output)

        system = QGroupBox("Windows")
        s_form = QFormLayout(system)
        self.autostart = QCheckBox("Start Satsuma when I sign in")
        self.autostart.setChecked(winutil.autostart_enabled())
        self.autostart.toggled.connect(winutil.set_autostart)
        self.sendto = QCheckBox("Add “Satsuma” to the right-click Send to menu")
        self.sendto.setChecked(winutil.sendto_enabled())
        self.sendto.toggled.connect(self._sendto_toggled)
        if not winutil.IS_WINDOWS:
            self.autostart.setEnabled(False)
            self.sendto.setEnabled(False)
        s_form.addRow(self.autostart)
        s_form.addRow(self.sendto)
        root.addWidget(system)
        root.addStretch(1)
        return tab

    def _mode_changed(self) -> None:
        mode = self.mode.currentData()
        settings.set("output_mode", mode)
        self.subfolder.setEnabled(mode == "subfolder")
        self.custom.setEnabled(mode == "custom")

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Save converted files to", self.custom.text())
        if folder:
            self.custom.setText(folder)
            settings.set("output_custom", folder)

    def _sendto_toggled(self, enabled: bool) -> None:
        if not winutil.set_sendto(enabled):
            self.sendto.blockSignals(True)
            self.sendto.setChecked(winutil.sendto_enabled())
            self.sendto.blockSignals(False)

    # ================================================================== Converters
    def _converters_tab(self) -> QWidget:
        tab = QWidget()
        root = QVBoxLayout(tab)
        quality = QGroupBox("Quality")
        q_form = QFormLayout(quality)
        q_form.addRow("JPG / WEBP quality", _slider("jpeg_quality", 10, 100, live=False))
        q_form.addRow("Compress quality", _slider("compress_quality", 10, 100, live=False))
        root.addWidget(quality)

        engines = QGroupBox("Converters")
        e_layout = QVBoxLayout(engines)
        ff_row = QHBoxLayout()
        self.ff_label = QLabel()
        self.ff_button = QPushButton("Download FFmpeg")
        self.ff_button.clicked.connect(self._fetch_ffmpeg)
        ff_row.addWidget(self.ff_label, 1)
        ff_row.addWidget(self.ff_button)
        e_layout.addLayout(ff_row)
        self.ff_progress = QProgressBar()
        self.ff_progress.setRange(0, 1000)
        self.ff_progress.hide()
        e_layout.addWidget(self.ff_progress)
        lo = documents.libreoffice_path()
        office = any(documents.office_available(k) for k in ("word", "slides", "sheets"))
        doc_text = ("Documents: LibreOffice found" if lo else
                    "Documents: Microsoft Office (to PDF only)" if office else
                    "Documents: install LibreOffice for Word/Excel/PowerPoint conversions")
        e_layout.addWidget(QLabel(doc_text))
        self._refresh_ffmpeg()
        root.addWidget(engines)
        root.addStretch(1)
        return tab

    def _refresh_ffmpeg(self) -> None:
        path = ff.ffmpeg_path()
        if path:
            self.ff_label.setText("Video & audio: FFmpeg ready")
            self.ff_label.setToolTip(str(path))
            self.ff_button.hide()
        else:
            self.ff_label.setText("Video & audio: FFmpeg downloads on first use (100–200 MB)")
            self.ff_label.setToolTip(f"Saved to {BIN_DIR}")
            self.ff_button.setVisible(winutil.IS_WINDOWS)

    def _fetch_ffmpeg(self) -> None:
        if self._fetcher and self._fetcher.isRunning():
            return
        self.ff_button.setEnabled(False)
        self.ff_progress.show()
        self._fetcher = _FFmpegFetcher(self)
        self._fetcher.progressed.connect(lambda f, m: (self.ff_progress.setValue(int(f * 1000)),
                                                       self.ff_label.setText(m)))
        self._fetcher.done.connect(self._fetched)
        self._fetcher.start()

    def _fetched(self, ok: bool, message: str) -> None:
        self.ff_progress.hide()
        self.ff_button.setEnabled(True)
        self._refresh_ffmpeg()
        if not ok:
            self.ff_label.setText(message.splitlines()[0])
