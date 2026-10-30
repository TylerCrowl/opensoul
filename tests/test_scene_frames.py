"""Start frames: the shot's cast (saved pictures) composed into its scene, as a new still take."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from opensoul import scene
from release_assets import LUMI_REFS, requires_demo_asset

ROOT = Path(__file__).resolve().parents[1]


def test_frame_inputs_fill_one_picture_slot_per_cast_member():
    wf = json.loads((ROOT / scene.WORKFLOW).read_text())
    ins = scene.frame_inputs(["a.png", "b.png"], "Two friends at a counter.", 7, 1344, 768)
    for node in ins:
        assert node in wf
    assert ins["5"]["image"] == "a.png" and ins["51"]["image"] == "b.png"
    assert ins["3"]["seed"] == 7
    with pytest.raises(ValueError):
        scene.frame_inputs([], "x", 1, 1344, 768)
    with pytest.raises(ValueError):
        scene.frame_inputs(["a"] * (scene.MAX_CAST + 1), "x", 1, 1344, 768)


def test_cast_prompt_names_who_is_who_and_bans_brands():
    p = scene.cast_prompt([{"name": "Mio", "prompt_lock": "lavender hair"}, {"name": "Ren", "prompt_lock": "red hair"}], "They wave.")
    assert "picture 1 (Mio)" in p and "Mio" in p and "picture 2 (Ren)" in p and "Ren" in p
    assert "No real brand" in p and "They wave." in p


def test_size_for_aspect():
    assert scene.size_for("16:9")[0] > scene.size_for("16:9")[1]
    assert scene.size_for("9:16")[0] < scene.size_for("9:16")[1]


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    return TestClient(server.app)


@requires_demo_asset(*LUMI_REFS)
def test_cast_lists_saved_characters_with_pictures_never_the_demo(client):
    import app.server as server

    cast = client.get("/api/storyboard/cast").json()["cast"]
    assert {"Lumi", "Mio", "Ren"} <= {c["name"] for c in cast}
    assert not any(c.get("pack_dir") and server._is_demo_pack(c["pack_dir"]) for c in cast)  # never the bundled demo pack


@requires_demo_asset(*LUMI_REFS)
def test_new_start_frame_is_a_new_still_take_and_keeps_old_takes(client):
    p = client.post("/api/storyboard/projects", json={"title": "F", "character": "Lumi"}).json()
    p = client.post(f"/api/storyboard/projects/{p['id']}/shots", json={"beat": "Meet", "prompt": "night store"}).json()
    sid = p["shots"][0]["id"]
    base = f"/api/storyboard/projects/{p['id']}/shots/{sid}"
    client.post(f"{base}/regenerate", json={"seed": 3})
    client.patch(base, json={"characters": ["Lumi", "Mio", "a customer"]})
    r = client.post(f"{base}/frame", json={"seed": 9})
    assert r.status_code == 200, r.text
    vs = r.json()["shots"][0]["versions"]
    assert [v["id"] for v in vs] == ["v1", "v2"]
    f = vs[-1]
    assert f["kind"] == "frame" and f["placeholder"] and f["settings"]["cast"] == ["Lumi", "Mio"]
    assert "a customer" in f["prompt"] and f["seed"] == 9
    # A still can seed a video draft, but can't be "finalised" directly.
    assert client.post(f"{base}/final", json={"version_id": f["id"]}).status_code == 400
    r = client.post(f"{base}/regenerate", json={"from_version": f["id"], "seed": 4})
    assert r.status_code == 200, r.text


def test_start_frame_needs_a_cast_picture(client):
    p = client.post("/api/storyboard/projects", json={"title": "G", "character": "Lumi"}).json()
    p = client.post(f"/api/storyboard/projects/{p['id']}/shots", json={"beat": "x", "prompt": "y"}).json()
    sid = p["shots"][0]["id"]
    base = f"/api/storyboard/projects/{p['id']}/shots/{sid}"
    client.patch(base, json={"characters": ["Nobody Yet"]})
    r = client.post(f"{base}/frame", json={})
    assert r.status_code == 400 and "character sheet" in r.json()["detail"]


def test_cast_prompt_hides_subtle_ears_in_the_hair():
    p = scene.cast_prompt([{"name": "Lumi", "prompt_lock": "silver hair, short subtle pointed elf ears close to the head"}], "She reads.")
    assert "covers most of the ears" in p
    q = scene.cast_prompt([{"name": "Ren", "prompt_lock": "red hair"}], "He waves.")
    assert "covers most of the ears" not in q
