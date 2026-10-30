"""Several packs under one name (<Name>, <Name>_2, <Name>_4 ...): the original wins, the others are listed as
variants (was: the newest <Name>_N silently shadowed the original). Create's lookup finds characters saved in the
app too, including ones made from a description with no picture yet."""
import json
import os
import time

from fastapi.testclient import TestClient

from tests.demo_character import OTHER_NAME


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    monkeypatch.setattr(server, "LIBRARY", tmp_path / "library")
    return TestClient(server.app)


def _pack(tmp_path, folder, name, lock, age):
    d = tmp_path / "packs" / folder
    d.mkdir(parents=True)
    (d / "pack.json").write_text(json.dumps({"name": name, "prompt_lock": lock, "ref_images": []}))
    t = time.time() - age
    os.utime(d / "pack.json", (t, t))
    return d


def test_original_pack_wins_and_variants_are_listed(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    orig = _pack(tmp_path, OTHER_NAME, OTHER_NAME, "the original look", age=300)
    _pack(tmp_path, f"{OTHER_NAME}_4", OTHER_NAME, "a newer try", age=10)
    _pack(tmp_path, f"{OTHER_NAME}_2", OTHER_NAME, "a second try", age=100)
    cast = [x for x in c.get("/api/storyboard/cast").json()["cast"] if x["name"] == OTHER_NAME]
    assert len(cast) == 1
    assert cast[0]["prompt_lock"] == "the original look" and cast[0]["folder"] == OTHER_NAME
    assert [v["folder"] for v in cast[0]["variants"]] == [f"{OTHER_NAME}_2", f"{OTHER_NAME}_4"]
    from app.storyboard_api import _resolve_pack

    assert _resolve_pack(OTHER_NAME.lower())["pack_dir"] == str(orig)


def test_without_the_original_the_lowest_variant_wins(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _pack(tmp_path, f"{OTHER_NAME}_3", OTHER_NAME, "third", age=100)
    _pack(tmp_path, f"{OTHER_NAME}_5", OTHER_NAME, "fifth", age=1)
    cast = [x for x in c.get("/api/storyboard/cast").json()["cast"] if x["name"] == OTHER_NAME]
    assert cast[0]["prompt_lock"] == "third" and [v["folder"] for v in cast[0]["variants"]] == [f"{OTHER_NAME}_5"]


def test_create_lookup_finds_a_text_only_cast_character(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.post("/api/storyboard/cast", data={"name": "Bram Oake", "description": "tall lighthouse keeper, grey beard"})
    assert r.status_code == 200, r.text
    d = c.get("/api/look", params={"name": "bram oake"}).json()
    assert d["source"] == "library"
    assert d["library"]["name"] == "Bram Oake" and d["library"]["prompt_lock"].startswith("tall lighthouse keeper")
    assert d["library"]["variants"] == []
    assert c.get("/api/look", params={"name": "Bram Oake", "library": 0}).json()["library"] is None  # "Start fresh"


def test_create_lookup_lists_variants(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _pack(tmp_path, OTHER_NAME, OTHER_NAME, "the original look", age=300)
    _pack(tmp_path, f"{OTHER_NAME}_2", OTHER_NAME, "newer", age=1)
    lib = c.get("/api/look", params={"name": OTHER_NAME}).json()["library"]
    assert lib["prompt_lock"] == "the original look" and lib["variants"] == [f"{OTHER_NAME}_2"]


def _pic_pack(tmp_path, folder, color, age):
    from PIL import Image

    d = _pack(tmp_path, folder, OTHER_NAME, f"look {folder}", age)
    (d / "refs").mkdir()
    Image.new("RGB", (32, 32), color).save(d / "refs" / "ref_00.png")
    (d / "pack.json").write_text(json.dumps({"name": OTHER_NAME, "prompt_lock": f"look {folder}",
                                             "ref_images": [str(d / "refs" / "ref_00.png")]}))
    t = time.time() - age
    os.utime(d / "pack.json", (t, t))


def test_a_version_saved_twice_or_identical_to_the_one_in_use_is_not_counted(monkeypatch, tmp_path):
    """QA round 2: the chip said '+3' when two of those were the same picture saved twice (and one matched the chosen)."""
    c = _client(monkeypatch, tmp_path)
    _pic_pack(tmp_path, OTHER_NAME, "red", 400)
    _pic_pack(tmp_path, f"{OTHER_NAME}_2", "blue", 300)
    _pic_pack(tmp_path, f"{OTHER_NAME}_3", "blue", 200)   # same picture as _2
    _pic_pack(tmp_path, f"{OTHER_NAME}_4", "red", 100)    # same picture as the one in use
    cast = [x for x in c.get("/api/storyboard/cast").json()["cast"] if x["name"] == OTHER_NAME]
    assert [v["folder"] for v in cast[0]["variants"]] == [f"{OTHER_NAME}_2"]


def test_variant_tooltips_are_user_facing():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "app" / "web" / "static"
    sb, app = (root / "storyboard.js").read_text(), (root / "app.js").read_text()
    assert "Also saved under this name" not in sb and "other saved version" in sb
    assert "also saved under this name" not in app and "other saved version" in app
