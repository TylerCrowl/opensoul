"""Hardware-to-model picker: presets/hardware_profiles.yaml, opensoul/hardware.py, /api/hardware/*, the Settings view."""
from __future__ import annotations

import copy
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi.testclient import TestClient

from opensoul import hardware as HW

ROOT = Path(__file__).resolve().parents[1]
STAGES = {"stills", "video", "lipsync", "tts", "music"}


@pytest.fixture(scope="module")
def data():
    return HW.load()


# ---------------------------------------------------------------- yaml schema and honesty rules

def test_profiles_file_is_valid(data):
    assert HW.problems(data) == []
    assert data["schema"] == 1
    assert {s["id"] for s in data["stages"]} == STAGES


def test_tiers_are_the_five_in_order_and_only_one_spark_is_tested(data):
    assert [t["id"] for t in data["tiers"]] == ["spark_x1", "spark_x2", "rtx_32gb", "rtx_24gb", "fallback"]
    for t in data["tiers"]:
        assert isinstance(t["tested"], bool), t["id"]
    assert [t["id"] for t in data["tiers"] if t["tested"]] == ["spark_x1"]
    status = {t["id"]: (t["status"], t["status_label"]) for t in data["tiers"]}
    assert status == {"spark_x1": ("tested", "tested (measured on Spark)"), "spark_x2": ("planned", "planned"),
                      "rtx_32gb": ("untested", "untested (estimate)"), "rtx_24gb": ("untested", "untested (estimate)"),
                      "fallback": ("none", "no recommendation")}


def test_every_model_license_is_in_an_allowed_class_and_ltx_needs_the_ai_label(data):
    allow = set(data["license_allowlist"])
    assert allow == {"Apache-2.0", "MIT", "BSD-2-Clause", "BSD-3-Clause", "CC0-1.0", "CC-BY-4.0"}
    restricted = set(data["license_classes"]["use_restricted"]["licenses"])
    assert restricted == {"OpenRAIL++-M", "Llama 3.2 Community License"}
    for mid, m in data["models"].items():
        lic = m["license"]
        assert (lic in allow or lic in restricted
                or (lic == "LTX-2.x Community License" and m.get("ai_label") is True)), mid
        assert HW.license_allowed(m, data), mid
        assert isinstance(m["license_verified"], bool) and m["license_source"], mid
        if m["license_verified"]:
            assert "hf:" in m["license_source"], mid  # cites the Hub repo@revision it was read from


def test_verified_sources_pin_a_full_revision(data):
    import re

    for mid, m in data["models"].items():
        for ref in re.findall(r"hf:([\w.-]+/[\w.-]+)@(\w+)", m["license_source"] + " " + m.get("weights_source", "")):
            assert len(ref[1]) == 40, (mid, ref)


def test_blocked_and_unlisted_licences_are_never_recommended(data):
    nr = data["not_recommended"]
    assert set(nr) == {"demucs", "arcface"}  # LatentSync and Orpheus moved to the use-restricted class
    for mid, m in nr.items():
        assert mid not in data["models"]
        assert not HW.license_allowed(m, data), mid
        assert m["reason"]
    picked = {p["model"] for t in data["tiers"] for p in t.get("picks") or []}
    assert picked <= set(data["models"])
    assert not picked & set(nr)


def test_licence_rules_block_nc_research_gated_and_unlicensed(data):
    for lic in ("CC-BY-NC-4.0", "research-only (weights)", "gated", "no redistribution", "unlicensed", "", None,
                "non-commercial (weights)"):
        assert not HW.license_allowed({"license": lic}, data), lic
    assert not HW.license_allowed({"license": "LTX-2.x Community License"}, data)  # no AI label: not allowed
    assert not HW.license_allowed({"license": "OpenRAIL++-M (research only)"}, data)
    assert not HW.license_allowed({"license": "Llama 4 Community License"}, data)  # only the listed licences


def test_licence_classes(data):
    cls = lambda lic, **kw: HW.license_class({"license": lic, **kw}, data)  # noqa: E731
    assert cls("MIT") == cls("Apache-2.0") == "open"
    assert cls("LTX-2.x Community License", ai_label=True) == "ai_label"
    assert cls("OpenRAIL++-M") == cls("Llama 3.2 Community License") == "use_restricted"
    assert cls("CC-BY-NC-4.0") is None and cls("research-only (weights)") is None
    ur = data["license_classes"]["use_restricted"]
    assert ur["label"] == "Open weights, use-restricted"
    assert ur["explain"] == "Commercial use allowed; some uses prohibited."
    assert HW.license_class(data["models"]["latentsync"], data) == "use_restricted"
    assert HW.license_class(data["models"]["orpheus"], data) == "use_restricted"
    assert HW.license_class(data["models"]["voxcpm2"], data) == "open"


def test_no_measured_number_on_an_untested_tier_or_pick(data):
    for t in data["tiers"]:
        for p in t.get("picks") or []:
            mem = p["memory"]
            if "measured_gb" in mem:
                assert t["tested"] and p["tested"], (t["id"], p["stage"])
                assert mem["source"] == "docs/HARDWARE_MEMORY.md"
                assert "est_gb" not in mem
            else:
                assert mem["source"] == "estimate" and mem["basis"] and isinstance(mem["est_gb"], (int, float))


def test_validator_catches_a_measured_number_on_an_untested_tier(data):
    bad = copy.deepcopy(data)
    p = next(t for t in bad["tiers"] if t["id"] == "rtx_32gb")["picks"][0]
    p["memory"] = {"measured_gb": 20, "source": "docs/HARDWARE_MEMORY.md"}
    assert any("measured_gb on an untested tier" in x for x in HW.problems(bad))


def test_validator_catches_bad_licences_missing_flags_and_fake_fallback(data):
    bad = copy.deepcopy(data)
    bad["models"]["kokoro"]["license"] = "CC-BY-NC-4.0"
    del bad["tiers"][1]["tested"]
    next(t for t in bad["tiers"] if t.get("fallback"))["picks"] = [{"stage": "tts", "model": "kokoro"}]
    probs = HW.problems(bad)
    assert any("kokoro" in x and "not allowed" in x for x in probs)
    assert any("spark_x2: needs tested" in x for x in probs)
    assert any("fallback must not recommend" in x for x in probs)


def test_measured_numbers_match_docs_hardware_memory(data):
    doc = (ROOT / "docs/HARDWARE_MEMORY.md").read_text()
    spark = next(t for t in data["tiers"] if t["id"] == "spark_x1")
    by = {p["stage"]: p["memory"] for p in spark["picks"]}
    assert by["stills"]["measured_gb"] == 28.8 and "28.8 GB" in doc and "28.7 GiB" in doc
    assert by["video"]["measured_gb"] == 70.7 and "70.7 GB" in doc and "68.0 GiB" in doc


def test_model_ids_reuse_the_registries(data):
    reg = yaml.safe_load((ROOT / "presets/models.yaml").read_text())
    backends = {b["id"] for s in reg["stages"] for b in s["backends"]}
    for mid, m in {**data["models"], **data["not_recommended"]}.items():
        if m.get("in_app") is False:
            assert "registry" not in m and m["in_app_note"], mid
            continue
        if m["registry"]["file"].endswith(".yaml"):
            assert mid == m["registry"]["backend"] and mid in backends, mid


def test_every_tier_but_the_fallback_covers_every_stage(data):
    for t in data["tiers"]:
        stages = {p["stage"] for p in t.get("picks") or []}
        assert stages == (set() if t.get("fallback") else STAGES), t["id"]


# ---------------------------------------------------------------- detection (mocked, nothing real is run)

SMI_SPARK = "NVIDIA GB10, [N/A]\n"
SMI_5090 = "NVIDIA GeForce RTX 5090, 32607\n"
SMI_4090 = "NVIDIA GeForce RTX 4090, 24564\n"
SMI_12GB = "NVIDIA GeForce RTX 3060, 12288\n"
MEM_SPARK = "MemTotal:       127607332 kB\nMemFree:  1000 kB\nMemAvailable: 122000000 kB\n"
MEM_PC = "MemTotal:       65660000 kB\n"
MEM_SMALL = "MemTotal:       16303000 kB\n"


def fake_run(smi_out=None, smi_exc=None, torch_out=None):
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        assert kw.get("timeout"), "every probe needs a timeout"
        if cmd[0] == "nvidia-smi":
            if smi_exc:
                raise smi_exc
            return SimpleNamespace(returncode=0 if smi_out is not None else 9, stdout=smi_out or "", stderr="")
        return SimpleNamespace(returncode=0, stdout=torch_out or "[]", stderr="")
    run.calls = calls
    return run


def _mem(tmp_path, text):
    p = tmp_path / "meminfo"
    p.write_text(text)
    return p


def test_parse_helpers():
    assert HW.parse_nvidia_smi(SMI_SPARK) == [{"name": "NVIDIA GB10", "vram_gb": None}]
    assert HW.parse_nvidia_smi(SMI_5090)[0]["vram_gb"] == 31.84
    assert HW.parse_meminfo(MEM_SPARK) == 121.7
    assert HW.parse_nvidia_smi("") == [] and HW.parse_meminfo("junk") is None


@pytest.mark.parametrize("smi,mem,tier,cls", [
    (SMI_SPARK, MEM_SPARK, "spark_x1", "spark"),
    (SMI_5090, MEM_PC, "rtx_32gb", "discrete"),
    (SMI_4090, MEM_PC, "rtx_24gb", "discrete"),
    (SMI_12GB, MEM_PC, "fallback", "discrete"),
])
def test_detect_with_mocked_nvidia_smi(tmp_path, smi, mem, tier, cls):
    hw = HW.detect(run=fake_run(smi), meminfo=_mem(tmp_path, mem), env={})
    assert hw["gpu_class"] == cls and hw["machines"] == 1 and hw["machines_source"] == "default"
    assert HW.pick_tier(hw) == tier


def test_spark_is_unified_memory_and_reads_meminfo(tmp_path):
    hw = HW.detect(run=fake_run(SMI_SPARK), meminfo=_mem(tmp_path, MEM_SPARK), env={})
    assert hw["unified_memory"] is True and hw["vram_gb"] is None and hw["memory_gb"] == 121.7
    assert "unified" in HW.describe_hardware(hw)


def test_cpu_only_when_nvidia_smi_is_missing(tmp_path, monkeypatch):
    import importlib.util

    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)  # no torch either
    run = fake_run(smi_exc=FileNotFoundError())
    hw = HW.detect(run=run, meminfo=_mem(tmp_path, MEM_SMALL), env={})
    assert hw["gpu_class"] == "none" and hw["gpus"] == []
    assert "nvidia-smi not found" in hw["notes"] and "torch not installed" in hw["notes"]
    assert HW.pick_tier(hw) == "fallback"


def test_nvidia_smi_timeout_falls_back_to_torch_in_a_child_process(tmp_path, monkeypatch):
    import importlib.util

    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    run = fake_run(smi_exc=subprocess.TimeoutExpired("nvidia-smi", 5),
                   torch_out='[{"name": "NVIDIA GeForce RTX 5090", "vram_gb": 31.4}]')
    hw = HW.detect(run=run, meminfo=_mem(tmp_path, MEM_PC), env={})
    assert any("timed out" in n for n in hw["notes"]) and "torch.cuda" in hw["notes"]
    assert run.calls[1][1] == "-c"  # torch runs in a child process, never imported into the app
    assert HW.pick_tier(hw) == "rtx_32gb"


def test_detection_never_raises(tmp_path, monkeypatch):
    import importlib.util

    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    hw = HW.detect(run=fake_run(smi_exc=PermissionError()), meminfo=tmp_path / "missing", env={})
    assert hw["gpu_class"] == "none" and hw["memory_gb"] is None


def test_detection_source_has_no_network_calls():
    import re

    src = (ROOT / "opensoul/hardware.py").read_text() + (ROOT / "app/hardware_routes.py").read_text()
    for mod in ("socket", "urllib", "requests", "httpx", "http.client", "paramiko", "zeroconf"):
        assert not re.search(rf"^\s*(import|from)\s+{re.escape(mod)}\b", src, re.M), mod
    for cmd in ("ssh", "ping", "nmap", "arp", "avahi-browse", "curl", "nc"):
        assert not re.search(rf"[\[(,]\s*[\"']{re.escape(cmd)}[\"']", src), cmd  # never run as a subprocess


def test_machine_count_comes_from_env_then_setting_then_one():
    assert HW.machines_setting({}, {}) == (1, "default")
    assert HW.machines_setting({"machines": 2}, {}) == (2, "setting")
    assert HW.machines_setting({"machines": 1}, {"OPENSOUL_MACHINES": "2"}) == (2, "OPENSOUL_MACHINES")
    assert HW.machines_setting({}, {"OPENSOUL_MACHINES": "lots"}) == (1, "default")


# ---------------------------------------------------------------- recommendation

def test_two_sparks_split_video_from_pictures_and_sound(tmp_path, data):
    hw = HW.detect(run=fake_run(SMI_SPARK), meminfo=_mem(tmp_path, MEM_SPARK), env={"OPENSOUL_MACHINES": "2"})
    assert HW.pick_tier(hw, data) == "spark_x2"
    r = HW.recommend("spark_x2", data)
    where = {c["stage"]: c["machine"] for c in r["cards"]}
    assert where["video"] == where["lipsync"] == "a"
    assert where["stills"] == where["tts"] == where["music"] == "b"
    assert not r["tested"] and all(c["memory_kind"] == "estimate" and c["measured_gb"] is None for c in r["cards"])
    assert "never looks for the second machine" in r["note"]


def test_two_sparks_is_planned_with_a_plain_reason(data):
    r = HW.recommend("spark_x2", data)
    assert r["status"] == "planned" and r["status_label"] == "planned"
    assert "one ComfyUI address" in r["planned_reason"]
    assert all(c["badge"] == "planned (estimate)" for c in r["cards"])
    assert {t["id"]: t["status"] for t in HW.tiers_summary(data)}["spark_x2"] == "planned"
    bad = copy.deepcopy(data)
    del next(t for t in bad["tiers"] if t["id"] == "spark_x2")["planned_reason"]
    assert any("planned_reason" in x for x in HW.problems(bad))


def test_spark_recommendation_is_the_measured_bf16_stack(data):
    r = HW.recommend("spark_x1", data)
    by = {c["stage"]: c for c in r["cards"]}
    assert r["tested"] and [c["stage"] for c in r["cards"]] == ["stills", "video", "lipsync", "tts", "music"]
    assert by["video"]["model_id"] == "ltx25_bf16" and by["video"]["badge"] == "tested (measured on Spark)"
    assert by["stills"]["model_id"] == "qwen_edit_bf16" and by["stills"]["measured_gb"] == 28.8
    assert by["music"]["badge"] == "untested (estimate)" and by["music"]["est_gb"] == 24  # never run from the app
    assert all(c["license"] for c in r["cards"])


def test_32gb_and_24gb_use_compressed_ltx_and_are_estimates(data):
    for tid in ("rtx_32gb", "rtx_24gb"):
        r = HW.recommend(tid, data)
        by = {c["stage"]: c for c in r["cards"]}
        assert by["video"]["model_id"] == "ltx25_int8" and by["stills"]["model_id"] == "qwen_edit_fp8mixed"
        assert "--lowvram" in r["launch_flags"]
        assert all(c["badge"] == "untested (estimate)" and c["measured_gb"] is None for c in r["cards"])
    assert {c["stage"]: c["model_id"] for c in HW.recommend("rtx_24gb", data)["cards"]}["tts"] == "kokoro"


def test_lipsync_card_shows_the_real_default_a2v_plus_latentsync_stage2(data):
    c = next(c for c in HW.recommend("spark_x1", data)["cards"] if c["stage"] == "lipsync")
    assert c["model_id"] == "ltx_av" and "camera-locked" in c["model"] and "a2v" in c["model"]
    s2 = c["stage2"]
    assert s2["model_id"] == "latentsync" and s2["model"] == "LatentSync 1.6"
    assert s2["license"] == "OpenRAIL++-M" and s2["license_class"] == "use_restricted"
    assert s2["license_class_label"] == "Open weights, use-restricted"
    assert s2["tested"] and s2["badge"] == "tested (measured on Spark)"
    assert (s2["measured_low_gb"], s2["measured_gb"]) == (17.0, 21.6)  # 17-22 GB
    assert s2["why"].startswith("Optional, off by default") and "may pale lips" in s2["why"]  # review ruling
    doc = (ROOT / "docs/HARDWARE_MEMORY.md").read_text()
    assert "21.6 GB" in doc and "17.0 GiB" in doc
    for tid in ("spark_x2", "rtx_32gb", "rtx_24gb"):  # elsewhere Stage 2 is an estimate, never "measured"
        c = next(c for c in HW.recommend(tid, data)["cards"] if c["stage"] == "lipsync")
        assert c["stage2"]["model_id"] == "latentsync" and c["stage2"]["memory_kind"] == "estimate"


def test_no_second_model_wording_is_gone():
    text = (ROOT / "presets/hardware_profiles.yaml").read_text() + (ROOT / "app/web/static/hardware.js").read_text()
    for gone in ("no second model", "needs nothing extra", "No extra model", "no extra lip-sync pass"):
        assert gone.lower() not in text.lower(), gone


def test_ltx_licence_line_stays_factual(data):
    note = data["models"]["ltx25_bf16"]["license_note"]
    assert "accept the license on Hugging Face first" in note  # gated download
    assert "$10M or more in yearly revenue need a paid license" in note
    assert "AI-generated label" in note


def test_voice_options_voxcpm2_for_new_stories_orpheus_as_fallback(data):
    vo = HW.voice_options(data)
    by = {v["model_id"]: v for v in vo}
    assert list(by) == ["chatterbox", "orpheus", "kokoro", "voxcpm2"]
    assert by["chatterbox"]["status"] == "recommended" and by["chatterbox"]["license"] == "MIT"
    assert by["orpheus"]["status"] == "app_default" and by["orpheus"]["license"] == "Llama 3.2 Community License"
    assert by["orpheus"]["license_class_label"] == "Open weights, use-restricted"
    assert by["voxcpm2"]["status"] == "new_stories_default" and by["voxcpm2"]["in_app"] is True  # runner + 03d
    assert by["voxcpm2"]["status_label"] == "Default for new stories" and "Orpheus" in by["voxcpm2"]["note"]
    assert by["voxcpm2"]["license"] == "Apache-2.0" and by["voxcpm2"]["license_verified"]
    assert "hf:openbmb/VoxCPM2@32279effe8c19989596f05d353d1447f51d9e915" in by["voxcpm2"]["license_source"]
    # The picker never claims a default the app doesn't use: app_default is presets/models.yaml's.
    reg = yaml.safe_load((ROOT / "presets/models.yaml").read_text())
    assert next(st for st in reg["stages"] if st["id"] == "voice")["default_backend"] == "orpheus"
    assert data["voice_options"]["app_default"] == "orpheus"
    tts = next(c for c in HW.recommend("spark_x1", data)["cards"] if c["stage"] == "tts")
    assert tts["model_id"] == "chatterbox" and tts["recommended"]
    assert "New stories speak with VoxCPM2" in tts["app_default_note"] and "Orpheus" in tts["app_default_note"]
    bad = copy.deepcopy(data)
    bad["voice_options"]["app_default"] = "chatterbox"
    assert any("default_backend" in x for x in HW.problems(bad))
    bad = copy.deepcopy(data)  # the picker's new-story default must be the preset's
    next(o for o in bad["voice_options"]["options"] if o["model"] == "voxcpm2")["status"] = "in_app"
    assert any("tts_default_new" in x for x in HW.problems(bad))


def test_a_model_not_in_the_app_can_never_be_a_pick(data):
    bad = copy.deepcopy(data)
    bad["models"]["voxcpm2"].update(in_app=False, in_app_note="not wired")  # VoxCPM2 is in the app now: pretend
    bad["models"]["voxcpm2"].pop("registry", None)
    next(p for p in bad["tiers"][0]["picks"] if p["stage"] == "tts")["model"] = "voxcpm2"
    assert any("not in the app" in x for x in HW.problems(bad))


def test_fallback_recommends_nothing_and_says_why(data):
    r = HW.recommend("fallback", data)
    assert r["fallback"] and r["cards"] == [] and "24 GB" in r["summary"] and "Preview mode" in r["note"]


def test_simulations_cover_every_tier(data):
    got = {name: HW.pick_tier(HW.simulated(name, data), data) for name in data["simulations"]}
    assert got == {"spark": "spark_x1", "spark_x2": "spark_x2", "rtx5090": "rtx_32gb", "rtx24": "rtx_24gb", "cpu": "fallback"}


def test_settings_validate_and_keep_labels_only(tmp_path, data):
    s = HW.save_settings(tmp_path, {"machines": 2, "tier_override": "rtx_24gb",
                                    "machine_list": [{"label": "Studio A", "role": "video", "host": "studio-a.example"}]}, data)
    assert s == {"machines": 2, "tier_override": "rtx_24gb", "machine_list": [{"label": "Studio A", "role": "video"}]}
    assert HW.load_settings(tmp_path) == s
    for bad in ({"machines": 0}, {"machines": True}, {"tier_override": "nope"}, {"machine_list": [{"role": "x"}]}):
        with pytest.raises(ValueError):
            HW.save_settings(tmp_path, bad, data)
    assert HW.save_settings(tmp_path, {"tier_override": "auto", "machines": None}, data) == {
        "machine_list": [{"label": "Studio A", "role": "video"}]}


# ---------------------------------------------------------------- API

@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import hardware_routes as routes
    from app import server

    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    monkeypatch.delenv("OPENSOUL_MACHINES", raising=False)
    monkeypatch.setattr(server, "DATA", tmp_path)
    routes._cache.clear()
    monkeypatch.setattr(HW, "detect", lambda **kw: {
        "simulated": False, "gpus": [], "memory_gb": 15.6, "gpu_class": "none", "unified_memory": False,
        "vram_gb": None, "gpu_name": None, "machines": 1, "machines_source": "default", "machine_list": [],
        "notes": ["nvidia-smi not found"]})
    yield TestClient(server.app)
    routes._cache.clear()


def test_api_detect_real_and_simulated(client):
    d = client.get("/api/hardware/detect").json()
    assert d["auto_tier"] == "fallback" and d["hardware"]["simulated"] is False and d["dry_run"] is True
    d = client.get("/api/hardware/detect?simulate=rtx5090").json()
    assert d["auto_tier"] == "rtx_32gb" and d["hardware"]["simulated"] is True
    assert client.get("/api/hardware/detect?simulate=nope").status_code == 404


def test_api_simulation_is_preview_only(client, monkeypatch):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "0")
    assert client.get("/api/hardware/detect?simulate=spark").status_code == 400
    assert client.get("/api/hardware/recommend").json()["simulations"] == []


def test_api_recommend_detected_manual_and_saved(client):
    d = client.get("/api/hardware/recommend").json()
    assert d["tier_source"] == "detected" and d["recommendation"]["fallback"] and d["recommendation"]["cards"] == []
    assert [t["id"] for t in d["tiers"]][-1] == "fallback" and len(d["simulations"]) == 5
    d = client.get("/api/hardware/recommend?tier=spark_x1").json()
    assert d["tier_source"] == "manual" and d["recommendation"]["tested"] is True
    assert client.get("/api/hardware/recommend?tier=nope").status_code == 404
    assert client.post("/api/hardware/settings", json={"tier_override": "rtx_24gb"}).status_code == 200
    d = client.get("/api/hardware/recommend").json()
    assert d["tier_source"] == "setting" and d["recommendation"]["tier"] == "rtx_24gb"
    d = client.get("/api/hardware/recommend?simulate=spark").json()  # a preview ignores the saved choice
    assert d["tier_source"] == "simulated" and d["recommendation"]["tier"] == "spark_x1"


def test_api_settings_machine_count(client, monkeypatch):
    assert client.get("/api/hardware/settings").json()["machines"] == 1
    assert client.post("/api/hardware/settings", json={"machines": 2}).json()["machines_source"] == "setting"
    assert client.get("/api/hardware/detect").json()["hardware"]["machines"] == 2
    assert client.post("/api/hardware/settings", json={"machines": 99}).status_code == 400
    monkeypatch.setenv("OPENSOUL_MACHINES", "1")
    assert client.get("/api/hardware/settings").json()["machines_source"] == "OPENSOUL_MACHINES"


def test_api_tiers_reports_no_problems(client):
    d = client.get("/api/hardware/tiers").json()
    assert d["problems"] == [] and d["tiers"][0]["tested"] is True


# ---------------------------------------------------------------- page

def test_settings_view_is_wired_into_the_page():
    html = (ROOT / "app/web/index.html").read_text()
    for bit in ('id="settingsLink"', 'id="settingsView"', 'id="hwIntro"', "/static/hardware.js", "/static/hardware.css"):
        assert bit in html, bit
    js = (ROOT / "app/web/static/hardware.js").read_text()
    for bit in ("/api/hardware/recommend", "/api/hardware/settings", "/api/hardware/detect", "Tested · measured on Spark",
                "Untested · estimate", "Planned · estimate", "hw-badge planned", "hw-badge restricted", "Stage 2",
                "Voice options", "Recommended", "<dt>License</dt>", "Models we don’t offer", "opensoul.hwIntroSeen"):
        assert bit in js, bit
