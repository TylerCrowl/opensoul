"""Screenshots of the Storyboard flows (Create → Storyboard → Export) for review.

Run against a PREVIEW server on a throwaway copy of the data folder, never the real one:

    cp -a data/projects data/packs /tmp/os_shot_data/
    OPENSOUL_DATA=/tmp/os_shot_data OPENSOUL_DRY_RUN=1 python -m uvicorn app.server:app --port 8799
    python scripts/storyboard_screenshots.py --base http://127.0.0.1:8799 --out shots/storyboard --start 33

Needs Playwright (``pip install playwright && playwright install chromium``). No GPU, no models.
"""
from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

SCRIPT = """# The Last Bus
INT. BUS STOP - NIGHT
Rain. Kai waits alone under a flickering light. Close on his tired face.
KAI
Come on, come on.

EXT. EMPTY ROAD - CONTINUOUS
The bus appears out of the fog. The camera pulls back to reveal the empty city.

INT. BUS - LATER
Kai sits by the window. Ada, the night driver, glances at him in the mirror.
ADA: Last stop is the sea.

EXT. SEASIDE - DAWN
The camera circles around Kai as the sun comes up over the water.
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8799")
    ap.add_argument("--out", default=os.environ.get("OPENSOUL_SHOTS_DIR", "shots/storyboard"))
    ap.add_argument("--start", type=int, default=33)
    a = ap.parse_args()
    from PIL import Image, ImageDraw
    from playwright.sync_api import sync_playwright

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    n = [a.start]
    shots: list[str] = []

    def snap(pg, name: str, full: bool = False) -> None:
        pg.wait_for_timeout(450)
        p = out / f"{n[0]:02d}_{name}.png"
        pg.screenshot(path=str(p), full_page=full)
        shots.append(str(p))
        n[0] += 1

    # a neutral stand-in picture for the "new character from a reference picture" step (no real person)
    tmp = Path(tempfile.mkdtemp())
    pic = tmp / "kai_reference.png"
    img = Image.new("RGB", (640, 960), "#dfe6ee")
    d = ImageDraw.Draw(img)
    d.ellipse((240, 170, 400, 330), fill="#7d8fa3")
    d.rounded_rectangle((180, 360, 460, 760), radius=90, fill="#e2b33c")
    img.save(pic)

    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
        errs: list[str] = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.on("dialog", lambda dlg: dlg.accept())

        # 1. the demo story with the new flow bar and inline-editable shot names
        pg.goto(f"{a.base}/?view=storyboard&story=lumi-night-shift")
        pg.wait_for_selector(".sb-card")
        snap(pg, "flow_bar_demo_strip")

        # 2. a NEW story from the Lumi template (a copy; the demo itself is never edited here)
        pg.click("#sbNewStory")
        pg.wait_for_selector(".sb-tpl")
        pg.fill("#sbStoryName", "Night Shift (my copy)")
        pg.click('.sb-tpl[data-t="lumi-night-shift"]')
        pg.fill("#sbStoryName", "Night Shift (my copy)")
        snap(pg, "new_story_templates")
        pg.click("#sbStoryMake")
        pg.wait_for_selector(".sb-card")
        # inline rename on the card
        inp = pg.locator(".sb-card input.sb-beat").first
        inp.click()
        inp.fill("Rainy cold open")
        snap(pg, "rename_shot_inline")
        inp.press("Enter")
        pg.wait_for_timeout(500)
        # hover tools + delete with Undo
        card = pg.locator(".sb-card").nth(2)
        card.hover()
        card.locator('[data-act="del"]').click()
        pg.wait_for_selector("#sbUndo")
        snap(pg, "delete_shot_undo_toast")
        pg.click("#sbUndo")
        pg.wait_for_timeout(600)
        print("after undo:", pg.eval_on_selector_all(".sb-card input.sb-beat", "e => e.map(x => x.value)"))

        # 3. a blank story: empty state, add a shot, cast chips, new character
        pg.click("#sbNewStory")
        pg.wait_for_selector(".sb-tpl")
        pg.fill("#sbStoryName", "Courier")
        snap(pg, "new_story_blank_selected")
        pg.click("#sbStoryMake")
        pg.wait_for_selector("#sbEmpty:not([hidden])")
        snap(pg, "blank_story_empty_state")
        pg.click("#sbAddFirst")
        pg.wait_for_selector("#sbNewBeat")
        pg.fill("#sbNewBeat", "Doorstep")
        pg.fill("#sbNewPrompt", "A courier in a yellow rain jacket rings the bell, holding a small box.")
        pg.select_option("#sbNewCam", "push_in_gentle")
        snap(pg, "new_shot_form_cast_chips")
        pg.click("#sbNewCast [data-new]")
        pg.wait_for_selector("#sbCName")
        pg.fill("#sbCName", "Kai")
        pg.set_input_files("#sbCFile", str(pic))
        pg.check("#sbCConsent")
        pg.fill("#sbCDesc", "a tall courier in his thirties, short black hair, yellow rain jacket")
        snap(pg, "new_character_from_reference")
        pg.click("#sbCSave")
        pg.wait_for_selector("#sbNewBeat")
        snap(pg, "new_character_added_to_shot")
        pg.click("#sbNewAdd")
        pg.wait_for_selector("#sbSheetName")
        snap(pg, "shot_sheet_cast_camera")
        pg.click("#sbClose")

        # 4. start from a script
        pg.click("#sbNewStory")
        pg.wait_for_selector(".sb-tpl")
        pg.click('.sb-tpl[data-t="script"]')
        pg.wait_for_selector("#sbScript")
        pg.fill("#sbScript", SCRIPT)
        snap(pg, "script_paste")
        pg.click("#sbSplit")
        pg.wait_for_selector(".sb-srow")
        pg.locator(".sb-srow-beat").nth(1).fill("The bus arrives")
        snap(pg, "script_split_editable")
        pg.locator("#sbSheet").evaluate("e => e.scrollTo(0, e.scrollHeight)")
        snap(pg, "script_split_bottom")
        pg.click("#sbScriptDone")
        pg.wait_for_selector(".sb-card")
        snap(pg, "story_from_script_strip")
        pg.locator(".sb-card").nth(2).click()
        pg.wait_for_selector("#sbSheetName")
        snap(pg, "script_shot_missing_cast")
        pg.click("#sbRegen")
        pg.wait_for_selector(".sb-film li")
        pg.click("#sbClose")

        # 5. export
        pg.click('.vs-btn[data-view="export"]')
        pg.wait_for_selector("#sbReel li")
        snap(pg, "export_review")
        pg.click("#sbExport")
        pg.wait_for_selector("#sbExportResult:not([hidden])", timeout=120000)
        snap(pg, "export_done")
        # 6. back to Create: the same flow bar, step 1
        pg.click('.vs-btn[data-view="create"]')
        pg.wait_for_selector("#step1")
        snap(pg, "create_step_in_flow")
        print("errors:", errs)
        b.close()
    print("\n".join(shots))


if __name__ == "__main__":
    main()
