"""OS-026 / OS-035 / OS-037 / OS-042: the typed change reaches the take and wins; animating the keeper frame makes
the video the keeper; a changed shot text is flagged."""
from __future__ import annotations

from pathlib import Path

from app.storyboard_api import _merge_edit


def test_closed_mouth_change_drops_the_laugh():
    text = "Momo stands by the rooster, laughs with her mouth open, the sun rises."
    out, dropped = _merge_edit(text, "Momo keeps her mouth closed in a soft smile, she does not talk or sing")
    assert "laughs" not in out and "sun rises" in out
    assert out.endswith("she does not talk or sing")
    assert dropped and "laughs" in dropped[0]


def test_no_x_change_drops_x():
    out, dropped = _merge_edit("A barn, a tractor with headlights, morning light.", "no headlights")
    assert "headlights" not in out.split("Most important")[0] and dropped


def test_no_edit_is_unchanged():
    assert _merge_edit("A barn.", "") == ("A barn.", [])


def test_edit_box_survives_a_rerender():
    js = (Path(__file__).resolve().parents[1] / "app/web/static/storyboard.js").read_text(encoding="utf-8")
    assert "sb.editDraft" in js and 'ed.addEventListener("input"' in js


def test_animating_the_keeper_frame_keeps_the_video(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    monkeypatch.setenv("OPENSOUL_SHEET_SYNC", "1")
    from fastapi.testclient import TestClient

    import app.server as server
    from app import storyboard_api as A
    from opensoul import storyboard as sb

    monkeypatch.setattr(server, "DATA", tmp_path)
    monkeypatch.setattr(server, "LIBRARY", tmp_path / "library")
    st = sb.Store(tmp_path / "projects")
    monkeypatch.setattr(A, "_store", lambda: st)
    p = st.create_project("Edit test")
    s = st.add_shot(p.id, "Wave", prompt="Momo waves.", characters=[])
    pic = tmp_path / "f.png"
    from PIL import Image

    Image.new("RGB", (64, 36), (90, 90, 90)).save(pic)
    st.add_version(p.id, s.id, take=st.reserve_take(p.id, s.id), file=sb.rel_path(pic), poster=sb.rel_path(pic),
                   prompt="Start frame of: Momo sits calmly.", kind="frame", label="Start frame")
    p = st.load(p.id)
    s = p.shots[0]
    st.set_keeper(p.id, s.id, s.versions[0].id)
    c = TestClient(server.app)
    r = c.post(f"/api/storyboard/projects/{p.id}/shots/{s.id}/regenerate",
               json={"quality": "final", "from_version": s.versions[0].id, "edit": "slower"})
    assert r.status_code == 200, r.text
    shot = r.json()["shots"][0]
    new = shot["versions"][-1]
    assert shot["keeper"] == new["id"]  # OS-026: the video is the keeper, not the still
    assert "What happens changed" in (new.get("note") or "")  # OS-042
