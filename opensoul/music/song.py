"""Song step: lyrics or a prompt -> song.wav (+ vocals.wav for lip-sync).

* Preview (dry run, no GPU): :func:`placeholder_song` writes ORIGINAL synthetic audio: a click track whose bars follow
  the lyric sections ([verse] / [chorus] / [bridge] ...) and a soft hum on each lyric line as the stand-in
  vocal stem. Labelled preview everywhere.
* Studio: :func:`run_song_workflow` runs the model's ComfyUI workflow (registry ``runner.workflow``, API format, the same
  ``opensoul.comfy_client.run_workflow_file`` path every other workflow uses), patching the nodes named in
  ``runner.nodes``. Stems the same way with the stem model's workflow. Nothing here imports a model.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np

from opensoul.music import beats as B

ROOT = Path(__file__).resolve().parents[2]
TAG = re.compile(r"^\s*\[\s*([A-Za-z][A-Za-z0-9 \-]*?)\s*\]\s*$")
BPM = re.compile(r"(\d{2,3})\s*bpm", re.I)
KIND = {"verse": "a", "pre": "c", "chorus": "b", "hook": "b", "bridge": "c", "intro": "a", "outro": "a", "drop": "b"}
MAX_LYRICS = 3000
DEFAULT_BPM = 100


class SongError(ValueError):
    pass


def parse_lyrics(text: str) -> list[dict]:
    """[{tag, lines}] in order. Lines before any tag form a 'verse'. Empty sections are kept (instrumental)."""
    text = (text or "").replace("\r\n", "\n")
    if len(text) > MAX_LYRICS:
        raise SongError(f"Keep the lyrics under {MAX_LYRICS} characters.")
    out: list[dict] = []
    for raw in text.split("\n"):
        m = TAG.match(raw)
        if m:
            out.append({"tag": m.group(1).strip().lower(), "lines": []})
            continue
        line = " ".join(raw.split())
        if not line:
            continue
        if not out:
            out.append({"tag": "verse", "lines": []})
        out[-1]["lines"].append(line[:200])
    return out


def bpm_from_style(style: str, default: int = DEFAULT_BPM) -> int:
    m = BPM.search(style or "")
    v = int(m.group(1)) if m else default
    return v if 60 <= v <= 200 else default


def section_plan(sections: list[dict], seconds: float, bpm: int, beats_per_bar: int = 4) -> list[tuple[int, str, str]]:
    """[(bars, synth kind, tag)] filling ``seconds``: 2 bars per lyric line (min 4, max 16), scaled to fit."""
    if not sections:
        sections = [{"tag": "verse", "lines": []}]
    want = [max(4, min(16, 2 * len(s["lines"]) or 4)) for s in sections]
    bar_s = beats_per_bar * 60.0 / bpm
    total = max(4, int(seconds / bar_s))
    scale = total / sum(want)
    bars = [max(2, int(round(w * scale))) for w in want]
    while sum(bars) > total and max(bars) > 2:  # trim the longest sections until it fits
        bars[bars.index(max(bars))] -= 1
    while sum(bars) < total:  # and fill the asked length: the section furthest below its share grows by a bar
        k = max(range(len(bars)), key=lambda i: want[i] * scale - bars[i])
        bars[k] += 1
    plan = []
    for s, n in zip(sections, bars):
        key = next((k for k in KIND if s["tag"].startswith(k)), "verse")
        plan.append((n, KIND[key], s["tag"]))
    return plan


def placeholder_song(dest_dir: Path, *, lyrics: str, style: str = "", seconds: float = 30.0, seed: int = 0) -> dict:
    """Preview song + stand-in vocal stem (original synthetic audio). Returns paths and the planned sections."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    sections = parse_lyrics(lyrics)
    bpm = bpm_from_style(style)
    plan = section_plan(sections, seconds, bpm)
    lead = 0.0  # bar 1 starts at 0:00 and the song is whole bars long, so shots come out in whole bars
    mix = B.click_track(bpm=bpm, bars=sum(n for n, _, _ in plan), lead_in_s=lead,
                        sections=[(n, k) for n, k, _ in plan], seed=seed, tail_s=0.0)
    sr = B.SR
    vocal = np.zeros_like(mix)
    bar_s = 4 * 60.0 / bpm
    t0 = lead
    rng = np.random.default_rng(seed)
    sung: list[tuple[float, float, str]] = []
    for (n, _, _), sec in zip(plan, sections or [{"lines": []}]):
        lines = sec["lines"]
        f = float(rng.choice([196.0, 220.0, 247.0, 262.0, 294.0]))  # one hum pitch per section
        if lines:
            per = n * bar_s / len(lines)
            for j, _line in enumerate(lines):
                a, b = t0 + j * per + 0.1 * per, t0 + (j + 1) * per - 0.15 * per
                ia, ib = int(a * sr), min(len(vocal), int(b * sr))
                if ib <= ia:
                    continue
                sung.append((round(a, 3), round(b, 3), _line))
                t = np.arange(ib - ia) / sr
                env = np.minimum(1.0, np.minimum(t, t[::-1]) / 0.05)
                vocal[ia:ib] += (0.08 * env * np.sin(2 * np.pi * f * t) * (1 + 0.3 * np.sin(2 * np.pi * 5 * t))).astype(np.float32)
        t0 += n * bar_s
    song = np.clip(mix + vocal, -1, 1)
    B.write_wav(dest_dir / "song.wav", song)
    B.write_wav(dest_dir / "vocals.wav", vocal)
    B.write_wav(dest_dir / "instrumental.wav", mix)
    from opensoul.music import lrc

    (dest_dir / "song.lrc").write_text(lrc.write(sung), encoding="utf-8")
    return {"lrc": dest_dir / "song.lrc", "song": dest_dir / "song.wav", "vocals": dest_dir / "vocals.wav", "instrumental": dest_dir / "instrumental.wav",
            "bpm": bpm, "plan": [{"bars": n, "tag": tag} for n, _, tag in plan], "seconds": round(len(song) / sr, 3)}


# ---------------------------------------------------------------- studio (needs a GPU and ComfyUI)
def workflow_path(model: dict) -> Path | None:
    """The model's API-format workflow: env OPENSOUL_<ID>_WORKFLOW, else ``runner.workflow`` (repo-relative)."""
    from opensoul.music.registry import workflow_file

    return workflow_file(model)


def is_api_format(graph: dict) -> bool:
    """API format = {node_id: {class_type, inputs}}. The UI format (nodes/links lists) can't be queued as is."""
    return isinstance(graph, dict) and "nodes" not in graph and bool(graph) and all(
        isinstance(v, dict) and "class_type" in v for v in graph.values())


def song_inputs(model: dict, *, lyrics: str, style: str, seconds: float, seed: int) -> dict[str, dict]:
    """Node overrides from ``runner.nodes`` ({"lyrics": [node, input], ...}); unknown keys are skipped."""
    nodes = (model.get("runner") or {}).get("nodes") or {}
    values = {"lyrics": lyrics, "tags": style, "seconds": float(seconds), "duration": float(seconds), "seed": int(seed),
              "sampler_seed": int(seed), "language": "en", "timesignature": "4"}
    bpm = BPM.search(style or "")
    if bpm and 60 <= int(bpm.group(1)) <= 200:
        values["bpm"] = int(bpm.group(1))
    out: dict[str, dict] = {}
    for key, target in nodes.items():
        if key in values and isinstance(target, list) and len(target) == 2:
            out.setdefault(str(target[0]), {})[target[1]] = values[key]
    return out


def run_song_workflow(model: dict, dest_dir: Path, *, lyrics: str, style: str, seconds: float, seed: int,
                      run=None) -> Path:
    """Queue the song workflow on the studio ComfyUI and save its audio output as dest_dir/song.<ext>."""
    wf = workflow_path(model)
    if wf is None or not wf.is_file():
        raise SongError(f"{model['name']} has no workflow file yet.")
    graph = json.loads(wf.read_text(encoding="utf-8"))
    if not is_api_format(graph):
        raise SongError(f"{wf.name} is a ComfyUI editor file. Save it with Export (API) first.")
    out_node = str((model.get("runner") or {}).get("nodes", {}).get("output") or "")
    if not out_node:
        raise SongError(f"{model['name']}: the registry doesn't name the workflow's output node.")
    if run is None:
        from opensoul.comfy_client import run_workflow_file as run
    saved = run(wf, inputs=song_inputs(model, lyrics=lyrics, style=style, seconds=seconds, seed=seed),
                output_node_id=out_node, out_dir=dest_dir)
    if not saved:
        raise SongError("The song workflow finished without an audio file.")
    return Path(saved[0])
