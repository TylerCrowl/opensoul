"""A text-made sheet for a character you already have extends that character's pack
(was: a duplicate packs/<Name>_2 the cast silently switched to, with the old pack orphaned)."""
import json
from pathlib import Path

from fastapi.testclient import TestClient


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    monkeypatch.setenv("OPENSOUL_SHEET_SYNC", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    monkeypatch.setattr(server, "LIBRARY", tmp_path / "library")
    return TestClient(server.app)


def test_text_sheet_for_a_text_character_lands_in_their_pack(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.post("/api/storyboard/cast", data={"name": "Bram Oake", "description": "a stocky night cook, flour on his apron"})
    assert r.status_code == 200, r.text
    pack = tmp_path / "packs" / "Bram_Oake"
    lock = json.loads((pack / "pack.json").read_text())["prompt_lock"]
    r = c.post("/api/sheet", data={"name": "Bram Oake", "prompt_lock": "a stocky night cook, flour on his apron"})
    assert r.status_code == 200, r.text
    assert r.json()["pack_dir"] == str(pack) and r.json()["state"] == "done"
    assert not (tmp_path / "packs" / "Bram_Oake_2").exists()
    data = json.loads((pack / "pack.json").read_text())
    assert data["prompt_lock"] == lock and data["name"] == "Bram Oake"
    refs = data["ref_images"]
    assert refs[0].startswith("refs/reference") and (pack / refs[0]).is_file()  # the drawn reference is the anchor
    assert sum(Path(x).name.startswith("sheet_") for x in refs) == 6
    assert any((pack / f"character_sheet{e}").is_file() for e in (".png", ".jpg"))
    cast = [x for x in c.get("/api/storyboard/cast").json()["cast"] if x["name"] == "Bram Oake"]
    assert len(cast) == 1 and cast[0]["sheet_url"]


def test_second_text_sheet_keeps_the_same_anchor(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    c.post("/api/storyboard/cast", data={"name": "Mira Vale", "description": "a tall usher with silver braids"})
    c.post("/api/sheet", data={"name": "Mira Vale", "prompt_lock": "a tall usher with silver braids"})
    pack = tmp_path / "packs" / "Mira_Vale"
    first = json.loads((pack / "pack.json").read_text())["ref_images"][0]
    anchor = (pack / first).read_bytes()
    r = c.post("/api/sheet", data={"name": "Mira Vale", "prompt_lock": "a tall usher with silver braids"})
    assert r.json()["pack_dir"] == str(pack)
    data = json.loads((pack / "pack.json").read_text())
    assert data["ref_images"][0] == first and (pack / first).read_bytes() == anchor  # extended from the same face
    assert list((tmp_path / "packs").iterdir()) == [pack]

