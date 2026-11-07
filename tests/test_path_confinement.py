"""Caller-supplied paths stay inside the data folder or the repo.

The API has no login. Another account on this computer can call it, so a path must not make the server
read a file that account could not name inside OpenSoul's own folders.
"""
import json
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from opensoul import storyboard as sb


def _png(path: Path, color: str = "red") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), color).save(path)
    return path


def test_abs_path_stays_inside_the_data_dir_and_the_repo(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    sb.set_data_dir(data)
    try:
        assert sb.abs_path("data/projects/p/x.png") == data / "projects" / "p" / "x.png"
        assert sb.abs_path(str(data / "plate.png")) == data / "plate.png"
        assert sb.abs_path("assets/lumi/character.json") == sb.ROOT / "assets" / "lumi" / "character.json"
        outside = tmp_path / "outside.png"
        # Absolute paths stay resolvable for files this process just wrote. Callers that take a path from
        # the network have to apply within() themselves (the plate route does).
        assert sb.abs_path(str(outside)) == outside
        assert not sb.within(outside, data) and not sb.within(outside, sb.ROOT)
        assert sb.abs_path("data/../../etc/passwd") is None
        assert sb.abs_path("../etc/passwd") is None
        secret = _png(tmp_path / "secret.png")
        link = data / "link.png"
        link.symlink_to(secret)
        assert sb.abs_path("data/link.png") is None
        assert not sb.within(link, data)
    finally:
        sb.set_data_dir(None)


def _client(monkeypatch, data: Path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", data)
    monkeypatch.setattr(server, "LIBRARY", data / "library")
    return TestClient(server.app), server


def test_location_plate_cannot_be_a_picture_outside_the_app(monkeypatch, tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    outside = _png(tmp_path / "family.png", "blue")
    inside = _png(data / "plate.png", "green")
    c, _server = _client(monkeypatch, data)
    pid = c.post("/api/storyboard/projects", json={"title": "House"}).json()["id"]
    base = f"/api/storyboard/projects/{pid}/locations/Kitchen"
    refused = c.put(base, json={"image": str(outside)})
    assert refused.status_code == 400
    assert str(outside) not in refused.text
    assert c.get(f"/api/storyboard/projects/{pid}").json()["locations"] == []
    ok = c.put(base, json={"image": str(inside)})
    assert ok.status_code == 200, ok.text
    assert ok.json()["locations"][0]["image"]


def test_video_script_id_cannot_read_a_markdown_file_outside_the_bundle(monkeypatch, tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    secret = tmp_path / "notes.md"
    secret.write_text("PRIVATE_NOTE_MARKER not a bundled script\n")
    c, server = _client(monkeypatch, data)
    # The old join treated an absolute id as the file itself. This test is that path, and it must not be read.
    script_id = str(secret.with_suffix(""))
    assert (server.SCRIPTS / f"{script_id}.md").resolve() == secret.resolve()
    r = c.post("/api/video", data={"script_id": script_id})
    assert r.status_code == 200, r.text
    assert "PRIVATE_NOTE_MARKER" not in r.text
    from os.path import relpath

    climb = relpath(secret.resolve(), server.SCRIPTS.resolve())
    climb_id = climb[:-3] if climb.endswith(".md") else climb
    r = c.post("/api/video", data={"script_id": climb_id})
    assert "PRIVATE_NOTE_MARKER" not in r.text
    bundled = c.post("/api/video", data={"script_id": "01_roast_date"})
    assert bundled.status_code == 200
    assert "roasted eleven days ago" in bundled.json()["script_preview"]


def test_photos_do_not_copy_a_picture_named_from_outside_the_pack(monkeypatch, tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    secret = _png(tmp_path / "secret.png")
    pack = tmp_path / "evil"
    pack.mkdir()
    (pack / "pack.json").write_text(json.dumps({
        "name": "Eve", "prompt_lock": "a person", "ref_images": [str(secret)],
    }))
    c, _server = _client(monkeypatch, data)
    r = c.post("/api/photos", data={"pack_dir": str(pack), "scene": "room", "n": "1"})
    assert r.status_code == 400
    assert not list(data.rglob("still_00.png"))
    assert secret.read_bytes()  # the file is untouched

    own = data / "packs" / "Eve"
    (own / "refs").mkdir(parents=True)
    kept = _png(own / "refs" / "ref_00.png", "green")
    (own / "pack.json").write_text(json.dumps({
        "name": "Eve", "prompt_lock": "a person",
        "ref_images": [str(secret), "refs/ref_00.png"],
    }))
    r = c.post("/api/photos", data={"pack_dir": str(own), "scene": "room", "n": "1"})
    assert r.status_code == 200, r.text
    copied = list(data.rglob("still_00.png"))
    assert len(copied) == 1 and copied[0].read_bytes() == kept.read_bytes()
    assert copied[0].read_bytes() != secret.read_bytes()
