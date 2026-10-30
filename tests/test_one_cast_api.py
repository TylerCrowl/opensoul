"""Unify step 2: one cast API. POST /api/cast, /api/storyboard/cast and Create's /api/character all save through
storyboard_api.save_character, so a character made anywhere is the same pack everywhere."""
import io
import json

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
    Image.new("RGB", (64, 96), color).save(b, "PNG")
    return b.getvalue()


def test_the_three_routes_make_the_same_kind_of_pack(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    a = c.post("/api/cast", data={"name": "Tamsin Reed", "description": "a tall gardener in a yellow raincoat"})
    b = c.post("/api/storyboard/cast", data={"name": "Odo Fenn", "description": "a short baker with a flour-dusted apron"})
    d = c.post("/api/character", data={"name": "Pell Marsh", "prompt_lock": "a lanky courier in a teal raincoat"})
    assert a.status_code == b.status_code == d.status_code == 200, (a.text, b.text, d.text)
    packs = {p.name: json.loads((p / "pack.json").read_text()) for p in (tmp_path / "packs").iterdir()}
    assert set(packs) == {"Tamsin_Reed", "Odo_Fenn", "Pell_Marsh"}
    assert {tuple(sorted(v)) for v in packs.values()} and all(v["ref_images"] == [] for v in packs.values())
    names = {x["name"] for x in c.get("/api/cast").json()["cast"]}
    assert {"Tamsin Reed", "Odo Fenn", "Pell Marsh"} <= names
    assert c.get("/api/cast").json() == c.get("/api/storyboard/cast").json()


def test_cast_api_takes_up_to_three_pictures_with_the_rights_tick(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    files = [("images", (f"r{i}.png", _png(col), "image/png")) for i, col in enumerate(["red", "green", "blue", "gray"])]
    r = c.post("/api/cast", data={"name": "Ivo Lark"}, files=files)
    assert r.status_code == 400 and "permission" in r.json()["detail"]
    r = c.post("/api/cast", data={"name": "Ivo Lark", "consent": "true"}, files=files)
    assert r.status_code == 200, r.text
    refs = json.loads((tmp_path / "packs" / "Ivo_Lark" / "pack.json").read_text())["ref_images"]
    assert len(refs) == 3
    assert c.post("/api/cast", data={"name": "ivo lark", "description": "again, another one"}).status_code == 400


def test_create_save_refuses_a_file_that_is_not_an_image(monkeypatch, tmp_path):
    """Create now gets the cast's checks too (it saved any bytes before)."""
    c = _client(monkeypatch, tmp_path)
    r = c.post("/api/character", data={"name": "Quill Ash", "prompt_lock": "a courier"},
               files=[("images", ("x.png", b"not an image", "image/png"))])
    assert r.status_code == 400 and "image" in r.json()["detail"]


def test_create_save_still_rewrites_its_own_folder(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    for desc in ("a lanky courier in a teal raincoat", "a lanky courier in a red raincoat"):
        assert c.post("/api/character", data={"name": "Pell Marsh", "prompt_lock": desc}).status_code == 200
    assert [p.name for p in (tmp_path / "packs").iterdir()] == ["Pell_Marsh"]
    assert "red raincoat" in json.loads((tmp_path / "packs" / "Pell_Marsh" / "pack.json").read_text())["prompt_lock"]
