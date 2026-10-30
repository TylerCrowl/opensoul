"""Draft / Final quality tiers: draft is smaller, shorter, fewer steps, no lip-sync; Final re-renders a take."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opensoul import presets
from opensoul.presets import NODE_AUDIO_LATENT, NODE_LATENT, NODE_SCALE, NODE_SIGMAS_1, NODE_SIGMAS_2, build_shot_plan

ROOT = Path(__file__).resolve().parents[1]
WF = json.loads((ROOT / presets.I2V_WORKFLOW).read_text())


def _steps(sig: str) -> int:
    return len([x for x in sig.split(",") if x.strip()]) - 1


def test_draft_is_smaller_shorter_and_has_fewer_steps_than_final():
    land = {"width": 1280, "height": 704}
    d = build_shot_plan(camera="dolly_in", line="Hello there.", seed=5, quality="draft", overrides=land)
    # the I2V tiers (with a post-video lip-sync); the default ltx_av Final renders with workflow 04b instead
    f = build_shot_plan(camera="dolly_in", line="Hello there.", seed=5, quality="final", overrides=land,
                        lipsync_backend="latentsync")
    fa = build_shot_plan(camera="dolly_in", line="Hello there.", seed=5, quality="final", overrides=land)
    assert next(s for s in fa["stages"] if s["stage"] == "video")["workflow"] == "workflows/04b_a2v_ltx_api.json"
    dv = next(s for s in d["stages"] if s["stage"] == "video")
    fv = next(s for s in f["stages"] if s["stage"] == "video")
    assert dv["inputs"][NODE_SCALE] == {"width": 896, "height": 512}
    assert fv["inputs"][NODE_SCALE] == {"width": 1280, "height": 704}
    assert dv["inputs"][NODE_LATENT]["width"] == 448 and dv["inputs"][NODE_LATENT]["height"] == 256
    assert fv["inputs"][NODE_LATENT] == {"width": 640, "height": 352}
    frames = dv["inputs"][NODE_LATENT]["length"]
    assert frames < WF[NODE_LATENT]["inputs"]["length"] and (frames - 1) % 8 == 0
    assert dv["inputs"][NODE_AUDIO_LATENT]["frames_number"] == frames
    assert "length" not in fv["inputs"][NODE_LATENT]  # final keeps the workflow's own length
    assert _steps(dv["inputs"][NODE_SIGMAS_1]["sigmas"]) < _steps(WF[NODE_SIGMAS_1]["inputs"]["sigmas"])
    assert _steps(dv["inputs"][NODE_SIGMAS_2]["sigmas"]) < _steps(WF[NODE_SIGMAS_2]["inputs"]["sigmas"])
    assert NODE_SIGMAS_1 not in fv["inputs"]
    kinds_d = [s["stage"] for s in d["stages"]]
    kinds_f = [s["stage"] for s in f["stages"]]
    assert "lipsync" not in kinds_d and "voice" not in kinds_d
    assert "lipsync" in kinds_f and "voice" in kinds_f
    assert d["quality"] == "draft" and dv["quality"] == "draft"


def test_draft_inputs_name_real_nodes_and_inputs():
    from opensoul.comfy_client import apply_inputs

    for aspect in ({"width": 1280, "height": 704}, {"width": 704, "height": 1280}):
        for q in ("draft", "final"):
            plan = build_shot_plan(camera="static", quality=q, overrides=aspect)
            apply_inputs(WF, plan["stages"][0]["inputs"])  # raises on a typo'd node/input


def test_draft_portrait_and_unknown_quality():
    d = build_shot_plan(camera="static", quality="draft")
    assert d["stages"][0]["inputs"][NODE_SCALE] == {"width": 512, "height": 896}
    with pytest.raises(KeyError):
        build_shot_plan(camera="static", quality="ultra")


def test_with_loras_chains_between_unet_and_guider():
    from opensoul.shot import with_loras

    g = with_loras(WF, [{"name": "a.safetensors", "strength": 0.9}, {"name": "b.safetensors"}])
    assert g["70"]["inputs"]["model"] == ["10", 0] and g["71"]["inputs"]["model"] == ["70", 0]
    assert g["34"]["inputs"]["model"] == ["71", 0]
    assert WF["34"]["inputs"]["model"] == ["10", 0]  # original untouched


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    return TestClient(server.app)


def test_storyboard_draft_then_final_makes_new_takes(client):
    p = client.post("/api/storyboard/projects", json={"title": "Q", "character": "Lumi"}).json()
    p = client.post(f"/api/storyboard/projects/{p['id']}/shots", json={"beat": "Open", "prompt": "rain"}).json()
    sid = p["shots"][0]["id"]
    base = f"/api/storyboard/projects/{p['id']}/shots/{sid}"
    r = client.post(f"{base}/regenerate", json={"seed": 11})  # default = draft
    v1 = r.json()["shots"][0]["versions"][-1]
    assert v1["settings"]["quality"] == "draft" and "draft" in v1["label"].lower()
    r = client.post(f"{base}/final", json={})  # keeper (v1) at final quality
    assert r.status_code == 200, r.text
    vs = r.json()["shots"][0]["versions"]
    assert [v["id"] for v in vs] == ["v1", "v2"]
    v2 = vs[-1]
    assert v2["settings"]["quality"] == "final" and v2["seed"] == 11 and v2["based_on"] == "v1"
    assert vs[0]["file"] == v1["file"]  # the draft stays untouched
    assert client.post(f"{base}/regenerate", json={"quality": "ultra"}).status_code == 400


def test_final_refuses_concept_takes(client):
    p = client.get("/api/storyboard/projects/lumi-night-shift").json()
    s = p["shots"][0]
    r = client.post(f"/api/storyboard/projects/{p['id']}/shots/{s['id']}/final", json={})
    assert r.status_code == 400
