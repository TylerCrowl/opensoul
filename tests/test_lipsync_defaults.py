"""Default lip-sync is LTX joint audio+video (04b) everywhere; LatentSync is an optional download."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_models_yaml_default_and_optional_latentsync():
    stages = {s["id"]: s for s in yaml.safe_load((ROOT / "presets" / "models.yaml").read_text())["stages"]}
    ls = stages["lipsync"]
    assert ls["default_backend"] == "ltx_av"
    b = {x["id"]: x for x in ls["backends"]}
    assert b["latentsync"]["optional"] is True and not b["ltx_av"].get("optional")
    assert "workflows/04b_a2v_ltx_api.json" in ls["workflows"]


def test_code_defaults_are_ltx_av(monkeypatch):
    monkeypatch.delenv("OPENSOUL_LIPSYNC", raising=False)
    from opensoul import lipsync as L
    from opensoul import shot, speak
    from opensoul.presets import build_shot_plan

    assert L.DEFAULT_BACKEND == "ltx_av" and shot.lipsync_backend_name() == "ltx_av"
    assert speak.get_lipsync(dry_run=True).name == "ltx_av"
    plan = build_shot_plan(camera="static", line="Hi there <chuckle>", quality="final")
    vid = next(s for s in plan["stages"] if s["stage"] == "video")
    assert vid["workflow"] == L.A2V_WORKFLOW and not any(s["stage"] == "lipsync" for s in plan["stages"])
    assert [s["stage"] for s in plan["stages"]][:2] == ["voice", "video"]


def test_registry_reports_ltx_av_as_the_default_and_latentsync_optional():
    from opensoul import models_registry as mr

    mr.clear_registry_cache()
    row = next(r for r in mr.backend_choices() if r["stage"] == "lipsync")
    assert row["default"] == "ltx_av"
    assert row["all_ids"][0] == "ltx_av" and "latentsync" in row["all_ids"]
    st = next(s for s in mr.stage_status() if s["id"] == "lipsync")
    assert {b["id"]: b["optional"] for b in st["backends"]} == {"ltx_av": False, "latentsync": True}
