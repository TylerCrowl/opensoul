"""Stage sheet backend for the Storyboard UI: plate upload (master / empty / angle), angle rename, angle status,
readiness checklist (like the character sheet), suggestions."""
import io

from fastapi.testclient import TestClient
from PIL import Image


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    monkeypatch.setattr(server, "LIBRARY", tmp_path / "library")
    return TestClient(server.app)


def _png(color="teal"):
    b = io.BytesIO()
    Image.new("RGB", (96, 54), color).save(b, format="PNG")
    return b.getvalue()


def _loc(p, name="Night Diner"):
    return next(l for l in p["locations"] if l["name"] == name)


def test_new_stage_from_an_upload_then_angles_sheet_and_readiness(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    pid = c.post("/api/storyboard/projects", json={"title": "Diner"}).json()["id"]
    u = f"/api/storyboard/projects/{pid}/locations/Night Diner"
    r = c.post(f"{u}/upload", data={"role": "master"}, files={"image": ("m.png", _png(), "image/png")})
    assert r.status_code == 400 and "permission" in r.json()["detail"]  # consent, like a character photo
    r = c.post(f"{u}/upload", data={"role": "master", "consent": "true", "description": "chrome counter, red stools"},
               files={"image": ("m.png", _png(), "image/png")})
    assert r.status_code == 200, r.text
    loc = _loc(r.json())
    assert loc["image_url"] and loc["description"].startswith("chrome")
    ready = {i["id"]: i for i in loc["readiness"]}
    assert ready["master"]["done"] and not ready["angles"]["done"] and not ready["sheet"]["done"] and not loc["ready"]
    for a in ("reverse angle", "medium"):
        p = c.put(f"{u}/angles/{a}", json={"generate": True, "seed": 3}).json()
    loc = _loc(p)
    assert [a["name"] for a in loc["angles"]] == ["reverse angle", "medium"]
    assert loc["angles"][0]["note"].startswith("the camera turns around")  # generic suggestion note
    p = c.post(f"{u}/sheet").json()
    loc = _loc(p)
    assert loc["ready"] and loc["sheet_url"] and not loc["sheet_stale"]
    # a new angle picture makes the built sheet out of date
    import os
    import time

    time.sleep(0.01)
    p = c.post(f"{u}/upload", data={"role": "angle", "angle": "from the left", "consent": "true"},
               files={"image": ("a.png", _png("navy"), "image/png")}).json()
    f = next(a for a in _loc(p)["angles"] if a["name"] == "from the left")
    assert f["image_url"]
    sheet = tmp_path / "projects" / pid / "stages" / "night_diner" / "stage_sheet.jpg"
    if sheet.exists():
        os.utime(sheet, (time.time() - 100, time.time() - 100))
    loc = _loc(c.get(f"/api/storyboard/projects/{pid}").json())
    assert loc["sheet_stale"] and not loc["ready"]


def test_bad_upload_and_unknown_stage(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    pid = c.post("/api/storyboard/projects", json={"title": "Diner"}).json()["id"]
    u = f"/api/storyboard/projects/{pid}/locations/Night Diner"
    r = c.post(f"{u}/upload", data={"role": "master", "consent": "true"}, files={"image": ("x.png", b"not an image", "image/png")})
    assert r.status_code == 400 and c.get(f"/api/storyboard/projects/{pid}").json()["locations"] == []
    r = c.post(f"{u}/upload", data={"role": "empty", "consent": "true"}, files={"image": ("e.png", _png(), "image/png")})
    assert r.status_code == 404


def test_new_stage_from_a_take_and_rename_angle_follows_shots(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    p = c.post("/api/storyboard/projects", json={"title": "Diner", "shots": [{"beat": "Counter", "characters": []}]}).json()
    pid, sid = p["id"], p["shots"][0]["id"]
    p = c.post(f"/api/storyboard/projects/{pid}/shots/{sid}/regenerate", json={"quality": "draft"}).json()
    vid = p["shots"][0]["versions"][-1]["id"]
    u = f"/api/storyboard/projects/{pid}/locations/Night Diner"
    assert c.put(u, json={"from_version": f"{sid}/{vid}"}).status_code == 200
    c.put(f"{u}/angles/medium", json={"generate": True})
    c.patch(f"/api/storyboard/projects/{pid}/shots/{sid}", json={"location": "Night Diner", "stage_angle": "medium"})
    p = c.put(f"{u}/angles/medium", json={"rename": "Booth medium"}).json()
    assert [a["name"] for a in _loc(p)["angles"]] == ["Booth medium"] and p["shots"][0]["stage_angle"] == "Booth medium"
    assert _loc(p)["shots_using"] == 1
    c.put(f"{u}/angles/reverse angle", json={"generate": True})
    assert c.put(f"{u}/angles/reverse angle", json={"rename": "booth MEDIUM"}).status_code == 400


def test_suggestions_and_live_angle_status(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    s = c.get("/api/storyboard/stage/angle-suggestions").json()
    assert [a["name"] for a in s["angles"]] == ["reverse angle", "from the left", "from the right", "medium"]
    assert s["max"] == 6 and s["min"] == 2
    pid = c.post("/api/storyboard/projects", json={"title": "Diner"}).json()["id"]
    u = f"/api/storyboard/projects/{pid}/locations/Night Diner"
    c.post(f"{u}/upload", data={"role": "master", "consent": "true"}, files={"image": ("m.png", _png(), "image/png")})
    import app.server as server
    from opensoul import scene

    jobs = []
    monkeypatch.setattr(server, "_dry", lambda: False)
    monkeypatch.setattr(server, "_start", lambda fn: jobs.append(fn))
    loc = _loc(c.put(f"{u}/angles/medium", json={"generate": True}).json())
    assert loc["angles"][0]["status"] == "rendering" and loc["rendering"] == 1

    def boom(*a, **k):
        raise RuntimeError("studio computer offline")

    monkeypatch.setattr(scene, "compose_frame", boom)
    jobs[0]()
    loc = _loc(c.get(f"/api/storyboard/projects/{pid}").json())
    assert loc["angles"][0]["status"] == "failed" and "offline" in loc["angles"][0]["error"]


def test_one_angle_count_everywhere_and_the_checklist_never_says_3_of_2(monkeypatch, tmp_path):
    """QA round 2: the editor said '3 of 6', the row/shot picker '4 angles' (+ master) and the checklist '3 of 2'."""
    c = _client(monkeypatch, tmp_path)
    pid = c.post("/api/storyboard/projects", json={"title": "Diner"}).json()["id"]
    u = f"/api/storyboard/projects/{pid}/locations/Night Diner"
    c.post(f"{u}/upload", data={"role": "master", "consent": "true"}, files={"image": ("m.png", _png(), "image/png")})
    p = c.put(f"{u}/angles/medium", json={"generate": True, "seed": 3}).json()
    loc = _loc(p)
    assert loc["angle_count"] == 1 and {i["id"]: i for i in loc["readiness"]}["angles"]["detail"] == "1 of 2"
    for a in ("reverse angle", "from the left"):
        p = c.put(f"{u}/angles/{a}", json={"generate": True, "seed": 3}).json()
    loc = _loc(p)
    ang = {i["id"]: i for i in loc["readiness"]}["angles"]
    assert loc["angle_count"] == 3 and ang["done"] and ang["detail"] == "3 made"  # never "3 of 2"; master not counted
