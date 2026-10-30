"""Unify step 5 (D1): a single shot is always a project. New quick shots land in "Shorts" (id quick-shots); old Create outputs
are brought in by `python -m opensoul.migrate` (dry run by default, backup first, files referenced in place)."""
import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient

from opensoul import migrate


def _tree(root: Path) -> dict:
    return {str(p.relative_to(root)): hashlib.md5(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file()}


def _outputs(data: Path):
    for name, files in {"aaa111": ["final.mp4", "voice.wav", "video.mp4"], "bbb222": ["video.mp4"], "ccc333": []}.items():
        d = data / "outputs" / "shots" / name
        d.mkdir(parents=True)
        for f in files:
            (d / f).write_bytes(f"{name}/{f}".encode())


def test_dry_run_writes_nothing(tmp_path, capsys):
    _outputs(tmp_path)
    before = _tree(tmp_path)
    assert migrate.main(["--data", str(tmp_path)]) == 0
    assert "2 quick shot(s)" in capsys.readouterr().out
    assert _tree(tmp_path) == before and not (tmp_path / "projects").exists()


def test_apply_is_additive_idempotent_and_backs_up_first(tmp_path):
    _outputs(tmp_path)
    outputs_before = _tree(tmp_path / "outputs")
    r = migrate.apply(tmp_path)
    assert r["backup"] is None and len(r["added"]) == 2  # the empty folder is skipped
    p = json.loads((tmp_path / "projects" / "quick-shots" / "project.json").read_text())
    assert p["title"] == "Shorts" and len(p["shots"]) == 2
    v = p["shots"][0]["versions"][0]
    assert v["file"] == "data/outputs/shots/aaa111/final.mp4" and v["settings"]["migrated_from"] == "outputs/shots/aaa111"
    assert v["settings"]["quality"] == "final" and p["shots"][1]["versions"][0]["settings"]["quality"] == "draft"
    r2 = migrate.apply(tmp_path)
    assert r2["added"] == [] and r2["backup"] and Path(r2["backup"]).is_file()  # backup taken before writing
    assert _tree(tmp_path / "outputs") == outputs_before  # nothing moved, changed or deleted


def test_a_quick_shot_from_create_lands_in_the_project(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    monkeypatch.setattr(server, "LIBRARY", tmp_path / "library")
    c = TestClient(server.app)
    assert c.post("/api/character", data={"name": "Odo Fenn", "prompt_lock": "a short baker with a flour-dusted apron"}).status_code == 200
    r = c.post("/api/shot", json={"name": "Odo Fenn", "camera": "dolly_in", "pack_dir": str(tmp_path / "packs" / "Odo_Fenn")})
    assert r.status_code == 200, r.text
    q = r.json()["quick_shot"]
    assert q and q["project"] == "quick-shots"
    proj = c.get("/api/storyboard/projects/quick-shots").json()
    assert proj["title"] == "Shorts" and proj["shots"][0]["characters"] == ["Odo Fenn"]
    assert proj["shots"][0]["camera"] == "dolly_in" and proj["shots"][0]["versions"][0]["placeholder"] is True


def test_migrated_cards_get_a_poster_and_a_readable_title(tmp_path):
    import pytest
    from opensoul import media
    if not media.ffmpeg_bin():
        pytest.skip("no ffmpeg")
    img = tmp_path / "s.png"
    from PIL import Image
    Image.new("RGB", (64, 112), (40, 90, 160)).save(img)
    d = tmp_path / "outputs" / "shots" / "ddd444"
    media.still_to_clip(img, d / "video.mp4", seconds=0.5, width=64, height=112)
    outputs_before = _tree(tmp_path / "outputs")
    r = migrate.apply(tmp_path)
    p = json.loads((tmp_path / "projects" / "quick-shots" / "project.json").read_text())
    s = p["shots"][0]
    assert s["beat"].startswith("Short · ") and "ddd444" not in s["beat"]
    poster = s["versions"][0]["poster"]
    assert poster and poster.startswith("data/projects/quick-shots/posters/") and (tmp_path / poster[5:]).is_file()
    assert _tree(tmp_path / "outputs") == outputs_before and len(r["added"]) == 1


def test_a_dry_run_name_card_migrates_as_a_preview_never_final(tmp_path):
    import pytest
    from opensoul import media
    if not media.ffmpeg_bin():
        pytest.skip("no ffmpeg")
    import app.server as server
    card = server._name_card("Lumi", tmp_path / "card.png", (360, 640), "Preview · drawn from the description in Studio")
    d = tmp_path / "outputs" / "shots" / "eee555"
    media.still_to_clip(card, d / "final.mp4", seconds=0.5, width=360, height=640)
    (d / "voice.wav").write_bytes(b"RIFF")  # would have meant "final" before
    migrate.apply(tmp_path)
    v = json.loads((tmp_path / "projects" / "quick-shots" / "project.json").read_text())["shots"][0]["versions"][0]
    assert v["placeholder"] is True and v["kind"] == "preview" and v["settings"]["quality"] == "draft"


def test_a_real_frame_is_not_mistaken_for_a_preview(tmp_path):
    from PIL import Image
    p = tmp_path / "f.png"
    Image.new("RGB", (48, 64), (40, 90, 160)).save(p)
    assert migrate.looks_like_preview(p) is False and migrate.looks_like_preview(None) is False


def test_a_take_whose_file_is_gone_is_flagged_missing(monkeypatch, tmp_path):
    from opensoul import storyboard as sb
    import app.server as server
    monkeypatch.setattr(server, "DATA", tmp_path)
    sb.set_data_dir(tmp_path)
    st = sb.Store(tmp_path / "projects")
    p = st.create_project("Gone")
    s = st.add_shot(p.id, "Lost clip")
    gone = tmp_path / "outputs" / "x" / "final.mp4"
    gone.parent.mkdir(parents=True)
    gone.write_bytes(b"x")
    st.add_version(p.id, s.id, file=sb.rel_path(gone), kind="render")
    gone.unlink()
    j = TestClient(server.app).get(f"/api/storyboard/projects/{p.id}").json()
    v = j["shots"][0]["versions"][0]
    assert v["missing"] is True and v["video_url"] is None


def test_cards_never_show_a_silhouette_for_a_missing_or_posterless_take():
    js = (Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "storyboard.js").read_text()
    assert "Video missing" in js and "k && k.missing" in js and "k && k.video_url ? `<div class=\"sb-thumb\"><video" in js
