"""P1-04 / P1-03: no absolute path (on a Mac it holds the account name) in media URLs, status or the approve command;
Preview mode says models are needed only for a studio."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.server as server
from opensoul import setup_engine as SE


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    monkeypatch.setattr(server, "DATA", tmp_path)
    return TestClient(server.app)


def test_file_urls_use_short_keys_and_still_serve(client, tmp_path):
    f = tmp_path / "projects" / "a b" / "take.jpg"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"x")
    url = server._file_url(f)
    assert url.startswith("/api/file?path=data/projects/a%20b/take.jpg") and str(tmp_path) not in url
    assert client.get(url).content == b"x"
    repo = server._key(server.ROOT / "assets" / "juno_pell" / "juno_ref_00.jpg")
    assert repo == "assets/juno_pell/juno_ref_00.jpg"
    assert client.get(f"/api/file?path={repo}").status_code == 200
    # old absolute links keep working, and keys can't climb out
    assert client.get(f"/api/file?path={f}").status_code == 200
    for bad in ("data/../../etc/passwd", "../etc/passwd", "/etc/passwd"):
        assert client.get(f"/api/file?path={bad}").status_code == 403


def test_storyboard_take_urls_have_no_absolute_paths(client, tmp_path):
    p = client.post("/api/storyboard/projects", json={"title": "Paths"}).json()
    p = client.post(f"/api/storyboard/projects/{p['id']}/shots", json={"beat": "One", "prompt": "x"}).json()
    sid = p["shots"][0]["id"]
    v = client.post(f"/api/storyboard/projects/{p['id']}/shots/{sid}/regenerate", json={}).json()["shots"][0]["versions"][-1]
    for k in ("video_url", "poster_url"):
        if v.get(k):
            assert str(tmp_path) not in v[k] and "path=data/" in v[k], v[k]


def test_status_shows_home_as_tilde(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    assert server.tilde(tmp_path / "Library" / "OpenSoul") == "~/Library/OpenSoul"
    assert server.tilde("/opt/x") == "/opt/x"


def test_launcher_status_has_no_home(client):
    assert "home" not in client.get("/api/launcher/status").json()


def test_approve_command_from_a_package_uses_its_python_and_tilde(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setenv("OPENSOUL_LAUNCHED", "1")
    rt = tmp_path / "Library" / "Application Support" / "OpenSoul" / "runtime" / "1.0"
    monkeypatch.setattr(SE, "ROOT", rt / "app")
    monkeypatch.setattr("sys.executable", str(rt / "python" / "bin" / "python3"))
    data = tmp_path / "Library" / "Application Support" / "OpenSoul" / "data"
    cmd = SE.approve_command({"plan_id": "p1", "license_acks_needed": []}, data)
    assert str(tmp_path) not in cmd
    assert cmd == ("cd ~/'Library/Application Support/OpenSoul/runtime/1.0/app' && "
                   "~/'Library/Application Support/OpenSoul/runtime/1.0/python/bin/python3' -I -m opensoul.setup_engine "
                   "--data ~/'Library/Application Support/OpenSoul/data' approve p1")


def test_preview_status_says_models_are_for_a_studio(client):
    rows = {r["label"]: r["value"] for r in client.get("/api/health").json()["summary"]}
    assert rows["Mode"].startswith("Preview mode")
    assert not any("download_models.sh" in v for v in rows.values())
    assert "Needed only for a studio" in rows.values() or all("missing" not in v for v in rows.values())


def test_every_ui_file_is_cache_busted(client):
    import re

    html = client.get("/").text
    for src in re.findall(r'/static/([\w.]+\.(?:js|css))', html):
        assert re.search(rf'/static/{re.escape(src)}\?v=\w+"', html), src
