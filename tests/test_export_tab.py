"""Unify step 9: Export tab = reel + vertical clip + credits; unified is the default, classic stays at ?ui=classic (D2)."""
from pathlib import Path

from fastapi.testclient import TestClient
from release_assets import requires_demo_asset, V8F_TAKE

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "app" / "web" / "static" / "unified.js").read_text()


def test_vertical_clip_accepts_a_storyboard_take_url_with_its_cache_buster(monkeypatch, tmp_path):
    import app.server as server
    monkeypatch.setattr(server, "DATA", tmp_path)
    clip = tmp_path / "projects" / "p" / "takes" / "v1.mp4"
    clip.parent.mkdir(parents=True)
    clip.write_bytes(b"x")
    seen = {}
    monkeypatch.setattr(server, "_export_vertical", lambda src, dest: seen.setdefault("src", src) is not None)
    r = TestClient(server.app).post("/api/share", json={"video_url": f"/api/file?path={clip}&v=1760000000", "title": "Doors chime", "name": "Mio"})
    assert r.status_code == 200 and seen["src"] == clip.resolve() and r.json()["mp4_url"]
    assert r.json()["caption"].startswith("Mio — Doors chime.")


def test_share_still_refuses_files_outside_the_app(monkeypatch, tmp_path):
    import app.server as server
    monkeypatch.setattr(server, "DATA", tmp_path / "data")
    seen = {}
    monkeypatch.setattr(server, "_export_vertical", lambda src, dest: seen.setdefault("src", src) is not None)
    TestClient(server.app).post("/api/share", json={"video_url": "/api/file?path=/etc/hostname&v=1"})
    assert seen["src"] is None


def test_export_tab_has_the_cards_and_the_default_switch():
    for bit in ("Vertical clip", "Export vertical MP4", "Copy caption", '"/api/share"', "uf-exp"):
        assert bit in JS, bit
    # Credits is linked once, from the footer (the same dialog), not again as a card on this tab
    assert "Show credits &amp; licenses" not in JS and 'id="btnCredits"' in (ROOT / "app/web/index.html").read_text()
    assert 'if (mode === "classic") return;' in JS
    assert '{ storyboard: "shots", export: "export" }[params.get("view")]' in JS  # old links land on the right tab


@requires_demo_asset(V8F_TAKE)
def test_vertical_clip_accepts_a_shipped_asset_take_and_nothing_outside_assets(monkeypatch, tmp_path):
    import app.server as server
    monkeypatch.setattr(server, "DATA", tmp_path)
    seen = []
    monkeypatch.setattr(server, "_export_vertical", lambda src, dest: seen.append(src) or src is not None)
    c = TestClient(server.app)
    c.post("/api/share", json={"video_url": "/assets/demo_audited/placeholder_frame.svg", "title": "x"})
    c.post("/api/share", json={"video_url": "/assets/../app/server.py", "title": "x"})
    r = c.post("/api/share", json={"video_url": "/assets/demo_audited/shot01_doodling_v8f.mp4", "title": "Cold open", "name": "Lumi"}).json()
    assert seen == [(ROOT / "assets/demo_audited/placeholder_frame.svg").resolve(), None, None]
    assert r["mp4_url"] is None and r["note"] == "This demo clip plays in the app but isn't exported. Make your own shot to share."
