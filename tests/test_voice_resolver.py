"""Unify step 3: one voice resolver. The character's voice is the default; a shot's own pick overrides it (D4)."""
from opensoul.character_voices import set_voice, voice_for_shot


def test_resolver_order(tmp_path):
    set_voice(tmp_path, "Odo Fenn", "leo")
    assert voice_for_shot(tmp_path, "odo  fenn") == ("leo", "character")
    assert voice_for_shot(tmp_path, "Odo Fenn", "mia") == ("mia", "shot")
    assert voice_for_shot(tmp_path, "") [1] == "default"


def test_quick_shot_and_storyboard_use_the_same_resolver():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "app"
    assert "voice_for_shot(DATA, req.name, None)" in (root / "server.py").read_text()
    assert "voice_for_shot(_srv().DATA, _speaker(s), s.voice or None)" in (root / "storyboard_api.py").read_text()


def test_quick_shot_reports_where_the_voice_came_from(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    import app.server as server
    from fastapi.testclient import TestClient

    monkeypatch.setattr(server, "DATA", tmp_path)
    set_voice(tmp_path, "Odo Fenn", "leo")
    c = TestClient(server.app)
    r = c.post("/api/shot", json={"name": "Odo Fenn", "camera": "static", "line": "Morning."})
    assert r.status_code == 200, r.text
    assert (r.json()["voice"], r.json()["voice_from"]) == ("leo", "character")
    r = c.post("/api/shot", json={"name": "Odo Fenn", "camera": "static", "line": "Morning.", "voice": "mia"})
    assert (r.json()["voice"], r.json()["voice_from"]) == ("mia", "shot")


def test_shot_sheet_folds_the_override_under_advanced():
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "storyboard.js").read_text()
    assert '<details class="sb-adv"' in js and "<summary>Advanced</summary>" in js
    assert "from the character" in js and "· this shot" in js
