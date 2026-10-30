import importlib.util
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_workflows", ROOT / "scripts/check_workflows.py")
cw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cw)


def test_all_workflows_use_only_allowlisted_nodes():
    assert cw.violations() == []


def test_checker_rejects_unknown_and_api_nodes(tmp_path, monkeypatch):
    (tmp_path / "workflows").mkdir()
    (tmp_path / "workflows/node_allowlist.json").write_text(json.dumps({"comfy_core": ["SaveImage"], "opensoul_nodes": []}))
    (tmp_path / "workflows/x_api.json").write_text(json.dumps({
        "1": {"class_type": "SaveImage", "inputs": {}},
        "2": {"class_type": "SomeRandomCustomNode", "inputs": {}},
        "3": {"class_type": "OpenAIGPTImage1", "inputs": {}}}))
    monkeypatch.setattr(cw, "ROOT", tmp_path)
    v = cw.violations()
    assert len(v) == 2 and any("SomeRandomCustomNode" in s for s in v) and any("partner/API" in s for s in v)


def test_no_note_or_stub_workflows():
    for f in (ROOT / "workflows").glob("*_api.json"):
        g = json.loads(f.read_text())
        assert all(n["class_type"] != "Note" for n in g.values()), f.name


def test_no_raw_comfyui_http_in_app_code():
    """Live GPU work must go through comfy_sdk (opensoul/comfy_client.py), not raw /prompt calls."""
    pat = re.compile(r"""["']/prompt["']|:8188/|ws://""")
    for d in ("opensoul", "app", "scripts"):
        for p in (ROOT / d).rglob("*.py"):
            assert not pat.search(p.read_text()), f"raw ComfyUI HTTP in {p.relative_to(ROOT)}"


def test_checker_flags_model_files_missing_from_downloader(tmp_path, monkeypatch):
    (tmp_path / "workflows").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/download_models.sh").write_text("fetch x/known.safetensors\n")
    (tmp_path / "workflows/node_allowlist.json").write_text(json.dumps({"comfy_core": ["UNETLoader"], "opensoul_nodes": []}))
    (tmp_path / "workflows/x_api.json").write_text(json.dumps({
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "known.safetensors"}},
        "2": {"class_type": "UNETLoader", "inputs": {"unet_name": "missing_bf16.safetensors"}}}))
    monkeypatch.setattr(cw, "ROOT", tmp_path)
    v = cw.violations()
    assert len(v) == 1 and "missing_bf16.safetensors" in v[0]
