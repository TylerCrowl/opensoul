"""OS-005: in studio mode the Models screen and Settings judge the studio (ComfyUI /system_stats and model folders),
not this computer."""
from __future__ import annotations

from opensoul import hardware as HW
from opensoul import model_manifest as MM
from opensoul import studio_info as SI

GB10 = {"system": {"os": "linux", "ram_total": 130663165952, "comfyui_version": "0.41.2"},
        "devices": [{"name": "cuda:0 NVIDIA GB10 : cudaMallocAsync", "type": "cuda",
                     "vram_total": int(121.7 * 1024 ** 3)}]}


def test_hardware_from_stats_is_a_spark():
    hw = SI.hardware_from_stats(GB10, "http://studio:8188")
    assert hw["studio"] is True and hw["gpu_class"] == "spark" and hw["platform"] == "nvidia"
    assert hw["memory_gb"] == 121.7
    assert HW.pick_tier(hw) != next(t["id"] for t in HW.load()["tiers"] if t.get("fallback"))
    assert "NVIDIA GB10" in HW.describe_hardware(hw)


def test_fit_label_names_the_studio():
    hw = SI.hardware_from_stats(GB10)
    m = {"platforms": ["nvidia"], "memory": {"est_gb": 20}}
    assert MM.fit(m, hw, where="studio")["label"] == "Fits your studio"
    assert "your studio" in MM.fit({"platforms": ["apple"]}, hw, where="studio")["label"]


def test_installed_on_studio():
    have = {"diffusion_models/z.safetensors", "vae/ae.safetensors"}
    assert SI.installed_on_studio(["diffusion_models/z.safetensors", "vae/ae.safetensors"], have) is True
    assert SI.installed_on_studio(["diffusion_models/missing.safetensors"], have) is False
    assert SI.installed_on_studio(["$OPENSOUL_HOME/models/x.pth"], have) is None


def test_models_route_uses_the_studio(monkeypatch):
    from fastapi.testclient import TestClient

    from app import server

    monkeypatch.setenv("OPENSOUL_DRY_RUN", "0")
    monkeypatch.setenv("OPENSOUL_COMFYUI_URL", "http://studio.invalid:8188")
    SI.clear_cache()
    monkeypatch.setattr(SI, "hardware", lambda refresh=False, opener=None: SI.hardware_from_stats(GB10, "x"))
    monkeypatch.setattr(SI, "model_files", lambda refresh=False, opener=None: {
        "diffusion_models/z_image_turbo_bf16.safetensors", "text_encoders/qwen_3_4b.safetensors", "vae/ae.safetensors"})
    c = TestClient(server.app)
    d = c.get("/api/hardware/models").json()
    assert d["studio"] is True and d["summary"].startswith("Your studio: NVIDIA GB10")
    labels = [o["fit"]["label"] for s in d["slots"] for o in s["options"]]
    assert not any("this computer" in x for x in labels)
    z = [o for s in d["slots"] for o in s["options"] if o["id"] == "z_image_turbo"]
    if z:
        assert z[0]["installed"] is True and z[0]["installed_where"] == "studio"
    det = c.get("/api/hardware/detect").json()
    assert det["summary"].startswith("Your studio:")
