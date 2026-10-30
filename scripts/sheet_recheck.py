#!/usr/bin/env python3
"""Re-run the auto-fix checks (current question set) on images of an existing sheet, without rendering.

  python scripts/sheet_recheck.py SHEET_DIR VIEW_ID:IMAGE [VIEW_ID:IMAGE ...]
Loads the local VLM once (on demand, waits for OPENSOUL_MIN_FREE_GB headroom) and prints one JSON line per image.
"""
import json, logging, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from opensoul import sheet_check as sc  # noqa: E402
from opensoul.character_sheet import load_preset, make_vlm  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
man = json.loads(Path(sys.argv[1], "sheet.json").read_text())
views = {v["id"]: v for v in load_preset()["views"]}
vlm = make_vlm()
if vlm is None:
    sys.exit("no local VLM")
try:
    for arg in sys.argv[2:]:
        vid, img = arg.split(":", 1)
        ev = sc.evaluate(views[vid], img, man["checklist"], vlm, patch=1.0, patch_ok=True)
        print(json.dumps({"view": vid, "image": img, "failed": ev.failed,
                          "answers": {c["id"]: c["answer"] for c in ev.checks}}), flush=True)
finally:
    vlm.release(force=True)
