# PyInstaller recipe for dist\Satsuma.exe (used by build.bat).
#
# A one-file exe unpacks everything inside it on every launch, so whatever isn't needed is left
# out: it makes Satsuma start faster. Satsuma only uses Qt's Core, Gui, Widgets and Network.
from PyInstaller.utils.hooks import collect_all

datas = [("assets", "assets")]
binaries = []
hiddenimports = []
for package in ("pypdfium2", "pypdfium2_raw", "pillow_heif"):
    found = collect_all(package)
    datas += found[0]
    binaries += found[1]
    hiddenimports += found[2]

# Qt parts nothing in Satsuma uses (plugins drag them in: the virtual keyboard brings QML and
# Quick, the PDF image plugin brings Qt PDF; opengl32sw is a 20 MB software OpenGL fallback).
UNUSED = (
    "opengl32sw.dll", "qt6pdf", "qt6qml", "qt6quick", "qt6virtualkeyboard", "qt6opengl",
    "qtvirtualkeyboardplugin", "imageformats\\qpdf", "platforms\\qdirect2d", "platforms\\qminimal",
    "generic\\qtuiotouchplugin",
)


def wanted(entry) -> bool:
    name = entry[0].lower().replace("/", "\\")
    return not (name.startswith("pyside6\\") and any(part in name for part in UNUSED))


a = Analysis(
    ["main.py"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtPdf", "PySide6.QtOpenGL"],
)
a.binaries = [entry for entry in a.binaries if wanted(entry)]
a.datas = [entry for entry in a.datas if wanted(entry)]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Satsuma",
    debug=False,
    strip=False,
    upx=False,                # compressed DLLs would only add unpacking time
    console=False,
    icon=["assets\\icon.ico"],
)
