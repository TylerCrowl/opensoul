#!/usr/bin/env python3
"""Render story takes through the app pipeline (presets.build_shot_plan + shot.run_shot) and add each one to a
storyboard project as a NEW take (opensoul.storyboard.Store.add_version: never overwrites, never moves the keeper).

  COMFY_BASE_URL=... python scripts/story_draft.py takes.json --project lumi-night-shift [--quality draft] \
      [--mem-cmd "CMD"] [--root data/projects]

takes.json: [{"shot": "<shot id>", "image": "start.png", "prompt": "...", "seeds": [1, 2], "camera": "static"?}]
camera defaults to the shot's camera. The motion-direction check runs where the camera preset expects a move
(run_shot default in live mode). Every take's wall time is stored in settings.render_seconds and appended to
<root>/<project>/draft_runs.jsonl.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from story_frames import wait_mem  # noqa: E402

from opensoul import storyboard as sb  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("takes")
    ap.add_argument("--project", required=True)
    ap.add_argument("--root", default=str(ROOT / "data/projects"))
    ap.add_argument("--quality", default="draft", choices=["draft", "final"])
    ap.add_argument("--era", default="film_35mm")
    ap.add_argument("--only", default="")
    ap.add_argument("--mem-cmd", default=None)
    ap.add_argument("--min-gb", type=float, default=30.0)
    ap.add_argument("--hold-file", default=None, help="wait (before every take) while this file exists")
    a = ap.parse_args()
    from opensoul.presets import build_shot_plan
    from opensoul.shot import run_shot

    st = sb.Store(a.root)
    p = st.load(a.project)
    landscape = p.aspect != "9:16"
    only = {x for x in a.only.split(",") if x}
    log = st.project_dir(p.id) / "draft_runs.jsonl"
    for job in json.loads(Path(a.takes).read_text()):
        if only and job["shot"] not in only:
            continue
        s = st.load(p.id).shot(job["shot"])
        cam = job.get("camera") or s.camera
        for seed in job["seeds"]:
            while a.hold_file and Path(a.hold_file).exists():
                print(f"ON HOLD: {a.hold_file} exists", flush=True)
                time.sleep(30)
            gb = wait_mem(a.mem_cmd, a.min_gb)
            take = st.reserve_take(p.id, s.id)
            work = st.take_dir(p.id, s.id, take)
            work.mkdir(parents=True, exist_ok=True)
            start = work / ("start" + Path(job["image"]).suffix)
            shutil.copy2(job["image"], start)
            plan = build_shot_plan(camera=cam, character_prompt=job["prompt"], seed=int(seed), quality=a.quality,
                                   era=a.era, overrides={"width": 1280 if landscape else 704, "height": 704 if landscape else 1280})
            # Optional per-job node edits, e.g. {"31": {"strength": 1.0}, "3": {"img_compression": 10}}:
            # merged into the video stage's inputs (the workflow file stays read-only).
            for nid, vals in (job.get("node_overrides") or {}).items():
                for stg in plan["stages"]:
                    if stg["stage"] == "video":
                        stg["inputs"][nid] = {**stg["inputs"].get(nid, {}), **vals}
            settings = {"camera": cam, "aspect": p.aspect, "base_image": sb.rel_path(start), "quality": a.quality,
                        "plan_notes": plan["notes"],
                        "node_overrides": job.get("node_overrides") or {}}
            st.add_version(p.id, s.id, take=take, prompt=job["prompt"], seed=int(seed), settings=settings,
                           kind="render", status="rendering", label=f"Rendering {a.quality}…",
                           note=job.get("note", ""))
            t0 = time.time()
            rec = {"shot": s.id, "beat": s.beat, "take": f"v{take}", "seed": seed, "quality": a.quality,
                   "camera": cam, "mem_gb": gb}
            try:
                res = run_shot(plan, start, work)
                poster = work / "poster.jpg"
                from opensoul import media

                media._run([media.ffmpeg_bin() or "ffmpeg", "-y", "-loglevel", "error", "-i", str(res.video),
                            "-frames:v", "1", str(poster)], poster)
                mc = [x for x in res.steps if x["stage"] == "motion_check"]
                vid = [x for x in res.steps if x["stage"] == "video"]
                st.update_version(p.id, s.id, f"v{take}", file=sb.rel_path(res.video), poster=sb.rel_path(poster),
                                  status="ready", label=a.quality.capitalize(),
                                  note="; ".join([job.get("note", ""), *res.notes]).strip("; "),
                                  settings={**settings, "steps": res.steps, "render_seconds": res.seconds},
                                  scores={"motion": mc[-1]} if mc else {})
                rec.update(ok=True, secs=res.seconds, video_secs=[x.get("secs") for x in vid], file=str(res.video),
                           motion=[{k: m[k] for k in ("ok", "label", "confidence", "expected")} for m in mc],
                           notes=res.notes)
            except Exception as e:  # noqa: BLE001
                st.update_version(p.id, s.id, f"v{take}", status="failed", label="Failed", note=f"Couldn't render: {e}")
                rec.update(ok=False, secs=round(time.time() - t0, 1), error=str(e)[:500])
            with open(log, "a") as f:
                f.write(json.dumps(rec) + "\n")
            print(json.dumps(rec), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
