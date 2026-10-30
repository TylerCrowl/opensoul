#!/usr/bin/env python3
"""Fail (exit 1) if any workflows/*_api.json uses a node outside workflows/node_allowlist.json,
or anything that looks like a partner/API node, or references a model file that scripts/download_models.sh
does not fetch from Hugging Face (so a fresh clone can't hit a missing-model error, and every weight has a known open source). Run in CI and by tests/test_workflow_allowlist.py."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_NODE = re.compile(r"(Api|API)Node$|^(OpenAI|Gemini|Kling|Luma|Runway|Pika|Minimax|MiniMax|Ideogram|Recraft|"
                      r"Stability|Veo|Moonvalley|Bfl|Flux(Pro|Kontext(Pro|Max))|ByteDance|Tripo|Rodin|ElevenLabs|"
                      r"Vidu|Wan(Text|Image)ToVideoApi|Topaz|Bria|Hailuo)")


# Workflows the app depends on: missing one is a violation too (so a rename can't silently skip the check).
REQUIRED = ["02_consistent_stills_api.json", "03_tts_api.json", "04_i2v_ltx_api.json", "05_lipsync_api.json",
            "06_identity_gate_api.json", "07_character_sheet_api.json",
            "07b_character_sheet_back_from_side_api.json", "07t_character_from_text_api.json",
            "07z_master_from_text_zimage_api.json"]


def allowlist() -> set[str]:
    d = json.loads((ROOT / "workflows/node_allowlist.json").read_text())
    return set(d["comfy_core"]) | set(d["opensoul_nodes"])


MODEL_FILE = re.compile(r"\.(safetensors|ckpt|pt|pth|bin|onnx|gguf)$")


def model_violations(files) -> list[str]:
    dl = ROOT / "scripts/download_models.sh"
    if not dl.is_file():
        return []
    known, bad = dl.read_text(), []
    for f in files:
        for nid, node in json.loads(f.read_text()).items():
            for key, val in node.get("inputs", {}).items():
                if isinstance(val, str) and MODEL_FILE.search(val) and Path(val).name not in known:
                    bad.append(f"{f.name} node {nid}: {key}={val} is not fetched by scripts/download_models.sh")
    return bad


def violations() -> list[str]:
    allowed, bad = allowlist(), []
    files = sorted((ROOT / "workflows").glob("*_api.json"))
    if not files:
        return ["no workflows found"]
    names = {f.name for f in files}
    bad += [f"required workflow {r} is missing" for r in REQUIRED if r not in names and (ROOT / "workflows/node_allowlist.json").is_file()
            and ROOT == Path(__file__).resolve().parents[1]]
    for f in files:
        for nid, node in json.loads(f.read_text()).items():
            ct = node.get("class_type", "<missing>")
            if API_NODE.search(ct):
                bad.append(f"{f.name} node {nid}: {ct} looks like a partner/API node")
            elif ct not in allowed:
                bad.append(f"{f.name} node {nid}: {ct} is not in workflows/node_allowlist.json")
    return bad + model_violations(files)


if __name__ == "__main__":
    v = violations()
    print("\n".join(v) if v else "OK: all workflow nodes are allowlisted (core + opensoul_nodes, no API nodes) and every model file is in download_models.sh")
    sys.exit(1 if v else 0)
