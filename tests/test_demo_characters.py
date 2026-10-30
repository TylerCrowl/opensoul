"""The bundled demo characters: Lumi first, Pixel second (R16: the old demo character can't ship)."""
import json
from pathlib import Path

from fastapi.testclient import TestClient

from demo_character import DEMO_NAME, DEMO_PACK, DEMO_PACKS, OTHER_NAME, SECOND_DEMO, demo_ref
from opensoul.character_pack import CharacterPack
from release_assets import requires_demo_asset

ROOT = Path(__file__).resolve().parents[1]


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    return TestClient(server.app), server


@requires_demo_asset()
def test_demo_is_lumi_then_pixel_and_every_bundled_file_exists(monkeypatch, tmp_path):
    assert (DEMO_NAME, SECOND_DEMO) == ("Lumi", "Pixel")
    c, server = _client(monkeypatch, tmp_path)
    b = c.get("/api/bootstrap").json()
    assert b["character"]["name"] == "Lumi" and b["character"]["pack_dir"] == str(DEMO_PACK)
    assert [d["name"] for d in b["demos"]] == ["Lumi", "Pixel"] and all(d["prompt_lock"] for d in b["demos"])
    for n, d in DEMO_PACKS.items():
        cp = CharacterPack.load(d)
        assert cp.name == n and cp.ref_images and all(Path(r).is_file() for r in cp.ref_images)
    stills = b["photos"]["items"]
    assert len(stills) == 4 and [s["passed"] for s in stills] == [True, True, True, False]
    for u in [*(s["url"] for s in stills), b["character"]["sheet_url"], b["video"]["poster_url"]]:
        assert u and (ROOT / u.removeprefix("/")).is_file(), u
    assert "coffee" in b["photos"]["scene"]
    assert b["video"]["scripts"] and all(s["spoken"] and s["shots"] for s in b["video"]["scripts"])


@requires_demo_asset()
def test_a_demo_picture_is_fine_under_its_own_name_and_caught_under_another(monkeypatch, tmp_path):
    c, server = _client(monkeypatch, tmp_path)
    ref = demo_ref()
    assert server._is_demo_image(ref) and server._is_demo_image(ref, OTHER_NAME) and not server._is_demo_image(ref, "lumi")
    own = CharacterPack(name=DEMO_NAME, prompt_lock="x", ref_images=[str(ref)])
    own.save(tmp_path / "packs" / DEMO_NAME)
    kept = server._own_refs(tmp_path / "packs" / DEMO_NAME)
    assert len(kept) == 1 and kept[0].read_bytes() == ref.read_bytes()
    other = CharacterPack(name=OTHER_NAME, prompt_lock="x", ref_images=[str(ref)])
    other.save(tmp_path / "packs" / OTHER_NAME)
    assert server._own_refs(tmp_path / "packs" / OTHER_NAME) == [] and server._pack_borrows_demo(tmp_path / "packs" / OTHER_NAME)
    pixel = Path(CharacterPack.load(DEMO_PACKS["Pixel"]).ref_images[0])
    assert server._is_demo_image(pixel, DEMO_NAME) and not server._is_demo_image(pixel, "Pixel")


@requires_demo_asset()
def test_the_saved_lumi_library_character_still_casts(monkeypatch, tmp_path):
    c, server = _client(monkeypatch, tmp_path)
    lib = server._library("Lumi")
    assert lib and lib["reference"] and lib["reference"].is_file()
    cast = c.get("/api/storyboard/cast").json()["cast"]
    lumi = next(x for x in cast if x["name"] == "Lumi")
    assert lumi["picture_url"]


def test_pixel_demo_from_the_page(monkeypatch, tmp_path):
    c, _ = _client(monkeypatch, tmp_path)
    html = c.get("/").text
    assert "Use the demo character (Lumi)" in html and 'id="btnLoadDemo2"' in html and "or try Pixel" in html
    js = (ROOT / "app" / "web" / "static" / "app.js").read_text()
    assert 'loadDemo("Pixel")' in js and "state.demos = data.demos" in js and 'let DEMO_NAME = "Lumi"' in js


@requires_demo_asset()
def test_demo_scores_file_matches_the_stills():
    d = json.loads((ROOT / "assets" / "demo_samples" / "scores.json").read_text())
    assert [r["passed"] for r in d["demo_stills"]] == [True, True, True, False]
    assert all((ROOT / "assets" / "demo_samples" / r["file"]).is_file() for r in d["demo_stills"])
