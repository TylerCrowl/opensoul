"""The Shorts story (id quick-shots) is 9:16, so shorts come out 720x1280."""
from fastapi.testclient import TestClient

from opensoul import migrate
from opensoul import storyboard as sb


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    monkeypatch.setattr(server, "LIBRARY", tmp_path / "library")
    sb.set_data_dir(tmp_path)
    return TestClient(server.app)


def test_shorts_button_makes_a_vertical_story(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    for title in ("Shorts", "Quick shots"):
        p = c.post("/api/storyboard/projects", json={"title": title}).json()
        assert p["id"] == "quick-shots" and p["aspect"] == "9:16" and p["title"] == "Shorts"
    assert sb._size("9:16") == (720, 1280)


def test_other_stories_stay_16_9(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    p = c.post("/api/storyboard/projects", json={"title": "Barn day"}).json()
    assert p["aspect"] == "16:9" and p["id"] != "quick-shots"


def test_old_wide_shorts_story_with_no_takes_becomes_vertical(tmp_path):
    st = sb.Store(tmp_path / "projects")
    st.create_project("Quick shots", pid="quick-shots", aspect="16:9")
    p = migrate.ensure_project(st)
    assert p.aspect == "9:16" and p.title == "Quick shots"  # stored title is not changed
    assert st.load("quick-shots").aspect == "9:16"


def test_old_wide_shorts_story_with_takes_stays_as_it_is(tmp_path):
    sb.set_data_dir(tmp_path)
    st = sb.Store(tmp_path / "projects")
    st.create_project("Quick shots", pid="quick-shots", aspect="16:9")
    s = st.add_shot("quick-shots", "old take")
    st.add_version("quick-shots", s.id, file="outputs/x.mp4")
    assert migrate.ensure_project(st).aspect == "16:9"
