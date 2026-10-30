"""Preview mode samples (presets/preview_samples.json, files in assets/demo_preview/).

Preview mode has no GPU, so it can't render. Instead of a gray stand-in card, each Preview take is one of these
short clips from a real OpenSoul render, fitted to the story's frame and labelled "Preview sample from a real render".
An export of Preview takes is then a real short sample video. Without the files (or without ffmpeg) the caller
falls back to the old stand-in card."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "presets" / "preview_samples.json"


def load(config: Path | None = None) -> dict:
    try:
        cfg = json.loads((config or CONFIG).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return cfg if isinstance(cfg, dict) else {}


def _ok(rel: str | None) -> Path | None:
    rel = str(rel or "").strip().lstrip("/")
    if not rel.startswith("assets/") or ".." in Path(rel).parts:
        return None
    p = ROOT / rel
    return p if p.is_file() else None


def clips(cfg: dict | None = None) -> list[dict]:
    """The sample clips whose video and poster both exist: [{video, poster, title, video_path, poster_path}]."""
    cfg = load() if cfg is None else cfg
    out = []
    for c in cfg.get("clips") or []:
        v, p = _ok(c.get("video")), _ok(c.get("poster"))
        if v and p:
            out.append({**c, "video_path": v, "poster_path": p})
    return out


def available() -> bool:
    return bool(clips())


def pick(n: int, cfg: dict | None = None) -> dict | None:
    cs = clips(cfg)
    return cs[n % len(cs)] if cs else None


def first_run_items(limit: int = 3) -> list[dict]:
    """The start card's examples: the first sample clips, labelled as samples."""
    cfg = load()
    return [{"title": c.get("title") or "", "video_url": "/" + c["video"], "poster_url": "/" + c["poster"],
             "label": cfg.get("label") or "Sample"} for c in clips(cfg)[:limit]]


def _fit_filter(w: int, h: int) -> str:
    """Fill a w×h frame: same shape -> scale; other shape -> the clip over a blurred, darkened copy of itself."""
    return (f"[0:v]split=2[a][b];[a]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=20:2,"
            f"eq=brightness=-0.12[bg];[b]scale={w}:{h}:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,fps=24,format=yuv420p[v]")


def make_take(n: int, work: Path, size: tuple[int, int]) -> tuple[Path, Path, dict] | None:
    """Write work/poster.jpg and work/preview.mp4 from sample ``n`` fitted to ``size``.

    Returns (clip, poster, sample) or None (no samples, no ffmpeg or ffmpeg failed: use the stand-in card)."""
    s = pick(n)
    if s is None:
        return None
    from opensoul.media import ffmpeg_bin

    ff = ffmpeg_bin()
    if not ff:
        return None
    w, h = size
    work.mkdir(parents=True, exist_ok=True)
    clip, poster = work / "preview.mp4", work / "poster.jpg"
    try:
        subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(s["video_path"]), "-filter_complex", _fit_filter(w, h),
                        "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
                        "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(clip)],
                       check=True, capture_output=True, timeout=120)
        subprocess.run([ff, "-y", "-loglevel", "error", "-ss", "1.0", "-i", str(clip), "-frames:v", "1", "-q:v", "3",
                        str(poster)], check=True, capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        for f in (clip, poster):
            f.unlink(missing_ok=True)
        return None
    if not poster.is_file():
        shutil.copyfile(s["poster_path"], poster)
    return clip, poster, s
