"""OpenSoul in its own window instead of a browser tab (macOS app; anywhere pywebview works if OPENSOUL_WINDOW=1).

The window is pywebview (BSD-3-Clause; on macOS a native WKWebView via PyObjC, MIT) pointed at OpenSoul's own server on
127.0.0.1. It only ever loads that address; other links open in the normal browser. Closing the window (or OpenSoul >
Quit OpenSoul, Cmd-Q) quits OpenSoul: the launcher then stops the server. If the server goes away first (Quit in the
app's corner), the window closes too. If pywebview is missing or can't start, ``run`` returns False and the launcher
opens the browser instead, exactly as before.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from typing import Callable

TITLE = "OpenSoul"
SIZE = (1280, 860)
MIN_SIZE = (960, 640)


def wanted(env: dict | None = None, platform: str | None = None) -> bool:
    """Own window when OPENSOUL_WINDOW says so, or by default inside the Mac app (OPENSOUL_APP=mac). Linux and Windows
    packages keep opening the browser unless OPENSOUL_WINDOW=1."""
    env = os.environ if env is None else env
    v = (env.get("OPENSOUL_WINDOW") or "").strip().lower()
    if v in ("0", "no", "browser", "off"):
        return False
    if v in ("1", "yes", "window", "on"):
        return True
    return (platform or sys.platform) == "darwin" and env.get("OPENSOUL_APP") == "mac"


def available() -> bool:
    try:
        import webview  # noqa: F401
    except Exception:
        return False
    return True


def _mac_identity(icon: str | None) -> None:
    """Dock name and icon: macOS takes them from the bundle (the launcher execs Python inside OpenSoul.app's process);
    this sets them again in case the Python binary's own identity wins. Best effort, never fatal."""
    try:
        from Foundation import NSBundle  # type: ignore

        info = NSBundle.mainBundle().infoDictionary()
        if info is not None:
            info["CFBundleName"] = TITLE
            info["CFBundleDisplayName"] = TITLE
    except Exception:
        pass
    if icon and Path(icon).is_file():
        try:
            from AppKit import NSApplication, NSImage  # type: ignore

            img = NSImage.alloc().initWithContentsOfFile_(icon)
            if img is not None:
                NSApplication.sharedApplication().setApplicationIconImage_(img)
        except Exception:
            pass


def _watch(window, alive: Callable[[], bool], every: float = 1.0, misses: int = 3) -> None:
    """Close the window when the server has stopped answering for a few seconds (Quit in the app's corner)."""
    missed = 0
    while True:
        time.sleep(every)
        if alive():
            missed = 0
            continue
        missed += 1
        if missed >= misses:
            try:
                window.destroy()
            except Exception:
                pass
            return


def run(url: str, alive: Callable[[], bool], storage: Path | None = None, icon: str | None = None,
        webview_module=None) -> bool:
    """Show OpenSoul at ``url`` in its own window and block until it closes. True if the window was shown."""
    try:
        webview = webview_module or __import__("webview")
    except Exception as e:
        print(f"OpenSoul window unavailable ({e.__class__.__name__}: {e}); using the browser.", file=sys.stderr)
        return False
    try:
        settings = getattr(webview, "settings", None)  # pywebview 5+: a mapping of known keys
        for k, v in (("ALLOW_DOWNLOADS", True), ("OPEN_EXTERNAL_LINKS_IN_BROWSER", True)):
            try:
                settings[k] = v  # downloads: exported films and clips save to Downloads
            except Exception:
                pass
        if sys.platform == "darwin":
            _mac_identity(icon)
        window = webview.create_window(TITLE, url, width=SIZE[0], height=SIZE[1], min_size=MIN_SIZE,
                                       text_select=True)
        kw = {"private_mode": False}
        if storage:
            Path(storage).mkdir(parents=True, exist_ok=True)
            kw["storage_path"] = str(storage)
        threading.Thread(target=_watch, args=(window, alive), daemon=True).start()
        webview.start(**kw)
        return True
    except Exception as e:  # no GUI, missing backend, ...: the browser still works
        print(f"OpenSoul window couldn't open ({e.__class__.__name__}: {e}); using the browser.", file=sys.stderr)
        return False
