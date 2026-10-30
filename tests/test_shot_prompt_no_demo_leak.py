"""A shot for a new character never carries the demo character's look lock (was: empty pack_dir + new name
-> the demo's full description in the video prompt)."""
from fastapi.testclient import TestClient
from release_assets import LUMI_REFS, requires_demo_asset


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    monkeypatch.setattr(server, "LIBRARY", tmp_path / "library")
    return TestClient(server.app), server


def test_new_name_without_a_pack_gets_no_demo_description(monkeypatch, tmp_path):
    c, server = _client(monkeypatch, tmp_path)
    demo_lock = server._pack_prompt("")  # the bundled demo's; "" in a release archive (no Lumi pack there)
    r = c.post("/api/shot", json={"name": "Quill", "camera": "static"})
    assert r.status_code == 200, r.text
    assert not demo_lock or demo_lock not in r.json()["plan"]["prompt"]


@requires_demo_asset(*LUMI_REFS)
def test_demo_character_still_gets_its_lock(monkeypatch, tmp_path):
    c, server = _client(monkeypatch, tmp_path)
    r = c.post("/api/shot", json={"name": server.DEMO_NAME, "camera": "static"})
    assert server._pack_prompt("") in r.json()["plan"]["prompt"]


def test_own_pack_lock_is_used(monkeypatch, tmp_path):
    c, server = _client(monkeypatch, tmp_path)
    made = c.post("/api/character", data={"name": "Quill", "prompt_lock": "a lanky courier in a teal raincoat"}).json()
    r = c.post("/api/shot", json={"name": "Quill", "pack_dir": made["pack_dir"], "camera": "static"})
    assert "teal raincoat" in r.json()["plan"]["prompt"] and (
        not server._pack_prompt("") or server._pack_prompt("") not in r.json()["plan"]["prompt"])
