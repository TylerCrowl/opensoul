"""OS-068: a story's Avoid list (default: famous design traits, plus the user's words) reaches every start frame (as a
plain sentence, since the image models run at cfg 1, and as negative) and every take's negative; known franchise names
in the shot words get a note."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import storyboard_api as A
from opensoul import originality as OG
from opensoul import scene
from opensoul.presets import build_shot_plan

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    monkeypatch.setenv("OPENSOUL_SHEET_SYNC", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    return TestClient(server.app)


def test_default_list_never_names_a_franchise():
    assert OG.DEFAULT_AVOID and not any(OG.names_in(x) for x in OG.DEFAULT_AVOID)
    assert any("V-shaped" in x for x in OG.DEFAULT_AVOID)


def test_items_clean_and_sentence():
    assert OG.clean(" horns ,, red scarf \n cape ") == "horns, red scarf, cape"
    got = OG.items("horns, V-shaped head fin or antenna on a robot", defaults=True)
    assert got[: len(OG.DEFAULT_AVOID)] == list(OG.DEFAULT_AVOID) and got[-1] == "horns" and len(got) == len(OG.DEFAULT_AVOID) + 1
    assert OG.items("", defaults=False) == [] and OG.sentence([]) == ""
    assert OG.sentence(["horns"]) == "Do not show: horns."
    # the default traits are never named in a picture prompt (a cfg-1 model draws what it reads)
    s = OG.sentence(OG.items(""), "A black robot knight launches.")
    assert "V-shaped" not in s and "fin" not in s and s.startswith("Original design:")
    assert OG.sentence(OG.items(""), "A girl reads a book.") == ""
    assert OG.sentence(OG.items(""), "A robot.", defaults=False) == ""
    assert OG.negative("text, logo", ["logo", "horns"]) == "text, logo, horns"


def test_names_in_finds_franchise_words():
    assert OG.names_in("A Gundam-style robot with a Sharingan eye") == ["Gundam", "Sharingan"]
    assert OG.names_in("An original finned lancer robot") == []
    assert "Describe your own design" in OG.note("like Evangelion")


def test_compose_frame_sends_the_avoid_negative(tmp_path):
    seen = {}

    def runner(wf, inputs, output_node_id, out_dir):
        seen.update(inputs)
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        f = Path(out_dir) / "x.png"
        Image.new("RGB", (8, 8)).save(f)
        return [f]

    scene.compose_frame(["a.png"], "x", 1, tmp_path / "f.png", runner=runner, avoid=["horns"])
    neg = seen[scene.NEGATIVE_NODE]["prompt"]
    assert neg.endswith("horns") and "watermark" in neg
    wf = json.loads(scene.WORKFLOW.read_text())
    assert "prompt" in wf[scene.NEGATIVE_NODE]["inputs"]


def test_project_avoid_round_trip_and_frame_prompt(client):
    p = client.post("/api/storyboard/projects", json={"title": "Mecha"}).json()
    pid = p["id"]
    assert p["avoid_defaults"] is True and p["avoid_default_items"]
    p = client.patch(f"/api/storyboard/projects/{pid}", json={"avoid": "horns,  red scarf"}).json()
    assert p["avoid"] == "horns, red scarf"
    p = client.post(f"/api/storyboard/projects/{pid}/shots",
                    json={"beat": "Launch", "prompt": "A Gundam robot launches from a deck at night.", "characters": []}).json()
    sid = p["shots"][0]["id"]
    v = client.post(f"/api/storyboard/projects/{pid}/shots/{sid}/frame", json={}).json()["shots"][0]["versions"][-1]
    assert "Do not show: horns; red scarf." in v["prompt"] and "Original design:" in v["prompt"]
    assert "V-shaped" not in v["prompt"] and "V-shaped head fin or antenna on a robot" in v["settings"]["avoid"]
    assert "Gundam" in v["note"] and "original designs" in v["note"]
    p = client.patch(f"/api/storyboard/projects/{pid}", json={"avoid_defaults": False, "avoid": ""}).json()
    v = client.post(f"/api/storyboard/projects/{pid}/shots/{sid}/frame", json={}).json()["shots"][0]["versions"][-1]
    assert "Do not show:" not in v["prompt"]


def test_video_negative_gets_the_avoid_list():
    plan = build_shot_plan(camera="static", character_prompt="x", seed=1)
    out = A._style_plan(plan, "", "x", avoid=["horns on the helmet"])
    vid = next(x for x in out["stages"] if x["stage"] == "video")
    assert vid["inputs"]["21"]["text"].endswith("horns on the helmet")


def test_ui_has_the_avoid_box():
    html = (ROOT / "app/web/index.html").read_text()
    assert 'id="sbAvoid"' in html and 'id="sbAvoidDefaults"' in html
    assert "avoid_defaults: e.target.checked" in (ROOT / "app/web/static/storyboard.js").read_text()
