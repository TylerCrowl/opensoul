"""Beats, bars and sections from an audio file. CPU only, numpy only (no librosa / madmom in the venv).

* onsets: spectral flux of a log-magnitude STFT (hop ~11.6 ms at 22.05 kHz)
* tempo: autocorrelation of the onset envelope, weighted toward 120 BPM (a log-normal prior, as in common
  beat trackers), range 60-200 BPM
* beats: dynamic-programming beat tracking (Ellis 2007): onset strength plus a penalty for straying from the period
* bars: 4/4 by default; bar 1 is the beat phase with the strongest onsets plus low-end (kick) energy. Heuristic:
  the UI lets the user move bar 1.
* sections: bar-synchronous band energies, a self-similarity novelty curve (checkerboard kernel), peaks snapped
  to bars, at least ``min_section_bars`` long; sections that sound alike share a letter (A, B, A ...).

Lyric section tags from a song model ([verse], [chorus]) override the letters when the model returns them.
"""
from __future__ import annotations

import subprocess
import wave
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

SR = 22050
N_FFT = 1024
HOP = 256


class AudioError(RuntimeError):
    pass


@dataclass
class Section:
    label: str
    start_bar: int
    end_bar: int          # exclusive
    start_s: float
    end_s: float
    energy: float         # 0..1, relative to the loudest section of this song
    name: str = ""        # lyric tag when known ("Chorus"), from the lyrics + LRC (opensoul.music.lrc.name_sections)


@dataclass
class BeatMap:
    duration_s: float
    tempo_bpm: float
    beats: list[float]
    beats_per_bar: int
    downbeat_phase: int   # index of the first downbeat within ``beats``
    bars: list[float]     # bar start times (downbeats)
    sections: list[Section] = field(default_factory=list)

    def bar_bounds(self) -> list[tuple[float, float]]:
        """(start, end) per bar; the last bar ends one bar-length later, capped at the song's end."""
        if not self.bars:
            return []
        period = 60.0 / self.tempo_bpm * self.beats_per_bar
        ends = self.bars[1:] + [min(self.duration_s, self.bars[-1] + period)]
        return [(s, e) for s, e in zip(self.bars, ends) if e > s]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["bar_count"] = len(self.bars)
        return d

    @staticmethod
    def from_dict(d: dict) -> "BeatMap":
        return BeatMap(duration_s=float(d["duration_s"]), tempo_bpm=float(d["tempo_bpm"]), beats=list(d["beats"]),
                       beats_per_bar=int(d["beats_per_bar"]), downbeat_phase=int(d["downbeat_phase"]), bars=list(d["bars"]),
                       sections=[Section(**s) for s in d.get("sections") or []])


# ---------------------------------------------------------------- audio in
def _read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        ch, width, sr, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if width == 1:
        y = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128.0) / 128.0
    elif width == 2:
        y = np.frombuffer(raw, "<i2").astype(np.float32) / 32768.0
    elif width == 3:
        b = np.frombuffer(raw, np.uint8).reshape(-1, 3).astype(np.int32)
        v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        y = (np.where(v >= 1 << 23, v - (1 << 24), v)).astype(np.float32) / float(1 << 23)
    elif width == 4:
        y = np.frombuffer(raw, "<i4").astype(np.float32) / float(1 << 31)
    else:
        raise AudioError(f"Unsupported WAV sample width: {width} bytes")
    if ch > 1:
        y = y.reshape(-1, ch).mean(axis=1)
    return y, sr


def _resample(y: np.ndarray, sr: int, target: int) -> np.ndarray:
    if sr == target or not len(y):
        return y
    n = int(round(len(y) * target / sr))
    return np.interp(np.arange(n) * (sr / target), np.arange(len(y)), y).astype(np.float32)


def load_audio(path: str | Path, sr: int = SR) -> np.ndarray:
    """Mono float32 at ``sr``. PCM WAV is read directly; anything else is decoded with ffmpeg."""
    p = Path(path)
    if not p.is_file():
        raise AudioError(f"No audio file at {p.name}")
    try:
        y, file_sr = _read_wav(p)
        return _resample(y, file_sr, sr)
    except (wave.Error, EOFError):
        pass
    from opensoul.media import ffmpeg_bin

    ff = ffmpeg_bin()
    if not ff:
        raise AudioError("OpenSoul can read only PCM WAV without ffmpeg.")
    r = subprocess.run([ff, "-v", "error", "-i", str(p), "-f", "f32le", "-ac", "1", "-ar", str(sr), "-"],
                       capture_output=True)
    if r.returncode != 0:
        raise AudioError(f"Couldn't read the audio: {r.stderr.decode(errors='replace').strip()[:200]}")
    return np.frombuffer(r.stdout, "<f4").astype(np.float32)


def write_wav(path: str | Path, y: np.ndarray, sr: int = SR) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(y, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return p


# ---------------------------------------------------------------- features
def _stft_mag(y: np.ndarray, n_fft: int = N_FFT, hop: int = HOP) -> np.ndarray:
    pad = np.pad(y, (n_fft // 2, n_fft // 2))
    n = 1 + max(0, (len(pad) - n_fft) // hop)
    idx = np.arange(n_fft)[None, :] + hop * np.arange(n)[:, None]
    frames = pad[idx] * np.hanning(n_fft)[None, :]
    return np.abs(np.fft.rfft(frames, axis=1)).astype(np.float32)  # (frames, bins)


def _flux(logmag: np.ndarray) -> np.ndarray:
    d = np.diff(logmag, axis=0, prepend=logmag[:1])
    return np.maximum(d, 0.0).sum(axis=1)


def _normalize(env: np.ndarray, fps: float) -> np.ndarray:
    w = max(1, int(fps * 0.5))
    local = np.convolve(env, np.ones(w) / w, mode="same")
    env = np.maximum(env - local, 0.0)
    sd = env.std()
    return env / sd if sd > 0 else env


def onset_envelope(y: np.ndarray, sr: int = SR) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(onset strength, low-end onset strength, log magnitude), one value per hop."""
    mag = _stft_mag(y)
    logmag = np.log1p(1000.0 * mag)
    fps = sr / HOP
    low_bins = max(2, int(200.0 * N_FFT / sr))
    env, low = _normalize(_flux(logmag), fps), _normalize(_flux(logmag[:, :low_bins]), fps)
    edge = N_FFT // HOP // 2 + 1  # the zero padding past the end makes a false onset there
    env[-edge:] = 0.0
    low[-edge:] = 0.0
    return env, low, logmag


def estimate_tempo(env: np.ndarray, fps: float, lo: float = 60.0, hi: float = 200.0, prior: float = 120.0) -> float:
    if env.size < 4 or not env.any():
        return prior
    x = env - env.mean()
    n = 1 << int(np.ceil(np.log2(2 * len(x))))
    ac = np.fft.irfft(np.abs(np.fft.rfft(x, n)) ** 2)[: len(x)]
    lags = np.arange(max(1, int(fps * 60.0 / hi)), min(len(ac) - 1, int(np.ceil(fps * 60.0 / lo))) + 1)
    if not len(lags):
        return prior
    bpm = 60.0 * fps / lags
    score = np.maximum(ac[lags], 0) * np.exp(-0.5 * (np.log2(bpm / prior) / 1.0) ** 2)
    i = int(np.argmax(score))
    lag = float(lags[i])
    if 0 < i < len(lags) - 1:  # parabolic refinement on the raw autocorrelation
        a, b, c = ac[lags[i] - 1], ac[lags[i]], ac[lags[i] + 1]
        den = a - 2 * b + c
        if den < 0:
            lag += 0.5 * (a - c) / den
    return float(60.0 * fps / lag)


def track_beats(env: np.ndarray, fps: float, bpm: float, tightness: float = 100.0) -> np.ndarray:
    """Beat frames by dynamic programming over the onset envelope."""
    if not env.any():
        return np.zeros(0, dtype=int)
    period = fps * 60.0 / bpm
    win = np.arange(-int(period), int(period) + 1)
    local = np.convolve(env, np.exp(-0.5 * (win * 32.0 / period) ** 2), mode="same")
    n = len(local)
    score = np.zeros(n)
    back = -np.ones(n, dtype=int)
    lo, hi = int(round(period / 2)), int(round(2 * period))
    offsets = np.arange(lo, hi + 1)
    penalty = -tightness * np.log(offsets / period) ** 2
    for t in range(n):
        prev = t - offsets
        ok = prev >= 0
        if ok.any():
            cand = score[prev[ok]] + penalty[ok]
            j = int(np.argmax(cand))
            if cand[j] > 0:
                score[t] = local[t] + cand[j]
                back[t] = prev[ok][j]
                continue
        score[t] = local[t]
    # last beat: the latest local maximum of the score that is strong enough
    peaks = [t for t in range(1, n - 1) if score[t] >= score[t - 1] and score[t] > score[t + 1]]
    if not peaks:
        return np.zeros(0, dtype=int)
    thr = 0.5 * np.median([score[t] for t in peaks])
    t = max(t for t in peaks if score[t] >= thr)
    beats = []
    while t >= 0:
        beats.append(t)
        t = back[t]
    beats = np.array(beats[::-1])
    # drop weak beats at either end (silence before / after the music)
    vals = local[beats]
    strong = vals > 0.5 * np.median(vals)
    if strong.any():
        first, last = np.argmax(strong), len(strong) - 1 - np.argmax(strong[::-1])
        beats = beats[first:last + 1]
    return beats


def bar_phase(beat_frames: np.ndarray, env: np.ndarray, low: np.ndarray, beats_per_bar: int) -> int:
    if len(beat_frames) < beats_per_bar:
        return 0
    s = env / (env.max() or 1.0) + low / (low.max() or 1.0)
    vals = s[beat_frames]
    return int(np.argmax([vals[p::beats_per_bar].mean() for p in range(beats_per_bar)]))


def _band_features(logmag: np.ndarray, sr: int, n_bands: int = 16) -> np.ndarray:
    edges = np.unique(np.geomspace(2, logmag.shape[1] - 1, n_bands + 1).astype(int))
    return np.stack([logmag[:, a:b].mean(axis=1) for a, b in zip(edges[:-1], edges[1:])], axis=1)


def find_sections(bars: list[tuple[float, float]], logmag: np.ndarray, sr: int, *, min_section_bars: int = 4,
                  kernel_bars: int = 4, same_threshold: float = 0.6) -> list[Section]:
    if not bars:
        return []
    fps = sr / HOP
    feats = _band_features(logmag, sr)
    rows, rms = [], []
    for s, e in bars:
        a, b = int(s * fps), max(int(s * fps) + 1, int(e * fps))
        seg = feats[a:b] if a < len(feats) else feats[-1:]
        rows.append(seg.mean(axis=0))
        rms.append(float(seg.mean()))
    X = np.array(rows)
    Z = (X - X.mean(axis=0)) / (X.std(axis=0) + 1e-6)
    nb = len(bars)
    bounds = [0]
    if nb >= 2 * min_section_bars:
        norm = Z / (np.linalg.norm(Z, axis=1, keepdims=True) + 1e-9)
        S = norm @ norm.T
        k = kernel_bars
        g = np.exp(-0.5 * (np.linspace(-1, 1, 2 * k) / 0.5) ** 2)
        sign = np.where(np.arange(2 * k) < k, -1.0, 1.0)
        K = np.outer(sign, sign) * np.outer(g, g)
        nov = np.zeros(nb)
        Sp = np.pad(S, k, mode="edge")
        for i in range(nb):
            nov[i] = (Sp[i:i + 2 * k, i:i + 2 * k] * K).sum()
        nov = np.maximum(nov, 0)
        thr = nov.mean() + 0.5 * nov.std()
        cand = [i for i in range(1, nb) if nov[i] > thr and nov[i] == nov[max(0, i - 2):i + 3].max()]
        for i in sorted(cand, key=lambda i: -nov[i]):
            if all(abs(i - b) >= min_section_bars for b in bounds) and nb - i >= min_section_bars:
                bounds.append(i)
        bounds.sort()
    bounds.append(nb)
    # label: alike sections share a letter
    protos: list[tuple[str, np.ndarray]] = []
    out: list[Section] = []
    lvl = np.array(rms)
    lo, hi = float(lvl.min()), float(lvl.max())
    for a, b in zip(bounds[:-1], bounds[1:]):
        v = Z[a:b].mean(axis=0)
        label = None
        for name, p in protos:
            sim = float(v @ p / ((np.linalg.norm(v) * np.linalg.norm(p)) + 1e-9))
            if sim >= same_threshold:
                label = name
                break
        if label is None:
            label = chr(ord("A") + len(protos)) if len(protos) < 26 else f"S{len(protos) + 1}"
            protos.append((label, v))
        energy = (float(lvl[a:b].mean()) - lo) / (hi - lo) if hi > lo else 0.5
        out.append(Section(label=label, start_bar=a, end_bar=b, start_s=round(bars[a][0], 4),
                           end_s=round(bars[b - 1][1], 4), energy=round(energy, 3)))
    return out


def _beats_before(y: np.ndarray, sr: int, beats: list[float], bpm: float) -> list[float]:
    """Beats one period before the first tracked beat, back to 0:00, when there is a hit as strong as the tracked
    ones (half their median energy) at that spot. Silence before the song adds nothing."""
    if len(beats) < 4:
        return []
    period = 60.0 / bpm

    def energy(t: float) -> float:
        a, b = max(0, int((t - 0.01) * sr)), int((t + 0.04) * sr)
        seg = y[a:b]
        return float(np.mean(seg * seg)) if len(seg) else 0.0

    ref = float(np.median([energy(t) for t in beats[: min(16, len(beats))]]))
    out: list[float] = []
    t = beats[0] - period
    while t > -0.05 and ref > 0 and energy(max(0.0, t)) >= 0.5 * ref:
        out.insert(0, round(max(0.0, t), 4))
        t -= period
    return out


def full_bars(bars: list[float], duration: float, bpm: float, beats_per_bar: int = 4) -> list[float]:
    """Drop a last bar that starts less than half a bar before the end: that's a tail, not a bar."""
    period = 60.0 / bpm * beats_per_bar
    return [b for b in bars if duration - b >= 0.5 * period]


def analyze_samples(y: np.ndarray, sr: int = SR, *, beats_per_bar: int = 4, min_section_bars: int = 4) -> BeatMap:
    if sr != SR:
        y = _resample(y, sr, SR)
        sr = SR
    duration = len(y) / sr
    if duration < 1.0:
        raise AudioError("The song is too short to find a beat (under 1 second).")
    fps = sr / HOP
    env, low, logmag = onset_envelope(y, sr)
    bpm = estimate_tempo(env, fps)
    frames = track_beats(env, fps, bpm)
    beats = [round(float(f) / fps, 4) for f in frames]
    if len(beats) >= 8:  # tempo from the tracked beats (steadier than the autocorrelation peak)
        bpm = 60.0 / float(np.median(np.diff(beats)))
    phase = bar_phase(frames, env, low, beats_per_bar)
    added = _beats_before(y, sr, beats, bpm)  # the onset envelope can't see a hit right at 0:00
    beats = added + beats
    phase = (phase + len(added)) % beats_per_bar
    bars = full_bars(beats[phase::beats_per_bar], duration, bpm, beats_per_bar)
    bm = BeatMap(duration_s=round(duration, 4), tempo_bpm=round(bpm, 2), beats=beats, beats_per_bar=beats_per_bar,
                 downbeat_phase=phase, bars=bars)
    bm.sections = find_sections(bm.bar_bounds(), logmag, sr, min_section_bars=min_section_bars)
    return bm


def analyze(path: str | Path, *, beats_per_bar: int = 4, min_section_bars: int = 4) -> BeatMap:
    """Beat map of an audio file (WAV directly, other formats through ffmpeg)."""
    return analyze_samples(load_audio(path), SR, beats_per_bar=beats_per_bar, min_section_bars=min_section_bars)


def active_regions(path: str | Path, *, threshold_db: float = -35.0, min_gap_s: float = 0.4,
                   min_len_s: float = 0.3) -> list[tuple[float, float]]:
    """Where a (vocal) stem is audible: RMS over 46 ms windows above ``threshold_db`` relative to its peak."""
    y = load_audio(path)
    win = 1024
    n = len(y) // win
    if n == 0:
        return []
    rms = np.sqrt((y[: n * win].reshape(n, win) ** 2).mean(axis=1) + 1e-12)
    db = 20 * np.log10(rms / (rms.max() or 1.0))
    on = db > threshold_db
    step = win / SR
    regions: list[list[float]] = []
    for i, v in enumerate(on):
        if not v:
            continue
        t = i * step
        if regions and t - regions[-1][1] <= min_gap_s:
            regions[-1][1] = t + step
        else:
            regions.append([t, t + step])
    return [(round(a, 3), round(b, 3)) for a, b in regions if b - a >= min_len_s]


# ---------------------------------------------------------------- synthetic audio (tests and dry-run placeholder)
def click_track(*, bpm: float = 120.0, bars: int = 8, beats_per_bar: int = 4, sr: int = SR, lead_in_s: float = 0.0,
                sections: list[tuple[int, str]] | None = None, seed: int = 0, tail_s: float = 0.5) -> np.ndarray:
    """Original synthetic audio: clicks (an accented, higher click on bar 1 of each bar) over a held tone whose
    colour changes per section. ``sections`` = [(bars, "a" | "b" | "c"), ...] (default: all "a")."""
    rng = np.random.default_rng(seed)
    beat = 60.0 / bpm
    total = lead_in_s + bars * beats_per_bar * beat + tail_s
    n = int(total * sr)
    y = np.zeros(n, dtype=np.float32)
    t = np.arange(n) / sr
    plan = sections or [(bars, "a")]
    tones = {"a": ([220.0], 0.05), "b": ([660.0, 990.0, 1320.0], 0.16), "c": ([330.0, 495.0], 0.1)}
    bar_s = beats_per_bar * beat
    start_bar = 0
    for nb, kind in plan:
        a = int((lead_in_s + start_bar * bar_s) * sr)
        b = min(n, int((lead_in_s + (start_bar + nb) * bar_s) * sr))
        freqs, amp = tones.get(kind, tones["a"])
        for f in freqs:
            y[a:b] += amp * np.sin(2 * np.pi * f * t[a:b]).astype(np.float32)
        start_bar += nb
    click_n = int(0.03 * sr)
    env = np.exp(-np.arange(click_n) / (0.006 * sr)).astype(np.float32)
    for k in range(bars * beats_per_bar):
        s = int((lead_in_s + k * beat) * sr)
        down = k % beats_per_bar == 0
        f = 1600.0 if down else 1000.0
        burst = np.sin(2 * np.pi * f * np.arange(click_n) / sr).astype(np.float32) * env * (0.9 if down else 0.5)
        if down:  # a short low thump on bar 1, like a kick
            burst += (np.sin(2 * np.pi * 60.0 * np.arange(click_n) / sr) * env * 0.6).astype(np.float32)
        e = min(n, s + click_n)
        y[s:e] += burst[: e - s]
    y += rng.normal(0, 0.002, n).astype(np.float32)
    return np.clip(y, -1.0, 1.0)


def analyze_with(path: str | Path, backend: str = "auto", *, beats_per_bar: int = 4,
                 min_section_bars: int = 4) -> tuple[BeatMap, str]:
    """(beat map, backend used). ``auto``/``beat_this``: beat_this when it is installed (studio env, needs torch),
    else the built-in tracker (``opensoul_onset``). Sections always come from the built-in novelty step."""
    from opensoul.music import beat_this_backend as bt

    if backend in ("auto", "beat_this") and bt.available():
        beats, downs = bt.beats_and_downbeats(path)
        y = load_audio(path)
        duration = len(y) / SR
        if len(beats) >= 2:
            bpm = 60.0 / float(np.median(np.diff(beats)))
            first = downs[0] if downs else beats[0]
            phase = int(np.argmin([abs(b - first) for b in beats]))
            bm = BeatMap(duration_s=round(duration, 4), tempo_bpm=round(bpm, 2), beats=[round(b, 4) for b in beats],
                         beats_per_bar=beats_per_bar, downbeat_phase=phase,
                         bars=full_bars([round(d, 4) for d in downs] or beats[phase::beats_per_bar], duration, bpm,
                                        beats_per_bar))
            _, _, logmag = onset_envelope(y, SR)
            bm.sections = find_sections(bm.bar_bounds(), logmag, SR, min_section_bars=min_section_bars)
            return bm, "beat_this"
    return analyze(path, beats_per_bar=beats_per_bar, min_section_bars=min_section_bars), "opensoul_onset"
