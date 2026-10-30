"""Preview mode follows the Final rule: Final of the keeper becomes the keeper (was: the draft stayed keeper in
dry-run, so the export stitched the draft)."""
from fastapi.testclient import TestClient


def test_final_of_the_keeper_becomes_the_keeper_in_preview(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    monkeypatch.setattr(server, "LIBRARY", tmp_path / "library")
    c = TestClient(server.app)
    p = c.post("/api/storyboard/projects", json={"title": "Final rule"}).json()
    p = c.post(f"/api/storyboard/projects/{p['id']}/shots", json={"beat": "One", "characters": []}).json()
    sid = p["shots"][0]["id"]
    p = c.post(f"/api/storyboard/projects/{p['id']}/shots/{sid}/regenerate", json={"seed": 3}).json()
    assert p["shots"][0]["keeper"] == "v1"
    p = c.post(f"/api/storyboard/projects/{p['id']}/shots/{sid}/regenerate", json={"seed": 4}).json()
    assert p["shots"][0]["keeper"] == "v1"  # a new draft doesn't steal the keeper
    p = c.post(f"/api/storyboard/projects/{p['id']}/shots/{sid}/final", json={}).json()
    s = p["shots"][0]
    assert s["keeper"] == "v3" and s["versions"][-1]["settings"]["quality"] == "final"
    p = c.post(f"/api/storyboard/projects/{p['id']}/shots/{sid}/final", json={"version_id": "v2"}).json()
    assert p["shots"][0]["keeper"] == "v3"  # Final of a non-keeper draft leaves the keeper alone
