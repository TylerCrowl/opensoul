"""A character made in Create shows up in the Storyboard pickers without a page reload (was: missing from the
lead/cast pickers, and re-adding them hit 'already in your characters' with the dialog stuck open)."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

JS = (Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "storyboard.js").read_text()


def _fn(name: str) -> str:
    m = re.search(r"(?:async )?function " + name + r"\(.*?\n  }\n", JS, re.S)
    assert m, name
    return m.group(0)


def test_cast_is_reloaded_when_the_storyboard_opens_and_before_new_story():
    assert "loadCast();" in _fn("setView")
    assert "await loadCast();" in _fn("newStory")


def test_already_in_your_characters_reuses_them_instead_of_sticking():
    body = JS[JS.index('const r = await api("/cast", { method: "POST", body: fd });') - 200:][:900]
    assert "await loadCast();" in body and "already in your characters. Using them." in body


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    monkeypatch.setattr(server, "LIBRARY", tmp_path / "library")
    return TestClient(server.app)


def test_a_character_saved_in_create_is_in_the_storyboard_cast(client):
    r = client.post("/api/character", data={"name": "Wren Vale", "prompt_lock": "a wiry cartographer in a moss-green coat"})
    assert r.status_code == 200, r.text
    names = [c["name"] for c in client.get("/api/storyboard/cast").json()["cast"]]
    assert "Wren Vale" in names
