import math

import pytest
from PySide6.QtCore import QPointF

from satsuma.config import DEFAULTS, settings


@pytest.fixture(autouse=True)
def fresh_settings():
    saved = settings.as_dict()
    yield
    settings._data.update(saved)


@pytest.fixture()
def image(tmp_path):
    path = tmp_path / "photo.png"
    path.write_bytes(b"x" * 2048)
    return path


def test_hit_testing_matches_wedges(qapp, image):
    from satsuma.ui.radial import RadialView, Wedge

    view = RadialView()
    view.set_paths([image], animate=False)
    centre = QPointF(200, 200)
    assert view.hit(centre, centre) == "hub"
    for wedge in view.page_wedges():
        assert view.hit(view.wedge_center(wedge, centre), centre) is wedge
    far = QPointF(200 + view.radius * 2, 200)
    assert view.hit(far, centre) is None
    first = view.page_wedges()[0]
    top = QPointF(200, 200 - (view.radius * 0.7))          # first wedge sits at 12 o'clock
    assert view.hit(top, centre) is first and isinstance(first, Wedge)


def test_rings_split_by_group_and_limit(qapp, image):
    from satsuma.ui.radial import RadialView

    settings._data["wedges_per_ring"] = 4
    view = RadialView()
    view.set_paths([image], animate=False)
    titles = [p.title for p in view.pages]
    assert titles[0] == "Convert 1" and titles[-1] == "Tools 2"
    kinds = [t.split()[0] for t in titles]
    assert kinds == sorted(kinds)   # every Convert ring comes before the Tools rings
    assert all(len(p.actions) <= 4 for p in view.pages)
    settings._data["start_page"] = "tools"
    view.set_paths([image], animate=False)
    assert view.pages[0].title.startswith("Tools")


def test_small_menus_share_one_ring(qapp, tmp_path):
    from satsuma.ui.radial import RadialView

    archive = tmp_path / "a.zip"
    archive.write_bytes(b"PK")
    view = RadialView()
    view.set_paths([archive], animate=False)
    assert len(view.pages) == 1


def test_resting_on_hub_swaps_ring(qapp, image):
    from satsuma.ui.radial import RadialView

    settings._data["hub_switch_ms"] = 300
    view = RadialView()
    view.set_paths([image], animate=False)
    view.open(animate=False)
    view.set_hover("hub")
    for _ in range(30):
        view.tick(1 / 60)
    assert view.page == 0, "must not swap while the cursor has not left the hub since opening"
    view.set_hover(view.page_wedges()[0])
    view.set_hover("hub")
    switched = False
    for _ in range(30):                       # 0.5 s > 300 ms
        switched |= view.tick(1 / 60)[1]
    assert switched and view.page == 1


def test_animation_off_snaps(qapp, image):
    from satsuma.ui.radial import RadialView

    settings._data["anim_speed"] = "off"
    view = RadialView()
    view.set_paths([image])
    view.open(animate=True)
    moving, _ = view.tick(1 / 60)
    assert view.opening.value == 1.0 and not moving


def test_spring_overshoots_only_with_bounce(qapp):
    from satsuma.ui.anim import Spring

    for bounce, expect_overshoot in ((True, True), (False, False)):
        settings._data["bounce"] = bounce
        spring = Spring(0.0)
        spring.to(1.0)
        peak = 0.0
        while spring.step(1 / 120):
            peak = max(peak, spring.value)
        assert (peak > 1.001) is expect_overshoot
        assert spring.value == 1.0


def test_customisation_hides_and_orders(qapp, image):
    from satsuma.actions import actions_for

    settings._data["actions_hidden"] = ["image:img-gif"]
    settings._data["actions_order"] = {"image": ["img-ico", "img-webp"]}
    labels = [a.label for a in actions_for([image])]
    assert "GIF" not in labels
    assert labels[:2] == ["ICO", "WEBP"]
    assert "JPG" in labels                      # unlisted ones keep their default place


def test_accent_and_text_contrast(qapp):
    from PySide6.QtGui import QColor

    from satsuma.ui.theme import palette, readable_on

    settings._data["accent"] = "#2F7BF6"
    assert palette().accent.name().upper() == "#2F7BF6"
    assert readable_on(QColor("#FFE066")).lightness() < 60     # dark text on yellow
    assert readable_on(QColor("#1E3A8A")).lightness() > 200    # white text on navy


def test_settings_window_reset(qapp):
    from satsuma.ui.settings_window import LOOK_KEYS, SettingsWindow

    window = SettingsWindow()
    window._set_accent("#9B5CF6")
    settings.set("menu_scale", 1.3)
    window._reset_look()
    for key in LOOK_KEYS:
        assert settings.get(key) == DEFAULTS[key]
    window.close()


def test_bad_settings_are_sanitised():
    from satsuma.config import Settings

    s = Settings.__new__(Settings)
    s._listeners = []
    s._data = dict(DEFAULTS, accent="orange", menu_scale=9, wedges_per_ring="x", anim_speed="warp")
    s._sanitise()
    assert s._data["accent"] == DEFAULTS["accent"]
    assert s._data["menu_scale"] == 1.5
    assert s._data["wedges_per_ring"] == DEFAULTS["wedges_per_ring"]
    assert s._data["anim_speed"] == "normal"
    assert not math.isnan(s._data["glass_opacity"])
