"""Advanced → engine pickers: registry-driven, installed-only, and wired into the shot plan."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opensoul import models_registry as mr
from opensoul.presets import build_shot_plan

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    from app import server

    monkeypatch.setattr(server, "DATA", tmp_path)
    return TestClient(server.app)


def _fake_status(voice_avail, lipsync_avail):
    def b(i, ok):
        return {"id": i, "label": i.title(), "license": "x", "optional": False, "available": ok, "missing_files": []}

    return [
        {"id": "voice", "label": "Voice", "default_backend": "kokoro", "download_hint": "./scripts/download_models.sh tts",
         "backends": [b("kokoro", voice_avail[0]), b("chatterbox", voice_avail[1])]},
        {"id": "lipsync", "label": "Lip-sync", "default_backend": "latentsync", "download_hint": "",
         "backends": [b("latentsync", lipsync_avail[0]), b("ltx_av", lipsync_avail[1])]},
    ]


def test_choices_hide_missing_backends(monkeypatch):
    monkeypatch.setattr(mr, "stage_status", lambda *_: _fake_status((True, False), (True, True)))
    rows = {r["stage"]: r for r in mr.backend_choices()}
    assert [o["id"] for o in rows["voice"]["options"]] == ["kokoro"]
    assert [o["id"] for o in rows["lipsync"]["options"]] == ["latentsync", "ltx_av"]
    assert rows["lipsync"]["default"] == "latentsync"


def test_choices_never_empty(monkeypatch):
    monkeypatch.setattr(mr, "stage_status", lambda *_: _fake_status((False, False), (False, True)))
    rows = {r["stage"]: r for r in mr.backend_choices()}
    assert rows["voice"]["options"] == [{"id": "kokoro", "label": "Kokoro", "license": "x", "available": False}]
    # default missing but another installed -> pick the installed one
    assert rows["lipsync"]["default"] == "ltx_av"


def test_real_registry_stages_present():
    rows = {r["stage"]: r for r in mr.backend_choices()}
    assert set(rows) == {"voice", "lipsync"}
    assert {"kokoro", "chatterbox"} <= set(rows["voice"]["all_ids"])
    assert {"latentsync", "ltx_av"} <= set(rows["lipsync"]["all_ids"])


def test_plan_carries_backends():
    plan = build_shot_plan(camera="static", line="Hi there", tts_backend="chatterbox", lipsync_backend="ltx_av")
    st = {s["stage"]: s for s in plan["stages"]}
    assert st["voice"]["backend"] == "chatterbox"
    assert "lipsync" not in st  # ltx_av is the video stage itself (04b with the voice), not a post step
    assert st["video"]["workflow"] == "workflows/04b_a2v_ltx_api.json" and st["video"]["audio_from"] == "voice"


def test_api_backends_and_shot_validation(client):
    data = client.get("/api/backends").json()
    assert {r["stage"] for r in data["stages"]} == {"voice", "lipsync"}
    r = client.post("/api/shot", json={"camera": "static", "line": "Hi", "lipsync_backend": "bogus"})
    assert r.status_code == 400 and "Unknown" in r.json()["detail"]


def test_shot_refuses_uninstalled_outside_preview(client, monkeypatch):
    from app import server

    monkeypatch.setattr(server, "backend_choices", lambda: [
        {"stage": "voice", "label": "Voice", "default": "kokoro", "all_ids": ["kokoro", "chatterbox"],
         "download_hint": "./scripts/download_models.sh tts",
         "options": [{"id": "kokoro", "label": "Kokoro", "license": "x", "available": True}]}])
    monkeypatch.setattr(server, "_dry", lambda: False)
    r = client.post("/api/shot", json={"camera": "static", "line": "Hi", "tts_backend": "chatterbox"})
    assert r.status_code == 400 and "isn't installed" in r.json()["detail"]


def test_ui_has_pickers_wired():
    html = (ROOT / "app" / "web" / "index.html").read_text()
    js = (ROOT / "app" / "web" / "static" / "app.js").read_text()
    assert 'id="advTts"' in html and 'id="advLipsync"' in html
    assert "/api/backends" in js and "tts_backend" in js and "lipsync_backend" in js
