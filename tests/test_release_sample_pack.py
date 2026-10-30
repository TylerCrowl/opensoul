"""Release archives leave the whole Lumi sample pack out (opensoul/export_guard.py DERIVED_DIRS). Without it the app
still starts, offers only the samples it has (Pixel), and never shows an empty or broken Lumi sample."""
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "app/web/static/app.js").read_text()


def _no_lumi_pack(monkeypatch, tmp_path):
    import app.server as server

    gone = tmp_path / "lumi_pack"  # what `git archive` leaves: an empty folder
    gone.mkdir()
    monkeypatch.setattr(server, "DATA", tmp_path / "data")
    monkeypatch.setattr(server, "DEMO_PACK", gone)
    monkeypatch.setattr(server, "DEMO_PACKS", {"Lumi": gone, "Pixel": server.DEMO / "pixel_pack"})
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    return server, gone


def test_without_the_lumi_pack_the_sample_is_hidden_and_nothing_breaks(monkeypatch, tmp_path):
    server, gone = _no_lumi_pack(monkeypatch, tmp_path)
    c = TestClient(server.app)
    boot = c.get("/api/bootstrap")
    assert boot.status_code == 200
    b = boot.json()
    assert [d["name"] for d in b["demos"]] == ["Pixel"]  # no Lumi sample card
    assert b["character"]["pack_dir"] is None and b["character"]["prompt_lock"] == ""
    for path in ("/", "/api/cast", "/api/presets", "/api/look", "/api/health", "/api/voices", "/api/backends"):
        assert c.get(path).status_code < 500, path
    for d in b["demos"]:  # every offered sample has its picture
        for u in (d.get("card_url"), d.get("sheet_url")):
            if u:
                assert c.get(u).status_code == 200, u
    r = c.post("/api/photos", data={"pack_dir": str(gone), "scene": "", "n": "3"})
    assert r.status_code < 500


def test_the_page_offers_only_the_samples_the_server_lists():
    assert "syncDemoButtons();" in JS and '$("btnLoadDemo").hidden = !main;' in JS
    assert "if (!hasDemo(want))" in JS and "if (!first) { newCharacter(); return; }" in JS
    assert '"Try the demo character (Pixel)"' in JS
