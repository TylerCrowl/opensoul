from fastapi.testclient import TestClient

from app.server import app


def test_index_cache_busts_ui_assets():
    r = TestClient(app).get("/")
    assert r.status_code == 200
    assert "no-cache" in r.headers.get("cache-control", "")
    assert "/static/app.js?v=" in r.text
    assert "/static/app.css?v=" in r.text
