import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opensoul.presets import PRESETS, build_shot_plan, caption_for, load_presets, shuffle_choice
from release_assets import DEMO_POSTER, requires_demo_asset

ROOT = Path(__file__).resolve().parents[1]
CAMERA = {"push_in_gentle", "dolly_in", "dolly_out", "dolly_left", "dolly_right", "jib_up", "jib_down",
          "static", "crash_zoom", "orbit", "fpv", "dolly_zoom"}
EFFECTS = {"earth_zoom_out", "orbit_freeze", "day_to_night", "outfit_switch"}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    return TestClient(server.app)


def test_preset_files_complete_and_valid():
    p = load_presets()
    assert {x["id"] for x in p["camera"]} == CAMERA
    assert {x["id"] for x in p["effects"]} == EFFECTS
    for item in p["camera"] + p["effects"]:
        assert len(item["prompt"]) > 120, item["id"]
        assert {"duration_s", "fps", "width", "height"} <= item["defaults"].keys()
        assert item["defaults"]["height"] > item["defaults"]["width"]  # vertical
        assert "lora" in item
    assert {e["id"] for e in p["eras"]} == {"iphone_ugc", "film_35mm"}


def test_lora_camera_presets_reference_ltx_lora():
    dolly = json.loads((PRESETS / "camera" / "dolly_in.json").read_text())
    assert "ltx" in dolly["lora"]["name"] and "dolly-in" in dolly["lora"]["name"]
    assert json.loads((PRESETS / "camera" / "crash_zoom.json").read_text())["lora"] is None


def test_plan_maps_to_i2v_workflow_nodes():
    wf = json.loads((ROOT / "workflows" / "04_i2v_ltx_api.json").read_text())
    plan = build_shot_plan(camera="orbit", era="film_35mm", seed=7, image_path="/x.png")
    video = next(s for s in plan["stages"] if s["stage"] == "video")
    for node in video["inputs"]:
        assert node in wf, node
    assert wf["20"]["class_type"] == "CLIPTextEncode"
    assert "35mm film" in video["inputs"]["20"]["text"]
    assert video["inputs"]["35"]["noise_seed"] == 7
    assert plan["stages"][-1]["stage"] == "era"


def test_plan_with_line_adds_voice_and_lipsync():
    plan = build_shot_plan(effect="earth_zoom_out", line="Hello there", voice=None)
    names = [s["stage"] for s in plan["stages"]]
    assert names == ["voice", "video", "era"]  # default ltx_av: the video stage is 04b, rendered to the voice
    assert plan["stages"][1]["workflow"] == "workflows/04b_a2v_ltx_api.json"
    plan_ls = build_shot_plan(effect="earth_zoom_out", line="Hello there", lipsync_backend="latentsync")
    assert [s["stage"] for s in plan_ls["stages"]] == ["voice", "video", "lipsync", "era"]
    assert plan["voice"]
    assert '"Hello there"' in plan["prompt"]


def test_unknown_preset_raises_and_overrides_filtered():
    with pytest.raises(KeyError):
        build_shot_plan(camera="nope")
    plan = build_shot_plan(camera="static", overrides={"steps": 20, "evil": 1})
    params = plan["stages"][0]["params"]
    assert params["steps"] == 20 and "evil" not in params


def test_shuffle_is_deterministic_and_valid():
    a, b = shuffle_choice(3), shuffle_choice(3)
    assert a == b
    assert bool(a["camera"]) != bool(a["effect"])
    build_shot_plan(camera=a["camera"], effect=a["effect"], era=a["era"])


def test_caption_has_hashtag():
    c = caption_for({"title": "Orbit"}, "Pixel")  # OS-044: our own tags, no other product name
    assert "#OpenSoul" in c and "Higgsfield" not in c
    assert caption_for({"title": "Laundromat, 2 a.m."}, "Juno Pell").startswith("Juno Pell — Laundromat, 2 a.m. Made")


@requires_demo_asset(DEMO_POSTER)
def test_api_presets_and_shot_dry_run(client):
    p = client.get("/api/presets").json()
    assert len(p["camera"]) == 12 and len(p["effects"]) == 4
    assert all("thumb_ready" in x for x in p["camera"])
    from opensoul.media import ffmpeg_bin

    r = client.post("/api/shot", json={"camera": "fpv", "era": "iphone_ugc", "line": "Hi", "voice": "am_michael"})
    if ffmpeg_bin() is None:  # no system ffmpeg and no imageio-ffmpeg: a clear 500, not a crash
        assert r.status_code == 500 and "ffmpeg" in r.json()["detail"]
    else:
        assert r.status_code == 200
        d = r.json()
        assert d["dry_run"] is True and d["plan"]["camera"] == "fpv"
        assert d["video_url"] and [s["stage"] for s in d["steps"]][-1] == "era"
        assert client.get(d["video_url"]).status_code == 200
    assert client.post("/api/shot", json={"camera": "bogus"}).status_code == 400
    assert set(client.get("/api/shuffle?seed=1").json()) >= {"camera", "effect", "era", "seed"}


@requires_demo_asset(DEMO_POSTER)
def test_api_share_exports_vertical_mp4(client, demo):
    import shutil

    d = client.post("/api/share", json={"title": "Orbit", "name": demo.DEMO_NAME}).json()
    assert "#OpenSoul" in d["caption"] and "Videos made with OpenSoul are AI-generated." in d["caption"]
    # The demo's preview pictures and clips never leave the app (opensoul/export_guard.py); the demo poster is now a
    # neutral placeholder, so a preview share exports that placeholder, labelled as one.
    assert d["mp4_url"] is None or (d["placeholder"] and "placeholder_tile" not in d["mp4_url"])
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    d = client.post("/api/share", json={"title": "Orbit", "name": "Pixel",
                                        "video_url": "/assets/example_character/pixel_reference.png"}).json()
    assert d["mp4_url"], d
    vid = client.get(d["mp4_url"])
    assert vid.status_code == 200 and len(vid.content) > 1000


def test_share_rejects_outside_paths(client):
    d = client.post("/api/share", json={"video_url": "/api/file?path=/etc/passwd"}).json()
    assert "caption" in d  # falls back to the demo poster, never reads /etc


def test_index_has_three_steps_and_controls(client):
    html = client.get("/").text
    for s in ("Character", "Shot", "Share", "Generate", "Shuffle", "Advanced", "Export vertical MP4", "Copy caption"):
        assert s in html


def test_anti_ghost_defaults():
    from opensoul.presets import build_shot_plan
    st = build_shot_plan(camera="static", character_prompt="A woman reads.", seed=1, quality="draft")["stages"]
    v = [x for x in st if x["stage"] == "video"][0]["inputs"]
    assert v["31"] == {"strength": 1.0} and v["3"] == {"img_compression": 10}
    assert "ghosting" in v["21"]["text"] and "pc game" in v["21"]["text"]
    st = build_shot_plan(camera="orbit", character_prompt="A woman reads.", seed=1, quality="draft")["stages"]
    v = [x for x in st if x["stage"] == "video"][0]["inputs"]
    assert "31" not in v and "ghosting" in v["21"]["text"]
