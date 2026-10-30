"""System status panel renders one row per model-registry stage (not just the general lines)."""
from pathlib import Path

from fastapi.testclient import TestClient

from app.server import app

JS = Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "app.js"


def test_health_exposes_stage_rows_for_ui():
    h = TestClient(app).get("/api/health").json()
    assert h["stages"], "registry stages missing from /api/health"
    for s in h["stages"]:
        assert {"label", "status", "default_backend", "backends", "download_hint"} <= set(s)
        assert s["status"] in {"installed", "optional_installed", "optional_missing", "missing"}


def test_status_panel_renders_stage_rows():
    js = JS.read_text()
    assert "h.stages" in js and "Models per stage" in js
    assert "stage-row" in js and "download_hint" in js
