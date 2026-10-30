"""Offline tests for presets/models.yaml + opensoul.models_registry."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from opensoul import models_registry as mr

ROOT = Path(__file__).resolve().parents[1]
YAML_PATH = ROOT / "presets" / "models.yaml"


def setup_function(_fn=None):
    mr.clear_registry_cache()


def test_models_yaml_loads_and_stages_have_id_default():
    data = yaml.safe_load(YAML_PATH.read_text(encoding="utf-8"))
    stages = data["stages"]
    assert len(stages) >= 6
    for s in stages:
        assert s.get("id"), s
        assert s.get("default_backend"), s
        assert s.get("backends"), s
        ids = {b["id"] for b in s["backends"]}
        assert s["default_backend"] in ids


def test_stage_status_returns_entries(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENSOUL_HOME", str(tmp_path / "OpenSoul"))
    monkeypatch.setenv("COMFY_DIR", str(tmp_path / "ComfyUI"))
    mr.clear_registry_cache()
    rows = mr.stage_status()
    assert isinstance(rows, list) and len(rows) >= 6
    ids = {r["id"] for r in rows}
    for need in ("sheet", "stills", "voice", "video", "lipsync", "identity_gate"):
        assert need in ids
    for r in rows:
        assert "status" in r and "backends" in r
        assert "missing_files" in r and "download_hint" in r
        assert "default_backend" in r


def test_missing_files_when_comfy_dir_empty(tmp_path, monkeypatch):
    home = tmp_path / "OpenSoul"
    comfy = tmp_path / "empty_comfy"
    (comfy / "models").mkdir(parents=True)
    home.mkdir()
    monkeypatch.setenv("OPENSOUL_HOME", str(home))
    monkeypatch.setenv("COMFY_DIR", str(comfy))
    # $HOME/... registry paths (e.g. ArcFace at ~/.insightface) must not see a real install.
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    # Clear env backends that might point at real installs.
    monkeypatch.delenv("OPENSOUL_TTS", raising=False)
    monkeypatch.delenv("OPENSOUL_LIPSYNC", raising=False)
    monkeypatch.delenv("LTX_VARIANT", raising=False)
    mr.clear_registry_cache()
    rows = {r["id"]: r for r in mr.stage_status()}
    # Required stages with weight files should be missing.
    assert rows["sheet"]["status"] == "missing"
    assert rows["stills"]["status"] == "missing"
    assert rows["voice"]["status"] == "missing"
    assert rows["video"]["status"] == "missing"
    assert rows["lipsync"]["status"] == "missing"
    assert rows["sheet"]["missing_files"]  # basenames only
    assert all("/" not in f for f in rows["sheet"]["missing_files"])
    assert "download_models.sh" in rows["sheet"]["download_hint"]
    # Patch identity gate has no files → installed.
    assert rows["identity_gate"]["status"] == "installed"
    # Optional stages → optional_missing, not a hard miss.
    assert rows["motion"]["status"] == "optional_missing"
    assert rows["pose"]["status"] == "optional_missing"
    arc = next(b for b in rows["identity_gate"]["backends"] if b["id"] == "arcface")
    assert arc["optional"] is True and arc["available"] is False


def test_health_lines_non_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENSOUL_HOME", str(tmp_path / "OpenSoul"))
    monkeypatch.setenv("COMFY_DIR", str(tmp_path / "ComfyUI"))
    (tmp_path / "ComfyUI" / "models").mkdir(parents=True)
    mr.clear_registry_cache()
    lines = mr.health_lines()
    assert lines
    assert all("label" in x and "value" in x for x in lines)
    labels = [x["label"] for x in lines]
    assert "Sheet" in labels and "Voice" in labels
