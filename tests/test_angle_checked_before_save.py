"""PUT …/angles/{a} with generate=true checks first: a refused or failed angle leaves no empty row behind
(was: "Wide" saved even though the call returned 400 for a missing master plate)."""
from fastapi.testclient import TestClient
from PIL import Image


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    monkeypatch.setattr(server, "LIBRARY", tmp_path / "library")
    return TestClient(server.app)


def _angles(c, pid, loc="Night Diner"):
    p = c.get(f"/api/storyboard/projects/{pid}").json()
    return [a["name"] for l in p["locations"] if l["name"] == loc for a in l["angles"]]


def test_no_master_plate_saves_nothing(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    pid = c.post("/api/storyboard/projects", json={"title": "Diner"}).json()["id"]
    assert c.put(f"/api/storyboard/projects/{pid}/locations/Night Diner", json={"description": "chrome counter"}).status_code == 200
    r = c.put(f"/api/storyboard/projects/{pid}/locations/Night Diner/angles/Wide", json={"generate": True})
    assert r.status_code == 400 and "master plate" in r.json()["detail"]
    assert _angles(c, pid) == []


def test_failed_preview_render_saves_nothing_and_a_good_one_saves_once(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    pid = c.post("/api/storyboard/projects", json={"title": "Diner"}).json()["id"]
    Image.new("RGB", (96, 54), "teal").save(tmp_path / "m.png")
    assert c.put(f"/api/storyboard/projects/{pid}/locations/Night Diner", json={"image": str(tmp_path / "m.png")}).status_code == 200
    from opensoul import scene

    def boom(*a, **k):
        raise OSError("plate unreadable")

    monkeypatch.setattr(scene, "preview_frame", boom)
    r = c.put(f"/api/storyboard/projects/{pid}/locations/Night Diner/angles/Wide", json={"generate": True})
    assert r.status_code == 400 and _angles(c, pid) == []
    monkeypatch.undo()
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    r = c.put(f"/api/storyboard/projects/{pid}/locations/Night Diner/angles/Wide", json={"generate": True, "seed": 3})
    assert r.status_code == 200, r.text
    loc = next(l for l in r.json()["locations"] if l["name"] == "Night Diner")
    assert [a["name"] for a in loc["angles"]] == ["Wide"] and loc["angles"][0]["image_url"]


def test_seventh_generated_angle_is_refused_before_rendering(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    pid = c.post("/api/storyboard/projects", json={"title": "Diner"}).json()["id"]
    Image.new("RGB", (96, 54), "teal").save(tmp_path / "m.png")
    c.put(f"/api/storyboard/projects/{pid}/locations/Night Diner", json={"image": str(tmp_path / "m.png")})
    for i in range(6):
        assert c.put(f"/api/storyboard/projects/{pid}/locations/Night Diner/angles/a{i}", json={"note": "x"}).status_code == 200
    calls = []
    from opensoul import scene

    monkeypatch.setattr(scene, "preview_frame", lambda *a, **k: calls.append(a))
    r = c.put(f"/api/storyboard/projects/{pid}/locations/Night Diner/angles/Extra", json={"generate": True})
    assert r.status_code == 400 and calls == [] and len(_angles(c, pid)) == 6


def test_a_dry_run_angle_is_labelled_with_its_own_name(monkeypatch, tmp_path):
    """QA round 2: every angle tile on a built stage sheet read 'Start frame · preview'."""
    c = _client(monkeypatch, tmp_path)
    pid = c.post("/api/storyboard/projects", json={"title": "Diner"}).json()["id"]
    Image.new("RGB", (96, 54), "teal").save(tmp_path / "m.png")
    c.put(f"/api/storyboard/projects/{pid}/locations/Night Diner", json={"image": str(tmp_path / "m.png")})
    from opensoul import scene

    seen = []
    real = scene.preview_frame
    monkeypatch.setattr(scene, "preview_frame", lambda *a, **k: (seen.append(k), real(*a, **k))[1])
    r = c.put(f"/api/storyboard/projects/{pid}/locations/Night Diner/angles/behind the counter", json={"generate": True, "seed": 2})
    assert r.status_code == 200, r.text
    assert seen and seen[0]["title"] == "behind the counter" and "Start frame" not in seen[0]["label"]
