#!/usr/bin/env python3
"""Run one workflow end to end through opensoul.comfy_client (comfy-sdk) and log every step.

  COMFY_BASE_URL=http://127.0.0.1:8189 python scripts/sdk_run.py workflows/02_consistent_stills_api.json \
      --set 5.image=assets/sheet.png --set 6.prompt="..." --output-node 9 --out out/
Values that are existing file paths are uploaded as SDK assets. Numbers are parsed as JSON.
"""
import argparse, json, logging, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from opensoul import comfy_client  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("workflow")
ap.add_argument("--set", action="append", default=[], help="NODE.INPUT=VALUE")
ap.add_argument("--output-node", default="9")
ap.add_argument("--out", default="outputs")
a = ap.parse_args()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
inputs: dict = {}
for s in a.set:
    k, v = s.split("=", 1)
    node, name = k.split(".", 1)
    try:
        v = json.loads(v)
    except ValueError:
        pass
    inputs.setdefault(node, {})[name] = v
import comfy_sdk  # noqa: E402
logging.info("comfy_sdk version %s, status %s", getattr(comfy_sdk, "__version__", "?"), comfy_client.sdk_status())
t = time.time()
paths = comfy_client.run_workflow_file(a.workflow, inputs=inputs, output_node_id=a.output_node, out_dir=a.out)
logging.info("DONE %d output(s) in %.1fs: %s", len(paths), time.time() - t, [str(p) for p in paths])
sys.exit(0 if paths else 1)
