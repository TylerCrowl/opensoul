"""A story file from another build (extra or broken fields) never takes the story list down (was a 500)."""
import json

import pytest
from fastapi.testclient import TestClient

from opensoul import storyboard as sb


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    monkeypatch.setattr(server, "LIBRARY", tmp_path / "library")
    return TestClient(server.app)


def _write(root, pid, data):
    d = root / pid
    d.mkdir(parents=True, exist_ok=True)
    (d / "project.json").write_text(json.dumps(data), encoding="utf-8")


def test_unknown_fields_from_a_newer_build_are_ignored(tmp_path):
    st = sb.Store(tmp_path)
    p = st.create_project("Mine")
    st.add_shot(p.id, "A")
    raw = json.loads((tmp_path / p.id / "project.json").read_text())
    raw["future_project_field"] = 1
    raw["shots"][0]["future_shot_field"] = "x"
    raw["locations"] = [{"name": "Set", "future_loc_field": 2, "angles": [{"name": "Wide", "future": 3}]}]
    _write(tmp_path, p.id, raw)
    q = st.load(p.id)
    assert q.shots[0].beat == "A" and q.location("Set").angle("Wide") is not None


def test_a_broken_story_is_listed_as_broken_not_a_500(client, tmp_path):
    root = tmp_path / "projects"
    _write(root, "good-one", {"id": "good-one", "title": "Good", "character": ""})
    _write(root, "bad-one", {"id": "bad-one", "title": "Bad", "character": "", "shots": [{"beat": "no id"}]})
    (root / "junk").mkdir()
    (root / "junk" / "project.json").write_text("{not json", encoding="utf-8")
    r = client.get("/api/storyboard/projects")
    assert r.status_code == 200, r.text
    ids = {p["id"] for p in r.json()["projects"]}
    assert "good-one" in ids and "bad-one" not in ids
    assert {b["id"] for b in r.json()["broken"]} == {"bad-one", "junk"}
    assert client.get("/api/storyboard/projects/bad-one").status_code == 400


def test_a_broken_demo_file_does_not_break_the_list(client, tmp_path):
    _write(tmp_path / "projects", sb.DEMO_ID, {"id": sb.DEMO_ID, "title": "Demo", "character": "",
                                               "shots": [{"beat": "missing id"}]})
    r = client.get("/api/storyboard/projects")
    assert r.status_code == 200, r.text
    assert [b["id"] for b in r.json()["broken"]] == [sb.DEMO_ID]


def test_ui_shows_an_error_when_stories_cant_load():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    js = (root / "app" / "web" / "static" / "storyboard.js").read_text()
    html = (root / "app" / "web" / "index.html").read_text()
    assert "Couldn't load your stories" in js and "broken" in js
    assert 'id="sbExport" type="button" disabled' in html  # nothing loaded yet: nothing to export
