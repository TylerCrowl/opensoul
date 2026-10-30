"""Era post-processing: the "look" of a shot, applied with ffmpeg after video.

* ``iphone_ugc``: subtle temporal grain, handheld micro-shake, natural grade.
* ``film_35mm``: heavier grain, gate weave, warm grade, vignette.

Params come from ``presets/eras.json`` ("post"). Runs on CPU, so it also runs
in dry-run mode.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from opensoul.presets import load_presets


class EraError(RuntimeError):
    pass


def era_params(era: str) -> dict:
    for e in load_presets()["eras"]:
        if e["id"] == era:
            return e["post"]
    raise KeyError(era)


def build_filter(post: dict) -> str:
    """Return an ffmpeg -vf chain for the given post params. Output keeps input size."""
    f: list[str] = []
    shake = float(post.get("shake", 0))
    weave = float(post.get("weave", 0))
    pad = int(max(shake, weave) * 2 + 2) if (shake or weave) else 0
    if pad:
        # Handheld micro-shake: two slow sines per axis. Gate weave: small jitter, mostly horizontal.
        x = f"{pad}/2"
        y = f"{pad}/2"
        if shake:
            x += f"+{shake}*sin(2*PI*t*1.3)+{shake / 2}*sin(2*PI*t*3.1)"
            y += f"+{shake}*cos(2*PI*t*1.1)+{shake / 2}*sin(2*PI*t*2.7)"
        if weave:
            x += f"+{weave}*(random(1)-0.5)"
            y += f"+{weave / 2}*(random(2)-0.5)"
        f.append(f"crop=iw-{2 * pad}:ih-{2 * pad}:'{x}':'{y}'")
        f.append(f"scale=iw+{2 * pad}:ih+{2 * pad}:flags=bicubic")
    sat = float(post.get("saturation", 1.0))
    con = float(post.get("contrast", 1.0))
    if sat != 1.0 or con != 1.0:
        f.append(f"eq=saturation={sat}:contrast={con}")
    warm = float(post.get("warmth", 0))
    if warm:
        f.append(f"colorbalance=rm={warm}:gm={warm / 3}:bm={-warm}:rh={warm / 2}:bh={-warm / 2}")
    vig = float(post.get("vignette", 0))
    if vig:
        f.append(f"vignette=angle=PI/{max(2.5, 6 - 4 * vig):.2f}")
    grain = int(post.get("grain", 0))
    if grain:
        f.append(f"noise=alls={grain}:allf=t+u")
    f.append("format=yuv420p")
    return ",".join(f)


def build_command(src: Path, dest: Path, era: str) -> list[str]:
    return [
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
        "-vf", build_filter(era_params(era)),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "copy", "-movflags", "+faststart", str(dest),
    ]


def apply_era(src: str | Path, dest: str | Path, era: str) -> Path:
    src, dest = Path(src), Path(dest)
    from opensoul.media import ffmpeg_bin

    exe = ffmpeg_bin()
    if not exe:
        raise EraError("ffmpeg is not installed; install it to apply the Era look.")
    if not src.is_file():
        raise EraError(f"Input video not found: {src}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([exe, *build_command(src, dest, era)[1:]], capture_output=True, text=True, check=False)
    if r.returncode != 0 or not dest.is_file():
        raise EraError(f"ffmpeg failed: {r.stderr.strip()[:400]}")
    return dest
