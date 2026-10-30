"""Stage sheets: continuity for places, the way character sheets keep a face the same.

A stage sheet is one locked master plate (wide / establishing), 3-4 consistent angles of the SAME room,
an empty plate and a set description + checklist. Angles are made by editing the master plate
(Qwen-Image-Edit) with a camera-move prompt that pins the set block; the sheet image puts them side by side
so a human can check by eye that it really is one room.
"""
from __future__ import annotations

import re

from pathlib import Path

# Default angles for an interior with a counter (shop, bar, café, reception). The prompts move only the camera.
DEFAULT_ANGLES = [
    {"name": "behind the counter", "note": "the camera stands behind the counter beside the register and looks out "
     "across the counter top toward the shop floor, the glass door and the rainy street window"},
    {"name": "customer side", "note": "the camera stands on the shop floor in front of the counter, facing the "
     "register and the clerk's side straight on, the shelves and wall panels behind the counter"},
    {"name": "window side", "note": "the camera stands by the front window and looks along the length of the "
     "counter toward the back of the store, the window and its rain on one side of the frame"},
    {"name": "medium at register", "note": "the same master angle, closer: a medium shot of the register end of the "
     "counter, waist-high, the same shelves and window behind"},
]


# Angles any stage can start from (the UI's "Make angles"): the same room, the camera moved. The konbini ones above
# are the demo stage's own.
GENERIC_ANGLES = [
    {"name": "reverse angle", "note": "the camera turns around and looks back the other way across the same room, "
     "toward where the master shot was taken from"},
    {"name": "from the left", "note": "the camera stands at the left side of the room and looks across it, the main "
     "features of the master shot seen from the side"},
    {"name": "from the right", "note": "the camera stands at the right side of the room and looks across it, the main "
     "features of the master shot seen from the other side"},
    {"name": "medium", "note": "the same master angle, closer: a waist-high medium shot of the middle of the set, the "
     "same background behind"},
]


def angle_note(name: str) -> str:
    """The suggested note for a known angle name (generic or demo), else ""."""
    key = " ".join(str(name or "").split()).lower()
    return next((a["note"] for a in GENERIC_ANGLES + DEFAULT_ANGLES if a["name"] == key), "")


def angle_prompt(note: str, description: str = "", look: str = "") -> str:
    """The edit prompt for one new angle of a stage. The 'keep' sentence names only what picture 1 shows (and the
    stage's own description), never the demo store's counter or its night rain (OS-012); the look sets the style."""
    from opensoul import looks

    desc = (description or "").strip().rstrip(".")
    closer = bool(re.search(r"\b(medium|close|closer|tight)\b", note or "", re.I))
    return ("Picture 1 is the master plate of a set. Show the SAME place from a different camera position: "
            f"{note.rstrip('.')}. Keep every element of the place identical in design, materials and colors, and keep "
            "the same light, weather and time of day as in picture 1; only the viewpoint changes."
            + (" The camera is much closer than in picture 1." if closer else "")
            + " Nobody in the place. No animals. No readable text, no logos, no brands. "
            + looks.get(look)["still"] + (f" The set: {desc}." if desc else ""))


def build_sheet(master: str | Path, angles: list[tuple[str, str | Path]], out: str | Path, *, empty: str | Path | None = None,
                title: str = "", checklist: list[str] | None = None, tile_w: int = 640) -> Path:
    """Render the stage sheet: master plate large on top, then the empty plate and the angles in a grid,
    each with a small caption, plus the checklist. Returns `out` (jpg/png)."""
    from PIL import Image, ImageDraw, ImageFont

    def load(p, w):
        im = Image.open(p).convert("RGB")
        return im.resize((w, round(im.height * w / im.width)))

    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 20)
        big = ImageFont.truetype("DejaVuSans-Bold.ttf", 26)
    except OSError:
        font = big = ImageFont.load_default()
    tiles = ([("empty plate", empty)] if empty else []) + list(angles)
    cols = 2 if len(tiles) <= 4 else 3
    W = tile_w * cols + 16 * (cols + 1)
    hero = load(master, W - 32)
    th = round(tile_w * hero.height / hero.width)
    cap = 34
    rows = (len(tiles) + cols - 1) // cols
    checklist = checklist or []
    H = 60 + hero.height + cap + rows * (th + cap + 16) + 16 + (30 * len(checklist) + 20 if checklist else 0)
    sheet = Image.new("RGB", (W, H), (24, 24, 28))
    d = ImageDraw.Draw(sheet)
    d.text((16, 16), f"STAGE SHEET · {title}" if title else "STAGE SHEET", fill=(235, 235, 235), font=big)
    y = 60
    sheet.paste(hero, (16, y)); y += hero.height
    d.text((16, y + 6), "master plate · wide (locked)", fill=(200, 200, 200), font=font); y += cap
    for i, (name, path) in enumerate(tiles):
        x = 16 + (i % cols) * (tile_w + 16)
        yy = y + (i // cols) * (th + cap + 16)
        t = load(path, tile_w)
        sheet.paste(t.crop((0, 0, tile_w, min(th, t.height))), (x, yy))
        d.text((x, yy + th + 6), name, fill=(200, 200, 200), font=font)
    y += rows * (th + cap + 16) + 8
    for j, item in enumerate(checklist):
        d.text((16, y + 30 * j), f"□ {item}", fill=(190, 190, 190), font=font)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, quality=92)
    return out
