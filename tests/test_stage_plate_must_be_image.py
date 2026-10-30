"""A plate that isn't a picture is refused when it's set (was: accepted, then a 500 on angle generate / sheet)."""
from fastapi.testclient import TestClient


def test_non_image_plate_and_angle_are_400(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    monkeypatch.setattr(server, "LIBRARY", tmp_path / "library")
    c = TestClient(server.app)
    junk = tmp_path / "notes.txt"
    junk.write_text("not a picture")
    p = c.post("/api/storyboard/projects", json={"title": "Plates"}).json()
    base = f"/api/storyboard/projects/{p['id']}/locations/Diner"
    r = c.put(base, json={"image": str(junk)})
    assert r.status_code == 400 and "image" in r.json()["detail"]
    r = c.put(base, json={"description": "chrome counter"})
    assert r.status_code == 200
    assert c.put(base, json={"empty": str(junk)}).status_code == 400
    assert c.put(base + "/angles/Wide", json={"image": str(junk)}).status_code == 400
