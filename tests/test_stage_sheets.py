"""Stage sheets: a location's master plate + consistent angles + empty plate + checklist; shots pick an angle."""
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from opensoul import scene, stage_sheet
from opensoul import storyboard as sb


def _img(path, color="grey"):
    Image.new("RGB", (96, 54), color).save(path)
    return str(path)


def test_store_angles_round_trip_and_shot_angle(tmp_path):
    st = sb.Store(tmp_path)
    p = st.create_project("Stage test")
    s = st.add_shot(p.id, "Counter", characters=[])
    st.set_location(p.id, "Konbini", image="m.png", empty="e.png", checklist=["register on the left", " ", "no cat"])
    st.set_stage_angle(p.id, "konbini", "Behind the counter", image="b.png", note="looks out")
    st.update_shot(p.id, s.id, location="Konbini", stage_angle="behind THE counter")
    q = st.load(p.id)
    loc = q.locations[0]
    assert loc.empty == "e.png" and loc.checklist == ["register on the left", "no cat"]
    assert loc.plate_for("behind the counter") == "b.png" and loc.plate_for("") == "m.png"
    assert q.shots[0].stage_angle == "Behind the counter"
    with pytest.raises(sb.StoryError):
        st.update_shot(p.id, s.id, stage_angle="ceiling cam")
    st.remove_stage_angle(p.id, "Konbini", "Behind the counter")
    assert st.load(p.id).shots[0].stage_angle == ""
    for i in range(sb.Store.MAX_ANGLES):
        st.set_stage_angle(p.id, "Konbini", f"a{i}")
    with pytest.raises(sb.StoryError):
        st.set_stage_angle(p.id, "Konbini", "one too many")


def test_angle_prompt_moves_only_the_camera():
    t = stage_sheet.angle_prompt(stage_sheet.DEFAULT_ANGLES[0]["note"], "white counter")
    assert "SAME place" in t and "No readable text" in t and "white counter" in t and "Nobody" in t
    loc = scene.location_sentence("Konbini", "white counter", "customer side", "faces the register")
    assert loc.startswith("Picture 1 is the customer side angle of the stage (Konbini)") and "faces the register" in loc


def test_build_sheet(tmp_path):
    out = stage_sheet.build_sheet(_img(tmp_path / "m.png"), [("behind", _img(tmp_path / "b.png", "blue")),
                                  ("window", _img(tmp_path / "w.png", "red"))], tmp_path / "s.jpg",
                                  empty=_img(tmp_path / "e.png", "black"), title="Konbini", checklist=["no cat"])
    im = Image.open(out)
    assert im.width > 1000 and im.height > 600


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    return TestClient(server.app)


def test_api_stage_sheet_and_angle_start_frame(client, tmp_path):
    master, empty, beh = _img(tmp_path / "m.png"), _img(tmp_path / "e.png", "black"), _img(tmp_path / "b.png", "blue")
    pid = client.post("/api/storyboard/projects", json={"title": "Stage", "character": "Lumi"}).json()["id"]
    sid = client.post(f"/api/storyboard/projects/{pid}/shots", json={"beat": "Counter"}).json()["shots"][0]["id"]
    base = f"/api/storyboard/projects/{pid}/locations/Konbini"
    assert client.put(base, json={"image": master, "empty": empty, "checklist": ["no cat"]}).status_code == 200
    r = client.put(base + "/angles/behind the counter", json={"image": beh})
    loc = r.json()["locations"][0]
    assert r.status_code == 200 and loc["angles"][0]["note"].startswith("the camera stands behind")  # default note
    # generated angle (dry run → placeholder from the empty plate)
    loc = client.put(base + "/angles/window side", json={"generate": True, "seed": 3}).json()["locations"][0]
    assert loc["angles"][1]["image"].endswith("window_side_s3.png")
    loc = client.post(base + "/sheet").json()["locations"][0]
    assert loc["sheet"].endswith("stage_sheet.jpg") and loc["sheet_url"]
    assert client.patch(f"/api/storyboard/projects/{pid}/shots/{sid}",
                        json={"location": "Konbini", "stage_angle": "behind the counter"}).status_code == 200
    v = client.post(f"/api/storyboard/projects/{pid}/shots/{sid}/frame", json={"seed": 4}).json()["shots"][0]["versions"][-1]
    assert v["settings"]["pictures"][0].endswith("b.png") and v["settings"]["stage_angle"] == "behind the counter"
    assert v["prompt"].startswith("Picture 1 is the behind the counter angle of the stage")
    assert client.delete(base + "/angles/behind the counter").json()["shots"][0]["stage_angle"] == ""
