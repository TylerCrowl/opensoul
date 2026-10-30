"""P2-15: a first-run browser visit to / starts on the welcome page, also when OpenSoul runs from source."""
import json

import pytest
from fastapi.testclient import TestClient

HTML = {"Accept": "text/html,application/xhtml+xml"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENSOUL_LAUNCHER_HOME", str(tmp_path))
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    from app.server import app

    return TestClient(app, base_url="http://127.0.0.1:7860"), tmp_path


def test_first_browser_visit_goes_to_welcome(client):
    c, _ = client
    r = c.get("/", headers=HTML, follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/welcome"


def test_after_the_welcome_the_app_opens(client):
    c, home = client
    (home / "launcher.json").write_text(json.dumps({"mode": "preview", "first_run_done": True}))
    r = c.get("/", headers=HTML, follow_redirects=False)
    assert r.status_code == 200 and "<html" in r.text.lower()


def test_queries_scripts_and_frames_are_not_redirected(client):
    c, _ = client
    for path, headers in (("/?quick=1", HTML), ("/?tab=shots", HTML), ("/", {"Accept": "*/*"}),
                          ("/", {**HTML, "Sec-Fetch-Dest": "iframe"})):
        assert c.get(path, headers=headers, follow_redirects=False).status_code == 200, (path, headers)
