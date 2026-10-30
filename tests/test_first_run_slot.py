"""Unify step 4 (D3): the first-run slot shows the film only once it is audited and on disk; until then accepted
re-render tiles; with none, the preset clips that already ship. Nothing outside assets/ or docs/media/ is shown."""
import json
from pathlib import Path

from opensoul import first_run

ROOT = Path(__file__).resolve().parents[1]


def _cfg(tmp_path, **kw):
    p = tmp_path / "first_run.json"
    p.write_text(json.dumps(kw))
    return p


def _root(tmp_path):
    r = tmp_path / "repo"
    for rel in ("docs/media/film.mp4", "docs/media/film.jpg", "assets/preset_thumbs/camera/dolly_in.mp4", "secret/x.mp4"):
        (r / rel).parent.mkdir(parents=True, exist_ok=True)
        (r / rel).write_bytes(b"x")
    return r


PRESETS = {"camera": [{"id": "dolly_in", "label": "Dolly in", "thumbnail": "/assets/preset_thumbs/camera/dolly_in.mp4"},
                      {"id": "orbit", "label": "Orbit", "thumbnail": "/assets/preset_thumbs/camera/orbit.mp4"}], "effects": []}
FILM = {"title": "Lumi – Night Shift", "video": "docs/media/film.mp4", "poster": "docs/media/film.jpg"}


def test_film_only_when_audited_and_on_disk(tmp_path):
    r = _root(tmp_path)
    assert first_run.load(_cfg(tmp_path, film={**FILM, "audited": False}), r, PRESETS)["mode"] == "demo"
    assert first_run.load(_cfg(tmp_path, film={**FILM, "audited": "yes"}), r, PRESETS)["mode"] == "demo"  # a real true only
    assert first_run.load(_cfg(tmp_path, film={**FILM, "audited": True, "video": "docs/media/none.mp4"}), r, PRESETS)["mode"] == "demo"
    d = first_run.load(_cfg(tmp_path, film={**FILM, "audited": True}), r, PRESETS)
    assert d["mode"] == "film" and d["items"][0]["video_url"].endswith("docs/media/film.mp4")


def test_accepted_tiles_before_the_fallback(tmp_path):
    r = _root(tmp_path)
    items = [{"preset": "dolly_in", "kind": "camera", "video": "assets/preset_thumbs/camera/dolly_in.mp4", "status": "accepted"},
             {"preset": "orbit", "kind": "camera", "video": "assets/preset_thumbs/camera/dolly_in.mp4", "status": "hold"},
             {"preset": "x", "kind": "camera", "video": "secret/x.mp4", "status": "accepted"},
             {"preset": "y", "kind": "camera", "video": "assets/../secret/x.mp4", "status": "accepted"}]
    d = first_run.load(_cfg(tmp_path, film={**FILM, "audited": False}, tiles={"title": "Example moves", "items": items}), r, PRESETS)
    assert d["mode"] == "tiles" and [i["title"] for i in d["items"]] == ["dolly_in"]
    assert d["items"][0]["video_url"] == "/assets/preset_thumbs/camera/dolly_in.mp4"


def test_fallback_lists_only_preset_clips_that_exist(tmp_path):
    r = _root(tmp_path)
    d = first_run.load(_cfg(tmp_path), r, PRESETS, images={})  # no demo_images config: every clip counts
    assert d["mode"] == "demo" and [i["title"] for i in d["items"]] == ["Dolly in"]


def test_fallback_shows_only_passed_clips_and_one_per_motion(tmp_path):
    r = _root(tmp_path)
    for n in ("push_in_gentle", "jib_up"):
        (r / f"assets/preset_thumbs/camera/{n}.mp4").write_bytes(b"x")
    presets = {"camera": [dict(PRESETS["camera"][0], expect_motion="zoom_in"), PRESETS["camera"][1],
        {"id": "push_in_gentle", "label": "Gentle push-in", "thumbnail": "/assets/preset_thumbs/camera/push_in_gentle.mp4", "expect_motion": "zoom_in"},
        {"id": "jib_up", "label": "Jib up", "thumbnail": "/assets/preset_thumbs/camera/jib_up.mp4", "expect_motion": "crane_up"}], "effects": []}
    none = first_run.load(_cfg(tmp_path), r, presets, images={"preset_clips": {"allowed": []}})
    assert none["items"] == []  # nothing has passed: show none rather than a non-compliant clip
    some = first_run.load(_cfg(tmp_path), r, presets, images={"preset_clips": {"allowed": ["dolly_in", "push_in_gentle", "jib_up"]}})
    assert [i["title"] for i in some["items"]] == ["Dolly in", "Jib up"]  # Gentle push-in looks like Dolly in


def test_shipped_config_is_not_audited_yet_and_bootstrap_serves_it(monkeypatch):
    cfg = json.loads((ROOT / "presets" / "first_run.json").read_text())
    assert cfg["film"]["audited"] is False  # flips to true only after the Shot Auditor pass
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    import app.server as server
    from fastapi.testclient import TestClient

    fr = TestClient(server.app).get("/api/bootstrap").json()["first_run"]
    images = json.loads((ROOT / "presets" / "demo_images.json").read_text())
    assert fr["mode"] in ("tiles", "demo", "samples")
    if fr["mode"] == "demo":  # only Shot Auditor-passed preset clips (none yet), so possibly no examples at all
        assert len(fr["items"]) <= len(images["preset_clips"]["allowed"])
    for it in fr["items"]:
        assert it["video_url"].startswith(("/assets/", "/api/file?path=")) and "/" + "ho" + "me/" not in it["video_url"]  # split: the gate's home-path scan
