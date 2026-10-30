"""Locations (sets): a master-plate picture + fixed set description, so a place looks the same in every shot."""
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from opensoul import scene
from opensoul import storyboard as sb
from release_assets import LUMI_REFS, requires_demo_asset


def test_location_prompt_puts_the_plate_first_and_shifts_the_cast():
    p = scene.cast_prompt([{"name": "Mio", "prompt_lock": "lavender hair"}], "She waves.",
                          location={"name": "Konbini", "description": "grey counter, rainy window"})
    assert p.startswith("Picture 1 is the master plate of the location (Konbini)")
    assert "grey counter, rainy window" in p and "picture 2 (Mio)" in p and "picture 1 (Mio)" not in p
    assert "No real brand" in p


def test_store_locations_round_trip_and_shot_link(tmp_path):
    st = sb.Store(tmp_path)
    p = st.create_project("Set test")
    s = st.add_shot(p.id, "Counter", characters=[])
    st.set_location(p.id, "Konbini interior", image="plate.png", description="grey counter")
    st.update_shot(p.id, s.id, location="konbini  INTERIOR")
    q = st.load(p.id)
    assert q.locations[0].description == "grey counter" and q.shots[0].location == "Konbini interior"
    with pytest.raises(sb.StoryError):
        st.update_shot(p.id, s.id, location="Nowhere")
    st.remove_location(p.id, "Konbini interior")
    assert st.load(p.id).shots[0].location == "" and not st.load(p.id).locations


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    return TestClient(server.app)


@requires_demo_asset(*LUMI_REFS)
def test_start_frame_of_a_located_shot_uses_the_plate_as_picture_1(client, tmp_path):
    plate = tmp_path / "plate.png"
    Image.new("RGB", (64, 36), "grey").save(plate)
    p = client.post("/api/storyboard/projects", json={"title": "Loc", "character": "Lumi"}).json()
    pid = p["id"]
    p = client.post(f"/api/storyboard/projects/{pid}/shots", json={"beat": "Counter", "prompt": "she reads"}).json()
    sid = p["shots"][0]["id"]
    r = client.put(f"/api/storyboard/projects/{pid}/locations/Konbini", json={"image": str(plate), "description": "grey counter"})
    assert r.status_code == 200 and r.json()["locations"][0]["name"] == "Konbini"
    assert client.put(f"/api/storyboard/projects/{pid}/locations/Bad", json={"image": str(tmp_path / "no.png")}).status_code == 400
    assert client.patch(f"/api/storyboard/projects/{pid}/shots/{sid}", json={"location": "Konbini"}).status_code == 200
    v = client.post(f"/api/storyboard/projects/{pid}/shots/{sid}/frame", json={"seed": 4}).json()["shots"][0]["versions"][-1]
    assert v["settings"]["location"] == "Konbini" and v["settings"]["pictures"][0].endswith("plate.png")
    assert v["prompt"].startswith("Picture 1 is the master plate") and "picture 2 (Lumi)" in v["prompt"]
    # a story with plates but too many cast members for the free slots is refused
    client.patch(f"/api/storyboard/projects/{pid}/shots/{sid}", json={"characters": ["Lumi", "Mio", "Ren"]})
    assert client.post(f"/api/storyboard/projects/{pid}/shots/{sid}/frame", json={"seed": 5}).status_code == 400
    assert client.delete(f"/api/storyboard/projects/{pid}/locations/Konbini").json()["shots"][0]["location"] == ""
