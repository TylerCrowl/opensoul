"""Demo mode (OPENSOUL_DEMO_CAST=1) shows only the example characters plus what was made since the server started:
test characters left in a data folder never show up in a judge demo or a screenshot."""
import json
import os
import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def c(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    monkeypatch.setenv("OPENSOUL_SHEET_SYNC", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    monkeypatch.setattr(server, "LIBRARY", tmp_path / "library")
    return TestClient(server.app)


def _old_pack(c, tmp_path, name):
    r = c.post("/api/character", data={"name": name, "prompt_lock": f"{name} is a test courier in a teal raincoat"})
    pj = tmp_path / "packs" / name / "pack.json"
    assert r.status_code == 200 and pj.is_file()
    old = time.time() - 10 * 24 * 3600
    os.utime(pj, (old, old))


def names(c):
    return {x["name"] for x in c.get("/api/storyboard/cast").json()["cast"]}


def test_demo_mode_hides_left_over_test_packs_but_not_new_ones(c, tmp_path, monkeypatch):
    _old_pack(c, tmp_path, "Juniper")
    assert "Juniper" in names(c)  # the normal app shows every saved character
    monkeypatch.setenv("OPENSOUL_DEMO_CAST", "1")
    assert "Juniper" not in names(c)
    m = c.post("/api/master", data={"name": "Odile", "look": "a tall baker with flour on her apron", "seed": "2"}).json()
    c.post(f"/api/master/{m['master_id']}/save", data={"name": "Odile"})
    assert "Odile" in names(c)  # made in this session: shown


# Test characters used for real-model runs and screenshots: never shipped, never in demo or served data.
TEST_CHARACTERS = {"marlowe", "juno"}


def test_no_test_character_in_shipped_or_served_data():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    names = {p.name.lower() for p in (root / "assets").iterdir() if p.is_dir()}
    names |= {p.name.lower().split("_")[0] for p in (root / "assets/demo_samples").iterdir()}
    for f in list((root / "assets").glob("*/character.json")) + list((root / "assets/demo_samples").glob("*/pack.json")):
        names.add(str(json.loads(f.read_text()).get("name", "")).lower())
    cfg = json.loads((root / "presets/demo_images.json").read_text())
    names |= {k.lower() for k in cfg.get("cast", {})} | {str(n).lower() for n in cfg.get("more_examples") or []}
    assert not names & TEST_CHARACTERS, names & TEST_CHARACTERS
    # the live and sandbox data dirs on the dev box, when present (read only)
    for data in (root / "data", Path("/tmp/sbdata2")):
        packs = data / "packs"
        if packs.is_dir():
            left = {p.name for p in packs.iterdir() if p.name.lower().split("_")[0] in TEST_CHARACTERS}
            assert not left, (str(packs), left)
        cv = data / "character_voices.json"
        if cv.is_file():
            assert not {k.lower() for k in json.loads(cv.read_text())} & TEST_CHARACTERS
