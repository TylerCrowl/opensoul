#!/usr/bin/env python3
"""CPU placeholder loops for the Camera / Effects preset tiles, from committed Lumi stills (no GPU, no model).

    python scripts/make_preset_tile_placeholders.py [--only dolly_in,orbit] [--check]

Each tile is a 4 s, 24 fps, 360x630 muted H.264 loop: a 2-D move on one still (push, pull, slide, rise, sweep) or a
look change (day to night, outfit switch) made with ffmpeg. They stand in until the real LTX re-render
(see presets/demo_images.json preset_clips) passes its checks. A flat still has no parallax, so
crane and orbit placeholders read as tilts / pans to opensoul/motion_check.py: --check reports that honestly.
"""
from __future__ import annotations

import argparse
import glob
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "preset_thumbs"
W, H, FPS, N = 360, 630, 24, 97
STILL = ROOT / "assets" / "lumi" / "concepts" / "v3_real_coffee.jpg"   # Lumi at the counter (1344x768)
WIDE = ROOT / "assets" / "lumi" / "concepts" / "v3_cold_open.jpg"
OUTFIT_A = ROOT / "assets" / "demo_samples" / "lumi_still_01_front.png"  # v3 look
OUTFIT_B = ROOT / "assets" / "demo_samples" / "lumi_still_reject_demo.png"  # retired v1 look (another outfit)

# zoompan on an 8x upscale: z = zoom, (x, y) = top-left of the window in input pixels; on = output frame number.
P = f"(on/{N - 1})"            # 0 -> 1 over the clip
E = f"(0.5-0.5*cos(PI*{P}))"   # eased
MOVES = {
    "static": ("1.06", "iw/2-iw/zoom/2", "ih/2-ih/zoom/2"),
    "push_in_gentle": (f"1.05+0.3*{P}", "iw/2-iw/zoom/2", "ih/2-ih/zoom/2"),
    "dolly_in": (f"1.05+0.35*{E}", "iw/2-iw/zoom/2", "ih/2-ih/zoom/2"),
    "fpv": (f"1.05+0.6*{P}", f"iw/2-iw/zoom/2+iw*0.03*sin(2*PI*{P})", "ih/2-ih/zoom/2"),
    "crash_zoom": (f"if(lt(on,30),1.05,1.05+1.1*min(1,(on-30)/10))", "iw/2-iw/zoom/2", "ih*0.42-ih/zoom/2"),
    "dolly_zoom": (f"1.05+0.5*{E}", "iw/2-iw/zoom/2", "ih/2-ih/zoom/2"),
    "dolly_out": (f"1.40-0.35*{E}", "iw/2-iw/zoom/2", "ih/2-ih/zoom/2"),
    "dolly_left": ("1.25", f"(iw-iw/zoom)*(0.85-0.7*{E})", "ih/2-ih/zoom/2"),
    "dolly_right": ("1.25", f"(iw-iw/zoom)*(0.15+0.7*{E})", "ih/2-ih/zoom/2"),
    "jib_up": ("1.25", "iw/2-iw/zoom/2", f"(ih-ih/zoom)*(0.9-0.8*{E})"),
    "jib_down": ("1.25", "iw/2-iw/zoom/2", f"(ih-ih/zoom)*(0.1+0.8*{E})"),
    "orbit": (f"1.18+0.05*sin(PI*{P})", f"(iw-iw/zoom)*(0.1+0.8*{E})", "ih/2-ih/zoom/2"),
    "orbit_freeze": (f"1.18+0.05*sin(PI*{P})", f"(iw-iw/zoom)*(0.9-0.8*{E})", "ih/2-ih/zoom/2"),
    "earth_zoom_out": (f"2.2-1.15*{E}", "iw/2-iw/zoom/2", "ih*0.42-ih/zoom/2"),
}
WIDE_START = {"dolly_out", "jib_up", "day_to_night", "earth_zoom_out"}


def ffmpeg() -> str:
    f = shutil.which("ffmpeg")
    if not f:
        raise SystemExit("ffmpeg not found")
    return f


def base_filter(src: Path) -> str:
    # 9:16 crop of the landscape still around Lumi, then an 8x upscale so zoompan moves smoothly
    return f"scale=-2:{H * 4},crop={W * 4}:{H * 4},scale={W * 8}:{H * 8}:flags=lanczos"


def render(pid: str, dest: Path) -> None:
    ff = ffmpeg()
    dest.parent.mkdir(parents=True, exist_ok=True)
    enc = ["-an", "-c:v", "libx264", "-crf", "30", "-preset", "slow", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
           "-frames:v", str(N), "-r", str(FPS)]
    if pid == "day_to_night":
        vf = (f"{base_filter(WIDE)},scale={W}:{H},loop={N}:1:0,fps={FPS},"
              f"eq=brightness='-0.28*t/4':saturation='1-0.4*t/4':eval=frame,"
              f"colorbalance=bs=0.25:bm=0.15,format=yuv420p")
        cmd = [ff, "-y", "-loglevel", "error", "-loop", "1", "-t", "4.05", "-i", str(WIDE), "-vf", vf, *enc, str(dest)]
    elif pid == "outfit_switch":
        a = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1"
        cmd = [ff, "-y", "-loglevel", "error", "-loop", "1", "-t", "4.05", "-i", str(OUTFIT_A), "-loop", "1", "-t", "4.05",
               "-i", str(OUTFIT_B), "-filter_complex",
               f"[0]{a},fps={FPS}[a];[1]{a},fps={FPS}[b];[a][b]xfade=transition=circleopen:duration=0.8:offset=1.6,format=yuv420p",
               *enc, str(dest)]
    else:
        z, x, y = MOVES[pid]
        src = WIDE if pid in WIDE_START else STILL
        vf = f"{base_filter(src)},zoompan=z='{z}':x='{x}':y='{y}':d={N}:s={W}x{H}:fps={FPS},format=yuv420p"
        cmd = [ff, "-y", "-loglevel", "error", "-i", str(src), "-vf", vf, *enc, str(dest)]
    subprocess.run(cmd, check=True)


def presets() -> list[dict]:
    out = []
    for f in sorted(glob.glob(str(ROOT / "presets" / "camera" / "*.json"))) + sorted(glob.glob(str(ROOT / "presets" / "effects" / "*.json"))):
        p = json.loads(Path(f).read_text())
        out.append({"id": p["id"], "kind": Path(f).parent.name, "thumb": p["thumbnail"], "expect": p.get("expect_motion")})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--check", action="store_true", help="run opensoul/motion_check on each tile and print the result")
    a = ap.parse_args()
    only = {x for x in a.only.split(",") if x}
    rows = []
    for p in presets():
        if only and p["id"] not in only:
            continue
        dest = ROOT / p["thumb"].removeprefix("/")
        render(p["id"], dest)
        row = {"id": p["id"], "file": str(dest.relative_to(ROOT)), "expect": p["expect"]}
        if a.check:
            import sys

            sys.path.insert(0, str(ROOT))
            from opensoul import motion_check

            r = motion_check.check(dest, p["expect"])
            row.update(detected=r.get("label"), ok=r.get("ok"))
        rows.append(row)
        print(json.dumps(row))


if __name__ == "__main__":
    main()
