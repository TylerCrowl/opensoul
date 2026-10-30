"""OS-066: a shot with no cast gets a start frame: from the words alone (Z-Image-Turbo, workflow 07z) with no stage,
or from the stage plate with no plate lock (the lock gave back the plate unchanged). 'No people' is not a clash."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import storyboard_api as A
from opensoul import scene

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    monkeypatch.setenv("OPENSOUL_SHEET_SYNC", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    return TestClient(server.app)


def _shot(client, **kw):
    p = client.post("/api/storyboard/projects", json={"title": "Waves"}).json()
    p = client.post(f"/api/storyboard/projects/{p['id']}/shots",
                    json={"beat": "Waves", "prompt": "Waves hit the rocks under a lighthouse at dusk.", "characters": [], **kw}).json()
    return p["id"], p["shots"][0]["id"]


def test_text_prompt_says_no_people_once():
    assert scene.text_prompt("Waves hit the rocks.").count(scene.NO_PEOPLE) == 1
    assert scene.NO_PEOPLE not in scene.text_prompt("An empty pier, no people.")
    assert scene.NO_PEOPLE not in scene.text_prompt("A crowd cheers.", no_people=False)


def test_text_frame_runs_workflow_07z_at_the_story_size(tmp_path):
    seen = {}

    def runner(wf, inputs, output_node_id, out_dir):
        seen.update(wf=wf, inputs=inputs, node=output_node_id)
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        f = Path(out_dir) / "x.png"
        Image.new("RGB", (8, 8)).save(f)
        return [f]

    out = scene.text_frame("Waves.", 5, tmp_path / "frame.png", aspect="16:9", runner=runner)
    assert out.is_file() and Path(seen["wf"]).name == "07z_master_from_text_zimage_api.json"
    wf = json.loads(Path(seen["wf"]).read_text())
    assert all(n in wf for n in seen["inputs"]) and seen["node"] in wf
    assert seen["inputs"]["7"]["width"] > seen["inputs"]["7"]["height"] and seen["inputs"]["8"]["seed"] == 5
    assert seen["inputs"]["5"]["text"] == "Waves."


def test_preview_no_cast_no_stage_frame_is_made(client):
    pid, sid = _shot(client)
    r = client.post(f"/api/storyboard/projects/{pid}/shots/{sid}/frame", json={})
    assert r.status_code == 200, r.text
    v = r.json()["shots"][0]["versions"][-1]
    assert v["kind"] == "frame" and v["settings"]["from_words"] and scene.NO_PEOPLE in v["prompt"]


def test_no_words_no_frame(client):
    p = client.post("/api/storyboard/projects", json={"title": "Empty"}).json()
    p = client.post(f"/api/storyboard/projects/{p['id']}/shots", json={"beat": "x", "characters": []}).json()
    r = client.post(f"/api/storyboard/projects/{p['id']}/shots/{p['shots'][0]['id']}/frame", json={})
    assert r.status_code == 400 and "What happens" in r.json()["detail"]


def test_studio_no_cast_frame_uses_text_frame_and_stage_shot_skips_plate_lock(client, monkeypatch, tmp_path):
    import app.server as server

    monkeypatch.setattr(server, "_dry", lambda: False)
    monkeypatch.setattr(server, "_start", lambda fn: fn())  # run the frame job inline (no thread race)
    calls = []

    def fake_text(prompt, seed, dest, aspect="16:9", **k):
        calls.append(("text", prompt))
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (64, 36), "#246").save(dest)
        return Path(dest)

    def fake_compose(pics, prompt, seed, dest, aspect="16:9", **k):
        calls.append(("compose", prompt))
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (64, 36), "#642").save(dest)
        return Path(dest)

    monkeypatch.setattr(scene, "text_frame", fake_text)
    monkeypatch.setattr(scene, "compose_frame", fake_compose)
    locked = []
    monkeypatch.setattr(A, "_plate_lock_still", lambda d, pl: locked.append(d))
    pid, sid = _shot(client)
    r = client.post(f"/api/storyboard/projects/{pid}/shots/{sid}/frame", json={})
    assert r.status_code == 200, r.text
    assert calls[-1][0] == "text"
    # the same shot on a stage: compose from the plate, no lock (it would hand back the plate unchanged)
    plate = tmp_path / "plate.png"
    Image.new("RGB", (64, 36), "#888").save(plate)
    st = A._store()
    st.set_location(pid, "Pier", str(plate), "A wooden pier.")
    client.patch(f"/api/storyboard/projects/{pid}/shots/{sid}", json={"location": "Pier"})
    r = client.post(f"/api/storyboard/projects/{pid}/shots/{sid}/frame", json={})
    assert r.status_code == 200, r.text
    assert calls[-1][0] == "compose" and scene.NO_PEOPLE in calls[-1][1] and locked == []
    vs = A._store().load(pid).shots[0].versions
    assert [v.status for v in vs] == ["ready", "ready"]


def test_no_people_note_is_not_a_clash():
    text, dropped = A._merge_edit("Wide shot of the launch deck, no people in frame.", "no people, the black mecha launches")
    assert dropped == [] and "no people in frame" in text
    _, dropped = A._merge_edit("Bastian stands on the deck. The mecha launches.", "no Bastian")
    assert dropped == ["Bastian stands on the deck"]
