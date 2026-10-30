"""A shot list cut to the beat: bars -> shot durations that fit LTX clip lengths.

Rules (docs/MUSIC.md):
* every cut lands on a bar line and a section change always cuts; a bar longer than ``max_shot_s`` is split on a beat
* no shot is shorter than one bar: a pickup before bar 1, a tail after the last bar or a short last piece joins
  its neighbour (even when that runs up to one bar over ``max_shot_s``)
* bars per shot follow the section: choruses cut every bar, verses every 2 bars, bridges / intros / outros hold
  4 bars (named sections; otherwise the section's loudness decides), then grown or shrunk to stay within
  [``min_shot_s``, ``max_shot_s``] (``bars_per_shot`` forces one value)
* each lyric line belongs to exactly one shot (the one it overlaps most); shots with no line are cutaways
* the first shot starts at 0 (a pickup before bar 1 joins it) and the last one ends with the song
* timing is in whole frames at ``fps`` from the song's start (cumulative rounding, so no drift); LTX renders
  8k+1 frames, so each shot renders ``render_frames`` >= ``frames`` and the export trims the tail
* a shot that overlaps the vocal stem's audible regions by at least ``lipsync_min_s`` (or half its length) is
  marked ``lipsync`` (rendered with the vocal slice as the a2v audio, opensoul.lipsync.a2v_stage)
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from opensoul.music import lrc as L
from opensoul.music.beats import BeatMap

# How long a named section holds a shot (lyric tags); unnamed sections go by loudness (energy_band)
BAND_BY_TAG = {"chorus": "high", "hook": "high", "drop": "high", "verse": "mid", "pre": "mid", "rap": "mid",
               "bridge": "low", "intro": "low", "outro": "low", "break": "low", "interlude": "low"}

FPS = 24
MIN_SHOT_S = 1.5
MAX_SHOT_S = 8.0            # Final; conservative until checked on a studio GPU (LTX-2.5 a2v, opensoul.lipsync.MAX_AUDIO_S = 20)
TOL_S = 0.05               # beat-tracking jitter allowed over max_shot_s (about one frame)
DRAFT_MAX_S = 4.0           # opensoul.presets.QUALITY["draft"]["max_seconds"]
# Camera presets (presets/camera/*.json ids) cycled per energy band
CAMERA_BY_ENERGY = {
    # Only presets not marked experimental (orbit and jib_down are).
    "low": ["static", "push_in_gentle", "dolly_left", "dolly_out"],
    "mid": ["push_in_gentle", "dolly_right", "jib_up", "dolly_in"],
    "high": ["dolly_in", "crash_zoom", "dolly_zoom", "dolly_out", "fpv"],
}


@dataclass
class CutShot:
    index: int
    start_s: float
    end_s: float
    start_frame: int
    frames: int             # exact length in the cut
    render_frames: int      # LTX length (8k+1 >= frames)
    trim_frames: int        # cut from the tail at export
    start_bar: int          # 1-based; 0 = pickup before bar 1
    bars: float
    section: str
    energy: str
    camera: str
    lipsync: bool
    vocal_s: float
    lyric: str = ""                       # LRC lines sung in this shot (joined)
    lines: list[int] | None = None        # their LRC line indexes
    sing_windows: list[list[float]] | None = None  # [start, end] seconds from the shot's start where a line is sung
    camera_label: str = ""                # the camera preset's label (presets/camera, same as the Shots tab)
    extra_s: float = 0.0                  # seconds beyond the whole bars (a pickup or tail that joined this shot)
    bars_label: str = ""                  # "2 bars", "1 bar + 0.5 s"

    def to_dict(self) -> dict:
        return asdict(self)


def ltx_render_frames(frames: int) -> int:
    """Smallest 8k+1 (k >= 1) that covers ``frames`` (same rule as opensoul.lipsync.a2v_frames)."""
    return 8 * max(1, math.ceil((frames - 1) / 8)) + 1


def energy_band(energy: float) -> str:
    return "high" if energy >= 0.66 else "mid" if energy >= 0.33 else "low"


def section_band(name: str, energy: float) -> str:
    key = (name or "").lower()
    return next((b for tag, b in BAND_BY_TAG.items() if key.startswith(tag)), energy_band(energy))


def camera_labels() -> dict[str, str]:
    """id -> label from presets/camera (the one source the Shots tab uses too)."""
    from opensoul.presets import load_presets

    return {c["id"]: c.get("label") or c["id"] for c in load_presets()["camera"]}


def bars_label(bars: int, extra_s: float) -> str:
    word = "bar" if bars == 1 else "bars"
    return f"{bars} {word}" + (f" + {extra_s:.1f} s" if extra_s >= 0.05 else "")


def _bars_for(band: str) -> int:
    return {"high": 1, "mid": 2, "low": 4}[band]


def _segments(bm: BeatMap, min_s: float, max_s: float, bars_per_shot: int | None, pickup: float = 0.0,
              lines: list | None = None) -> list[dict]:
    """[{start, end, start_bar, bars, section, band}] covering bar 1 to the last bar (pickup/tail handled by caller)."""
    bounds = bm.bar_bounds()
    max_s = max_s + TOL_S
    secs = bm.sections or []
    out: list[dict] = []
    for sec in secs or [None]:
        a = sec.start_bar if sec else 0
        b = min(sec.end_bar, len(bounds)) if sec else len(bounds)
        band = section_band(sec.name or "", sec.energy) if sec else "mid"
        label = (sec.name or sec.label) if sec else "A"
        i = a
        first_in_sec = len(out)
        while i < b:
            n = bars_per_shot or _bars_for(band)
            n = max(1, min(n, b - i))
            room = max_s - (pickup if i == 0 else 0.0)  # a short pickup before bar 1 joins the first shot
            while n > 1 and bounds[i + n - 1][1] - bounds[i][0] > room:
                n -= 1
            while i + n < b and bounds[i + n - 1][1] - bounds[i][0] < min_s and bounds[i + n][1] - bounds[i][0] <= max_s:
                n += 1
            if lines and i + n < b and L.inside_line(bounds[i + n - 1][1], lines):
                # don't cut through a sung line (LRC): one bar more if it fits, else one bar less if long enough.
                # The bar more must also fit a Draft clip, so Draft and Final cut sung parts the same way (one line
                # per shot; a longer Final limit never swallows the next line).
                grow_room = min(room, DRAFT_MAX_S + TOL_S - (pickup if i == 0 else 0.0))
                if bounds[i + n][1] - bounds[i][0] <= grow_room and not L.inside_line(bounds[i + n][1], lines):
                    n += 1
                elif n > 1 and bounds[i + n - 2][1] - bounds[i][0] >= min_s and not L.inside_line(bounds[i + n - 2][1], lines):
                    n -= 1
            start, end = bounds[i][0], bounds[i + n - 1][1]
            if end - start > max_s:  # one bar longer than a clip: split it on beats
                beats = [t for t in bm.beats if start < t < end]
                pieces = max(2, math.ceil((end - start) / max_s))
                cuts = [start] + [min(beats, key=lambda t: abs(t - (start + k * (end - start) / pieces)))
                                  for k in range(1, pieces)] if beats else [start + k * (end - start) / pieces for k in range(pieces)]
                cuts = sorted(set(cuts)) + [end]
                for k, (s0, e0) in enumerate(zip(cuts[:-1], cuts[1:])):
                    out.append({"start": s0, "end": e0, "start_bar": i + 1, "bars": round((e0 - s0) / (end - start), 3),
                                "section": label, "band": band})
            else:
                out.append({"start": start, "end": end, "start_bar": i + 1, "bars": n, "section": label, "band": band})
            i += n
        # a too-short last shot in a section joins the one before it (when that stays within max_s)
        if len(out) - first_in_sec >= 2:
            last, prev = out[-1], out[-2]
            if last["end"] - last["start"] < min_s and last["end"] - prev["start"] <= max_s:
                prev["end"] = last["end"]
                prev["bars"] = prev["bars"] + last["bars"]
                out.pop()
    return out


def _overlap(a: float, b: float, regions: list[tuple[float, float]]) -> float:
    return sum(max(0.0, min(b, e) - max(a, s)) for s, e in regions)


def shot_list(bm: BeatMap, *, fps: int = FPS, min_shot_s: float = MIN_SHOT_S, max_shot_s: float = MAX_SHOT_S,
              quality: str = "final", bars_per_shot: int | None = None,
              vocal_regions: list[tuple[float, float]] | None = None, lipsync_min_s: float = 1.0,
              lyrics: list | None = None) -> list[CutShot]:
    """``lyrics`` = LRC lines (opensoul.music.lrc.parse): cuts avoid splitting a sung line, each shot lists its lines,
    and the sung windows drive ``lipsync`` (used instead of ``vocal_regions`` when those aren't given)."""
    if quality == "draft":
        max_shot_s = min(max_shot_s, DRAFT_MAX_S)
    if min_shot_s * 2 > max_shot_s:
        raise ValueError("The shortest shot must be at most half the longest one.")
    pickup = bm.bars[0] if bm.bars and bm.bars[0] < min_shot_s else 0.0
    segs = _segments(bm, min_shot_s, max_shot_s, bars_per_shot, pickup, lyrics) if bm.bars else []
    if not segs:  # no beat found: even cuts of the longest allowed clip
        n = max(1, math.ceil(bm.duration_s / max_shot_s))
        segs = [{"start": k * bm.duration_s / n, "end": (k + 1) * bm.duration_s / n, "start_bar": 0, "bars": 0,
                 "section": "A", "band": "mid"} for k in range(n)]
    period = 60.0 / bm.tempo_bpm * bm.beats_per_bar if bm.tempo_bpm else max_shot_s
    # pickup before bar 1: its own (intro) shot when it is at least a bar long, else part of the first shot
    if segs[0]["start"] > 0:
        if segs[0]["start"] >= max(min_shot_s, period - TOL_S):
            segs.insert(0, {"start": 0.0, "end": segs[0]["start"], "start_bar": 0, "bars": 0, "section": "intro",
                            "band": "low"})
        else:
            segs[0]["start"] = 0.0
    # tail after the last bar: always part of the last shot (it is shorter than a bar by construction). When that
    # makes the last shot too long, the last shot is split on a bar line first so the tail joins its second half.
    last = segs[-1]
    if bm.duration_s - last["start"] > max_shot_s + TOL_S and isinstance(last["bars"], int) and last["bars"] >= 2:
        mid = [t for t in bm.bars if last["start"] < t < last["end"]]
        if mid:
            cut = mid[len(mid) // 2] if len(mid) > 1 else mid[0]
            n = sum(1 for t in mid if t < cut) + 1
            segs[-1] = {**last, "end": cut, "bars": n}
            segs.append({**last, "start": cut, "start_bar": last["start_bar"] + n, "bars": last["bars"] - n})
    if bm.duration_s > segs[-1]["end"]:
        segs[-1]["end"] = bm.duration_s
    # no shot under one bar (or under half a clip when bars are longer than clips): a short piece joins its
    # neighbour (the one before it; the first joins the next)
    shortest = min(period, max_shot_s / 2)
    k = 0
    while len(segs) > 1 and k < len(segs):
        if segs[k]["end"] - segs[k]["start"] < shortest - TOL_S:
            j = k - 1 if k > 0 else 1
            a, b = sorted((j, k))
            segs[a] = {**segs[a], "end": segs[b]["end"], "bars": segs[a]["bars"] + segs[b]["bars"]}
            segs.pop(b)
            k = max(0, a - 1)
            continue
        k += 1
    labels = camera_labels()
    regions = vocal_regions or (L.windows(lyrics) if lyrics else [])
    used: dict[str, int] = {}
    frames_at = [(round(s["start"] * fps), round(s["end"] * fps)) for s in segs]
    owner = _line_owners(lyrics or [], [(f0 / fps, f1 / fps) for f0, f1 in frames_at])
    out: list[CutShot] = []
    for k, (s, (f0, f1)) in enumerate(zip(segs, frames_at), 1):
        frames = max(1, f1 - f0)
        render = ltx_render_frames(frames)
        cams = CAMERA_BY_ENERGY[s["band"]]
        cam = cams[used.get(s["band"], 0) % len(cams)]
        used[s["band"]] = used.get(s["band"], 0) + 1
        vocal = _overlap(s["start"], s["end"], regions)
        dur = s["end"] - s["start"]
        a_s, b_s = f0 / fps, f1 / fps
        sung = [ln for ln in (lyrics or []) if owner.get(ln.index) == k - 1]
        win = [[round(max(a_s, ln.start) - a_s, 3), round(min(b_s, ln.end) - a_s, 3)] for ln in sung]
        whole = int(round(s["bars"])) if isinstance(s["bars"], int) or float(s["bars"]).is_integer() else 0
        extra = round(max(0.0, frames / fps - whole * period), 1) if whole else 0.0
        if whole and abs(frames / fps - whole * period) < 0.1:
            extra = 0.0
        if not whole:
            whole_f = frames / fps / period
            whole, extra = (int(round(whole_f)), 0.0) if abs(whole_f - round(whole_f)) < 0.05 else (int(whole_f), round(frames / fps - int(whole_f) * period, 1))
        sings = bool(sung) if lyrics else (bool(regions) and vocal >= min(lipsync_min_s, dur * 0.5))
        out.append(CutShot(index=k, start_s=round(a_s, 4), end_s=round(b_s, 4), start_frame=f0, frames=frames,
                           render_frames=render, trim_frames=render - frames, start_bar=int(s["start_bar"]),
                           bars=whole, section=s["section"], energy=s["band"], camera=cam, lipsync=sings,
                           vocal_s=round(vocal, 3), lyric=" / ".join(ln.text for ln in sung),
                           lines=[ln.index for ln in sung], sing_windows=win, camera_label=labels.get(cam, cam),
                           extra_s=extra, bars_label=bars_label(whole, extra)))
    return out


def _line_owners(lines: list, spans: list[tuple[float, float]]) -> dict[int, int]:
    """LRC line index -> the one shot (0-based) it overlaps most (ties: the earlier shot)."""
    owners: dict[int, int] = {}
    for ln in lines:
        best, best_ov = -1, 0.0
        for i, (a, b) in enumerate(spans):
            ov = min(b, ln.end) - max(a, ln.start)
            if ov > best_ov + 1e-6:
                best, best_ov = i, ov
        if best >= 0:
            owners[ln.index] = best
    return owners


def storyboard_shots(cut: list[CutShot], character: str, *, idea: str = "") -> list[dict]:
    """Rows for opensoul.storyboard.Store.add_shots (same shape as POST /api/storyboard/projects/{pid}/shots/batch)."""
    rows = []
    for c in cut:
        where = (f"bar {c.start_bar}" if c.start_bar else c.section)
        sec = c.section.title() if len(c.section) > 1 else f"Section {c.section}"
        prompt = f"{character} {'sings to the camera' if c.lipsync else 'moves with the music'}"
        if c.lipsync and c.lyric:
            prompt += f', singing "{c.lyric[:160]}"'
        if idea:
            prompt += f", {idea.strip().rstrip('.')}"
        rows.append({"beat": f"{sec} · {where}", "prompt": prompt + ".",
                     "characters": [character] if character else [], "camera": c.camera, "lipsync": c.lipsync})
    return rows
