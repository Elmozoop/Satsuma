"""Report a problem: opens a new GitHub issue on Satsuma's repository, already filled in with the
Satsuma and Windows versions. The recent log goes on the clipboard, for the user to paste in if they
want; nothing is sent by Satsuma itself.
"""
from __future__ import annotations

import os
import platform
import sys
from urllib.parse import urlencode

from .config import GITHUB_REPO, LOG_FILE, VERSION

LOG_LINES = 150


def system_line() -> str:
    kind = "exe" if getattr(sys, "frozen", False) else "from source"
    if sys.platform == "win32":
        build = sys.getwindowsversion().build
        windows = f"Windows {'11' if build >= 22000 else '10'} (build {build})"
    else:
        windows = platform.platform()
    return f"Satsuma {VERSION} ({kind}) · {windows}"


def recent_log(lines: int = LOG_LINES) -> str:
    """The end of the log, with the user's home folder shortened so their name isn't in it."""
    try:
        text = LOG_FILE.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    tail = "\n".join(text.splitlines()[-lines:])
    home = os.path.expanduser("~")
    if home and home != "~":
        tail = tail.replace(home, "%USERPROFILE%")
    return tail


def issue_url(problem: str = "", details: str = "") -> str:
    body = "\n".join([
        "**What happened?**",
        details or "",
        "",
        "**What did you do just before?** (the kind of file, which action…)",
        "",
        "",
        "---",
        system_line(),
        "",
        "<details><summary>Log</summary>",
        "",
        "```",
        "Satsuma copied its recent log to your clipboard: paste it here (Ctrl+V), or delete this part.",
        "```",
        "</details>",
    ])
    title = f"Problem: {problem}" if problem else ""
    return f"https://github.com/{GITHUB_REPO}/issues/new?" + urlencode({"title": title, "body": body})


def report(problem: str = "", details: str = "") -> str:
    """Put the log on the clipboard and open the pre-filled issue in the browser."""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices, QGuiApplication

    log = recent_log()
    if log:
        QGuiApplication.clipboard().setText(log)
    url = issue_url(problem, details)
    QDesktopServices.openUrl(QUrl(url))
    return url
