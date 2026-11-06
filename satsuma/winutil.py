"""Windows integration: input state, autostart, Send To, foreground rights.

Every function is a safe no-op on other platforms so the app can be developed
and tested anywhere.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)
IS_WINDOWS = sys.platform == "win32"

VK_LBUTTON = 0x01
VK_RBUTTON = 0x02
SM_SWAPBUTTON = 23
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "Satsuma"
# Windows' own on/off switch for each startup entry (Task Manager -> Startup apps). Current Windows 11
# only runs entries marked enabled here, so switching start-at-sign-in on sets the mark as well.
APPROVED_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
APPROVED_ON = bytes([2] + [0] * 11)

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    _user32.GetAsyncKeyState.restype = ctypes.c_short
    _user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    _user32.GetSystemMetrics.restype = ctypes.c_int
    _user32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
    _user32.AllowSetForegroundWindow.restype = wintypes.BOOL
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    _kernel32.SetProcessWorkingSetSizeEx.argtypes = [wintypes.HANDLE, ctypes.c_size_t,
                                                     ctypes.c_size_t, wintypes.DWORD]
    _kernel32.SetProcessWorkingSetSizeEx.restype = wintypes.BOOL


def key_down(vk: int) -> bool:
    if not IS_WINDOWS:
        return False
    return bool(_user32.GetAsyncKeyState(vk) & 0x8000)


def primary_button_vk() -> int:
    """Physical button that acts as 'left click' (respects swapped mouse buttons)."""
    if IS_WINDOWS and _user32.GetSystemMetrics(SM_SWAPBUTTON):
        return VK_RBUTTON
    return VK_LBUTTON


def allow_foreground_for_others() -> None:
    """Let the running instance take focus when we forward it a request."""
    if IS_WINDOWS:
        try:
            _user32.AllowSetForegroundWindow(0xFFFFFFFF)  # ASFW_ANY
        except Exception:
            pass


def trim_working_set() -> None:
    """Hand idle memory back to Windows. Pages come back on their own when next touched."""
    if IS_WINDOWS:
        try:
            # (size_t)-1 for both limits means "remove as many pages as possible".
            _kernel32.SetProcessWorkingSetSizeEx(_kernel32.GetCurrentProcess(),
                                                 ctypes.c_size_t(-1).value, ctypes.c_size_t(-1).value, 0)
        except Exception:
            pass


def recycle(paths) -> bool:
    """Send files or folders to the Recycle Bin (restorable). True if all of them went."""
    paths = [Path(p) for p in paths if Path(p).exists()]
    if not paths:
        return True
    if not IS_WINDOWS:
        return False

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort),
                    ("fAnyOperationsAborted", wintypes.BOOL), ("hNameMappings", ctypes.c_void_p),
                    ("lpszProgressTitle", wintypes.LPCWSTR)]

    FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 3, 0x4, 0x10, 0x40, 0x400
    # The list is NUL-separated and ends with two NULs.
    files = "\0".join(os.path.abspath(str(p)) for p in paths) + "\0\0"
    op = SHFILEOPSTRUCTW(None, FO_DELETE, files, None,
                         FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI, False, None, None)
    try:
        result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    except Exception as exc:
        log.warning("recycle failed: %s", exc)
        return False
    if result != 0 or op.fAnyOperationsAborted:
        log.warning("recycle failed: code %s", result)
        return False
    return not any(p.exists() for p in paths)


def launch_command() -> tuple[str, list[str]]:
    """(program, args) that start this app the same way it is running now."""
    if getattr(sys, "frozen", False):
        return sys.executable, []
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    program = str(pythonw if pythonw.exists() else exe)
    main = Path(__file__).resolve().parent.parent / "main.py"
    return program, [str(main)]


def _quote(part: str) -> str:
    return f'"{part}"' if (" " in part or not part) else part


# ----------------------------------------------------------------------------- autostart
def startup_approval() -> bytes | None:
    """Windows' mark for Satsuma's startup entry, or None when there is none yet."""
    if not IS_WINDOWS:
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APPROVED_KEY) as key:
            value = winreg.QueryValueEx(key, RUN_VALUE)[0]
            return bytes(value) if value else None
    except OSError:
        return None


def disabled_in_task_manager() -> bool:
    """True when the user switched Satsuma off in Task Manager -> Startup apps (odd first byte)."""
    mark = startup_approval()
    return bool(mark) and mark[0] % 2 == 1


def _set_approval(enabled: bool) -> None:
    import winreg

    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, APPROVED_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_BINARY, APPROVED_ON)
            else:
                try:
                    winreg.DeleteValue(key, RUN_VALUE)
                except FileNotFoundError:
                    pass
    except OSError as exc:
        log.warning("couldn't mark the startup entry: %s", exc)


def autostart_enabled() -> bool:
    """Satsuma will start at sign-in: it is registered and not switched off in Task Manager."""
    return registered_autostart() is not None and not disabled_in_task_manager()


def autostart_command() -> str:
    program, args = launch_command()
    return " ".join(_quote(p) for p in [program, *args, "--background"])


def registered_autostart() -> str | None:
    """The command Windows runs at sign-in for Satsuma, or None."""
    if not IS_WINDOWS:
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return str(winreg.QueryValueEx(key, RUN_VALUE)[0])
    except OSError:
        return None


def program_of(command: str) -> str:
    """The program a command line starts, quoted ("C:/a b/x.exe" --flag) or not (C:/a/x.exe --flag)."""
    command = command.strip()
    if command.startswith('"'):
        return command[1:].split('"', 1)[0]
    lower = command.lower()
    end = lower.find(".exe")
    return command[:end + 4] if end >= 0 else command.split(" ", 1)[0]


def repair_autostart() -> bool:
    """If start-at-sign-in points at a Satsuma that isn't there any more (the exe was moved or
    renamed), point it at this one. A Satsuma that still exists elsewhere is left alone, so opening
    a second copy never takes the setting over. True when it was repaired."""
    command = registered_autostart()
    if not command or disabled_in_task_manager():
        return False                       # off, or switched off by the user in Task Manager
    if os.path.exists(program_of(command)) or command == autostart_command():
        if startup_approval() is None:     # switched on before Windows needed the mark (Satsuma < 1.16.3)
            _set_approval(True)
            log.info("start-at-sign-in: marked as enabled for Windows")
            return True
        return False
    log.info("start-at-sign-in pointed at %s, which is gone; now it starts this copy", program_of(command))
    return set_autostart(True)


def set_autostart(enabled: bool) -> bool:
    if not IS_WINDOWS:
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, autostart_command())
                _set_approval(True)
            else:
                try:
                    winreg.DeleteValue(key, RUN_VALUE)
                except FileNotFoundError:
                    pass
                _set_approval(False)
        return True
    except OSError as exc:
        log.warning("autostart change failed: %s", exc)
        return False


# ----------------------------------------------------------------------------- Send To
def sendto_shortcut() -> Path | None:
    if not IS_WINDOWS:
        return None
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    return Path(appdata) / "Microsoft" / "Windows" / "SendTo" / "Satsuma.lnk"


def sendto_enabled() -> bool:
    link = sendto_shortcut()
    return bool(link and link.exists())


def set_sendto(enabled: bool) -> bool:
    link = sendto_shortcut()
    if link is None:
        return False
    if not enabled:
        try:
            link.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            log.warning("could not remove Send To shortcut: %s", exc)
            return False
        return True

    program, args = launch_command()
    arguments = " ".join(_quote(a) for a in args)
    icon = Path(program)
    from .config import ASSETS_DIR

    # The exe carries the icon itself; its bundled assets live in a temporary folder that goes
    # away when it closes, so a shortcut must never point there.
    if not getattr(sys, "frozen", False) and (ASSETS_DIR / "icon.ico").exists():
        icon = ASSETS_DIR / "icon.ico"
    # Values travel as environment variables: no quoting problems with odd paths.
    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:SAT_LNK);"
        "$s.TargetPath = $env:SAT_TARGET;"
        "$s.Arguments = $env:SAT_ARGS;"
        "$s.IconLocation = $env:SAT_ICON;"
        "$s.Description = 'Convert with Satsuma';"
        "$s.Save()"
    )
    env = dict(os.environ, SAT_LNK=str(link), SAT_TARGET=program, SAT_ARGS=arguments,
               SAT_ICON=f"{icon},0")
    try:
        link.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                       env=env, capture_output=True, stdin=subprocess.DEVNULL, timeout=30, creationflags=0x08000000)
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("could not create Send To shortcut: %s", exc)
        return False
    return link.exists()
