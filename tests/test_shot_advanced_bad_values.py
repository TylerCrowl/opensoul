"""Bad Advanced values are a 400 with a message (was: 500 Internal Server Error)."""
from fastapi.testclient import TestClient


def test_non_numeric_advanced_value_is_400(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    r = TestClient(server.app).post("/api/shot", json={"name": server.DEMO_NAME, "camera": "static", "advanced": {"width": "abc"}})
    assert r.status_code == 400 and "Advanced" in r.json()["detail"]
