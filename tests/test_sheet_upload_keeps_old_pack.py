"""Uploading a sheet photo under an existing character's name never touches that character's pack
(was: shutil.rmtree, then a move to packs_archive). The new character goes to the next free <name>_2, _3 folder."""
import io
import json

from fastapi.testclient import TestClient


def _png(color) -> bytes:
    from PIL import Image

    b = io.BytesIO()
    Image.new("RGB", (64, 96), color).save(b, format="PNG")
    return b.getvalue()


def _snapshot(d):
    return {str(p.relative_to(d)): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()}


def test_upload_under_an_existing_name_uses_the_next_free_folder(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    monkeypatch.setenv("OPENSOUL_SHEET_SYNC", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    monkeypatch.setattr(server, "LIBRARY", tmp_path / "library")
    c = TestClient(server.app)
    r = c.post("/api/character", data={"name": "Quill", "prompt_lock": "a lanky courier in a teal raincoat"},
               files={"images": ("q.png", _png((10, 120, 130)), "image/png")})
    assert r.status_code == 200, r.text
    old = tmp_path / "packs" / "Quill"
    (old / "my_notes.txt").write_text("keep me")
    (tmp_path / "packs" / "Quill_2").mkdir()  # taken (e.g. an earlier fresh start): skip to _3
    before = _snapshot(old)

    for want in ("Quill_3", "Quill_4"):
        r = c.post("/api/sheet", data={"name": "Quill", "consent": "true"},
                   files={"image": ("new.png", _png((200, 60, 60)), "image/png")})
        assert r.status_code == 200, r.text
        assert r.json()["pack_dir"] == str(tmp_path / "packs" / want)
        assert (tmp_path / "packs" / want / "pack.json").is_file()
        assert _snapshot(old) == before  # byte for byte: nothing deleted, moved or rewritten
    assert not (tmp_path / "packs_archive").exists()
    assert json.loads((old / "pack.json").read_text())["name"] == "Quill"
    cast = [x for x in c.get("/api/storyboard/cast").json()["cast"] if x["name"] == "Quill"]
    assert len(cast) == 1  # one Quill in the pickers: the newest


def test_upload_for_the_open_character_also_goes_to_a_new_folder(monkeypatch, tmp_path):
    """Create sends pack_dir of the open character; a new photo still never rewrites that pack."""
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    monkeypatch.setenv("OPENSOUL_SHEET_SYNC", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    monkeypatch.setattr(server, "LIBRARY", tmp_path / "library")
    c = TestClient(server.app)
    first = c.post("/api/sheet", data={"name": "Quill", "consent": "true"},
                   files={"image": ("a.png", _png((10, 120, 130)), "image/png")}).json()
    old = tmp_path / "packs" / "Quill"
    assert first["pack_dir"] == str(old)
    before = _snapshot(old)
    r = c.post("/api/sheet", data={"name": "Quill", "consent": "true", "pack_dir": str(old)},
               files={"image": ("b.png", _png((200, 60, 60)), "image/png")}).json()
    assert r["pack_dir"] == str(tmp_path / "packs" / "Quill_2") and _snapshot(old) == before
    # no new photo: re-making the open character's sheet still extends its own pack
    r = c.post("/api/sheet", data={"name": "Quill", "pack_dir": str(old)}).json()
    assert r["pack_dir"] == str(old)
