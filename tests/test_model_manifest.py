"""presets/model_manifest.yaml + opensoul/model_manifest.py: one slot per pipeline step, facts read from the existing
registries (never copied), honest memory labels, licence classes and the commercial-use filter. CPU only, no network."""
from __future__ import annotations

import copy
import re
from pathlib import Path

import pytest

from opensoul import hardware as HW
from opensoul import model_manifest as MM

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def data():
    return MM.load()


def test_manifest_is_valid(data):
    assert MM.problems(data) == []
    assert data["schema"] == 1


def test_seven_slots_in_order_with_the_apps_own_defaults(data):
    by = {s["id"]: s for s in data["slots"]}
    assert tuple(by) == MM.SLOT_IDS == ("image", "edit", "video", "lipsync", "music", "voice", "upscale")
    assert by["voice"]["default"] == "voxcpm2" and by["voice"]["fallback"] == "orpheus"  # owner decision, unchanged
    assert by["lipsync"]["default"] == "ltx_av"
    assert by["video"]["default"] == "ltx25_int8" and by["music"]["default"] == "ace_step"
    for s in data["slots"]:
        assert s["default"] == MM.app_default(s), s["id"]


def test_a_changed_default_is_caught(data):
    bad = copy.deepcopy(data)
    next(s for s in bad["slots"] if s["id"] == "voice")["default"] = "orpheus"
    next(s for s in bad["slots"] if s["id"] == "lipsync")["default"] = "latentsync"
    probs = MM.problems(bad)
    assert any("slot voice" in p and "app's own default" in p for p in probs)
    assert any("slot lipsync" in p and "app's own default" in p for p in probs)


def test_in_app_facts_come_from_hardware_profiles_not_copies(data):
    hw = HW.load()
    for mid, m in data["models"].items():
        if m["in_app"] and "own" not in m:
            r = MM.resolve(mid, data, hw)
            assert r["facts_from"] == "presets/hardware_profiles.yaml"
            for k in ("license", "license_source", "weights_gb", "url"):
                assert r[k] == hw["models"][mid].get(k), (mid, k)
    bad = copy.deepcopy(data)
    bad["models"]["voxcpm2"]["license"] = "Apache-2.0"
    assert any("read from hardware_profiles.yaml" in p for p in MM.problems(bad))


def test_every_slot_option_has_license_memory_disk_and_source(data):
    for s in MM.slots(data=data, check_files=False):
        assert s["options"], s["id"]
        for o in s["options"]:
            assert o["license"] and o["license_source"] and o["url"], o["id"]
            assert o["license_class"] in ("open", "ai_label", "use_restricted"), o["id"]
            assert "weights_gb" in o and o["weights_source"], o["id"]
            assert o["memory"] or o["memory_by_tier"] or o["bundled_with"], o["id"]


def test_candidates_are_never_measured_and_cite_full_revisions(data):
    for mid, m in data["models"].items():
        if m["in_app"]:
            continue
        assert m["install"] is None and m["in_app_note"], mid
        assert "measured_gb" not in m["memory"] and m["memory"]["source"] in ("estimate", "reported"), mid
        if m["license_verified"]:
            refs = re.findall(r"hf:([\w.-]+/[\w.-]+)@(\w+)", m["license_source"])
            assert refs and all(len(r[1]) == 40 for r in refs), mid
    bad = copy.deepcopy(data)
    bad["models"]["seedvr2_3b"]["memory"] = {"measured_gb": 12, "source": "estimate", "basis": "x"}
    assert any("measured_gb" in p for p in MM.problems(bad))
    bad = copy.deepcopy(data)
    bad["models"]["seedvr2_3b"]["install"] = {"download_groups": ["video"]}
    assert any("install: null" in p for p in MM.problems(bad))


def test_non_commercial_weights_are_blocked_never_options(data):
    ids = {b["id"] for b in MM.blocked(data)}
    assert ids == {"flux2_dev", "demucs", "arcface"}
    assert not ids & set(data["models"])
    bad = copy.deepcopy(data)
    bad["models"]["fake_nc"] = {**copy.deepcopy(bad["models"]["seedvr2_3b"]), "license": "CC-BY-NC-4.0"}
    assert any("fake_nc" in p and "not in an allowed class" in p for p in MM.problems(bad))


def test_commercial_use_filter(data):
    assert MM.commercial_ok({"commercial_use": "yes"}, "open_only")
    assert not MM.commercial_ok({"commercial_use": "conditional"}, "open_only")
    assert MM.commercial_ok({"commercial_use": "conditional"}, "allowed")
    assert not MM.commercial_ok({"commercial_use": "no"}, "any")
    with pytest.raises(ValueError):
        MM.commercial_ok({}, "nope")
    by = {s["id"]: s for s in MM.slots("open_only", data=data, check_files=False)}
    vids = {o["id"] for o in by["video"]["options"]}
    assert vids == {"wan22_ti2v_5b_gguf_q4"}  # every LTX file carries the revenue cap + AI label: conditional
    assert "orpheus" not in {o["id"] for o in by["voice"]["options"]}  # Llama 3.2 licence: conditional
    assert by["lipsync"]["options"] == []
    allowed = {s["id"]: s for s in MM.slots("allowed", data=data, check_files=False)}
    assert {"ltx25_int8", "ltx25_bf16"} <= {o["id"] for o in allowed["video"]["options"]}


def test_active_slot_is_the_default_unless_saved(data):
    s = {x["id"]: x for x in MM.slots(data=data, check_files=False)}
    assert s["voice"]["active"] == "voxcpm2" and s["voice"]["active_source"] == "app default"
    s = {x["id"]: x for x in MM.slots(data=data, check_files=False, active={"voice": "kokoro"})}
    assert s["voice"]["active"] == "kokoro" and s["voice"]["active_source"] == "saved"


def test_installed_is_a_local_file_check(tmp_path, monkeypatch, data):
    from opensoul import models_registry as MR

    monkeypatch.setenv("OPENSOUL_HOME", str(tmp_path))
    monkeypatch.setenv("COMFY_DIR", str(tmp_path / "ComfyUI"))
    r = MM.resolve("kokoro", data)
    assert MM.installed(r) is False
    for f in r["files"]:
        p = MR._resolve_path(f)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    assert MM.installed(r) is True
    assert MM.installed(MM.resolve("seedvr2_3b", data)) is None  # not in the app: OpenSoul can't tell


def test_download_groups_match_the_script():
    assert MM.download_groups() == {"stills", "sheet", "master", "video", "tts", "orpheus", "lipsync", "arcface",
                                    "motion", "pose", "music"}


def test_manifest_code_has_no_network_calls():
    src = (ROOT / "opensoul/model_manifest.py").read_text()
    for mod in ("socket", "urllib", "requests", "httpx", "http.client"):
        assert not re.search(rf"^\s*(import|from)\s+{re.escape(mod)}\b", src, re.M), mod


def test_api_slots(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app import server

    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    monkeypatch.setattr(server, "DATA", tmp_path)
    c = TestClient(server.app)
    d = c.get("/api/hardware/slots").json()
    assert d["problems"] == [] and [s["id"] for s in d["slots"]] == list(MM.SLOT_IDS)
    d = c.get("/api/hardware/slots?commercial=open_only").json()
    assert all(o["commercial_use"] == "yes" for s in d["slots"] for o in s["options"])
    assert c.get("/api/hardware/slots?commercial=maybe").status_code == 400
