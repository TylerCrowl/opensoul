#!/usr/bin/env python3
"""Drag-to-Applications disk image for the Mac app. macOS only (dmgbuild drives macOS's hdiutil).

    pip install dmgbuild==1.6.7
    python packaging/make_dmg.py path/to/OpenSoul.app dist/OpenSoul-<ver>-mac-arm64.dmg

The desktop CI workflow's macOS jobs run this after the smoke test. There is no reliable way to write a .dmg on
Linux, so build_bundle.py only makes the .zip. The window shows OpenSoul on the left, an arrow, and an Applications
shortcut on the right; the background is drawn here with Pillow (original, no Apple artwork).
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

W, H = 600, 360
APP_XY, APPS_XY = (165, 175), (435, 175)


def background(dest: Path, scale: int = 1) -> Path:
    from PIL import Image, ImageDraw, ImageFont

    w, h = W * scale, H * scale
    im = Image.new("RGB", (w, h), (246, 246, 248))
    d = ImageDraw.Draw(im)
    for y in range(h):  # a very soft top-to-bottom wash
        t = y / h
        d.line([(0, y), (w, y)], fill=(int(250 - 8 * t), int(250 - 7 * t), int(252 - 4 * t)))
    y = APP_XY[1] * scale
    x0, x1 = (APP_XY[0] + 78) * scale, (APPS_XY[0] - 78) * scale
    d.line([(x0, y), (x1 - 14 * scale, y)], fill=(150, 156, 168), width=4 * scale)
    d.polygon([(x1, y), (x1 - 18 * scale, y - 11 * scale), (x1 - 18 * scale, y + 11 * scale)], fill=(150, 156, 168))
    try:
        font = ImageFont.load_default(size=15 * scale)
    except TypeError:
        font = ImageFont.load_default()
    text = "Drag OpenSoul into Applications"
    tw = d.textlength(text, font=font)
    d.text(((w - tw) / 2, 292 * scale), text, fill=(90, 94, 104), font=font)
    im.save(dest, dpi=(72 * scale, 72 * scale))
    return dest


def settings(app: Path, bg: Path, icon: Path | None) -> dict:
    s = {
        "format": "UDZO",
        "files": [str(app)],
        "symlinks": {"Applications": "/Applications"},
        "icon_locations": {app.name: APP_XY, "Applications": APPS_XY},
        "window_rect": ((200, 160), (W, H)),
        "icon_size": 112,
        "text_size": 13,
        "show_status_bar": False, "show_tab_view": False, "show_toolbar": False, "show_pathbar": False,
        "show_sidebar": False,
        "background": str(bg),
    }
    if icon and icon.is_file():
        s["icon"] = str(icon)
    return s


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("app")
    ap.add_argument("dmg")
    a = ap.parse_args(argv)
    app = Path(a.app).resolve()
    if sys.platform != "darwin":
        raise SystemExit("make_dmg.py needs macOS (hdiutil). On Linux, ship the .zip.")
    import dmgbuild

    with tempfile.TemporaryDirectory() as tmp:
        bg = background(Path(tmp) / "background.png")
        background(Path(tmp) / "background@2x.png", scale=2)  # dmgbuild picks up @2x for Retina screens
        icon = app / "Contents" / "Resources" / "OpenSoul.icns"
        dmgbuild.build_dmg(a.dmg, "OpenSoul", settings=settings(app, bg, icon))
    print(f"wrote {a.dmg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
