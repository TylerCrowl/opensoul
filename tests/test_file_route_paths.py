"""/api/file serves only the repo and the data folder: no sibling folders that share a name prefix, no dot paths."""
from fastapi.testclient import TestClient


def test_sibling_prefix_folder_and_dot_paths_are_forbidden(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    import app.server as server

    data = tmp_path / "data"
    data.mkdir()
    (data / "ok.txt").write_text("ok")
    sib = tmp_path / "data_private"
    sib.mkdir()
    (sib / "secret.txt").write_text("no")
    (data / ".hidden").mkdir()
    (data / ".hidden" / "x.txt").write_text("no")
    monkeypatch.setattr(server, "DATA", data)
    c = TestClient(server.app)
    assert c.get("/api/file", params={"path": str(data / "ok.txt")}).status_code == 200
    assert c.get("/api/file", params={"path": str(sib / "secret.txt")}).status_code == 403
    assert c.get("/api/file", params={"path": str(data / ".hidden" / "x.txt")}).status_code == 403
    assert c.get("/api/file", params={"path": str(server.ROOT / ".git" / "HEAD")}).status_code == 403
    assert c.get("/api/file", params={"path": str(server.ROOT / "README.md")}).status_code == 200


def test_a_data_folder_under_a_dot_folder_still_works(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    import app.server as server

    data = tmp_path / ".local" / "opensoul"
    data.mkdir(parents=True)
    (data / "take.txt").write_text("ok")
    monkeypatch.setattr(server, "DATA", data)
    assert TestClient(server.app).get("/api/file", params={"path": str(data / "take.txt")}).status_code == 200
