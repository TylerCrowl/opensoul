"""A sandbox server (OPENSOUL_DATA=/tmp/...) must never read the repo's real data (QA round 2, :8766 served
data/projects/... files from the repo because stored relative paths resolved against the repo)."""
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from opensoul import storyboard as sb

REPO_DATA = str((sb.ROOT / "data").resolve())


def _srv():
    import app.server as server

    return server


@pytest.fixture()
def sandbox(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    import app.server as server

    data = tmp_path / "sbdata"
    monkeypatch.setattr(server, "DATA", data)
    monkeypatch.setattr(server, "LIBRARY", tmp_path / "library")
    yield data, TestClient(server.app)
    sb.set_data_dir(None)


def test_data_paths_resolve_against_the_data_dir_not_the_repo(tmp_path):
    sb.set_data_dir(tmp_path)
    try:
        assert sb.abs_path("data/projects/p/x.png") == tmp_path / "projects" / "p" / "x.png"
        assert sb.rel_path(tmp_path / "projects" / "p" / "x.png") == "data/projects/p/x.png"
        assert sb.abs_path("assets/lumi/character.json") == sb.ROOT / "assets" / "lumi" / "character.json"  # shipped files stay repo
    finally:
        sb.set_data_dir(None)
    assert sb.abs_path("data/projects/p/x.png") == sb.data_dir() / "projects" / "p" / "x.png"


def test_a_copied_story_never_serves_repo_files(sandbox):
    data, client = sandbox
    pdir = data / "projects" / "copied"
    (pdir / "stages").mkdir(parents=True)
    Image.new("RGB", (64, 36), "gray").save(pdir / "stages" / "plate.png")
    # A story file copied from the real data dir: its media paths are stored as data/projects/<id>/... (repo-relative
    # in the old builds). One file exists in the sandbox copy, one only in the repo's data (if at all).
    project = {"id": "copied", "title": "Copied", "character": "", "shots": [], "locations": [
        {"name": "Set", "image": "data/projects/copied/stages/plate.png", "angles": [],
         "sheet": "data/projects/lumi-night-shift/locations/master_konbini_v8b.png"}]}
    (pdir / "project.json").write_text(json.dumps(project), encoding="utf-8")
    r = client.get("/api/storyboard/projects/copied")
    assert r.status_code == 200, r.text
    body = json.dumps(r.json())
    assert REPO_DATA not in body and "/workspace/opensoul/data" not in body
    loc = r.json()["locations"][0]
    assert loc["image_url"] and _srv().file_of_url(loc["image_url"]) == (data / "projects" / "copied" / "stages" / "plate.png").resolve()
    assert str(data) not in loc["image_url"]  # P1-04: a short key, no absolute path
    assert not loc.get("sheet_url")  # only in the repo's data: not readable from the sandbox
