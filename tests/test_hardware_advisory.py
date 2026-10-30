"""Recommendation-only tiers (presets/model_manifest.yaml advisory_tiers): NVIDIA 8/12/16 GB, Apple Silicon 16-128 GB
and CPU only get model suggestions instead of a bare "no recommendation", without changing the picker's own tiers,
what the app runs, or any default. Apple detection is mocked (sysctl); nothing real is run."""
from __future__ import annotations

import copy
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from opensoul import hardware as HW
from opensoul import model_manifest as MM

ROOT = Path(__file__).resolve().parents[1]


def fake_run(sysctl=None, smi_out=None):
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        assert kw.get("timeout"), "every probe needs a timeout"
        if cmd[0] == "sysctl":
            v = (sysctl or {}).get(cmd[-1])
            return SimpleNamespace(returncode=0 if v else 1, stdout=v or "", stderr="")
        if cmd[0] == "nvidia-smi":
            return SimpleNamespace(returncode=0 if smi_out else 9, stdout=smi_out or "", stderr="")
        return SimpleNamespace(returncode=0, stdout="[]", stderr="")
    run.calls = calls
    return run


MAC32 = {"machdep.cpu.brand_string": "Apple M3 Pro", "hw.memsize": str(32 * 2**30)}


def test_apple_silicon_is_detected_with_sysctl_and_gets_the_fallback_tier(tmp_path):
    run = fake_run(MAC32)
    hw = HW.detect(run=run, meminfo=tmp_path / "none", env={}, platform="darwin")
    assert hw["platform"] == "apple" and hw["chip"] == "Apple M3 Pro" and hw["memory_gb"] == 32.0
    assert hw["unified_memory"] is True and hw["gpu_class"] == "none"
    assert all(c[0] == "sysctl" for c in run.calls)  # no nvidia-smi on a Mac
    assert HW.pick_tier(hw) == "fallback"            # the app has no Mac backend: its own tiers are unchanged
    assert MM.advisory_tier(hw) == "apple_32gb"
    assert "recommendation only" in HW.describe_hardware(hw)


def test_intel_mac_and_linux_do_not_take_the_apple_path(tmp_path, monkeypatch):
    import importlib.util

    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    run = fake_run({"machdep.cpu.brand_string": "Intel(R) Core(TM) i9"})
    hw = HW.detect(run=run, meminfo=tmp_path / "none", env={}, platform="darwin")
    assert hw["platform"] == "cpu" and "sysctl found no Apple Silicon chip" in hw["notes"]
    run = fake_run(MAC32, smi_out="NVIDIA GeForce RTX 4090, 24564\n")
    hw = HW.detect(run=run, meminfo=tmp_path / "none", env={}, platform="linux")
    assert hw["platform"] == "nvidia" and not any(c[0] == "sysctl" for c in run.calls)
    assert HW.pick_tier(hw) == "rtx_24gb" and MM.advisory_tier(hw) is None


@pytest.mark.parametrize("smi,adv", [
    ("NVIDIA GeForce RTX 4060, 8188\n", "nvidia_8gb"),
    ("NVIDIA GeForce RTX 3060, 12288\n", "nvidia_12gb"),
    ("NVIDIA GeForce RTX 4080, 16376\n", "nvidia_16gb"),
    ("NVIDIA GeForce GTX 1650, 4096\n", None),         # too small even for a suggestion
])
def test_small_nvidia_cards_get_an_advisory_tier(tmp_path, smi, adv):
    hw = HW.detect(run=fake_run(smi_out=smi), meminfo=tmp_path / "none", env={}, platform="linux")
    assert HW.pick_tier(hw) == "fallback" and MM.advisory_tier(hw) == adv


def test_every_mac_size_and_cpu_only_have_a_tier():
    for name, adv in {"mac16": "apple_16gb", "mac32": "apple_32gb", "mac64": "apple_64gb", "mac128": "apple_128gb",
                      "rtx4060": "nvidia_8gb", "rtx3060": "nvidia_12gb", "rtx4080": "nvidia_16gb"}.items():
        hw = MM.simulated(name)
        assert HW.pick_tier(hw) == "fallback" and MM.advisory_tier(hw) == adv, name
    assert MM.advisory_tier(HW.simulated("cpu")) == "cpu_only"
    for name in ("spark", "spark_x2", "rtx5090", "rtx24"):  # the picker's own stacks: no advisory
        assert MM.advisory_tier(HW.simulated(name)) is None


def test_advisory_cards_cover_every_slot_and_say_recommendation_only():
    for t in MM.load()["advisory_tiers"]:
        a = MM.advisory(t["id"])
        assert a["recommendation_only"] and "recommendation only" in a["status_label"]
        assert [c["slot"] for c in a["cards"]] == list(MM.SLOT_IDS)
        for c in a["cards"]:
            m = c["model"]
            assert m is None or (a["platform"] in m["platforms"]), (t["id"], c["slot"])
            if m and m["memory"]:
                assert "measured_gb" not in m["memory"]


def test_mac_tiers_carry_the_caveats_and_never_offer_cuda_only_models():
    a = MM.advisory("apple_64gb")
    text = " ".join(a["mac_caveats"])
    assert "15804" in text and "MLX" in text and "FLUX.2 klein" in text
    ids = {c["model"]["id"] for c in a["cards"] if c["model"]}
    assert "latentsync" not in ids and not any(MM.resolve(i)["platforms"] == ["nvidia"] for i in ids)
    assert MM.advisory("nvidia_16gb")["mac_caveats"] == []
    bad = copy.deepcopy(MM.load())
    next(t for t in bad["advisory_tiers"] if t["id"] == "apple_64gb")["picks"]["lipsync"] = {"model": "latentsync"}
    assert any("does not run on apple" in p for p in MM.problems(bad))


def test_8gb_card_says_lipsync_has_no_local_option():
    c = next(c for c in MM.advisory("nvidia_8gb")["cards"] if c["slot"] == "lipsync")
    assert c["model"] is None and "17 GB" in c["note"]


def test_licence_filter_hides_conditional_models_on_advisory_cards():
    a = MM.advisory("apple_32gb", "open_only")
    hidden = {c["slot"] for c in a["cards"] if c["hidden_by_license_filter"]}
    assert hidden == {"video", "lipsync"}  # the LTX MLX ports carry the LTX-2.x terms


# ---------------------------------------------------------------- API

@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import hardware_routes as routes
    from app import server

    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    monkeypatch.delenv("OPENSOUL_MACHINES", raising=False)
    monkeypatch.setattr(server, "DATA", tmp_path)
    routes._cache.clear()
    yield TestClient(server.app)
    routes._cache.clear()


def test_api_mac_gets_an_advisory_and_the_fallback_is_unchanged(client):
    d = client.get("/api/hardware/recommend?simulate=mac32").json()
    assert d["recommendation"]["fallback"] and d["recommendation"]["cards"] == []
    adv = d["advisory"]
    assert adv["tier"] == "apple_32gb" and len(adv["cards"]) == 7 and adv["mac_caveats"]
    assert len(d["simulations"]) == 5 and {s["id"] for s in d["advisory_simulations"]} >= {"mac16", "rtx4060"}
    assert client.get("/api/hardware/detect?simulate=rtx4060").json()["advisory_tier"] == "nvidia_8gb"


def test_api_tested_tier_has_no_advisory_and_the_licence_filter_marks_cards(client):
    d = client.get("/api/hardware/recommend?simulate=spark").json()
    assert d["advisory"] is None and all(not c["hidden_by_license_filter"] for c in d["recommendation"]["cards"])
    d = client.get("/api/hardware/recommend?simulate=spark&commercial=open_only").json()
    by = {c["stage"]: c for c in d["recommendation"]["cards"]}
    assert by["video"]["hidden_by_license_filter"] and by["video"]["commercial_use"] == "conditional"
    assert not by["stills"]["hidden_by_license_filter"] and by["stills"]["commercial_use"] == "yes"
    assert client.get("/api/hardware/recommend?commercial=free").status_code == 400


def test_api_advisory_simulations_are_preview_only(client, monkeypatch):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "0")
    assert client.get("/api/hardware/detect?simulate=mac32").status_code == 400


def test_page_renders_the_advisory_and_the_licence_filter():
    js = (ROOT / "app/web/static/hardware.js").read_text()
    for bit in ("advisoryBody", "Recommendation only", "Mac notes", 'id="hwLic"', "commercial", "advisory_simulations",
                "Hidden by the license filter", "No recommendation"):
        assert bit in js, bit
