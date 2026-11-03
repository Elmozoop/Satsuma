import os
import sys
import tempfile
from pathlib import Path

# Isolate settings/logs/ffmpeg cache BEFORE satsuma.config is imported.
_DATA = tempfile.mkdtemp(prefix="satsuma-test-")
os.environ["LOCALAPPDATA"] = _DATA
os.environ["XDG_DATA_HOME"] = _DATA
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32":
    # Offscreen Qt only looks in its own fonts folder, which PySide6 doesn't ship on Windows:
    # without this it has no fonts at all and renders text (e.g. text → PDF) as nothing.
    os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from PIL import Image  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


@pytest.fixture()
def workdir(tmp_path):
    Image.new("RGBA", (600, 400), (255, 140, 0, 128)).save(tmp_path / "alpha.png")
    Image.new("RGB", (800, 600), (30, 80, 200)).save(tmp_path / "photo.jpg", quality=95)
    return tmp_path


def pump(app, ms=50):
    import time

    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)
