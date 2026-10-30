"""Narrow-width (phone, 390px) screenshots of the storyboard flow. Runs against a dry-run server.

    OPENSOUL_DATA=/tmp/copy OPENSOUL_DRY_RUN=1 .venv/bin/python -m uvicorn app.server:app --port 8799
    .venv/bin/python scripts/storyboard_mobile_shots.py --base http://127.0.0.1:8799 --out shots/storyboard --start 51
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

SCRIPT = (Path(__file__).resolve().parents[1] / "tests/fixtures/scripts/numbered_skate.txt").read_text()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8799")
    ap.add_argument("--out", default=os.environ.get("OPENSOUL_SHOTS_DIR", "shots/storyboard"))
    ap.add_argument("--start", type=int, default=51)
    ap.add_argument("--width", type=int, default=390)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    n = [a.start]
    overflow: list[str] = []

    def snap(pg, name: str, full: bool = False) -> None:
        pg.wait_for_timeout(350)
        w = pg.evaluate("() => Math.max(document.documentElement.scrollWidth, document.body.scrollWidth)")
        if w > a.width + 1:
            overflow.append(f"{name}: page is {w}px wide")
        p = out / f"{n[0]:02d}_{name}.png"
        pg.screenshot(path=str(p), full_page=full)
        print(p, f"(scrollWidth {w})")
        n[0] += 1

    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page(viewport={"width": a.width, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
        pg.goto(f"{a.base}/?view=storyboard&story=lumi-night-shift")
        pg.wait_for_selector(".sb-card")
        snap(pg, "mobile_storyboard_demo")
        pg.locator(".sb-card").nth(0).click()
        pg.wait_for_selector("#sbSheetName")
        snap(pg, "mobile_shot_sheet")
        pg.click("#sbClose")
        pg.click("#sbNewStory")
        pg.wait_for_selector(".sb-tpl")
        snap(pg, "mobile_new_story")
        pg.click('.sb-tpl[data-t="script"]')
        pg.fill("#sbScript", SCRIPT)
        pg.click("#sbSplit")
        pg.wait_for_selector(".sb-srow-beat")
        snap(pg, "mobile_script_split")
        pg.locator(".sb-srow-beat").nth(1).scroll_into_view_if_needed()
        snap(pg, "mobile_script_rows")
        pg.click("#sbScriptDone")
        pg.wait_for_selector(".sb-card")
        snap(pg, "mobile_story_from_script")
        pg.click('.vs-btn[data-view="export"]')
        pg.wait_for_timeout(500)
        snap(pg, "mobile_export")
        pg.click('.vs-btn[data-view="create"]')
        snap(pg, "mobile_create")
        b.close()
    print("overflow:", overflow or "none")


if __name__ == "__main__":
    main()
