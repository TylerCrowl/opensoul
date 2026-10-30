"""Batch shots behave like single shots: no cast given casts the lead, a bad shot leaves nothing behind."""
from fastapi.testclient import TestClient

from opensoul import storyboard as sb


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    monkeypatch.setattr(server, "LIBRARY", tmp_path / "library")
    return TestClient(server.app)


def test_batch_without_cast_casts_the_lead_and_empty_list_means_nobody(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    p = c.post("/api/storyboard/projects", json={"title": "Lead test", "character": "Quill"}).json()
    p = c.post(f"/api/storyboard/projects/{p['id']}/shots/batch",
               json={"shots": [{"beat": "A"}, {"beat": "B", "characters": []}]}).json()
    assert [s["characters"] for s in p["shots"]] == [["Quill"], []]
    one = c.post(f"/api/storyboard/projects/{p['id']}/shots", json={"beat": "C"}).json()["shots"][-1]
    assert one["characters"] == ["Quill"]  # same rule as the single add


def test_create_with_a_bad_shot_leaves_no_empty_story(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.post("/api/storyboard/projects", json={"title": "Orphan", "shots": [{"beat": "ok"}, {"beat": "  "}]})
    assert r.status_code == 400
    assert all(p["title"] != "Orphan" for p in c.get("/api/storyboard/projects").json()["projects"])


def test_too_many_shots_is_an_error_not_a_silent_cut(tmp_path):
    st = sb.Store(tmp_path)
    p = st.create_project("Big")
    try:
        st.add_shots(p.id, [{"beat": f"s{i}"} for i in range(sb.MAX_BATCH + 1)])
        raise AssertionError("expected StoryError")
    except sb.StoryError:
        pass
    assert st.load(p.id).shots == []
