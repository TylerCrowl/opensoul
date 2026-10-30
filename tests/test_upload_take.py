"""OS-064: your own still or clip becomes a new take of a shot; it can be the keeper and goes into the export."""
import io
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from opensoul.media import ffmpeg_bin

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    return TestClient(server.app)


def _story(client):
    p = client.post("/api/storyboard/projects", json={"title": "Up"}).json()
    p = client.post(f"/api/storyboard/projects/{p['id']}/shots", json={"beat": "Card", "characters": []}).json()
    return p["id"], p["shots"][0]["id"]


def _png() -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (640, 360), "#123").save(b, "PNG")
    return b.getvalue()


def test_upload_a_still_is_a_new_take_and_the_first_keeper(client):
    pid, sid = _story(client)
    r = client.post(f"/api/storyboard/projects/{pid}/shots/{sid}/upload", data={"consent": "true"},
                    files={"file": ("title.png", _png(), "image/png")})
    assert r.status_code == 200, r.text
    s = r.json()["shots"][0]
    v = s["versions"][0]
    assert v["kind"] == "upload" and v["label"] == "Uploaded" and v["poster_url"] and s["keeper"] == v["id"]
    plan = client.post(f"/api/storyboard/projects/{pid}/export").json()["plan"]
    assert plan["items"][0]["source_kind"] == "still" and plan["items"][0]["take"] == v["id"]


def test_upload_needs_consent_and_a_known_file(client):
    pid, sid = _story(client)
    url = f"/api/storyboard/projects/{pid}/shots/{sid}/upload"
    assert client.post(url, files={"file": ("a.png", _png(), "image/png")}).status_code == 400
    r = client.post(url, data={"consent": "true"}, files={"file": ("a.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 400 and "PNG" in r.json()["detail"]
    r = client.post(url, data={"consent": "true"}, files={"file": ("a.png", b"not a png", "image/png")})
    assert r.status_code == 400
    r = client.post(url, data={"consent": "true"}, files={"file": ("a.mp4", b"not a clip", "video/mp4")})
    assert r.status_code == 400 and "clip" in r.json()["detail"]
    assert client.get(f"/api/storyboard/projects/{pid}").json()["shots"][0]["versions"] == [] or all(
        v["status"] != "ready" for v in client.get(f"/api/storyboard/projects/{pid}").json()["shots"][0]["versions"])


@pytest.mark.skipif(ffmpeg_bin() is None, reason="needs ffmpeg")
def test_an_uploaded_clip_wins_over_a_still_keeper(client, tmp_path):
    pid, sid = _story(client)
    url = f"/api/storyboard/projects/{pid}/shots/{sid}/upload"
    client.post(url, data={"consent": "true"}, files={"file": ("a.png", _png(), "image/png")})
    clip = tmp_path / "c.mp4"
    subprocess.run([ffmpeg_bin(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=s=320x180:r=24:d=2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)], check=True)
    r = client.post(url, data={"consent": "true"}, files={"file": ("c.mp4", clip.read_bytes(), "video/mp4")})
    assert r.status_code == 200, r.text
    s = r.json()["shots"][0]
    assert s["keeper"] == "v2" and s["versions"][1]["video_url"] and s["versions"][1]["poster_url"]


def test_shot_sheet_offers_the_upload():
    js = (ROOT / "app/web/static/storyboard.js").read_text()
    assert 'id="sbUpload"' in js and "/upload`" in js and 'fd.append("consent", "true")' in js
