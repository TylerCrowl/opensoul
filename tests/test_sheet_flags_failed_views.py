"""A sheet view that finished but failed its checks (passed=false) is flagged in the API and the UI
(was: flagged only when it had a note, so "Sheet ready … six reference angles" while close_back had failed)."""
import io
import re
from pathlib import Path
from types import SimpleNamespace as NS

from fastapi.testclient import TestClient

JS = (Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "app.js").read_text()


def _view(**kw):
    base = dict(id="close_back", label="Close back", status="done", score=0.4, passed=True, attempts=1, arcface=None,
                checks=[], note="", path=None)
    return NS(**{**base, **kw})


def test_flag_rules():
    from app.server import _view_flag as _vf, _view_json

    def _view_flag(v, dry=False):
        return _vf(v, dry)[0]

    assert _view_flag(_view()) == ""
    assert _view_flag(_view(passed=False, checks=[{"id": "hair", "label": "Hair colour", "passed": False}])) == \
        "Didn't pass the look check: Hair colour."
    assert _view_flag(_view(passed=False)) == "Didn't pass the look check."
    assert _view_flag(_view(note="ears too big")) == "ears too big"
    assert _view_flag(_view(status="failed")) == "This view didn't render."
    assert "Preview stand-in" in _view_flag(_view(passed=False), dry=True)
    assert _view_flag(_view(status="rendering", passed=False)) == ""  # not judged until it's finished
    j = _view_json(_view(passed=False))
    assert j["flagged"] is True and j["passed"] is False and j["flag_reason"] and j["flag_source"] == "studio"
    # preview: a stand-in comparison is flagged as "preview"; real failures stay "studio"
    assert _view_json(_view(passed=False), dry=True)["flag_source"] == "preview"
    assert _view_json(_view(status="failed"), dry=True)["flag_source"] == "studio"
    assert _view_json(_view(note="ears too big"), dry=True)["flag_source"] == "studio"
    assert _view_json(_view(), dry=True)["flag_source"] is None


def test_sheet_done_message_counts_failed_views(monkeypatch):
    from app import server

    job = {"views": []}
    res = NS(views=[_view(id="full_front", label="Front"), _view(passed=False)], sheet="/x/s.png", dry_run=False)
    server._sheet_done(job, res)
    assert "1 view(s) can still be wrong" in job["stage"] and "six reference angles" not in job["stage"]
    assert server._sheet_view_json({**job, "id": "j"})["flagged"] == ["close_back"]


def test_dry_sheet_api_exposes_the_flag(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    monkeypatch.setenv("OPENSOUL_SHEET_SYNC", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    monkeypatch.setattr(server, "LIBRARY", tmp_path / "library")
    from PIL import Image

    b = io.BytesIO()
    Image.new("RGB", (64, 96), "teal").save(b, format="PNG")
    r = TestClient(server.app).post("/api/sheet", data={"name": "Quill", "consent": "true"},
                                    files={"image": ("q.png", b.getvalue(), "image/png")}).json()
    assert r["state"] == "done"
    assert r["flagged"] == [v["id"] for v in r["views"] if v["flagged"]]
    for v in r["views"]:
        assert v["flagged"] == (v["passed"] is False or bool(v["note"]) or v["status"] == "failed")
    assert r["studio_flagged"] == [v["id"] for v in r["views"] if v["flag_source"] == "studio"]
    assert r["preview_note"] == "Preview mode: stand-in angles. Real angles are drawn and checked against the master when a studio is set up."
    if not r["studio_flagged"]:  # stand-in comparisons only: one calm line, no "can still be wrong"
        assert "can still be wrong" not in r["stage"] and r["preview_note"] not in r["stage"]  # shown once, under the views
    assert "look checks run in Studio mode" not in JS[JS.index("async function pollSheet"):JS.index("async function regenerate")]


def test_ui_warns_per_view_only_for_studio_flags_and_shows_one_preview_line():
    body = JS[JS.index("function renderSheetProgress"):JS.index("async function pollSheet")]
    assert 'v.flag_source === "studio"' in body and "Needs a look" in body and "flag_reason" in body and "⚠" in body
    assert "job.preview_note" in body and "vc-preview" in body
    assert re.search(r"const flagged = \(job\.studio_flagged \|\|", JS)


def test_preview_sheet_with_a_real_failure_still_flags(monkeypatch):
    from app import server

    job = {"views": [], "dry_run": True}
    res = NS(views=[_view(id="full_front", passed=False), _view(status="failed")], sheet="/x/s.png", dry_run=True)
    server._sheet_done(job, res)
    out = server._sheet_view_json({**job, "id": "j"})
    assert out["studio_flagged"] == ["close_back"] and "1 view(s) can still be wrong" in job["stage"]
