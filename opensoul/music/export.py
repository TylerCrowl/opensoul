"""Music video export: each shot trimmed to its exact frame count from the cut, joined in order, the song underneath.

A shot without a usable keeper becomes a plain dark card of the same length, so the picture never drifts off the
music. The song is the only audio, unless the user keeps the spoken lines: then those takes' own audio plays
over the song, and the song goes quieter under them (OS-024). ffmpeg only.
"""
from __future__ import annotations

from pathlib import Path

from opensoul import media

VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv"}
STILL_EXT = {".png", ".jpg", ".jpeg", ".webp"}


def segment_cmd(src: Path | None, frames: int, dest: Path, *, fps: int = 24, size: tuple[int, int] = (720, 1280),
                fill: bool = False) -> list[str]:
    """ffmpeg argv for one segment of exactly ``frames`` frames (video trimmed / still held / dark card).
    ``fill``: crop to fill the frame (a 16:9 take in a vertical video) instead of bars around it (OS-040)."""
    w, h = size
    fit = (f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}" if fill
           else f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2")
    vf = f"{fit},setsar=1,fps={fps},format=yuv420p"
    secs = f"{frames / fps:.4f}"
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    if src is not None and src.suffix.lower() in VIDEO_EXT:
        # hold the last frame if the take is shorter than the cut (tpad), then cut to the exact frame count
        cmd += ["-i", str(src), "-vf", vf + f",tpad=stop_mode=clone:stop_duration={secs}"]
    elif src is not None and src.suffix.lower() in STILL_EXT:
        cmd += ["-loop", "1", "-t", secs, "-i", str(src), "-vf", vf]
    else:
        cmd += ["-f", "lavfi", "-i", f"color=c=0x1d1d1f:s={w}x{h}:r={fps}:d={secs}", "-vf", "format=yuv420p"]
    return cmd + ["-an", "-frames:v", str(frames), "-c:v", "libx264", "-preset", "veryfast", "-r", str(fps), str(dest)]


def render(items: list[dict], song: Path, out: Path, *, fps: int = 24, size: tuple[int, int] = (720, 1280),
           fill: bool = False) -> Path:
    """``items`` = [{"source": Path | None, "frames": int}] in cut order. Returns ``out`` (mp4, song as audio)."""
    if not items:
        raise media.MediaError("Nothing to export.")
    work = out.parent / (out.stem + "_parts")
    work.mkdir(parents=True, exist_ok=True)
    segs = []
    for k, it in enumerate(items, 1):
        seg = work / f"seg_{k:03d}.mp4"
        src = Path(it["source"]) if it.get("source") else None
        if src is not None and not src.is_file():
            src = None
        media._run(segment_cmd(src, int(it["frames"]), seg, fps=fps, size=size, fill=fill), seg)
        segs.append(seg)
    lst = work / "concat.txt"
    lst.write_text("".join(f"file '{s.name}'\n" for s in segs), encoding="utf-8")
    total = sum(int(it["frames"]) for it in items) / fps
    if any(it.get("keep_audio") for it in items):  # OS-024: spoken lines over the song (the song ducks under them)
        voice = _voice_track(items, work, fps)
        media._run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(voice),
                    "-i", str(song), "-filter_complex", media.duck_filter(total, bed_gain=1.0, voice="1:a", bed="2:a"), "-map", "0:v:0", "-map", "[a]", "-c:v", "copy", "-c:a", "aac",
                    "-ar", "48000", "-ac", "2", "-t", f"{total:.4f}", "-movflags", "+faststart", str(out)], out)
        return out
    media._run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(song),
                "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-ar", "48000", "-ac", "2",
                "-t", f"{total:.4f}", "-movflags", "+faststart", str(out)], out)
    return out


def _has_audio(src: Path) -> bool:
    import subprocess

    r = subprocess.run([media.ffmpeg_bin() or "ffmpeg", "-hide_banner", "-i", str(src)], capture_output=True, text=True)
    return "Audio:" in r.stderr


def _voice_track(items: list[dict], work: Path, fps: int) -> Path:
    """One wav, as long as the cut: each kept take's own audio in its slot, silence everywhere else."""
    parts = []
    for k, it in enumerate(items, 1):
        secs = f"{int(it['frames']) / fps:.4f}"
        part = work / f"voice_{k:03d}.wav"
        src = Path(it["source"]) if it.get("source") else None
        if it.get("keep_audio") and src is not None and src.is_file() and src.suffix.lower() in VIDEO_EXT and _has_audio(src):
            cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-vn", "-af", f"apad=whole_dur={secs}",
                   "-t", secs, "-ar", "48000", "-ac", "2", str(part)]
        else:
            cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                   "-t", secs, str(part)]
        media._run(cmd, part)
        parts.append(part)
    lst = work / "voice.txt"
    lst.write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
    voice = work / "voice.wav"
    return media._run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                       "-c", "copy", str(voice)], voice)


def slice_audio(src: Path, start_s: float, seconds: float, dest: Path) -> Path:
    """A piece of the (vocal) stem, padded with silence past the end. Never time-stretched."""
    return media._run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{max(0.0, start_s):.4f}", "-i", str(src),
                       "-af", f"apad=whole_dur={seconds:.4f}", "-t", f"{seconds:.4f}", str(dest)], dest)
