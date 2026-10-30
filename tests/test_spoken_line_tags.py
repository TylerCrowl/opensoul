"""Emotion tags reach the voice engine and the result shows them (the video prompt drops them by design,
which read as '<chuckle> was silently dropped')."""
from pathlib import Path

from fastapi.testclient import TestClient
from release_assets import LUMI_REFS, requires_demo_asset

ROOT = Path(__file__).resolve().parents[1]


@requires_demo_asset(*LUMI_REFS)
def test_tags_reach_the_voice_stage_but_not_the_video_prompt(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    r = TestClient(server.app).post("/api/shot", json={"name": server.DEMO_NAME, "camera": "dolly_in",
                                                        "line": "The grinder never sleeps here. <chuckle>"})
    assert r.status_code == 200, r.text
    plan = r.json()["plan"]
    voice = next(s for s in plan["stages"] if s["stage"] == "voice")
    assert "<chuckle>" in voice["inputs"]["text"]
    assert "<chuckle>" not in plan["prompt"]


def test_result_panel_shows_the_spoken_line_with_tags():
    js = (ROOT / "app" / "web" / "static" / "app.js").read_text()
    html = (ROOT / "app" / "web" / "index.html").read_text()
    assert 'id="lineView"' in html and 'id="lineViewRow"' in html
    assert '$("lineView").textContent = spoken' in js and 'st.stage === "voice"' in js
