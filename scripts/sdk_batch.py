#!/usr/bin/env python3
"""SDK-native drop-in for the GPU-box render runner (``v4/batch2.py`` on the GPU box).

Same jobs.json format and the same graph edits as batch2.py, but every job is submitted through
``opensoul.comfy_client.run_workflow_file`` (comfy-sdk -> Comfy API v2 -> comfy-api-proxy -> ComfyUI)
instead of the raw ``/prompt`` smoke runner. Start images and audio are uploaded as SDK assets, so
nothing is copied into ``ComfyUI/input``.

  COMFY_BASE_URL=http://127.0.0.1:8189 RDIR=~/OpenSoul/v4 python scripts/sdk_batch.py jobs.json [--dry-run]

Job keys (as in batch2.py): type ("still"|"vid"), name, seed, prompt, img, wf, audio, frames, neg, lora, lora_w, lora2, lora2_w,
plus still-only wfs/ref. Optional ``lipsync`` (true, or {"steps", "guidance", "seed"}) on an audio job runs
LatentSync through the OpenSoul node pack (``workflows/05_lipsync_api.json``) on the finished take with the same
padded audio, also via comfy-sdk, and saves ``<name>_ls.mp4``. Results are appended to $RDIR/results.jsonl as
{"name", "ok", "via": "comfy-sdk"} (plus "stage": "lipsync" for the lip-sync pass).
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from opensoul import comfy_client  # noqa: E402

log = logging.getLogger("opensoul.sdk_batch")
ROOT = Path(__file__).resolve().parents[1]
FPS = 24


def a2v_frames(duration_s: float) -> int:
    """batch2.py rule: line length + 0.6 s, rounded up to 8k+1 frames at 24 fps."""
    return math.ceil((duration_s + 0.6) * FPS / 8) * 8 + 1


def prep_audio(src: Path, dst: Path) -> int:
    """Pad 0.25 s of lead silence and trim/pad to the frame count, exactly like batch2.py. Returns frames."""
    import numpy as np

    try:
        import soundfile as sf
    except ImportError:  # ComfyUI venvs often lack soundfile; 16-bit PCM WAV via the stdlib is enough here
        sf = _WavIO()
    a, sr = sf.read(str(src))
    frames = a2v_frames(len(a) / sr)
    n = int(frames / FPS * sr)
    lead = np.zeros((int(0.25 * sr),) + a.shape[1:], dtype=a.dtype)
    a = np.concatenate([lead, a])[:n]
    if len(a) < n:
        a = np.concatenate([a, np.zeros((n - len(a),) + a.shape[1:], dtype=a.dtype)])
    sf.write(str(dst), a, sr)
    return frames


class _WavIO:
    """Minimal soundfile stand-in: 16-bit PCM WAV read/write with the stdlib ``wave`` module."""

    def read(self, path):
        import wave
        import numpy as np

        with wave.open(path, "rb") as w:
            if w.getsampwidth() != 2:
                raise RuntimeError(f"{path}: need 16-bit PCM WAV (or install soundfile)")
            a = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype("float32") / 32768.0
            ch = w.getnchannels()
            return (a.reshape(-1, ch) if ch > 1 else a), w.getframerate()

    def write(self, path, a, sr):
        import wave
        import numpy as np

        pcm = (np.clip(a, -1, 1) * 32767).astype("<i2")
        with wave.open(path, "wb") as w:
            w.setnchannels(1 if pcm.ndim == 1 else pcm.shape[1])
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(pcm.tobytes())


def build_video_job(j: dict, rdir: Path, tmp: Path) -> tuple[dict, dict, str]:
    """Return (graph, sdk inputs, output node id) for one video job. Mirrors batch2.py's graph edits."""
    wf_path = Path(j["wf"]) if j["wf"].startswith("/") else rdir / j["wf"]
    wf = json.loads(wf_path.read_text())
    frames = j.get("frames", 169)
    inputs: dict[str, dict] = {"1": {"image": str(rdir / f"{j['img']}.png")}, "20": {"text": j["prompt"]},
                               "35": {"noise_seed": j["seed"]}, "43": {"noise_seed": j["seed"]}}
    if j.get("audio"):
        wav = tmp / f"{j['name']}_{j['audio']}.wav"
        frames = prep_audio(rdir / "audio" / f"{j['audio']}.wav", wav)
        inputs["60"] = {"audio": str(wav)}
    inputs["30"] = {"length": frames}
    inputs["32"] = {"frames_number": frames}
    if j.get("lora"):
        wf["70"] = {"class_type": "LoraLoaderModelOnly",
                    "inputs": {"model": ["10", 0], "lora_name": j["lora"], "strength_model": j.get("lora_w", 1.0)}}
        wf["34"]["inputs"]["model"] = ["70", 0]
    if j.get("lora2"):
        src = ["70", 0] if j.get("lora") else ["10", 0]
        wf["71"] = {"class_type": "LoraLoaderModelOnly",
                    "inputs": {"model": src, "lora_name": j["lora2"], "strength_model": j.get("lora2_w", 1.0)}}
        wf["34"]["inputs"]["model"] = ["71", 0]
    if "neg" in j:
        inputs["21"] = {"text": j["neg"]}
    return wf, inputs, "51"


def build_lipsync_job(j: dict, video: Path, wav: Path) -> tuple[dict, dict, str]:
    """LatentSync pass on a finished take, through the node pack (no LatentSync process outside Comfy)."""
    wf = json.loads((ROOT / "workflows/05_lipsync_api.json").read_text())
    opts = j["lipsync"] if isinstance(j.get("lipsync"), dict) else {}
    ls = {"inference_steps": opts.get("steps", wf["3"]["inputs"]["inference_steps"]), "guidance_scale": opts.get("guidance", 1.5),
          "seed": opts.get("seed", j.get("seed", 1247))}
    return wf, {"1": {"file": str(video)}, "2": {"audio": str(wav)}, "3": ls}, "9"


def build_still_job(j: dict, rdir: Path, home: Path) -> tuple[dict, dict, str]:
    wf = json.loads(Path(j.get("wfs", rdir / "02.json")).read_text())
    inputs = {"5": {"image": j.get("ref", str(home / "reference_sheet.jpg"))},
              "6": {"prompt": j["prompt"]}, "3": {"seed": j["seed"]}}
    return wf, inputs, str(j.get("output_node", "9"))


def wait_for_memory(min_gb: float) -> None:
    """Don't add load while the shared host is short on unified memory (memguard kills ComfyUI below 4 GB)."""
    while True:
        try:
            kb = next(int(line.split()[1]) for line in open("/proc/meminfo") if line.startswith("MemAvailable"))
        except (OSError, StopIteration):
            return
        if kb / 1048576 >= min_gb:
            return
        log.info("MemAvailable %.1f GB < %.1f GB, waiting", kb / 1048576, min_gb)
        time.sleep(30)


def run_lipsync(j: dict, video: Path, wav: str, tmp: Path, results) -> bool:
    lwf, lin, out = build_lipsync_job(j, video, Path(wav))
    comfy_client.apply_inputs(lwf, lin)
    lwf_file = tmp / f"_wf_ls_{j['name']}.json"
    lwf_file.write_text(json.dumps(lwf))
    ok = False
    try:
        paths = comfy_client.run_workflow_file(lwf_file, inputs=lin, output_node_id=out, out_dir=tmp / f"{j['name']}_ls")
        if paths:
            shutil.copy(paths[0], video.with_name(f"{j['name']}_ls.mp4"))
            ok = True
    except Exception as e:
        log.error("lipsync %s failed: %s", j["name"], e)
    results.write(json.dumps({"name": f"{j['name']}_ls", "ok": ok, "via": "comfy-sdk", "stage": "lipsync"}) + "\n")
    results.flush()
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("jobs")
    ap.add_argument("--dry-run", action="store_true", help="build and validate every job, submit nothing")
    ap.add_argument("--min-avail-gb", type=float, default=5.0)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    home = Path(os.environ.get("OPENSOUL_HOME", Path.home() / "OpenSoul"))
    rdir = Path(os.environ.get("RDIR", home / "rb3"))
    jobs = json.loads(Path(a.jobs).read_text())
    results = None if a.dry_run else open(rdir / "results.jsonl", "a")
    rc = 0
    with tempfile.TemporaryDirectory(prefix="sdk_batch_") as td:
        tmp = Path(td)
        for j in jobs:
            wf, inputs, out_node = (build_still_job(j, rdir, home) if j["type"] == "still"
                                    else build_video_job(j, rdir, tmp))
            wf_file = (tmp if a.dry_run else rdir) / f"_wf_sdk_{j['name']}.json"
            wf_file.write_text(json.dumps(wf))
            comfy_client.apply_inputs(wf, inputs)  # fail fast on a bad node/input name
            if a.dry_run:
                if j.get("lipsync") and j.get("audio"):
                    lwf, lin, _ = build_lipsync_job(j, rdir / f"{j['name']}.mp4", Path(inputs["60"]["audio"]))
                    comfy_client.apply_inputs(lwf, lin)
                log.info("DRY %s: %s, inputs %s%s", j["name"], wf_file.name, sorted(inputs),
                         " + lipsync" if j.get("lipsync") and j.get("audio") else "")
                continue
            wait_for_memory(a.min_avail_gb)
            ok = False
            try:
                # no job metadata: the SDK sends a label map, the local comfy-api-proxy 422s on it
                paths = comfy_client.run_workflow_file(wf_file, inputs=inputs, output_node_id=out_node,
                                                       out_dir=tmp / j["name"])
                if paths:
                    ext = ".png" if j["type"] == "still" else ".mp4"
                    shutil.copy(paths[0], rdir / f"{j['name']}{ext}")
                    ok = True
            except Exception as e:  # keep the batch going, like batch2.py
                log.error("job %s failed: %s", j["name"], e)
            rc |= 0 if ok else 1
            results.write(json.dumps({"name": j["name"], "ok": ok, "via": "comfy-sdk"}) + "\n")
            results.flush()
            if ok and j.get("lipsync") and j.get("audio"):
                rc |= 0 if run_lipsync(j, rdir / f"{j['name']}.mp4", inputs["60"]["audio"], tmp, results) else 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
