#!/usr/bin/env python3
"""Compose story start frames with up to three characters (workflow 08, Qwen-Image-Edit-2511 multi-image).

  COMFY_BASE_URL=... python scripts/story_frames.py frames.json --out DIR [--mem-cmd "CMD"]

frames.json: [{"name": "doors", "images": ["lumi.png", "mio.png", "ren.png"], "prompt": "...", "seeds": [1, 2],
               "width": 1344, "height": 768}]. With fewer than three images the last one is repeated.
--mem-cmd prints the GPU box's MemAvailable in GB; each job waits until it is >= --min-gb (default 30).
Writes DIR/<name>_s<seed>.png and appends {"name", "seed", "secs", "file"} to DIR/frames.jsonl.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from opensoul import scene  # noqa: E402

WF = scene.WORKFLOW


def wait_mem(cmd: str | None, min_gb: float) -> float | None:
    if not cmd:
        return None
    while True:
        try:
            gb = float(subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=180).stdout.strip().split()[-1])
        except (ValueError, IndexError, subprocess.SubprocessError):
            gb = -1.0
        if gb >= min_gb:
            return gb
        print(f"MemAvailable {gb:.1f} GB < {min_gb} GB, waiting", flush=True)
        time.sleep(30)


def frame_inputs(job: dict, seed: int) -> dict:
    if not job.get("images"):
        raise ValueError(f"{job['name']}: needs at least one picture")
    return scene.frame_inputs(job["images"], job["prompt"], seed, int(job.get("width", 1344)), int(job.get("height", 768)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("jobs")
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", default="")
    ap.add_argument("--mem-cmd", default=None)
    ap.add_argument("--min-gb", type=float, default=30.0)
    a = ap.parse_args()
    from opensoul.comfy_client import run_workflow_file

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    only = {x for x in a.only.split(",") if x}
    for job in json.loads(Path(a.jobs).read_text()):
        if only and job["name"] not in only:
            continue
        for seed in job.get("seeds", [1]):
            gb = wait_mem(a.mem_cmd, a.min_gb)
            t0 = time.time()
            tmp = out / f"_{job['name']}_s{seed}"
            paths = run_workflow_file(WF, inputs=frame_inputs(job, seed), output_node_id="9", out_dir=tmp)
            dest = out / f"{job['name']}_s{seed}.png"
            Path(paths[0]).replace(dest)
            rec = {"name": job["name"], "seed": seed, "secs": round(time.time() - t0, 1), "file": str(dest), "mem_gb": gb}
            with open(out / "frames.jsonl", "a") as f:
                f.write(json.dumps(rec) + "\n")
            print(json.dumps(rec), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
