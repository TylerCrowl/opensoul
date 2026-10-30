"""Unify step 7: one tiles component (tiles.js) for Create and the shot sheet; every move says how well it works."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "web" / "static"
NOT_WORKING = {"jib_down", "orbit", "earth_zoom_out", "orbit_freeze"}  # camera_plan.md §1, set 15


def _presets():
    return [json.loads(p.read_text()) for k in ("camera", "effects") for p in sorted((ROOT / "presets" / k).glob("*.json"))]


def test_every_move_carries_experimental_and_verified():
    for p in _presets():
        assert isinstance(p.get("experimental"), bool), p["id"]
        v = p.get("verified") or {}
        assert v.get("model") == "LTX-2.5 22B distilled" and v.get("path") == "prompt", p["id"]
        assert v.get("result") in {"works", "not working yet"} and v.get("evidence"), p["id"]
        assert p["experimental"] == (p["id"] in NOT_WORKING) == (v["result"] == "not working yet"), p["id"]


def test_nothing_claims_a_lora_path_yet():
    # Preset LoRAs are off by default and none is proven to bind on LTX-2.5, so no tile may say it was checked with one.
    assert all(p["verified"]["path"] != "lora" for p in _presets())


def test_presets_api_passes_the_flags_through(monkeypatch):
    from fastapi.testclient import TestClient
    import app.server as server
    d = TestClient(server.app).get("/api/presets").json()
    orbit = next(p for p in d["camera"] if p["id"] == "orbit")
    assert orbit["experimental"] is True and "thumb_ready" in orbit


def test_both_screens_use_the_shared_component():
    html = (ROOT / "app" / "web" / "index.html").read_text()
    assert html.index('src="/static/tiles.js"') < html.index('src="/static/app.js"') < html.index('src="/static/storyboard.js"')
    tiles = (STATIC / "tiles.js").read_text()
    assert "window.OpenSoulTiles = { tag, html, wire, label," in tiles and 'role="radiogroup"' in tiles
    assert "OpenSoulTiles.tag(p)" in (STATIC / "app.js").read_text()
    sb = (STATIC / "storyboard.js").read_text()
    assert "T.multiHTML(cams, { selected: moves" in sb and "T.wireMulti(root, movesOf(s)" in sb  # stacked moves (camera_plan §4)
    assert '<select id="sbCam"' in sb  # fallback when tiles.js is missing
