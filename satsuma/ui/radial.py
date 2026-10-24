"""The radial menu: geometry, hit-testing, animation state and painting.

Window-independent, so the real overlay and the live preview in Settings share it.

Layout (radii scale with the user's size setting):
    hub      – centre button: file info, the hovered action's name, or "swap ring"
    wedges   – a ring of rounded segments, first one at 12 o'clock, clockwise
    pages    – Convert / Tools rings (and overflow rings); rest on the hub to swap
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QPainter, QPainterPath,
                           QPainterPathStroker, QPen, QPixmap, QRadialGradient)

from .. import filetypes as ft
from ..actions import Action, actions_for
from ..config import settings
from ..engine.paths import human_size
from .anim import Spring, mix
from .icons import draw_icon
from .theme import palette

BASE_R = 150.0      # outer radius at 100 %
HUB_R = 0.33        # hub radius as a fraction of R
RING_IN = 0.43      # wedge inner radius as a fraction of R
PLATE_PAD = 8.0     # plate extends this far beyond the wedges
GAP = 5.0           # straight gap between wedges (px at 100 %)
CORNER = 9.0        # wedge corner radius (px at 100 %)
STAGGER = 0.024     # seconds between wedges appearing


@dataclass
class Page:
    title: str
    actions: list[Action]


@dataclass
class Wedge:
    action: Action
    page: int
    index: int
    hover: Spring = field(default_factory=lambda: Spring(0.0, "hover"))
    appear: Spring = field(default_factory=lambda: Spring(0.0, "main"))


def _sector(r_in: float, r_out: float, a0: float, a1: float, gap: float, corner: float,
            full: bool = False) -> QPainterPath:
    """Annular sector with straight gaps and rounded corners, centred on (0, 0)."""
    if full:
        path = QPainterPath()
        path.addEllipse(QPointF(0, 0), r_out, r_out)
        inner = QPainterPath()
        inner.addEllipse(QPointF(0, 0), r_in, r_in)
        return path.subtracted(inner)
    # Build the sector shrunk by `corner`, then grow it back with a round-join stroke.
    ro, ri, g = r_out - corner, r_in + corner, gap / 2 + corner
    if ri >= ro:
        return QPainterPath()
    ao0, ao1 = a0 + math.asin(min(1.0, g / ro)), a1 - math.asin(min(1.0, g / ro))
    ai0, ai1 = a0 + math.asin(min(1.0, g / ri)), a1 - math.asin(min(1.0, g / ri))
    if ao1 <= ao0 or ai1 <= ai0:
        return QPainterPath()
    path = QPainterPath()
    path.moveTo(ro * math.cos(ao0), ro * math.sin(ao0))
    path.arcTo(QRectF(-ro, -ro, 2 * ro, 2 * ro), -math.degrees(ao0), -math.degrees(ao1 - ao0))
    path.lineTo(ri * math.cos(ai1), ri * math.sin(ai1))
    path.arcTo(QRectF(-ri, -ri, 2 * ri, 2 * ri), -math.degrees(ai1), math.degrees(ai1 - ai0))
    path.closeSubpath()
    stroker = QPainterPathStroker()
    stroker.setWidth(2 * corner)
    stroker.setJoinStyle(Qt.RoundJoin)
    stroker.setCapStyle(Qt.RoundCap)
    return stroker.createStroke(path).united(path).simplified()


def _mix_color(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(int(mix(a.red(), b.red(), t)), int(mix(a.green(), b.green(), t)),
                  int(mix(a.blue(), b.blue(), t)), int(mix(a.alpha(), b.alpha(), t)))


class RadialView:
    def __init__(self):
        self.paths: list[Path] = []
        self.pages: list[Page] = []
        self.wedges: list[Wedge] = []
        self.page = 0                       # target page
        self.page_pos = Spring(0.0, "main")  # animated page position
        self.opening = Spring(0.0, "main")   # 0 hidden → 1 open
        self.hub_fade = Spring(1.0, "hover")
        self.hub_text = ("", "")
        self.hub_prev = ("", "")
        self.hover: Wedge | str | None = None   # Wedge, "hub", or None
        self.hub_armed = False                  # cursor must leave the hub before dwell counts
        self.dwell = 0.0
        self.dwell_enabled = True
        self.chosen: Wedge | None = None
        self.empty_text = "Drop files here"
        self._paths_cache: dict = {}
        self._sprites: dict = {}      # pre-rendered wedges / plate, reused every frame
        self._style_key = None
        self._fonts: dict = {}

    # ------------------------------------------------------------------ geometry
    @property
    def scale(self) -> float:
        return float(settings.get("menu_scale"))

    @property
    def radius(self) -> float:
        return BASE_R * self.scale

    @property
    def side(self) -> int:
        """Square window size needed to draw everything incl. shadow and hover pop."""
        return int(2 * (self.radius + (PLATE_PAD + 34) * self.scale))

    def _radii(self) -> tuple[float, float, float]:
        r = self.radius
        return r * HUB_R, r * RING_IN, r

    # ------------------------------------------------------------------ content
    def set_paths(self, paths, actions: list[Action] | None = None, animate: bool = True) -> None:
        self.paths = [Path(p) for p in paths]
        actions = actions if actions is not None else (actions_for(self.paths) if self.paths else [])
        per_ring = int(settings.get("wedges_per_ring"))
        convert = [a for a in actions if a.group == "convert"]
        tools = [a for a in actions if a.group != "convert"]
        groups = [("Convert", convert), ("Tools", tools)]
        if settings.get("start_page") == "tools":
            groups.reverse()
        pages: list[Page] = []
        for title, group in groups:
            chunks = [group[i:i + per_ring] for i in range(0, len(group), per_ring)]
            for n, chunk in enumerate(chunks):
                pages.append(Page(title if len(chunks) == 1 else f"{title} {n + 1}", chunk))
        # Small menus read better as one ring, like the original.
        if len(pages) == 2 and len(pages[0].actions) + len(pages[1].actions) <= min(per_ring, 6):
            pages = [Page(pages[0].title, pages[0].actions + pages[1].actions)]
        self.pages = pages
        self.wedges = [Wedge(a, p, i) for p, page in enumerate(pages) for i, a in enumerate(page.actions)]
        self.page = 0
        self.page_pos.snap(0.0)
        self.hover = None
        self.hub_armed = False
        self.dwell = 0.0
        self.chosen = None
        self._paths_cache.clear()
        self._sprites.clear()
        self._stagger_in(animate)
        self._update_hub_text(force=True)

    def _stagger_in(self, animate: bool, page: int | None = None) -> None:
        for wedge in self.wedges:
            if page is not None and wedge.page != page:
                continue
            if animate:
                wedge.appear.snap(0.0)
                wedge.appear.to(1.0, delay=STAGGER * wedge.index)
            else:
                wedge.appear.snap(1.0)

    def page_wedges(self, page: int | None = None) -> list[Wedge]:
        page = self.page if page is None else page
        return [w for w in self.wedges if w.page == page]

    def visible_actions(self) -> list[Action]:
        return [w.action for w in self.page_wedges()]

    # ------------------------------------------------------------------ open / close
    def open(self, animate: bool = True) -> None:
        self.opening.kind = "main"
        if animate:
            self.opening.snap(0.0)
            self.opening.to(1.0)
        else:
            self.opening.snap(1.0)
        self._stagger_in(animate)

    def close(self) -> None:
        self.opening.kind = "close"
        self.opening.to(0.0)

    @property
    def closed(self) -> bool:
        return self.opening.target == 0.0 and self.opening.value <= 0.02

    # ------------------------------------------------------------------ hit testing
    def wedge_angle(self, index: int, count: int) -> tuple[float, float, float]:
        span = 2 * math.pi / max(1, count)
        mid = -math.pi / 2 + index * span
        return mid - span / 2, mid + span / 2, mid

    def hit(self, point: QPointF, center: QPointF):
        """'hub', a Wedge, 'plate' (on the disc but not a target) or None (outside)."""
        dx, dy = point.x() - center.x(), point.y() - center.y()
        dist = math.hypot(dx, dy)
        hub_r, r_in, r_out = self._radii()
        if dist <= hub_r:
            return "hub"
        wedges = self.page_wedges()
        if wedges and r_in - 3 <= dist <= r_out + 6 * self.scale:
            span = 2 * math.pi / len(wedges)
            rel = (math.atan2(dy, dx) + math.pi / 2 + span / 2) % (2 * math.pi)
            return wedges[min(len(wedges) - 1, int(rel / span))]
        if dist <= r_out + PLATE_PAD * self.scale:
            return "plate"
        return None

    def wedge_center(self, wedge: Wedge, center: QPointF) -> QPointF:
        _, r_in, r_out = self._radii()
        count = len(self.page_wedges(wedge.page))
        _, _, mid = self.wedge_angle(wedge.index, count)
        r = (r_in + r_out) / 2
        return QPointF(center.x() + r * math.cos(mid), center.y() + r * math.sin(mid))

    # ------------------------------------------------------------------ interaction state
    def set_hover(self, target) -> None:
        if target == "plate":
            target = None
        if target is not self.hover:
            if self.hover == "hub" and target != "hub":
                self.dwell = 0.0
            self.hover = target
            if target != "hub":
                self.hub_armed = True
            for wedge in self.wedges:
                wedge.hover.to(1.0 if wedge is target else 0.0)
            self._update_hub_text()

    def switch_page(self, page: int | None = None) -> None:
        if len(self.pages) < 2:
            return
        self.page = (self.page + 1) % len(self.pages) if page is None else page % len(self.pages)
        self.page_pos.to(float(self.page))
        self.dwell = 0.0
        self.hub_armed = False
        for wedge in self.wedges:
            wedge.hover.to(0.0)
        self._stagger_in(True, self.page)
        self._update_hub_text()

    def _info_line(self) -> str:
        if not self.paths:
            return self.empty_text
        if len(self.paths) > 1:
            return f"{len(self.paths)} files"
        path = self.paths[0]
        mode = settings.get("hub_info")
        if mode == "name":
            return path.name
        if mode == "type":
            return ft.LABELS.get(ft.category_of(path), "File")
        try:
            return human_size(path.stat().st_size)
        except OSError:
            return path.name

    def _update_hub_text(self, force: bool = False) -> None:
        captions = bool(settings.get("show_captions"))
        if isinstance(self.hover, Wedge):
            text = (self.hover.action.label, self.hover.action.caption if captions else "")
        elif self.hover == "hub" and len(self.pages) > 1 and self.hub_armed:
            nxt = self.pages[(self.page + 1) % len(self.pages)].title
            text = (f"{nxt} ›", "hold to switch" if self.dwell_enabled else "click to switch")
        else:
            sub = self.pages[self.page].title if len(self.pages) > 1 else ""
            if not self.pages and self.paths:
                sub = "nothing to do"
            text = (self._info_line(), sub)
        if text != self.hub_text or force:
            self.hub_prev = self.hub_text if not force else text
            self.hub_text = text
            if force:
                self.hub_fade.snap(1.0)
            else:
                self.hub_fade.snap(0.0)
                self.hub_fade.to(1.0)

    def tick(self, dt: float) -> tuple[bool, bool]:
        """Advance animations. Returns (still animating, page switched by dwell)."""
        moving = False
        for spring in (self.opening, self.page_pos, self.hub_fade):
            moving |= spring.step(dt)
        for wedge in self.wedges:
            moving |= wedge.hover.step(dt)
            moving |= wedge.appear.step(dt)
        switched = False
        if (self.dwell_enabled and self.hover == "hub" and self.hub_armed and len(self.pages) > 1
                and not self.closed):
            before = self.dwell
            self.dwell += dt * 1000.0 / float(settings.get("hub_switch_ms"))
            if before == 0.0:
                self._update_hub_text()
            if self.dwell >= 1.0:
                self.switch_page()
                switched = True
            moving = True
        return moving, switched

    # ------------------------------------------------------------------ painting
    def _font(self, px: float, weight=QFont.DemiBold) -> QFont:
        key = (round(px * 4), weight)
        font = self._fonts.get(key)
        if font is None:
            font = QFont()
            font.setFamilies(["Segoe UI Variable Display", "Segoe UI", "Inter", "Helvetica Neue", "Arial"])
            font.setPixelSize(max(6, round(px)))
            font.setWeight(weight)
            font.setHintingPreference(QFont.PreferNoHinting)
            self._fonts[key] = font
        return font

    def _wedge_path(self, wedge: Wedge, count: int) -> QPainterPath:
        hub_r, r_in, r_out = self._radii()
        key = (wedge.page, wedge.index, count, round(r_out, 2))
        path = self._paths_cache.get(key)
        if path is None:
            a0, a1, _ = self.wedge_angle(wedge.index, count)
            path = _sector(r_in, r_out, a0, a1, GAP * self.scale, CORNER * self.scale, full=count == 1)
            self._paths_cache[key] = path
        return path

    # -- sprites -------------------------------------------------------------
    def _check_style(self, pal, dpr: float) -> None:
        key = (round(self.scale, 3), pal.panel.rgba(), pal.text.rgba(), pal.accent.rgba(),
               bool(settings.get("show_icons")), round(dpr, 2))
        if key != self._style_key:
            self._style_key = key
            self._sprites.clear()
            self._paths_cache.clear()
            self._fonts.clear()

    @staticmethod
    def _canvas(bounds: QRectF, dpr: float) -> tuple[QPixmap, QPainter]:
        pixmap = QPixmap(max(1, math.ceil(bounds.width() * dpr)), max(1, math.ceil(bounds.height() * dpr)))
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        painter.translate(-bounds.left(), -bounds.top())
        return pixmap, painter

    def _plate_sprite(self, pal, dark: bool, dpr: float):
        sprite = self._sprites.get("plate")
        if sprite:
            return sprite
        s = self.scale
        hub_r, r_in, r_out = self._radii()
        plate_r = r_out + PLATE_PAD * s
        bounds = QRectF(-plate_r, -plate_r, 2 * plate_r, 2 * plate_r).adjusted(-2, -2, 2, 2)
        pixmap, painter = self._canvas(bounds, dpr)

        # Glassy disc with a warm accent tint and a top highlight
        plate = QRadialGradient(QPointF(0, -plate_r * 0.55), plate_r * 1.6)
        top = QColor(pal.panel).lighter(118 if dark else 103)
        top.setAlpha(pal.panel.alpha())
        tint = _mix_color(pal.panel, QColor(pal.accent.red(), pal.accent.green(), pal.accent.blue(),
                                            pal.panel.alpha()), 0.10)
        plate.setColorAt(0.0, top)
        plate.setColorAt(1.0, tint)
        painter.setBrush(QBrush(plate))
        painter.setPen(QPen(pal.border, 1.0))
        painter.drawEllipse(QPointF(0, 0), plate_r, plate_r)

        # Hub disc (the pill and text are drawn live: they animate)
        fill = QColor(pal.panel).lighter(135 if dark else 98)
        fill.setAlpha(min(255, pal.panel.alpha() + 20))
        painter.setPen(QPen(pal.border, 1.0))
        painter.setBrush(fill)
        painter.drawEllipse(QPointF(0, 0), hub_r, hub_r)
        painter.end()
        sprite = self._sprites["plate"] = (pixmap, bounds.topLeft())
        return sprite

    def _shadow_sprite(self, dark: bool, dpr: float):
        """Soft drop shadow in its own sprite (full resolution: a 1:1 blit is the cheapest draw)."""
        sprite = self._sprites.get("shadow")
        if sprite:
            return sprite
        s = self.scale
        _, _, r_out = self._radii()
        shadow_r = r_out + (PLATE_PAD + 26) * s
        bounds = QRectF(-shadow_r, -shadow_r + 8 * s, 2 * shadow_r, 2 * shadow_r)
        pixmap, painter = self._canvas(bounds, dpr)
        gradient = QRadialGradient(QPointF(0, 8 * s), shadow_r)
        gradient.setColorAt(0.0, QColor(0, 0, 0, 90 if dark else 60))
        gradient.setColorAt((r_out + PLATE_PAD * s) / shadow_r, QColor(0, 0, 0, 55 if dark else 34))
        gradient.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(gradient))
        painter.drawEllipse(QPointF(0, 8 * s), shadow_r, shadow_r)
        painter.end()
        sprite = self._sprites["shadow"] = (pixmap, bounds.topLeft())
        return sprite

    def prerender(self, pal, dark: bool, dpr: float) -> None:
        """Build every ring's sprites up front so swapping rings never stalls a frame."""
        for page in range(len(self.pages)):
            wedges = self.page_wedges(page)
            for wedge in wedges:
                self._wedge_sprite(wedge, len(wedges), False, pal, dark, dpr)

    def _wedge_sprite(self, wedge: Wedge, count: int, hovered: bool, pal, dark: bool, dpr: float):
        key = ("hot" if hovered else "base", wedge.page, wedge.index, count)
        sprite = self._sprites.get(key)
        if sprite:
            return sprite
        s = self.scale
        _, r_in, r_out = self._radii()
        path = self._wedge_path(wedge, count)
        bounds = path.boundingRect().adjusted(-2, -2, 2, 2)
        pixmap, painter = self._canvas(bounds, dpr)
        _, _, mid = self.wedge_angle(wedge.index, count)
        r_mid = (r_in + r_out) / 2
        cx, cy = r_mid * math.cos(mid), r_mid * math.sin(mid)
        if count == 1:
            cx, cy = 0.0, -r_mid

        if hovered:
            glow = QRadialGradient(QPointF(cx * 1.15, cy * 1.15), r_out * 0.9)
            glow.setColorAt(0.0, pal.accent.lighter(118))
            glow.setColorAt(1.0, pal.accent.darker(122))
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(glow))
            fg = pal.on_accent
        else:
            painter.setPen(QPen(QColor(255, 255, 255, 26) if dark else QColor(0, 0, 0, 18), 1.0))
            painter.setBrush(QColor(255, 255, 255, 24) if dark else QColor(255, 255, 255, 175))
            fg = pal.text
        painter.drawPath(path)

        action = wedge.action
        if settings.get("show_icons") and action.icon:
            draw_icon(painter, action.icon, QPointF(cx, cy - 8 * s), 21 * s, fg, 1.7 * s)
            painter.setFont(self._font(10.5 * s, QFont.DemiBold))
            painter.setPen(fg)
            painter.drawText(QRectF(cx - 46 * s, cy + 6 * s, 92 * s, 16 * s), Qt.AlignCenter,
                             action.label.upper())
        else:
            size = 17 * s if len(action.label) <= 4 else 13 * s
            painter.setFont(self._font(size, QFont.Bold))
            painter.setPen(fg)
            painter.drawText(QRectF(cx - 50 * s, cy - 12 * s, 100 * s, 24 * s), Qt.AlignCenter,
                             action.label)
        painter.end()
        sprite = self._sprites[key] = (pixmap, bounds.topLeft(), QPointF(cx, cy), mid)
        return sprite

    # -- frame ---------------------------------------------------------------
    def paint(self, painter: QPainter, center: QPointF) -> None:
        open_t = max(0.0, self.opening.value)
        if open_t <= 0.001:
            return
        pal = palette()
        dark = pal.text.lightness() > 128
        dpr = painter.device().devicePixelRatioF() if painter.device() else 1.0
        self._check_style(pal, dpr)
        hub_r, r_in, r_out = self._radii()

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        painter.translate(center)
        grow = 0.55 + 0.45 * open_t           # springs past 1.0 → natural overshoot
        resting = abs(grow - 1.0) < 1e-6
        painter.setRenderHint(QPainter.SmoothPixmapTransform, not resting)
        if not resting:
            painter.scale(grow, grow)
        painter.setOpacity(min(1.0, open_t * 1.6))

        if "plate" not in self._sprites:
            self.prerender(pal, dark, dpr)
        shadow, shadow_origin = self._shadow_sprite(dark, dpr)
        painter.save()
        painter.setRenderHint(QPainter.SmoothPixmapTransform, False)  # a soft gradient: no visible cost
        painter.drawPixmap(shadow_origin, shadow)
        painter.restore()
        pixmap, origin = self._plate_sprite(pal, dark, dpr)
        painter.drawPixmap(origin, pixmap)

        if not self.pages:
            self._paint_ghost_ring(painter, pal, r_in, r_out, dark)
        else:
            for p in range(len(self.pages)):
                distance = p - self.page_pos.value
                alpha = 1.0 - min(1.0, abs(distance))
                if alpha <= 0.01:
                    continue
                painter.save()
                if abs(distance) > 1e-6:
                    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
                    painter.rotate(distance * 38.0)
                painter.setOpacity(painter.opacity() * alpha)
                self._paint_page(painter, p, pal, dark, dpr)
                painter.restore()

        self._paint_hub(painter, pal, dark, hub_r)
        painter.restore()

    def _paint_ghost_ring(self, painter, pal, r_in, r_out, dark) -> None:
        pen = QPen(pal.muted, 1.2 * self.scale, Qt.DashLine)
        pen.setDashPattern([3, 4])
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        mid = (r_in + r_out) / 2
        painter.drawEllipse(QPointF(0, 0), mid, mid)

    def _paint_page(self, painter: QPainter, page: int, pal, dark: bool, dpr: float) -> None:
        wedges = self.page_wedges(page)
        count = len(wedges)
        s = self.scale
        for wedge in wedges:
            a = max(0.0, wedge.appear.value)
            if a <= 0.001:
                continue
            h = max(0.0, min(1.2, wedge.hover.value))
            base, origin, centroid, mid = self._wedge_sprite(wedge, count, False, pal, dark, dpr)
            painter.save()
            painter.setOpacity(painter.opacity() * min(1.0, a))
            # Appear: rotate in from slightly behind and grow. Hover: pop outward and grow.
            if a < 0.999 or h > 0.001:
                painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
                painter.rotate((1.0 - min(1.0, a)) * -14.0)
                pop = 5.0 * s * h
                painter.translate(pop * math.cos(mid), pop * math.sin(mid))
                grow = (0.82 + 0.18 * a) * (1.0 + 0.06 * h)
                painter.translate(centroid)
                painter.scale(grow, grow)
                painter.translate(-centroid)
            painter.drawPixmap(origin, base)
            if h > 0.01:
                hot, hot_origin, _, _ = self._wedge_sprite(wedge, count, True, pal, dark, dpr)
                painter.setOpacity(painter.opacity() * min(1.0, h))
                painter.drawPixmap(hot_origin, hot)
            painter.restore()

    def _paint_hub(self, painter: QPainter, pal, dark: bool, hub_r: float) -> None:
        s = self.scale
        hub_h = 1.0 if self.hover == "hub" else 0.0

        # Pill
        pill = QRectF(-hub_r * 0.86, -hub_r * 0.36, hub_r * 1.72, hub_r * 0.72)
        pill_fill = QColor(pal.accent)
        pill_fill.setAlpha(int(52 + 40 * hub_h))
        painter.setPen(Qt.NoPen)
        painter.setBrush(pill_fill)
        painter.drawRoundedRect(pill, pill.height() / 2, pill.height() / 2)

        # Dwell progress around the hub
        if self.dwell > 0 and len(self.pages) > 1:
            pen = QPen(pal.accent, 3.0 * s, Qt.SolidLine, Qt.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            rr = hub_r - 3 * s
            painter.drawArc(QRectF(-rr, -rr, 2 * rr, 2 * rr), 90 * 16, int(-360 * 16 * min(1.0, self.dwell)))

        # Crossfading text
        fade = max(0.0, min(1.0, self.hub_fade.value))
        for text, alpha, lift in ((self.hub_prev, 1.0 - fade, -4 * s * fade),
                                  (self.hub_text, fade, 4 * s * (1.0 - fade))):
            if alpha <= 0.01 or not text[0]:
                continue
            painter.save()
            painter.setOpacity(painter.opacity() * alpha)
            primary, secondary = text
            font = self._font(13 * s if len(primary) <= 10 else 11 * s, QFont.Bold)
            metrics = QFontMetricsF(font)
            primary = metrics.elidedText(primary, Qt.ElideMiddle, pill.width() - 10 * s)
            painter.setFont(font)
            painter.setPen(pal.text)
            painter.drawText(QRectF(pill.left(), pill.top() + lift, pill.width(), pill.height()),
                             Qt.AlignCenter, primary)
            if secondary:
                small = self._font(9 * s, QFont.Medium)
                painter.setFont(small)
                painter.setPen(pal.muted)
                secondary = QFontMetricsF(small).elidedText(secondary, Qt.ElideRight, hub_r * 1.8)
                painter.drawText(QRectF(-hub_r, pill.bottom() + 1 * s + lift, 2 * hub_r, 13 * s),
                                 Qt.AlignHCenter | Qt.AlignTop, secondary)
            painter.restore()

        # Page dots
        if len(self.pages) > 1:
            n = len(self.pages)
            for i in range(n):
                x = (i - (n - 1) / 2) * 8 * s
                active = 1.0 - min(1.0, abs(i - self.page_pos.value))
                dot = _mix_color(pal.muted, pal.accent, active)
                painter.setPen(Qt.NoPen)
                painter.setBrush(dot)
                r = (2.0 + 1.0 * active) * s
                painter.drawEllipse(QPointF(x, -hub_r * 0.62), r, r)
