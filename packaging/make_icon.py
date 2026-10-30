#!/usr/bin/env python3
"""Re-draw the 1024 px icon master (packaging/icon/OpenSoul-1024.png) from app/web/static/opensoul-icon.svg.

    pip install playwright && playwright install chromium
    python packaging/make_icon.py

Only needed after editing the SVG. build_bundle.py turns the PNG into .icns (16-1024 px), .ico and .png with Pillow,
so packaging itself needs no SVG renderer and no iconutil.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SVG = ROOT / "app" / "web" / "static" / "opensoul-icon.svg"
OUT = ROOT / "packaging" / "icon" / "OpenSoul-1024.png"


def main() -> int:
    from playwright.sync_api import sync_playwright

    svg = SVG.read_text(encoding="utf-8").replace("<svg ", '<svg width="1024" height="1024" ', 1)
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1024, "height": 1024})
        pg.set_content(f"<html><body style='margin:0;background:transparent'>{svg}</body></html>")
        OUT.parent.mkdir(parents=True, exist_ok=True)
        pg.screenshot(path=str(OUT), omit_background=True, clip={"x": 0, "y": 0, "width": 1024, "height": 1024})
        b.close()
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
