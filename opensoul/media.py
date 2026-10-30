"""Small ffmpeg helpers shared by the dry-run backends and the share export."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path


class MediaError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def ffmpeg_bin() -> str | None:
    """Path to an ffmpeg binary: $OPENSOUL_FFMPEG, then ffmpeg on PATH, then the static build from the
    optional ``imageio-ffmpeg`` wheel (``pip install -e .[ffmpeg]``; has Linux x86_64/aarch64, macOS and
    Windows wheels, so a box with no system ffmpeg, e.g. a stock DGX Spark, still works)."""
    env = os.environ.get("OPENSOUL_FFMPEG")
    if env and Path(env).is_file():
        return env
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg  # type: ignore[import-not-found]

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        return exe if exe and Path(exe).is_file() else None
    except Exception:  # noqa: BLE001  not installed, or no binary for this platform
        return None


def _resolve(cmd: list[str]) -> list[str]:
    exe = ffmpeg_bin()
    if not exe:
        raise MediaError("ffmpeg is not installed (apt install ffmpeg, brew install ffmpeg, or pip install imageio-ffmpeg).")
    return [exe, *cmd[1:]] if cmd and cmd[0] == "ffmpeg" else cmd


def _run(cmd: list[str], dest: Path) -> Path:
    cmd = _resolve(cmd)
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if r.returncode != 0 or not dest.is_file():
        raise MediaError(f"ffmpeg failed: {r.stderr.strip()[:400]}")
    return dest


def first_frame(video: Path, dest: Path, width: int = 480) -> Path:
    """A JPEG poster from the first frame of a clip (scaled to ``width``, keeps the aspect)."""
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-frames:v", "1", "-vf", f"scale={width}:-2",
           "-q:v", "4", str(dest)]
    return _run(cmd, Path(dest))


def still_to_clip(image: Path, dest: Path, seconds: float = 3.0, width: int = 720, height: int = 1280) -> Path:
    """A vertical clip from one still with a gentle push-in (dry-run stand-in for I2V)."""
    frames = max(1, int(seconds * 24))
    vf = (
        f"scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase,crop={width * 2}:{height * 2},"
        f"zoompan=z='1+0.08*on/{frames}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d={frames}:s={width}x{height}:fps=24,"
        "format=yuv420p"
    )
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(image), "-t", f"{seconds}",
           "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-movflags", "+faststart", str(dest)]
    return _run(cmd, dest)


def silent_wav(dest: Path, seconds: float) -> Path:
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
           "-t", f"{seconds:.2f}", str(dest)]
    return _run(cmd, dest)


def mux(video: Path, audio: Path, dest: Path) -> Path:
    """Replace the video's audio; the result is exactly as long as the audio (the picture loops if it's shorter).

    A stream-copied ``-stream_loop -1`` + ``-shortest`` overshoots badly (a 2.4 s voice on a 2 s clip came out 44 s),
    so a loop re-encodes the picture and cuts at the audio's length. A clip at least as long as the audio is copied."""
    a = duration(Path(audio))
    v = duration(Path(video))
    if a > 0 and v > 0 and v + 1e-3 >= a:
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-i", str(audio), "-map", "0:v", "-map", "1:a",
               "-t", f"{a:.4f}", "-c:v", "copy", "-c:a", "aac", "-movflags", "+faststart", str(dest)]
    else:
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-stream_loop", "-1", "-i", str(video), "-i", str(audio),
               "-map", "0:v", "-map", "1:a", *(["-t", f"{a:.4f}"] if a > 0 else ["-shortest"]),
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-movflags", "+faststart", str(dest)]
    return _run(cmd, dest)


def to_vertical(src: Path, dest: Path) -> Path:
    vf = "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,format=yuv420p"
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    if src.suffix.lower() in {".png", ".jpg", ".jpeg"}:
        cmd += ["-loop", "1", "-t", "3", "-i", str(src), "-r", "24"]
    else:
        cmd += ["-i", str(src)]
    cmd += ["-vf", vf, "-c:v", "libx264", "-c:a", "aac", "-movflags", "+faststart", str(dest)]
    return _run(cmd, dest)


def duration(path: Path) -> float:
    if shutil.which("ffprobe"):
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                           capture_output=True, text=True, check=False)
        try:
            return float(r.stdout.strip())
        except ValueError:
            pass
    exe = ffmpeg_bin()  # imageio-ffmpeg ships no ffprobe; read "Duration: HH:MM:SS.ss" from ffmpeg -i
    if not exe:
        return 0.0
    r = subprocess.run([exe, "-hide_banner", "-i", str(path)], capture_output=True, text=True, check=False)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else 0.0


def reverse_video(src: Path, dest: Path) -> Path:
    """Play a clip backwards (video only; audio is dropped: reversed moves are silent effects).

    Used for ``reverse: true`` presets, e.g. Earth zoom out rendered as a zoom-in and reversed."""
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-an", "-vf", "reverse",
           "-c:v", "libx264", "-crf", "16", "-preset", "medium", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dest)]
    return _run(cmd, Path(dest))


# OS-024: a song under the story. The song goes quieter while someone talks (sidechain ducking); the talk stays as is.
BED_GAIN = 0.45  # song level under the shots (about -7 dB)


def duck_filter(seconds: float, bed_gain: float = BED_GAIN, bed_start: float = 0.0, *, voice: str = "0:a",
                bed: str = "1:a") -> str:
    """filter_complex: ``voice`` = the takes' own audio, ``bed`` = the song (ffmpeg stream labels). Output label [a]."""
    secs = f"{max(0.01, seconds):.4f}"
    fmt = "aformat=sample_rates=48000:channel_layouts=stereo"
    return (f"[{bed}]atrim=start={max(0.0, bed_start):.4f},asetpts=PTS-STARTPTS,{fmt},volume={bed_gain:.3f},"
            f"apad=whole_dur={secs}[bed];"
            f"[{voice}]{fmt},apad=whole_dur={secs},asplit=2[voice][key];"
            "[bed][key]sidechaincompress=threshold=0.015:ratio=12:attack=15:release=400[ducked];"
            f"[voice][ducked]amix=inputs=2:duration=longest:normalize=0,alimiter=limit=0.89:level=false,atrim=0:{secs}[a]")


def add_song_bed(video: Path, song: Path, dest: Path, *, bed_gain: float = BED_GAIN, bed_start: float = 0.0) -> Path:
    """The video with ``song`` mixed under its own audio (ducked under talk). The picture is copied, not re-encoded."""
    secs = duration(Path(video))
    if secs <= 0:
        raise MediaError("Couldn't read the length of the video.")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-i", str(song),
           "-filter_complex", duck_filter(secs, bed_gain, bed_start), "-map", "0:v:0", "-map", "[a]",
           "-c:v", "copy", "-c:a", "aac", "-ar", "48000", "-ac", "2", "-t", f"{secs:.4f}",
           "-movflags", "+faststart", str(dest)]
    return _run(cmd, dest)
