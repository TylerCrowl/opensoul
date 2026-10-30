"""Shape the voice clip of a talking take before LTX renders the mouth to it (OS-056, OS-059).

TTS engines put silence before and after the words (Kokoro: about 0.4 s before and 0.6 s after). The a2v model
fills long silence with an open or moving mouth. This module:

- finds the spoken part of the clip (energy above ``FLOOR_DB`` under the peak, in 10 ms windows);
- keeps only ``LEAD_S`` of silence before the first word and ``TAIL_S`` after the last word;
- pads the clip with silence to the take length: the shot's planned length (``target_s``), or the line plus a
  short closed-mouth hold (``HOLD_S``) when no length is set; never shorter than the line;
- returns where the words start and stop in the take, so the render can hold the mouth closed after the line.

ffmpeg reads the clip (any format); the result is a 16-bit mono WAV at the source rate. Local, no model.
"""
from __future__ import annotations

import math
import subprocess
import wave
from pathlib import Path

import numpy as np

LEAD_S = 0.10        # silence kept before the first word (the first frame is the start picture, mouth closed)
TAIL_S = 0.15        # silence kept after the last word (lips close naturally)
HOLD_S = 0.50        # auto length: closed-mouth time after the last word (TAIL_S included)
FLOOR_DB = 40.0      # a window is speech when it is less than this many dB under the loudest window
WIN_S = 0.01
MIN_GAP_S = 0.12     # shorter gaps inside the line are not pauses
PAUSE_S = 0.25       # gaps this long or longer are listed as pauses (the mouth should rest)
MAX_SECONDS = 20.0   # longest planned length the app accepts for a talking take
SR = 24000


def read_mono(path: str | Path, sr: int = SR) -> np.ndarray:
    from opensoul.media import ffmpeg_bin

    raw = subprocess.run([ffmpeg_bin() or "ffmpeg", "-loglevel", "error", "-i", str(path), "-f", "f32le", "-ac", "1",
                          "-ar", str(sr), "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).copy()


def write_mono(path: str | Path, x: np.ndarray, sr: int = SR) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(x, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return path


def speech_spans(x: np.ndarray, sr: int = SR, *, floor_db: float = FLOOR_DB, min_gap_s: float = MIN_GAP_S
                 ) -> list[tuple[float, float]]:
    """[(start_s, end_s)] of the spoken parts. Gaps shorter than ``min_gap_s`` are joined. [] for a silent clip."""
    w = max(1, int(sr * WIN_S))
    n = len(x) // w
    if n == 0:
        return []
    rms = np.sqrt((x[: n * w].reshape(n, w).astype(np.float64) ** 2).mean(1))
    db = 20 * np.log10(rms + 1e-9)
    if db.max() < -60:  # digital silence
        return []
    on = db > db.max() - floor_db
    spans: list[list[float]] = []
    i = 0
    while i < n:
        if on[i]:
            j = i
            while j < n and on[j]:
                j += 1
            a, b = i * WIN_S, j * WIN_S
            if spans and a - spans[-1][1] < min_gap_s:
                spans[-1][1] = b
            else:
                spans.append([a, b])
            i = j
        else:
            i += 1
    return [(round(a, 3), round(b, 3)) for a, b in spans if b - a >= 0.03]


def a2v_frames_for(seconds: float, fps: int = 24) -> int:
    """LTX frame count (8k + 1) that lasts at least ``seconds``."""
    k = max(1, math.ceil((float(seconds) * fps - 1) / 8))
    return 8 * k + 1


def plan_length(speech_s: float, target_s: float = 0.0, *, lead_s: float = LEAD_S, hold_s: float = HOLD_S,
                min_frames: int = 0, fps: int = 24) -> int:
    """Frame count of a talking take: the planned length when set, never shorter than the line plus a short hold."""
    need = lead_s + float(speech_s) + hold_s
    want = max(need, float(target_s or 0))
    return max(a2v_frames_for(want, fps), int(min_frames or 0))


def shape_voice(src: str | Path, dest: str | Path, *, target_s: float = 0.0, min_frames: int = 0, fps: int = 24,
                lead_s: float = LEAD_S, tail_s: float = TAIL_S, hold_s: float = HOLD_S) -> dict:
    """Trim the clip's lead and tail silence, pad it to the take length and write ``dest``.

    Returns {"file", "frames", "seconds", "speech_start", "speech_end", "pauses", "source_s", "cut_lead_s",
    "cut_tail_s", "target_s"}; times are in the shaped clip. A clip with no speech found is padded only."""
    x = read_mono(src)
    src_s = len(x) / SR
    spans = speech_spans(x)
    if spans:
        a = max(0.0, spans[0][0] - lead_s)
        b = min(src_s, spans[-1][1] + tail_s)
    else:
        a, b = 0.0, src_s
    y = x[int(a * SR): int(b * SR)]
    s0 = (spans[0][0] - a) if spans else 0.0
    s1 = (spans[-1][1] - a) if spans else len(y) / SR
    frames = plan_length(s1 - s0, target_s, lead_s=s0, hold_s=hold_s, min_frames=min_frames, fps=fps)
    total = frames / fps
    n = int(round(total * SR))
    y = np.concatenate([y, np.zeros(max(0, n - len(y)), np.float32)])[:n]
    write_mono(dest, y)
    pauses = [(round(p[1] - a, 3), round(q[0] - a, 3)) for p, q in zip(spans, spans[1:]) if q[0] - p[1] >= PAUSE_S]
    return {"file": str(dest), "frames": frames, "seconds": round(total, 4), "speech_start": round(s0, 3),
            "speech_end": round(min(s1, total), 3), "pauses": pauses, "source_s": round(src_s, 3),
            "cut_lead_s": round(a, 3), "cut_tail_s": round(max(0.0, src_s - b), 3), "target_s": float(target_s or 0)}


def clean_seconds(v) -> float:
    """A shot's planned length: 0 (auto) or 1 to MAX_SECONDS seconds, one decimal. Raises ValueError."""
    if v in (None, ""):
        return 0.0
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ValueError("Type the length in seconds, for example 5.") from None
    if f == 0:
        return 0.0
    if not 1.0 <= f <= MAX_SECONDS:
        raise ValueError(f"Set a length from 1 to {MAX_SECONDS:g} seconds, or 0 for automatic.")
    return round(f, 1)
