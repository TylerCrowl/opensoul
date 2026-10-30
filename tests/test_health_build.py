"""/api/health says which code is running: loaded commit, HEAD now, dirty flag, start time, data dir, stale."""
import subprocess

from fastapi.testclient import TestClient


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    return TestClient(server.app), server


def test_health_reports_the_running_build(monkeypatch, tmp_path):
    c, server = _client(monkeypatch, tmp_path)
    b = c.get("/api/health").json()["build"]
    assert set(b) >= {"sha", "short_sha", "head_sha", "stale", "dirty", "started", "pid", "data_dir"}
    assert b["data_dir"] == str(tmp_path.resolve())
    head = subprocess.run(["git", "-C", str(server.ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    if head:
        assert b["head_sha"] == head and len(b["sha"]) == 40 and b["short_sha"] == b["sha"][:7]
    assert b["started"].endswith("+00:00")


def test_a_server_older_than_head_says_restart(monkeypatch, tmp_path):
    c, server = _client(monkeypatch, tmp_path)
    monkeypatch.setitem(server._START, "sha", "0" * 40)
    h = c.get("/api/health").json()
    if h["build"]["head_sha"]:
        assert h["build"]["stale"] is True
        code = next(x for x in h["summary"] if x["label"] == "Code")
        assert "restart" in code["value"]


def test_stale_lists_the_changed_files_and_whether_the_app_changed(monkeypatch, tmp_path):
    c, server = _client(monkeypatch, tmp_path)
    head = server._git("rev-parse", "HEAD")
    if not head:
        return
    b = c.get("/api/health").json()["build"]
    monkeypatch.setitem(server._START, "sha", head)
    b = c.get("/api/health").json()["build"]
    assert b["stale"] is False and b["changed"] == [] and b["app_changed"] is False
    monkeypatch.setattr(server, "_changed_since", lambda a, z: ["tests/test_x.py", "docs/notes.md"])
    monkeypatch.setitem(server._START, "sha", "1" * 40)
    b = c.get("/api/health").json()["build"]
    assert b["stale"] and b["changed_count"] == 2 and b["app_changed"] is False  # tests/docs only: no banner
    monkeypatch.setattr(server, "_changed_since", lambda a, z: ["tests/test_x.py", "app/web/static/app.js"])
    assert c.get("/api/health").json()["build"]["app_changed"] is True
    monkeypatch.setattr(server, "_changed_since", lambda a, z: [])  # unknown diff counts as changed
    assert c.get("/api/health").json()["build"]["app_changed"] is True


def test_the_page_shows_a_banner_for_a_stale_or_restarted_server():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    js = (root / "app" / "web" / "static" / "app.js").read_text()
    html = (root / "app" / "web" / "index.html").read_text()
    assert 'id="staleBanner"' in html
    for bit in ("function staleBannerHTML", "b.app_changed === false", "runs older code", "restarted with newer code",
                'data-stale="reload"', 'data-stale="dismiss"', "staleDismissed.${b.head_sha}", "setInterval(", "visibilitychange"):
        assert bit in js, bit
