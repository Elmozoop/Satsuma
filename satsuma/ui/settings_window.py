"""Settings: Appearance (with live preview), Ring actions, Trigger, Saving, Converters, About."""
from __future__ import annotations

from functools import partial
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QComboBox, QDialog,
                               QDialogButtonBox,
                               QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QProgressBar, QPushButton,
                               QScrollArea, QSlider, QSpinBox, QStackedWidget, QStyle,
                               QStyledItemDelegate, QStyleOptionViewItem, QToolButton, QVBoxLayout,
                               QWidget)

from .. import watcher, winutil
from ..actions import catalogue, is_shown
from ..config import BIN_DIR, DATA_DIR, DEFAULTS, LOG_FILE, VERSION, settings
from ..engine import documents
from ..engine import ffmpeg_tool as ff
from ..engine.paths import open_file
from .controls import Segmented, Toggle, confirm, pick_colour, stylesheet
from .icons import draw_icon
from .preview import SAMPLES, RadialPreview
from .theme import ACCENT_PRESETS, palette, readable_on

LOOK_KEYS = ["theme", "accent", "menu_scale", "glass_opacity", "anim_speed", "bounce", "show_icons",
             "show_captions", "hub_info", "wedges_per_ring", "hub_switch_ms", "start_page", "type_colors",
             "explain_actions"]
PROJECT_URL = "https://github.com/Elmozoop/Satsuma"
PAGES = ["Appearance", "Ring actions", "Trigger", "Saving", "Watched folders", "Converters", "About"]
WATCH_PAGE = PAGES.index("Watched folders")
PAGE_ICONS = ["palette", "ring", "pointer", "save", "folder", "gear", "info"]
RESTYLE_KEYS = {"theme", "accent", "*"}


class _FFmpegFetcher(QThread):
    progressed = Signal(float, str)
    done = Signal(bool, str)

    def run(self) -> None:
        try:
            ff.ensure(lambda f, m: self.progressed.emit(f, m))
            self.done.emit(True, "FFmpeg is ready.")
        except Exception as exc:  # shown to the user
            self.done.emit(False, str(exc))


# ----------------------------------------------------------------------------- bound controls
def _segmented(options, key: str) -> Segmented:
    control = Segmented(options, settings.get(key))
    control.changed.connect(lambda v: settings.set(key, v))
    return control


def _toggle(key: str) -> Toggle:
    control = Toggle(bool(settings.get(key)))
    control.toggled.connect(lambda v: settings.set(key, v))
    return control


def _slider(key: str, low: int, high: int, factor: float = 1.0, suffix: str = "",
            live: bool = True) -> QWidget:
    """Slider bound to a setting. `factor` maps slider ints to the stored value."""
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    slider = QSlider(Qt.Horizontal)
    slider.setRange(low, high)
    slider.setValue(round(float(settings.get(key)) / factor))
    slider.setFixedWidth(200)
    value = QLabel()
    value.setObjectName("value")
    value.setMinimumWidth(52)
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
    layout.addWidget(slider)
    layout.addWidget(value)
    row.slider = slider
    return row


def _swatch_icon(color: QColor, selected: bool) -> QIcon:
    """A colour dot; a ring and a tick mark the current accent."""
    pixmap = QPixmap(64, 64)
    pixmap.setDevicePixelRatio(2.0)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    if selected:
        painter.setPen(QPen(color, 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QRectF(2, 2, 28, 28))
    painter.setPen(Qt.NoPen)
    painter.setBrush(color)
    painter.drawEllipse(QRectF(6, 6, 20, 20))
    if selected:
        painter.setPen(QPen(readable_on(color), 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawPolyline([QPointF(11.5, 16.5), QPointF(14.5, 19.5), QPointF(20.5, 12.5)])
    painter.end()
    return QIcon(pixmap)


def _label(text: str, name: str, wrap: bool = False) -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(wrap)
    return label


class _Card(QFrame):
    """A rounded panel of setting rows: title and explanation on the left, control on the right."""

    def __init__(self):
        super().__init__()
        self.setObjectName("card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

    def add(self, title: str, hint: str = "", control: QWidget | None = None) -> QWidget:
        if self._layout.count():
            sep = QFrame()
            sep.setObjectName("sep")
            self._layout.addWidget(sep)
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(16, 10, 14, 10)
        layout.setSpacing(16)
        text = QVBoxLayout()
        text.setSpacing(1)
        text.addWidget(_label(title, "rowTitle"))
        row.hint = _label(hint, "rowHint", wrap=True)
        text.addWidget(row.hint)
        row.text = text
        layout.addLayout(text, 1)
        # Only after it sits inside the row: showing a parentless label opens it as its own window.
        row.hint.setVisible(bool(hint))
        if control is not None:
            layout.addWidget(control, 0, Qt.AlignVCenter | Qt.AlignRight)
        row.setMinimumHeight(54)
        self._layout.addWidget(row)
        # Hide the row together with the separator above it.
        row.separator = sep if self._layout.count() > 1 else None
        return row

    def add_widget(self, widget: QWidget) -> None:
        self._layout.addWidget(widget)


def _set_row_visible(row: QWidget, visible: bool) -> None:
    row.setVisible(visible)
    if row.separator is not None:
        row.separator.setVisible(visible)


class _ActionDelegate(QStyledItemDelegate):
    """Action rows: icon, label, caption and which ring the action lives on."""

    def paint(self, painter: QPainter, option, index) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        label, caption, ring = index.data(Qt.UserRole + 1)
        opt.text = ""
        widget = option.widget
        style = widget.style()
        text_rect = style.subElementRect(QStyle.SE_ItemViewItemText, opt, widget)
        box = QRectF(style.subElementRect(QStyle.SE_ItemViewItemCheckIndicator, opt, widget))
        # Draw our own checkbox in the accent colour; clicks still hit the style's indicator rect.
        opt.features &= ~QStyleOptionViewItem.HasCheckIndicator
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, widget)
        pal = palette()
        shown = Qt.CheckState(index.data(Qt.CheckStateRole)) == Qt.Checked
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        box = QRectF(0, 0, 18, 18).translated(box.center() - QPointF(9, 9))
        if shown:
            painter.setPen(Qt.NoPen)
            painter.setBrush(pal.accent)
            painter.drawRoundedRect(box, 5, 5)
            painter.setPen(QPen(pal.on_accent, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            c = box.center()
            painter.drawPolyline([c + QPointF(-4.5, 0.5), c + QPointF(-1.5, 3.5), c + QPointF(4.5, -3.5)])
        else:
            painter.setPen(QPen(pal.muted, 1.4))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(box.adjusted(0.7, 0.7, -0.7, -0.7), 5, 5)
        painter.setOpacity(1.0 if shown else 0.45)
        bold = QFont(opt.font)
        bold.setWeight(QFont.DemiBold)
        painter.setFont(bold)
        painter.setPen(pal.text)
        label_rect = text_rect.adjusted(4, 0, 0, 0)
        painter.drawText(label_rect, Qt.AlignVCenter | Qt.AlignLeft, label)
        width = painter.fontMetrics().horizontalAdvance(label)
        painter.setFont(opt.font)
        painter.setPen(pal.muted)
        painter.drawText(label_rect.adjusted(width + 12, 0, -96, 0), Qt.AlignVCenter | Qt.AlignLeft,
                         caption)
        # Ring chip on the right
        chip = QRectF(text_rect.right() - 86, text_rect.center().y() - 10, 80, 20)
        tint = QColor(pal.accent if ring == "Convert" else pal.muted)
        tint.setAlphaF(0.18)
        painter.setPen(Qt.NoPen)
        painter.setBrush(tint)
        painter.drawRoundedRect(chip, 10, 10)
        painter.setPen(pal.accent if ring == "Convert" else pal.text)
        small = QFont(opt.font)
        small.setPointSizeF(max(7.0, opt.font.pointSizeF() - 1.5))
        painter.setFont(small)
        painter.drawText(chip, Qt.AlignCenter, f"{ring} ring")
        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        return QSize(0, 36)


# ----------------------------------------------------------------------------- the window
class SettingsWindow(QDialog):
    def __init__(self):
        super().__init__(None)
        self.setWindowTitle("Satsuma Settings")
        self.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint | Qt.WindowMinimizeButtonHint
                            | Qt.WindowMaximizeButtonHint)
        self.resize(1080, 700)
        self.setMinimumSize(900, 560)
        self._fetcher: _FFmpegFetcher | None = None

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setAttribute(Qt.WA_StyledBackground, True)
        sidebar.setFixedWidth(210)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(12, 18, 12, 14)
        side.addWidget(_label("🍊  Satsuma", "brand"))
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setIconSize(QSize(18, 18))
        for name in PAGES:
            self.nav.addItem(name)
        self._paint_nav_icons()
        side.addWidget(self.nav, 1)
        side.addWidget(_label(f"Version {VERSION}", "hint"))
        root.addWidget(sidebar)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        self._build_pages()
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)

        self.setStyleSheet(stylesheet())
        listener = self._on_setting
        settings.subscribe(listener)
        self.destroyed.connect(partial(settings.unsubscribe, listener))

    @property
    def busy(self) -> bool:
        """True while a background FFmpeg download still reports to this window."""
        return bool(self._fetcher and self._fetcher.isRunning())

    def _paint_nav_icons(self) -> None:
        colour = palette().text
        for row, name in enumerate(PAGE_ICONS):
            pixmap = QPixmap(40, 40)
            pixmap.setDevicePixelRatio(2.0)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing)
            draw_icon(painter, name, QPointF(10, 10), 17, colour, 1.6)
            painter.end()
            self.nav.item(row).setIcon(QIcon(pixmap))

    def _on_setting(self, key: str) -> None:
        if key in RESTYLE_KEYS:
            self.setStyleSheet(stylesheet())
            self._paint_nav_icons()
            self._refresh_swatches()
            self.update()
        if key in ("output_mode", "output_subfolder", "output_custom", "overwrite", "*"):
            self._refresh_example()

    def _build_pages(self) -> None:
        builders = [self._appearance_page, self._actions_page, self._trigger_page,
                    self._saving_page, self._watch_page, self._converters_page, self._about_page]
        for build in builders:
            self.stack.addWidget(build())

    def _rebuild(self) -> None:
        """Recreate every page so each control shows the stored values again."""
        index = self.stack.currentIndex()
        while self.stack.count():
            page = self.stack.widget(0)
            self.stack.removeWidget(page)
            page.deleteLater()
        self._build_pages()
        self.stack.setCurrentIndex(index)
        self.setStyleSheet(stylesheet())

    @staticmethod
    def _page(title: str, subtitle: str = "") -> tuple[QScrollArea, QVBoxLayout]:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        body.setObjectName("page")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(28, 22, 28, 24)
        layout.setSpacing(8)
        layout.addWidget(_label(title, "pageTitle"))
        if subtitle:
            layout.addWidget(_label(subtitle, "hint", wrap=True))
        scroll.setWidget(body)
        return scroll, layout

    @staticmethod
    def _section(layout: QVBoxLayout, title: str) -> _Card:
        layout.addWidget(_label(title, "cardTitle"))
        card = _Card()
        layout.addWidget(card)
        return card

    # ================================================================== Appearance
    def _appearance_page(self) -> QWidget:
        page = QWidget()
        outer = QHBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        preview_panel = QWidget()
        preview_panel.setFixedWidth(340)
        left = QVBoxLayout(preview_panel)
        left.setContentsMargins(24, 24, 4, 24)
        self.preview = RadialPreview()
        self.preview.setMinimumSize(300, 300)
        left.addWidget(self.preview, 1)
        controls = QHBoxLayout()
        self.preview_kind = QComboBox()
        for kind, label in (("image", "Image"), ("video", "Video"), ("audio", "Audio"),
                            ("pdf", "PDF"), ("document", "Document")):
            self.preview_kind.addItem(f"Preview: {label}", kind)
        self.preview_kind.currentIndexChanged.connect(
            lambda _i: self.preview.set_kind(self.preview_kind.currentData()))
        replay = QPushButton("Replay")
        replay.clicked.connect(self.preview.replay)
        controls.addWidget(self.preview_kind, 1)
        controls.addWidget(replay)
        left.addLayout(controls)
        left.addWidget(_label("Hover the preview to try it. Click the centre to swap rings.", "hint", wrap=True))
        outer.addWidget(preview_panel)

        scroll, layout = self._page("Appearance", "Changes show in the preview straight away.")
        colour = self._section(layout, "Colour")
        colour.add("Theme", "", _segmented((("system", "System"), ("light", "Light"), ("dark", "Dark")),
                                            "theme"))
        colour.add("Accent", "", self._accent_picker())
        colour.add("Glass", "How solid the ring is", _slider("glass_opacity", 35, 100, 0.01, "%"))

        shape = self._section(layout, "Shape")
        shape.add("Size", "", _slider("menu_scale", 70, 150, 0.01, "%", live=False))
        spin = QSpinBox()
        spin.setRange(3, 10)
        spin.setValue(int(settings.get("wedges_per_ring")))
        spin.setFixedWidth(72)
        spin.valueChanged.connect(lambda v: settings.set("wedges_per_ring", v))
        shape.add("Wedges per ring", "Extra actions spill onto another ring", spin)
        shape.add("First ring", "Which ring opens first",
                  _segmented((("convert", "Convert"), ("tools", "Tools")), "start_page"))
        shape.add("Icons on tool wedges", "", _toggle("show_icons"))
        shape.add("Colour by file type", "Images blue, video purple, audio green, documents gold",
                  _toggle("type_colors"))

        motion = self._section(layout, "Motion")
        motion.add("Animation", "", _segmented((("off", "Off"), ("fast", "Fast"), ("normal", "Normal"),
                                                ("relaxed", "Relaxed")), "anim_speed"))
        motion.add("Springy bounce", "A little overshoot as the ring opens", _toggle("bounce"))
        motion.add("Hold centre to swap", "Rest on the centre this long to switch rings",
                   _slider("hub_switch_ms", 150, 1500, 1.0, " ms"))

        centre = self._section(layout, "Centre")
        centre.add("Shows", "", _segmented((("size", "Size"), ("name", "Name"), ("type", "Type")),
                                           "hub_info"))
        centre.add("Describe the action under the cursor", "", _toggle("show_captions"))
        centre.add("Explain actions in a bubble", "A short note beside the wedge: what it does, where the file goes",
                   _toggle("explain_actions"))

        reset = QPushButton("Reset appearance")
        reset.clicked.connect(self._reset_look)
        layout.addSpacing(8)
        layout.addWidget(reset, alignment=Qt.AlignRight)
        layout.addStretch(1)
        outer.addWidget(scroll, 1)
        return page

    def _accent_picker(self) -> QWidget:
        row = QWidget()
        grid = QGridLayout(row)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)
        self._swatches = QButtonGroup(row)
        self._swatches.setExclusive(True)
        for i, (name, hex_) in enumerate(ACCENT_PRESETS):
            button = QToolButton()
            button.setToolTip(name)
            button.setCheckable(True)
            button.setAutoRaise(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setIconSize(QSize(30, 30))
            button.setStyleSheet("QToolButton { border: none; background: transparent; padding: 0; }")
            button.setProperty("hex", hex_)
            button.clicked.connect(lambda _c=False, h=hex_: self._set_accent(h))
            self._swatches.addButton(button)
            grid.addWidget(button, 0, i)
        custom = QToolButton()
        custom.setToolTip("Pick any colour")
        custom.setText("+")
        custom.setCursor(Qt.PointingHandCursor)
        custom.setIconSize(QSize(30, 30))
        custom.setStyleSheet("QToolButton { border: none; background: transparent; font-size: 14pt; }")
        custom.clicked.connect(self._custom_accent)
        grid.addWidget(custom, 0, len(ACCENT_PRESETS))
        self._custom_button = custom
        self._refresh_swatches()
        return row

    def _refresh_swatches(self) -> None:
        if not hasattr(self, "_custom_button"):
            return
        try:
            current = str(settings.get("accent")).upper()
            for button in self._swatches.buttons():
                hex_ = button.property("hex")
                selected = hex_.upper() == current
                button.setChecked(selected)
                button.setIcon(_swatch_icon(QColor(hex_), selected))
            is_custom = all(h.upper() != current for _n, h in ACCENT_PRESETS)
            self._custom_button.setIcon(_swatch_icon(QColor(current), True) if is_custom else QIcon())
            self._custom_button.setToolButtonStyle(Qt.ToolButtonIconOnly if is_custom
                                                   else Qt.ToolButtonTextOnly)
        except RuntimeError:   # the page was rebuilt; its buttons are gone
            pass

    def _set_accent(self, hex_: str) -> None:
        settings.set("accent", hex_.upper())
        self._refresh_swatches()

    def _custom_accent(self) -> None:
        colour = pick_colour(self, QColor(str(settings.get("accent"))), "Accent colour")
        if colour.isValid():
            self._set_accent(colour.name())

    def _reset_look(self) -> None:
        settings.reset(LOOK_KEYS)
        self._rebuild()

    # ================================================================== Ring actions
    def _actions_page(self) -> QWidget:
        scroll, layout = self._page(
            "Ring actions",
            "Choose what appears in the ring for each kind of file. Drag rows to reorder them. "
            "Convert and Tools actions sit on separate rings; rest on the centre to swap between them.")
        top = QHBoxLayout()
        top.addWidget(_label("When I drag", "rowTitle"))
        self.action_kind = QComboBox()
        self.action_kind.setMinimumWidth(180)
        self._catalogue = catalogue()
        for category, label, _actions in self._catalogue:
            self.action_kind.addItem(label, category)
        self.action_kind.currentIndexChanged.connect(self._load_action_list)
        top.addWidget(self.action_kind)
        top.addStretch(1)
        layout.addLayout(top)

        body = QHBoxLayout()
        body.setSpacing(16)
        column = QVBoxLayout()
        self.action_list = QListWidget()
        self.action_list.setObjectName("actions")
        self.action_list.setItemDelegate(_ActionDelegate(self.action_list))
        self.action_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.action_list.setDefaultDropAction(Qt.MoveAction)
        self.action_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.action_list.setIconSize(QSize(18, 18))
        self.action_list.setMinimumHeight(340)
        self.action_list.itemChanged.connect(lambda _i: self._save_action_list())
        self.action_list.model().rowsMoved.connect(lambda *_a: self._save_action_list())
        column.addWidget(self.action_list, 1)

        buttons = QHBoxLayout()
        for text, handler in (("↑", lambda: self._move_selected(-1)), ("↓", lambda: self._move_selected(1))):
            button = QPushButton(text)
            button.setFixedWidth(40)
            button.setToolTip("Move up" if text == "↑" else "Move down")
            button.clicked.connect(handler)
            buttons.addWidget(button)
        buttons.addSpacing(8)
        for text, checked in (("Show all", True), ("Hide all", False)):
            button = QPushButton(text)
            button.clicked.connect(lambda _c=False, v=checked: self._check_all(v))
            buttons.addWidget(button)
        buttons.addStretch(1)
        reset = QPushButton("Reset")
        reset.setToolTip("Default actions and order for this kind of file")
        reset.clicked.connect(self._reset_action_list)
        buttons.addWidget(reset)
        column.addLayout(buttons)
        body.addLayout(column, 3)

        preview_column = QVBoxLayout()
        self.actions_preview = RadialPreview()
        self.actions_preview.setMinimumSize(300, 300)
        preview_column.addWidget(self.actions_preview, 1)
        self.actions_preview_note = _label("", "hint", wrap=True)
        self.actions_preview_note.setAlignment(Qt.AlignCenter)
        preview_column.addWidget(self.actions_preview_note)
        body.addLayout(preview_column, 2)
        layout.addLayout(body, 1)
        self._load_action_list()
        return scroll

    def _current_actions(self):
        category = self.action_kind.currentData()
        for cat, _label, actions in self._catalogue:
            if cat == category:
                return category, actions
        return category, []

    def _load_action_list(self) -> None:
        category, actions = self._current_actions()
        order = (settings.get("actions_order") or {}).get(category) or []
        rank = {a: i for i, a in enumerate(order)}
        ordered = sorted(actions, key=lambda a: (0, rank[a.id]) if a.id in rank else (1, actions.index(a)))
        colour = palette().text
        self.action_list.blockSignals(True)
        self.action_list.clear()
        for action in ordered:
            ring = "Convert" if action.group == "convert" else "Tools"
            item = QListWidgetItem(f"{action.label} — {action.caption}")   # used for accessibility
            item.setData(Qt.UserRole, action.id)
            item.setData(Qt.UserRole + 1, (action.label, action.caption, ring))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsDragEnabled)
            item.setFlags(item.flags() & ~Qt.ItemIsDropEnabled)
            item.setCheckState(Qt.Checked if is_shown(category, action) else Qt.Unchecked)
            # Every row gets an icon (blank for format wedges) so rows line up.
            pixmap = QPixmap(36, 36)
            pixmap.setDevicePixelRatio(2.0)
            pixmap.fill(Qt.transparent)
            if action.icon:
                painter = QPainter(pixmap)
                painter.setRenderHint(QPainter.Antialiasing)
                draw_icon(painter, action.icon, QPointF(9, 9), 16, colour, 1.6)
                painter.end()
            item.setIcon(QIcon(pixmap))
            self.action_list.addItem(item)
        self.action_list.blockSignals(False)
        self._update_actions_preview(category)

    def _update_actions_preview(self, category: str) -> None:
        if category in SAMPLES:
            self.actions_preview.show()
            self.actions_preview.set_kind(category)
            self.actions_preview_note.setText(f"Dragging “{SAMPLES[category][0]}”")
        else:
            self.actions_preview.hide()
            self.actions_preview_note.setText("No preview for a mix of file types.")

    def _save_action_list(self) -> None:
        category, actions = self._current_actions()
        by_id = {a.id: a for a in actions}
        ids = [self.action_list.item(i).data(Qt.UserRole) for i in range(self.action_list.count())]
        checked = {self.action_list.item(i).data(Qt.UserRole) for i in range(self.action_list.count())
                   if self.action_list.item(i).checkState() == Qt.Checked}
        mine = f"{category}:"
        hidden = [h for h in (settings.get("actions_hidden") or []) if not h.startswith(mine)]
        shown = [h for h in (settings.get("actions_shown") or []) if not h.startswith(mine)]
        # Store only choices that differ from each action's default.
        hidden += [mine + a for a in ids if a not in checked and not by_id[a].hidden_by_default]
        shown += [mine + a for a in ids if a in checked and by_id[a].hidden_by_default]
        order = dict(settings.get("actions_order") or {})
        order[category] = ids
        settings.set("actions_order", order)
        settings.set("actions_shown", shown)
        settings.set("actions_hidden", hidden)

    def _check_all(self, checked: bool) -> None:
        self.action_list.blockSignals(True)
        for i in range(self.action_list.count()):
            self.action_list.item(i).setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self.action_list.blockSignals(False)
        self.action_list.viewport().update()
        self._save_action_list()

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
        for key in ("actions_hidden", "actions_shown"):
            settings.set(key, [h for h in (settings.get(key) or []) if not h.startswith(f"{category}:")])
        order = dict(settings.get("actions_order") or {})
        order.pop(category, None)
        settings.set("actions_order", order)
        self._load_action_list()

    # ================================================================== Trigger
    def _trigger_page(self) -> QWidget:
        scroll, layout = self._page("Trigger", "How the ring opens while you drag files.")
        drag = self._section(layout, "Dragging")
        drag.add("Open the ring while dragging files", "Hold the key below as you drag",
                 _toggle("enabled"))
        drag.add("Key to hold", "Shift is easiest; pick another if it clashes with an app",
                 _segmented((("shift", "Shift"), ("ctrl", "Ctrl"), ("alt", "Alt")), "modifier"))
        drag.add("Only for real file drags",
                 "Ignore text selections and window moves; the ring appears once files arrive",
                 _toggle("smart_detect"))

        system = self._section(layout, "Windows")
        self.autostart = Toggle(winutil.autostart_enabled())
        self.autostart.toggled.connect(winutil.set_autostart)
        system.add("Start when I sign in", "Satsuma waits quietly in the tray", self.autostart)
        self.sendto = Toggle(winutil.sendto_enabled())
        self.sendto.toggled.connect(self._sendto_toggled)
        system.add("Add to the “Send to” menu", "Right-click files → Send to → Satsuma opens the ring",
                   self.sendto)
        if not winutil.IS_WINDOWS:
            self.autostart.setEnabled(False)
            self.sendto.setEnabled(False)
        layout.addStretch(1)
        return scroll

    def _sendto_toggled(self, enabled: bool) -> None:
        if not winutil.set_sendto(enabled):
            self.sendto.blockSignals(True)
            self.sendto.setChecked(winutil.sendto_enabled())
            self.sendto.blockSignals(False)

    # ================================================================== Saving
    def _saving_page(self) -> QWidget:
        scroll, layout = self._page("Saving", "Your original file is never changed, moved or deleted.")
        where = self._section(layout, "Where results go")
        self.mode = QComboBox()
        self.mode.addItem("Next to the original", "source")
        self.mode.addItem("In a subfolder next to the original", "subfolder")
        self.mode.addItem("In one folder I choose", "custom")
        self.mode.setCurrentIndex(max(0, self.mode.findData(settings.get("output_mode"))))
        self.mode.setMinimumWidth(260)
        where.add("Save results", "", self.mode)

        self.subfolder = QLineEdit(str(settings.get("output_subfolder")))
        self.subfolder.setFixedWidth(260)
        self.subfolder.editingFinished.connect(
            lambda: settings.set("output_subfolder", self.subfolder.text().strip() or "Converted"))
        self._subfolder_row = where.add("Subfolder name", "Created next to each original", self.subfolder)

        custom_row = QWidget()
        custom_layout = QHBoxLayout(custom_row)
        custom_layout.setContentsMargins(0, 0, 0, 0)
        self.custom = QLineEdit(str(settings.get("output_custom")))
        self.custom.setPlaceholderText("Choose a folder…")
        self.custom.setFixedWidth(260)
        self.custom.editingFinished.connect(lambda: settings.set("output_custom", self.custom.text().strip()))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        custom_layout.addWidget(self.custom)
        custom_layout.addWidget(browse)
        self._custom_row = where.add("Folder", "", custom_row)
        self.mode.currentIndexChanged.connect(self._mode_changed)

        self.example = _label("", "example", wrap=True)
        example_box = QWidget()
        example_layout = QVBoxLayout(example_box)
        example_layout.setContentsMargins(16, 6, 14, 12)
        example_layout.addWidget(self.example)
        where.add_widget(example_box)

        files = self._section(layout, "Files")
        files.add("Replace files with the same name",
                  "Off: add a number instead, like “photo (1).webp”", _toggle("overwrite"))
        files.add("Show the result in File Explorer", "Opens the folder with the new file selected",
                  _toggle("reveal_after"))
        layout.addStretch(1)
        self._mode_changed()
        return scroll

    def _mode_changed(self) -> None:
        mode = self.mode.currentData()
        if settings.get("output_mode") != mode:
            settings.set("output_mode", mode)
        _set_row_visible(self._subfolder_row, mode == "subfolder")
        _set_row_visible(self._custom_row, mode == "custom")
        self._refresh_example()

    def _refresh_example(self) -> None:
        if not hasattr(self, "example"):
            return
        try:
            source = Path.home() / "Pictures" / "Holiday.png"
            mode = settings.get("output_mode")
            folder = source.parent
            if mode == "subfolder":
                folder = folder / str(settings.get("output_subfolder") or "Converted")
            elif mode == "custom" and str(settings.get("output_custom") or "").strip():
                folder = Path(str(settings.get("output_custom")).strip())
            self.example.setText(f"Example:  {source}\n      →  {folder / 'Holiday.webp'}")
        except RuntimeError:   # the page was rebuilt
            pass

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Save converted files to", self.custom.text())
        if folder:
            self.custom.setText(folder)
            settings.set("output_custom", folder)

    # ================================================================== Watched folders
    def _watch_page(self) -> QWidget:
        scroll, layout = self._page(
            "Watched folders",
            "Satsuma runs an action on every new file that lands in these folders, like turning "
            "screenshots into WEBP. Files already there are left alone, and Satsuma never re-processes "
            "its own results.")
        card = self._section(layout, "Folders")
        rules = list(settings.get("watch_rules") or [])
        if not rules:
            card.add("No watched folders yet", "Add one below.")
        for index, rule in enumerate(rules):
            folder = Path(str(rule.get("folder", "")))
            hint = f"→ {watcher.describe(str(rule.get('action', '')))}"
            if not folder.is_dir():
                hint += "   ·   folder not found"
            controls = QWidget()
            row_layout = QHBoxLayout(controls)
            row_layout.setContentsMargins(0, 0, 0, 0)
            toggle = Toggle(bool(rule.get("enabled", True)))
            toggle.setToolTip("Watch this folder")
            toggle.toggled.connect(lambda on, i=index: self._edit_rule(i, enabled=on))
            remove = QPushButton("Remove")
            remove.clicked.connect(lambda _c=False, i=index: self._edit_rule(i, remove=True))
            row_layout.addWidget(toggle)
            row_layout.addWidget(remove)
            card.add(folder.name or str(folder), f"{folder}\n{hint}", controls)
        add = QPushButton("Add a folder…")
        add.setObjectName("primary")
        add.clicked.connect(self._add_rule)
        layout.addSpacing(8)
        layout.addWidget(add, alignment=Qt.AlignLeft)
        layout.addStretch(1)
        return scroll

    def _edit_rule(self, index: int, enabled: bool | None = None, remove: bool = False) -> None:
        rules = [dict(r) for r in (settings.get("watch_rules") or [])]
        if not 0 <= index < len(rules):
            return
        if remove:
            rules.pop(index)
        else:
            rules[index]["enabled"] = bool(enabled)
        settings.set("watch_rules", rules)
        if remove:
            self._refresh_page(WATCH_PAGE, self._watch_page)

    def _add_rule(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Watch which folder?")
        if not folder:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("What should happen to new files?")
        box = QVBoxLayout(dialog)
        box.addWidget(QLabel(f"New files in <b>{Path(folder).name}</b>:"))
        choice = QComboBox()
        for label, _category, action in watcher.watchable_actions():
            caption = f" ({action.caption})" if action.caption else ""
            choice.addItem(f"{label}: {action.label}{caption}", action.id)
        box.addWidget(choice)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        box.addWidget(buttons)
        dialog.setStyleSheet(stylesheet())
        if dialog.exec() != QDialog.Accepted:
            return
        rules = [dict(r) for r in (settings.get("watch_rules") or [])]
        rules.append({"folder": str(Path(folder)), "action": choice.currentData(), "enabled": True})
        settings.set("watch_rules", rules)
        self._refresh_page(WATCH_PAGE, self._watch_page)

    def _refresh_page(self, index: int, build) -> None:
        old = self.stack.widget(index)
        self.stack.insertWidget(index, build())
        self.stack.removeWidget(old)
        old.deleteLater()
        self.stack.setCurrentIndex(index)

    # ================================================================== Converters
    def _converters_page(self) -> QWidget:
        scroll, layout = self._page("Converters")
        quality = self._section(layout, "Quality")
        quality.add("JPG and WEBP quality", "Higher looks better; files get bigger",
                    _slider("jpeg_quality", 10, 100, live=False))
        quality.add("Compress strength", "Quality used by the Compress tools; lower means smaller files",
                    _slider("compress_quality", 10, 100, live=False))

        engines = self._section(layout, "Helpers")
        ff_control = QWidget()
        ff_layout = QHBoxLayout(ff_control)
        ff_layout.setContentsMargins(0, 0, 0, 0)
        self.ff_status = QLabel("●")
        self.ff_button = QPushButton("Download FFmpeg")
        self.ff_button.setObjectName("primary")
        self.ff_button.clicked.connect(self._fetch_ffmpeg)
        ff_layout.addWidget(self.ff_status)
        ff_layout.addWidget(self.ff_button)
        ff_row = engines.add("Video and audio (FFmpeg)", "", ff_control)
        self.ff_label = ff_row.hint
        self.ff_label.show()
        self.ff_progress = QProgressBar()
        self.ff_progress.setRange(0, 1000)
        self.ff_progress.setTextVisible(False)
        self.ff_progress.hide()
        ff_row.text.addWidget(self.ff_progress)

        lo = documents.libreoffice_path()
        office = any(documents.office_available(k) for k in ("word", "slides", "sheets"))
        doc_ok = bool(lo or office)
        doc_hint = ("LibreOffice found: every document conversion works" if lo else
                    "Microsoft Office found: conversion to PDF works; LibreOffice adds the rest" if office
                    else "Install LibreOffice (free) for Word, Excel and PowerPoint conversions")
        doc_status = QLabel("●")
        doc_status.setObjectName("dotOk" if doc_ok else "dotWarn")
        doc_row = QWidget()
        doc_layout = QHBoxLayout(doc_row)
        doc_layout.setContentsMargins(0, 0, 0, 0)
        doc_layout.addWidget(doc_status)
        if not lo:
            get = QPushButton("Get LibreOffice")
            get.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://www.libreoffice.org/download/")))
            doc_layout.addWidget(get)
        engines.add("Office documents", doc_hint, doc_row)
        layout.addStretch(1)
        self._refresh_ffmpeg()
        return scroll

    def _refresh_ffmpeg(self) -> None:
        path = ff.ffmpeg_path()
        if path:
            self.ff_label.setText("Ready")
            self.ff_label.setToolTip(str(path))
            self.ff_status.setObjectName("dotOk")
            self.ff_button.hide()
        else:
            self.ff_label.setText("Downloads automatically the first time you need it (100–200 MB)")
            self.ff_label.setToolTip(f"Saved to {BIN_DIR}")
            self.ff_status.setObjectName("dotWarn")
            self.ff_button.setVisible(winutil.IS_WINDOWS)
        # Re-apply the stylesheet for the new object name.
        self.ff_status.style().unpolish(self.ff_status)
        self.ff_status.style().polish(self.ff_status)

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

    # ================================================================== About
    def _about_page(self) -> QWidget:
        scroll, layout = self._page("About")
        about = self._section(layout, f"Satsuma {VERSION}")
        project = QPushButton("Open on GitHub")
        project.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(PROJECT_URL)))
        about.add("Drag-to-convert for Windows",
                  "Everything runs on your PC. Files are never uploaded.", project)
        log = QPushButton("Open log")
        log.clicked.connect(lambda: open_file(LOG_FILE))
        about.add("Something went wrong?", "The log has the details of every failed job", log)
        data = QPushButton("Open folder")
        data.clicked.connect(lambda: open_file(DATA_DIR))
        about.add("Data folder", str(DATA_DIR), data)

        danger = self._section(layout, "Reset")
        reset = QPushButton("Reset everything")
        reset.setObjectName("danger")
        reset.clicked.connect(self._reset_all)
        danger.add("Reset all settings", "Look, actions, trigger and saving go back to their defaults",
                   reset)
        layout.addStretch(1)
        return scroll

    def _reset_all(self) -> None:
        if confirm(self, "Reset all settings",
                   "Put every Satsuma setting back to its default? Watched folders are removed too.",
                   "Reset everything", danger=True):
            settings.reset(list(DEFAULTS))
            self._rebuild()
