"""Offer, once, to move OpenSoul.app into Applications when it was opened from Downloads (macOS only).

    python -m opensoul.mac_move /path/to/OpenSoul.app      # mac_launcher.sh runs this before starting OpenSoul

It always asks first ("Move to Applications" / "Not Now") and never moves anything on its own. It asks once per copy
of the app; "Not Now" is remembered. Moving is a rename inside the same disk, so nothing is copied or deleted; if
Applications is on another disk it says so and leaves the app where it is. Pure Python plus macOS's own osascript
for the question. Exit codes: 3 = moved and the moved copy is opening (the caller should stop), 0 = carry on.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

MOVED = 3
QUESTION = ("OpenSoul is running from your Downloads folder. Move it to Applications, so it shows up in Launchpad "
            "and stays put when you tidy Downloads?")


def _state_file(home: Path) -> Path:
    from opensoul.launcher import home as launcher_home

    return launcher_home({"HOME": str(home)}, "darwin") / "move_prompt.json"


def original_path(app: Path) -> Path:
    """macOS may run a downloaded app from a hidden read-only copy ("App Translocation"). Ask the Security framework
    where the real one is (best effort; the app's own path otherwise)."""
    if "/AppTranslocation/" not in str(app) or sys.platform != "darwin":
        return app
    try:
        import ctypes

        cf = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        sec = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/Security.framework/Security")
        cf.CFURLCreateFromFileSystemRepresentation.restype = ctypes.c_void_p
        cf.CFURLCreateFromFileSystemRepresentation.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_bool]
        cf.CFURLGetFileSystemRepresentation.restype = ctypes.c_bool
        cf.CFURLGetFileSystemRepresentation.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_char_p, ctypes.c_long]
        cf.CFRelease.argtypes = [ctypes.c_void_p]
        sec.SecTranslocateCreateOriginalPathForURL.restype = ctypes.c_void_p
        sec.SecTranslocateCreateOriginalPathForURL.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        raw = os.fsencode(str(app))
        url = cf.CFURLCreateFromFileSystemRepresentation(None, raw, len(raw), True)
        orig = sec.SecTranslocateCreateOriginalPathForURL(url, None) if url else None
        buf = ctypes.create_string_buffer(4096)
        ok = bool(orig) and cf.CFURLGetFileSystemRepresentation(orig, True, buf, len(buf))
        for ref in (orig, url):
            if ref:
                cf.CFRelease(ref)
        return Path(os.fsdecode(buf.value)) if ok and buf.value else app
    except Exception:
        return app


def in_downloads(app: Path, home: Path) -> bool:
    try:
        return app.resolve().is_relative_to((home / "Downloads").resolve())
    except OSError:
        return False


def destination(app: Path, home: Path, system_apps: Path = Path("/Applications")) -> Path | None:
    """/Applications if this user may write there, else ~/Applications (made when moving). None if a copy is already
    in either place."""
    personal = home / "Applications"
    if any((d / app.name).exists() for d in (system_apps, personal)):
        return None
    if system_apps.is_dir() and os.access(system_apps, os.W_OK):
        return system_apps
    return personal


def ask(question: str = QUESTION, run=subprocess.run) -> bool:
    """macOS's own dialog; True only when the person clicks "Move to Applications"."""
    script = (f'display dialog "{question}" with title "OpenSoul" buttons {{"Not Now", "Move to Applications"}} '
              'default button "Move to Applications" cancel button "Not Now"')
    try:
        r = run(["/usr/bin/osascript", "-e", script], capture_output=True, text=True, timeout=600)
    except Exception:
        return False
    return r.returncode == 0 and "button returned:Move to Applications" in (r.stdout or "")


def tell(message: str, run=subprocess.run) -> None:
    try:
        run(["/usr/bin/osascript", "-e", f'display dialog "{message}" with title "OpenSoul" buttons {{"OK"}} '
             'default button "OK"'], capture_output=True, timeout=600)
    except Exception:
        pass


def offer(app: Path, home: Path | None = None, asker: Callable[[], bool] = ask, teller: Callable[[str], None] = tell,
          opener: Callable[[Path], None] | None = None, system_apps: Path = Path("/Applications")) -> int:
    home = home or Path.home()
    app = original_path(Path(app))
    if app.suffix != ".app" or not app.is_dir() or not in_downloads(app, home):
        return 0
    sf = _state_file(home)
    try:
        asked = json.loads(sf.read_text(encoding="utf-8")).get("asked", [])
    except (OSError, ValueError, AttributeError):
        asked = []
    if str(app) in asked:
        return 0
    dest_dir = destination(app, home, system_apps)
    if dest_dir is None:
        return 0
    sf.parent.mkdir(parents=True, exist_ok=True)
    sf.write_text(json.dumps({"asked": asked + [str(app)]}), encoding="utf-8")  # ask once, whatever the answer
    if not asker():
        return 0
    target = dest_dir / app.name
    try:
        dest_dir.mkdir(exist_ok=True)
        os.rename(app, target)  # same disk: a rename, nothing copied or deleted
    except OSError:
        teller(f"OpenSoul couldn't move itself to {dest_dir}. You can drag it there from Downloads in Finder.")
        return 0
    (opener or (lambda p: subprocess.Popen(["/usr/bin/open", "-n", str(p)])))(target)
    return MOVED


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if sys.platform != "darwin" or not argv:
        return 0
    try:
        return offer(Path(argv[0]))
    except Exception as e:  # never stop OpenSoul from opening over this
        print(f"move-to-Applications offer skipped: {e}", file=sys.stderr)
        return 0


if __name__ == "__main__":
    sys.exit(main())
