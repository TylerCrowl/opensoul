#!/usr/bin/env python3
"""Build assets/demo_samples/ (the dry-run demo characters Lumi + Pixel) from the committed character art. CPU only.

    python scripts/make_demo_samples.py

Lumi: pack refs + demo stills are crops of the v3 sheet (assets/lumi/lumi_character_sheet_v3_trimmed.jpg); the
"Needs a redo" still is the close-up from the retired v1 look (assets/lumi/lumi_character_sheet_v1.jpg), off-model on
purpose so the look check visibly fails. Pixel: the Apache-2.0 geometric placeholder (assets/example_character/).
Every file is re-encoded as PNG, so the demo pictures have their own fingerprints (app/server.py _demo_hashes).
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
LUMI = ROOT / "assets" / "lumi"
OUT = ROOT / "assets" / "demo_samples"

# v3 trimmed sheet: 1200x1100, a 3x2 grid under a title bar, a caption strip under each row.
V3_CELLS = {"full_front": (0, 47, 400, 645), "full_side": (400, 47, 800, 645), "close_front": (0, 674, 400, 1072),
            "close_side": (400, 674, 800, 1072)}
V1_CLOSE_FRONT = (21, 1347, 852, 2592)  # v1 sheet 2576x2668


def crop(src: Path, box, dest: Path, size=None) -> Path:
    im = Image.open(src).convert("RGB").crop(box)
    if size:
        im = cover(im, size)
    dest.parent.mkdir(parents=True, exist_ok=True)
    im.save(dest, optimize=True)
    return dest


def cover(im: Image.Image, size) -> Image.Image:
    w, h = size
    s = max(w / im.width, h / im.height)
    im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    x, y = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


# The CI placeholder carries a caption box (top left) and a license footnote (bottom left). On a character card or as a
# reference picture they read as a stray white rectangle and stray text, so the demo copy paints them out.
PIXEL_LABELS = ((36, 36, 425, 105), (40, 705, 600, 745))


def pixel_card(im: Image.Image) -> Image.Image:
    from PIL import ImageDraw

    im = im.copy()
    bg = im.getpixel((8, 8))
    d = ImageDraw.Draw(im)
    for box in PIXEL_LABELS:
        d.rectangle(box, fill=bg)
    return im


def main() -> None:
    lock = json.loads((LUMI / "character.json").read_text())["prompt_lock"]
    sheet = LUMI / "lumi_character_sheet_v3_trimmed.jpg"
    pack = OUT / "lumi_pack"
    if pack.exists():
        shutil.rmtree(pack)
    refs = [crop(sheet, V3_CELLS["full_front"], pack / "refs" / "ref_00.png"),
            crop(sheet, V3_CELLS["close_front"], pack / "refs" / "ref_01.png"),
            crop(sheet, V3_CELLS["close_side"], pack / "refs" / "ref_02.png")]
    (pack / "pack.json").write_text(json.dumps({
        "name": "Lumi", "prompt_lock": lock,
        "negative_prompt": "deformed, extra fingers, bad anatomy, lowres, watermark, text, logo", "seed": 42,
        "ref_images": [f"refs/{r.name}" for r in refs], "lora_path": None, "lora_strength": 0.8,
        "notes": "Demo pack: crops of assets/lumi/lumi_character_sheet_v3_trimmed.jpg (scripts/make_demo_samples.py).",
        "created_at": "2026-10-18T23:30:00+00:00", "meta": {}}, indent=2) + "\n")
    stills = [crop(sheet, V3_CELLS["full_front"], OUT / "lumi_still_01_front.png", (768, 960)),
              crop(sheet, V3_CELLS["full_side"], OUT / "lumi_still_02_side.png", (768, 960)),
              crop(sheet, V3_CELLS["close_front"], OUT / "lumi_still_03_close.png", (768, 960)),
              crop(LUMI / "lumi_character_sheet_v1.jpg", V1_CLOSE_FRONT, OUT / "lumi_still_reject_demo.png", (768, 960))]
    # Sheet preview 1280x720 (letterboxed) and a 9:16 poster from the v3 cold-open start frame.
    im = Image.open(sheet).convert("RGB")
    im.thumbnail((1280, 720), Image.LANCZOS)
    prev = Image.new("RGB", (1280, 720), (236, 236, 240))
    prev.paste(im, ((1280 - im.width) // 2, (720 - im.height) // 2))
    prev.save(OUT / "lumi_sheet_preview.jpg", quality=88)
    cover(Image.open(LUMI / "concepts" / "v3_cold_open.jpg").convert("RGB"), (720, 1280)).save(OUT / "lumi_video_poster.png", optimize=True)
    # Pixel (second demo character).
    px = OUT / "pixel_pack"
    if px.exists():
        shutil.rmtree(px)
    (px / "refs").mkdir(parents=True)
    pixel_card(Image.open(ROOT / "assets" / "example_character" / "pixel_reference.png").convert("RGB")).save(px / "refs" / "ref_00.png", optimize=True)
    (px / "pack.json").write_text(json.dumps({
        "name": "Pixel", "prompt_lock": "Pixel, a small friendly geometric robot: rounded square head with two round eyes, "
        "boxy body, short arms, flat pastel colours", "negative_prompt": "deformed, lowres, watermark, text, logo",
        "seed": 42, "ref_images": ["refs/ref_00.png"], "lora_path": None, "lora_strength": 0.8,
        "notes": "Demo pack: assets/example_character/pixel_reference.png (Apache-2.0).",
        "created_at": "2026-10-18T23:30:00+00:00", "meta": {}}, indent=2) + "\n")
    try:  # real look-check scores against the pack refs (CPU patch backend); None if it can't run here
        import sys

        sys.path.insert(0, str(ROOT))
        from opensoul.consistency import score_consistency

        scores = [score_consistency(s, refs, threshold=0.78, mode="mean") for s in stills]
        rows = [{"file": s.name, "score": round(float(r.score), 4), "passed": bool(r.passed)} for s, r in zip(stills, scores)]
    except Exception as e:  # noqa: BLE001
        print("scoring skipped:", e)
        rows = [{"file": s.name, "score": None, "passed": "reject" not in s.name} for s in stills]
    for r in rows:  # the CPU patch score can't tell the v1 and v3 looks apart; this one is off-model by design
        if "reject" in r["file"]:
            r.update(score=None, passed=False, note="retired v1 look (long ears, apron), marked by hand as the 'Needs a redo' example")
    (OUT / "scores.json").write_text(json.dumps({"demo_stills": rows, "pack": "assets/demo_samples/lumi_pack"}, indent=2) + "\n")
    print(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
