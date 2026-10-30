"""A new character gets a default voice no other character uses (never Lumi's 'tara' by accident)."""
import json

import pytest
from fastapi.testclient import TestClient

from opensoul import character_voices as cv
from opensoul.orpheus import VOICE_IDS


def test_free_voice_skips_taken_voices_and_lumis(tmp_path):
    assert cv.free_voice(tmp_path, "Wren") == "mia"  # tara, leah, zac, jess belong to Lumi, Mio, Ren, Pixel
    cv.set_voice(tmp_path, "Wren", "mia")
    assert cv.free_voice(tmp_path, "Moss") == "zoe"
    assert cv.ensure_voice(tmp_path, "Moss") == "zoe" and cv.ensure_voice(tmp_path, "Moss") == "zoe"  # kept
    assert cv.ensure_voice(tmp_path, "Lumi") == "tara" and cv.ensure_voice(tmp_path, "mio") == "leah"
    for n in ("A1", "A2", "A3", "A4", "A5", "A6"):
        assert cv.ensure_voice(tmp_path, n) != "tara"
    assert set(cv.load(tmp_path).values()) <= set(VOICE_IDS)


@pytest.fixture
def c(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    monkeypatch.setenv("OPENSOUL_SHEET_SYNC", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    monkeypatch.setattr(server, "LIBRARY", tmp_path / "library")
    return TestClient(server.app)


def test_text_characters_get_distinct_voices(c, tmp_path):
    voices = []
    for name, look in (("Juno", "a short florist with a bright red bob"), ("Odile", "a tall baker with flour on her apron")):
        m = c.post("/api/master", data={"name": name, "look": look, "seed": "3"}).json()
        assert c.post(f"/api/master/{m['master_id']}/save", data={"name": name}).status_code == 200
        voices.append(json.loads((tmp_path / cv.FILENAME).read_text())[name.lower()])
    sh = c.post("/api/sheet", data={"name": "Pell", "prompt_lock": "a lanky courier in a teal raincoat"}).json()
    assert sh["state"] == "done"
    voices.append(cv.load(tmp_path)["pell"])
    assert len(set(voices)) == 3 and "tara" not in voices
    cast = {x["name"]: x for x in c.get("/api/storyboard/cast").json()["cast"]}
    assert cast["Juno"]["voice"] == voices[0]
