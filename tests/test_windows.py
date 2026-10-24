"""Windows-only integration checks. They run on the GitHub Actions Windows runner."""
import os
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
on_ci = pytest.mark.skipif(not os.environ.get("CI"), reason="changes user settings; CI only")


def test_input_state_calls():
    from satsuma import winutil

    assert winutil.primary_button_vk() in (winutil.VK_LBUTTON, winutil.VK_RBUTTON)
    assert winutil.key_down(0x10) in (True, False)
    winutil.allow_foreground_for_others()


@on_ci
def test_autostart_roundtrip():
    from satsuma import winutil

    assert winutil.set_autostart(True) and winutil.autostart_enabled()
    assert winutil.set_autostart(False) and not winutil.autostart_enabled()


@on_ci
def test_sendto_roundtrip():
    from satsuma import winutil

    assert winutil.set_sendto(True) and winutil.sendto_shortcut().exists()
    assert winutil.set_sendto(False) and not winutil.sendto_enabled()


def test_office_probe_does_not_crash():
    from satsuma.engine import documents

    for kind in ("word", "slides", "sheets"):
        assert documents.office_available(kind) in (True, False)
