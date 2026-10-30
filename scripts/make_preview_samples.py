"""Build assets/demo_preview/ (the Preview mode sample pack) and assets/juno_pell/ from the Spin Cycle renders.

Run once on the production computer; the sources are not in this repo. CPU only (ffmpeg + Pillow).
    python scripts/make_preview_samples.py <music_video_folder>
Every output is re-encoded (no metadata kept except an "AI-generated" comment) and carries a small burned-in
"AI-generated sample" label. Provenance: assets/demo_preview/PROVENANCE.md.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "demo_preview"
JUNO = ROOT / "assets" / "juno_pell"
FILM = "MV_v2_2.mp4"  # the cleared cut (0 FAIL in its content audit)
# (name, start s, seconds, what it shows): whole single-take spans of the cut (one take each, no splice inside)
CLIPS = [("clip_folding", 16.68, 3.0, "Juno folds a towel at the laundromat table (wide)."),
         ("clip_disco_wide", 27.62, 2.9, "The laundromat turns into a disco; Juno dances (wide)."),
         ("clip_sock", 43.97, 3.0, "Juno sings and holds up a lost sock (medium)."),
         ("clip_tangerine", 79.67, 3.0, "Juno sings in the tangerine suit, disco lights (close)."),
         ("clip_washer_wall", 109.41, 3.0, "Juno in the tangerine suit by the glowing washers (wide).")]
STILLS = [("still_folding", 18.5), ("still_washer", 26.0), ("still_disco", 29.0), ("still_basket", 34.5),
          ("still_sock", 45.5), ("still_door", 60.8), ("still_tangerine", 81.5), ("still_washer_wall", 111.0)]
MASTER = "singer/portrait_s303.png"
SHEET = ["singer/portrait_s303.png", "singer/juno_v2/SH_threequarter_s7.png", "singer/juno_v2/SH_fullbody_s7.png",
         "singer/juno_v2/SH_outfitB_s7.png"]
LABEL = "AI-generated sample"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def label_png(w: int, h: int, dest: Path) -> Path:
    """A transparent overlay with the small corner label (bottom left)."""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=max(14, h // 48))
    except TypeError:
        font = ImageFont.load_default()
    pad = max(10, w // 40)
    tw = d.textlength(LABEL, font=font)
    th = getattr(font, "size", 14)
    d.rounded_rectangle((pad, h - pad - th - 12, pad + tw + 16, h - pad), radius=8, fill=(0, 0, 0, 140))
    d.text((pad + 8, h - pad - th - 7), LABEL, fill=(255, 255, 255, 235), font=font)
    img.save(dest)
    return dest


def labelled(img: Image.Image) -> Image.Image:
    tmp = OUT / ".label.png"
    label_png(img.width, img.height, tmp)
    out = Image.alpha_composite(img.convert("RGBA"), Image.open(tmp)).convert("RGB")
    tmp.unlink()
    return out


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True)


def main(src: Path) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    JUNO.mkdir(parents=True, exist_ok=True)
    film = src / FILM
    record = {"film": {"file": FILM, "sha256": sha(film)}, "clips": [], "stills": [], "juno": {}}
    w, h = 540, 960
    lab = label_png(w, h, OUT / ".clip_label.png")
    for name, t0, secs, what in CLIPS:
        dest = OUT / f"{name}.mp4"
        run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t0}", "-t", f"{secs}", "-i", str(film), "-i", str(lab),
             "-filter_complex", f"[0:v]scale={w}:{h}:flags=lanczos,fps=24[v];[v][1:v]overlay=0:0,format=yuv420p[o]",
             "-map", "[o]", "-map", "0:a:0", "-c:v", "libx264", "-preset", "slow", "-crf", "28", "-profile:v", "high",
             "-c:a", "aac", "-b:a", "64k", "-ac", "1", "-map_metadata", "-1", "-metadata", "comment=AI-generated video",
             "-movflags", "+faststart", str(dest)])
        poster = OUT / f"{name}.jpg"
        run(["ffmpeg", "-y", "-v", "error", "-ss", "1.0", "-i", str(dest), "-frames:v", "1", "-q:v", "4", str(poster)])
        record["clips"].append({"file": dest.name, "poster": poster.name, "from": FILM, "start_s": t0, "seconds": secs,
                                "shows": what})
    lab.unlink()
    for name, t in STILLS:
        tmp = OUT / f".{name}.png"
        run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t}", "-i", str(film), "-frames:v", "1",
             "-vf", f"scale={w}:{h}:flags=lanczos", str(tmp)])
        labelled(Image.open(tmp)).save(OUT / f"{name}.jpg", quality=80, optimize=True, progressive=True)
        tmp.unlink()
        record["stills"].append({"file": f"{name}.jpg", "from": FILM, "time_s": t})
    master = Image.open(src / MASTER).convert("RGB")
    ImageOps.contain(master, (640, 960)).save(JUNO / "juno_ref_00.jpg", quality=84, optimize=True)
    views = [Image.open(src / f).convert("RGB") for f in SHEET]
    vh = 720
    views = [v.resize((round(v.width * vh / v.height), vh), Image.LANCZOS) for v in views]
    sheet = Image.new("RGB", (sum(v.width for v in views), vh), (128, 128, 128))
    x = 0
    for v in views:
        sheet.paste(v, (x, 0))
        x += v.width
    sheet.save(JUNO / "juno_character_sheet_v1.jpg", quality=82, optimize=True, progressive=True)
    record["juno"] = {"reference": {"file": "juno_ref_00.jpg", "from": MASTER, "sha256": sha(src / MASTER)},
                      "sheet": {"file": "juno_character_sheet_v1.jpg",
                                "from": [{"file": f, "sha256": sha(src / f)} for f in SHEET]}}
    (OUT / "build.json").write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(Path(sys.argv[1])))
