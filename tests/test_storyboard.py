"""Storyboard: order, takes are never overwritten, keeper per shot, export order, persistence."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opensoul import storyboard as sb
from release_assets import CONCEPT, LUMI_REFS, requires_demo_asset, V8F_TAKE

ROOT = Path(__file__).resolve().parents[1]


def _ffmpeg() -> bool:
    from opensoul.media import ffmpeg_bin

    return ffmpeg_bin() is not None


@pytest.fixture()
def store(tmp_path):
    return sb.Store(tmp_path / "projects")


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    monkeypatch.setenv("OPENSOUL_SHEET_SYNC", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    return TestClient(server.app)


def _beats(p):
    return [s.beat for s in p.shots]


# ---------------------------------------------------------------- ordering
def test_shots_keep_insertion_order_and_index(store):
    p = store.create_project("Test", "Lumi")
    for b in ("A", "B", "C"):
        store.add_shot(p.id, b)
    store.add_shot(p.id, "Start", index=0)
    assert _beats(store.load(p.id)) == ["Start", "A", "B", "C"]


def test_reorder_is_a_permutation_and_move_clamps(store):
    p = store.create_project("Test", "Lumi")
    ids = [store.add_shot(p.id, b).id for b in ("A", "B", "C")]
    store.reorder(p.id, [ids[2], ids[0], ids[1]])
    assert _beats(store.load(p.id)) == ["C", "A", "B"]
    with pytest.raises(sb.StoryError):
        store.reorder(p.id, [ids[0], ids[1]])  # a shot would be lost
    with pytest.raises(sb.StoryError):
        store.reorder(p.id, [ids[0], ids[0], ids[1]])
    store.move_shot(p.id, ids[2], +5)  # C to the end
    assert _beats(store.load(p.id)) == ["A", "B", "C"]
    store.move_shot(p.id, ids[1], -1)
    assert _beats(store.load(p.id)) == ["B", "A", "C"]


def test_new_shot_stars_the_project_character(store):
    p = store.create_project("Test", "Lumi")
    assert store.add_shot(p.id, "A").characters == ["Lumi"]


# ---------------------------------------------------------------- versions are never overwritten
def test_add_version_appends_and_never_reuses_numbers(store):
    p = store.create_project("Test", "Lumi")
    s = store.add_shot(p.id, "A")
    v1 = store.add_version(p.id, s.id, file="a.jpg")
    v2 = store.add_version(p.id, s.id, file="b.jpg")
    assert (v1.id, v2.id) == ("v1", "v2")
    with pytest.raises(sb.StoryError):
        store.add_version(p.id, s.id, take=1, file="c.jpg")  # same take number = overwrite: refused
    with pytest.raises(sb.StoryError):
        store.update_version(p.id, s.id, "v1", file="c.jpg")
    with pytest.raises(sb.StoryError):
        store.delete_version(p.id, s.id, "v2")  # no confirm
    store.delete_version(p.id, s.id, "v2", confirm=True)
    v3 = store.add_version(p.id, s.id, file="d.jpg")
    assert v3.id == "v3"  # v2's number is never handed out again
    shot = store.load(p.id).shot(s.id)
    assert [(v.id, v.file) for v in shot.versions] == [("v1", "a.jpg"), ("v3", "d.jpg")]


def test_regenerate_api_makes_new_takes_and_keeps_all_old_ones(client):
    p = client.post("/api/storyboard/projects", json={"title": "Night", "character": "Lumi"}).json()
    p = client.post(f"/api/storyboard/projects/{p['id']}/shots", json={"beat": "Cold open", "prompt": "rain"}).json()
    sid = p["shots"][0]["id"]
    seen = []
    for i, edit in enumerate(["", "warmer light", "slower push-in"], 1):
        r = client.post(f"/api/storyboard/projects/{p['id']}/shots/{sid}/regenerate", json={"edit": edit, "seed": 7 + i})
        assert r.status_code == 200, r.text
        shot = r.json()["shots"][0]
        assert [v["id"] for v in shot["versions"]] == [f"v{k}" for k in range(1, i + 1)]
        new = shot["versions"][-1]
        assert new["edit"] == edit and new["seed"] == 7 + i and new["placeholder"] and new["kind"] == "preview"
        assert "Preview" in new["label"]
        files = {v["id"]: (v["file"], v["poster"]) for v in shot["versions"]}
        for vid, f in seen:
            assert files[vid] == f  # earlier takes untouched
        seen.append((new["id"], files[new["id"]]))
        assert shot["keeper"] == "v1"  # a new take never replaces the keeper by itself
    for _, (f, poster) in seen:
        assert (sb.abs_path(poster)).is_file()
    assert len({f for _, (f, _) in seen}) == 3


def test_delete_take_api_needs_confirm(client):
    p = client.post("/api/storyboard/projects", json={"title": "D", "character": "Lumi"}).json()
    p = client.post(f"/api/storyboard/projects/{p['id']}/shots", json={"beat": "A"}).json()
    sid = p["shots"][0]["id"]
    client.post(f"/api/storyboard/projects/{p['id']}/shots/{sid}/regenerate", json={})
    assert client.delete(f"/api/storyboard/projects/{p['id']}/shots/{sid}/versions/v1").status_code == 400
    r = client.delete(f"/api/storyboard/projects/{p['id']}/shots/{sid}/versions/v1?confirm=1")
    assert r.status_code == 200 and r.json()["shots"][0]["versions"] == []


# ---------------------------------------------------------------- keeper
def test_keeper_selection(store, client):
    p = store.create_project("Test", "Lumi")
    s = store.add_shot(p.id, "A")
    store.add_version(p.id, s.id, file="a.jpg")
    store.add_version(p.id, s.id, file="b.jpg")
    assert store.load(p.id).shot(s.id).keeper == "v1"  # first finished take is the default keeper
    store.set_keeper(p.id, s.id, "v2")
    assert store.load(p.id).shot(s.id).keeper == "v2"
    with pytest.raises(sb.NotFound):
        store.set_keeper(p.id, s.id, "v9")
    store.add_version(p.id, s.id, status="rendering")
    with pytest.raises(sb.StoryError):
        store.set_keeper(p.id, s.id, "v3")  # not finished yet
    store.delete_version(p.id, s.id, "v2", confirm=True)
    assert store.load(p.id).shot(s.id).keeper == "v1"  # falls back to a finished take


def test_keeper_api(client):
    p = client.post("/api/storyboard/projects", json={"title": "K", "character": "Lumi"}).json()
    p = client.post(f"/api/storyboard/projects/{p['id']}/shots", json={"beat": "A"}).json()
    sid = p["shots"][0]["id"]
    for _ in range(2):
        client.post(f"/api/storyboard/projects/{p['id']}/shots/{sid}/regenerate", json={"edit": "x"})
    r = client.post(f"/api/storyboard/projects/{p['id']}/shots/{sid}/keeper", json={"version_id": "v2"})
    assert r.json()["shots"][0]["keeper"] == "v2"
    assert client.post(f"/api/storyboard/projects/{p['id']}/shots/{sid}/keeper", json={"version_id": "v7"}).status_code == 404


# ---------------------------------------------------------------- export
def test_export_plan_follows_shot_order_and_lists_skipped(store):
    p = store.create_project("Test", "Lumi")
    a, b, c = (store.add_shot(p.id, x) for x in ("A", "B", "C"))
    store.add_version(p.id, a.id, file="a1.jpg")
    store.add_version(p.id, a.id, file="a2.mp4")
    store.set_keeper(p.id, a.id, "v2")
    store.add_version(p.id, c.id, file="c1.jpg", placeholder=True)
    store.reorder(p.id, [c.id, b.id, a.id])
    plan = sb.export_plan(store.load(p.id))
    assert [(i["beat"], i["take"], i["source_kind"]) for i in plan["items"]] == [("C", "v1", "still"), ("A", "v2", "video")]
    assert [i["index"] for i in plan["items"]] == [1, 3]
    assert plan["skipped"] == [{"index": 2, "shot_id": b.id, "beat": "B", "reason": "no keeper take yet", "seconds": 0.0}]
    assert plan["placeholder"] is True


@pytest.mark.skipif(not _ffmpeg(), reason="needs ffmpeg")
def test_export_api_stitches_keepers_in_order(client, tmp_path):
    p = client.post("/api/storyboard/projects", json={"title": "Stitch", "character": "Lumi"}).json()
    pid = p["id"]
    for b in ("One", "Two"):
        p = client.post(f"/api/storyboard/projects/{pid}/shots", json={"beat": b}).json()
    s1, s2 = (s["id"] for s in p["shots"])
    for sid in (s1, s2):
        client.post(f"/api/storyboard/projects/{pid}/shots/{sid}/regenerate", json={"edit": "x"})
    client.post(f"/api/storyboard/projects/{pid}/reorder", json={"order": [s2, s1]})
    r = client.post(f"/api/storyboard/projects/{pid}/export")
    assert r.status_code == 200, r.text
    j = r.json()
    assert [i["shot_id"] for i in j["plan"]["items"]] == [s2, s1]
    out = Path(j["output_path"])
    assert out.is_file() and out.stat().st_size > 1000 and out.name.endswith("_preview.mp4")
    concat = (out.parent / "concat.txt").read_text()
    assert concat.splitlines() == ["file 'seg_01.mp4'", "file 'seg_02.mp4'"]
    saved = json.loads((out.parent / "plan.json").read_text())
    assert [i["shot_id"] for i in saved["items"]] == [s2, s1]
    from opensoul.media import duration

    assert duration(out) > 3.0  # two ~2 s placeholder clips


def test_export_with_no_keepers_is_a_friendly_error(client):
    p = client.post("/api/storyboard/projects", json={"title": "E", "character": "Lumi"}).json()
    r = client.post(f"/api/storyboard/projects/{p['id']}/export")
    assert r.status_code == 400 and "keeper" in r.json()["detail"]


# ---------------------------------------------------------------- persistence
def test_persists_across_store_instances_and_writes_atomically(store, tmp_path):
    p = store.create_project("Persist", "Lumi")
    s = store.add_shot(p.id, "A", prompt="rain", camera="dolly_in")
    store.add_version(p.id, s.id, file="a.jpg", seed=5, scores={"identity": 0.91}, settings={"x": 1})
    again = sb.Store(tmp_path / "projects").load(p.id)
    v = again.shot(s.id).versions[0]
    assert (again.title, again.shot(s.id).camera, v.seed, v.scores, v.settings) == ("Persist", "dolly_in", 5, {"identity": 0.91}, {"x": 1})
    d = tmp_path / "projects" / p.id
    assert sorted(x.name for x in d.iterdir()) == ["project.json"]  # no temp files left behind
    json.loads((d / "project.json").read_text())


def test_failed_write_keeps_the_old_file(store, monkeypatch):
    p = store.create_project("Safe", "Lumi")
    store.add_shot(p.id, "A")
    f = store.project_dir(p.id) / "project.json"
    before = f.read_text()

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(sb.os, "replace", boom)
    with pytest.raises(OSError):
        store.add_shot(p.id, "B")
    assert f.read_text() == before
    assert [x.name for x in f.parent.iterdir()] == ["project.json"]


def test_deleting_a_shot_needs_confirm_and_keeps_its_takes(store):
    p = store.create_project("Del", "Lumi")
    s = store.add_shot(p.id, "A")
    store.add_version(p.id, s.id, file="a.jpg")
    with pytest.raises(sb.StoryError):
        store.delete_shot(p.id, s.id)
    store.delete_shot(p.id, s.id, confirm=True)
    p2 = store.load(p.id)
    assert p2.shots == [] and p2.deleted_shots[0].versions[0].file == "a.jpg"


def test_bad_project_ids_are_rejected(client):
    assert client.get("/api/storyboard/projects/..%2Fetc").status_code == 404
    assert client.get("/api/storyboard/projects/nope").status_code == 404


# ---------------------------------------------------------------- demo project + current character
def test_demo_project_beats_in_order_with_labelled_concepts(client):
    projects = client.get("/api/storyboard/projects").json()["projects"]
    lumi = next(x for x in projects if x["id"] == sb.DEMO_ID)
    assert lumi["title"] == "Lumi – Night Shift" and lumi["demo"]
    p = client.get(f"/api/storyboard/projects/{sb.DEMO_ID}").json()
    assert p["character"] == "Lumi"
    assert [s["beat"] for s in p["shots"]] == ["Cold open", "Doors chime", "Canned coffee", "Real coffee",
                                                "Sip and freeze", "Into the rain", "Daydream", "Ending"]
    assert "receipt" not in p["shots"][7]["prompt"]
    # Served text follows the audited script (presets/demo_images.json shot_text): no cat, no ancient book
    assert "sketchbook" in p["shots"][7]["prompt"] and "cat" not in p["shots"][7]["prompt"] and "ancient" not in p["shots"][0]["prompt"]
    for s in p["shots"]:
        for v in s["versions"]:
            if v.get("shipped"):  # the approved Shot 1 take (presets/demo_images.json), served from assets/, never stored
                assert s["beat"] == "Cold open" and v["file"].startswith("assets/demo_audited/")
                continue
            assert v["placeholder"] and v["label"] == sb.CONCEPT_LABEL
            assert v["file"].startswith("assets/lumi/concepts/") and (ROOT / v["file"]).is_file()
    # seeding again never touches user edits
    first = p["shots"][0]["id"]
    client.post(f"/api/storyboard/projects/{sb.DEMO_ID}/shots/{first}/move", json={"delta": 1})
    client.get("/api/storyboard/projects")
    again = client.get(f"/api/storyboard/projects/{sb.DEMO_ID}").json()
    assert again["shots"][1]["id"] == first


@requires_demo_asset()
def test_story_project_never_uses_bundled_demo_pictures(client):
    import app.server as server

    p = client.get(f"/api/storyboard/projects/{sb.DEMO_ID}").json()
    for s in p["shots"]:
        for v in s["versions"]:
            assert not server._is_demo_image(sb.abs_path(v["file"]))
    empty = next(s for s in p["shots"] if not s["versions"])
    r = client.post(f"/api/storyboard/projects/{sb.DEMO_ID}/shots/{empty['id']}/regenerate", json={"edit": "rain"})
    v = next(s for s in r.json()["shots"] if s["id"] == empty["id"])["versions"][0]
    base = v["settings"]["base_image"]
    assert base and "demo_samples" not in base
    assert not server._is_demo_image(sb.abs_path(base))


@requires_demo_asset(*LUMI_REFS)
def test_live_regenerate_reuses_the_shot_pipeline_as_a_new_take(client, monkeypatch, tmp_path):
    import app.server as server
    import opensoul.shot as shot_mod
    from opensoul.shot import ShotResult

    calls = []

    def fake_run_shot(plan, image, out_dir, **kw):
        calls.append((plan, Path(image)))
        out = Path(out_dir) / "final.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"fake")
        return ShotResult(video=out, steps=[{"stage": "video"}], notes=["ok"])

    p = client.get(f"/api/storyboard/projects/{sb.DEMO_ID}").json()
    s = p["shots"][0]
    monkeypatch.setattr(server, "_dry", lambda: False)
    monkeypatch.setattr(server, "_start", lambda fn: fn())
    monkeypatch.setattr(shot_mod, "run_shot", fake_run_shot)
    r = client.post(f"/api/storyboard/projects/{sb.DEMO_ID}/shots/{s['id']}/regenerate", json={"edit": "cat looks up", "seed": 3})
    assert r.status_code == 200, r.text
    after = client.get(f"/api/storyboard/projects/{sb.DEMO_ID}").json()["shots"][0]
    stored = [v for v in after["versions"] if not v.get("shipped")]  # the approved Shot 1 take is listed first, not stored
    # OS-026: v1 is the keeper start frame (a concept), so the video made from it becomes the keeper when ready
    assert [v["id"] for v in stored] == ["v1", "v2"] and after.get("stored_keeper", after["keeper"]) == "v2"
    v2 = stored[1]
    assert not v2.get("unapproved") and v2["video_url"]  # a take made now shows (only pre-audit takes are hidden)
    assert v2["status"] == "ready" and v2["kind"] == "render" and v2["file"].endswith("final.mp4") and v2["seed"] == 3
    plan, image = calls[0]
    assert "cat looks up" in json.dumps(plan)  # the edit prompt reaches the video stage
    assert image.name == "v3_cold_open.jpg"  # starts from the shot's own keeper picture, not a bundled demo picture
    assert "it wins over anything above: cat looks up" in v2["prompt"]  # OS-035


@requires_demo_asset(CONCEPT)
def test_refresh_demo_names_the_couple_and_drops_v2_placeholders_only(store):
    p = store.create_project(sb.DEMO_TITLE, "Lumi", pid=sb.DEMO_ID)
    old = store.add_shot(p.id, "Canned coffee", "He grabs a canned coffee.", ["Lumi", sb.OLD_DEMO_CAST])
    store.add_version(p.id, old.id, file=f"{sb.CONCEPTS}/B_konbini.jpg", kind="concept", placeholder=True)
    cold = store.add_shot(p.id, "Cold open", "my own words", ["Lumi"])
    store.add_version(p.id, cold.id, file=f"{sb.CONCEPTS}/B_konbini.jpg", kind="concept", placeholder=True)
    real = store.add_version(p.id, cold.id, file="data/x.mp4", kind="render", keep=True)
    assert sb.refresh_demo(store) is True
    q = store.load(p.id)
    a, c = q.shots
    assert a.characters == ["Lumi", "Mio", "Ren"] and "Ren" in a.prompt and a.versions == [] and a.keeper is None
    assert c.prompt == "my own words" and c.keeper == real.id
    files = [v.file for v in c.versions]
    assert "data/x.mp4" in files and f"{sb.CONCEPTS}/v3_cold_open.jpg" in files and not any("B_konbini" in f for f in files)
    assert len({v.id for v in c.versions}) == len(c.versions)
    assert sb.refresh_demo(store) is False      # idempotent


@requires_demo_asset("assets/mio/mio_ref_00.jpg", "assets/ren/ren_ref_00.jpg")
def test_cast_looks_approved_and_pictures_from_the_library(client):
    """Mio and Ren's photoreal v1 looks were approved in review (Oct 18, 8:23 AM ET): no 'not final' note. Their
    library pictures still drive renders, but while the open-model remake is pending (presets/demo_images.json
    pre_rebuild_hide) the old Lumi/Mio/Ren pictures and sheets display as each one's card picture instead."""
    from app.storyboard_api import _cast_library
    from opensoul.demo_images import cast_card

    lib = {c["name"]: c for c in _cast_library()}
    cast = {c["name"]: c for c in client.get("/api/storyboard/cast").json()["cast"]}
    for name in ("Lumi", "Mio", "Ren"):
        if name in cast:
            assert cast[name]["look_pending"] == ""
            assert f"assets/{name.lower()}/" in str(lib[name]["picture"])  # renders: unchanged
            assert cast[name]["picture_url"] == cast_card(name)["card_url"]  # display: the card, never the old design
    for name in ("Mio", "Ren"):
        if name in cast:
            assert str(lib[name]["sheet"]).endswith(f"{name.lower()}_character_sheet_v1.jpg")
            assert cast[name]["sheet_url"] == cast_card(name)["card_url"]
            meta = json.loads((ROOT / "assets" / name.lower() / "character.json").read_text())
            assert "look_pending" not in meta and meta["approved"]["by"] == "project"


@requires_demo_asset(V8F_TAKE)
def test_demo_story_serves_no_v8f_take_and_exports_nothing(client):
    client.get("/api/storyboard/projects")  # seeds the demo story
    p = client.get(f"/api/storyboard/projects/{sb.DEMO_ID}").json()
    # paused before the K-vs-D decision (closed-generator lineage): no shipped take is served, so nothing plays or exports
    assert not any(v.get("shipped") for v in p["shots"][0]["versions"])
    assert "shot01_doodling_v8f" not in json.dumps(p) and "shot01_cold_open_v8f" not in json.dumps(p)
    r = client.post(f"/api/storyboard/projects/{sb.DEMO_ID}/export")
    assert r.status_code == 400 and r.json()["detail"] == "Pick a keeper take for at least one shot first."


def test_fix_camera_is_off_by_default_and_saved(client):  # OS-017
    p = client.get(f"/api/storyboard/projects/{sb.DEMO_ID}").json()
    assert p["fix_camera"] is False
    r = client.patch(f"/api/storyboard/projects/{sb.DEMO_ID}", json={"fix_camera": True})
    assert r.status_code == 200 and r.json()["fix_camera"] is True
    assert client.get(f"/api/storyboard/projects/{sb.DEMO_ID}").json()["fix_camera"] is True


def test_preview_demo_is_juno_spin_cycle_and_its_drafts_are_its_own_clips(client):  # OS-001, OS-002
    r = client.get("/api/storyboard/projects").json()
    assert r["preview"] is True
    juno = next(x for x in r["projects"] if x["preview_demo"])
    assert juno["id"] == sb.PREVIEW_DEMO_ID and juno["title"] == "Juno – Spin Cycle" and juno["shots"] == 5
    p = client.get(f"/api/storyboard/projects/{sb.PREVIEW_DEMO_ID}").json()
    assert p["character"] == "Juno Pell" and p["aspect"] == "9:16"
    from opensoul import preview_samples

    titles = [c["title"] for c in preview_samples.clips()]
    if not titles:
        return
    s = p["shots"][0]
    client.post(f"/api/storyboard/projects/{p['id']}/shots/{s['id']}/regenerate", json={"quality": "draft"})
    v = client.get(f"/api/storyboard/projects/{p['id']}").json()["shots"][0]["versions"][-1]
    assert v["settings"]["sample"]["video"].endswith("clip_folding.mp4") and v["settings"]["sample"]["cast"] == "Juno Pell"


def test_preview_export_says_samples_not_placeholders(client):  # OS-003
    from opensoul import preview_samples

    if not preview_samples.clips():
        return
    client.get("/api/storyboard/projects")  # seeds the Preview demo
    p = client.get(f"/api/storyboard/projects/{sb.PREVIEW_DEMO_ID}").json()
    s = p["shots"][0]
    client.post(f"/api/storyboard/projects/{p['id']}/shots/{s['id']}/regenerate", json={"quality": "draft"})
    vid = client.get(f"/api/storyboard/projects/{p['id']}").json()["shots"][0]["versions"][-1]["id"]
    client.post(f"/api/storyboard/projects/{p['id']}/shots/{s['id']}/keeper", json={"version_id": vid})
    r = client.post(f"/api/storyboard/projects/{p['id']}/export").json()
    import shutil

    if shutil.which("ffmpeg"):
        assert r.get("output_url"), r
        assert "1 keeper is a sample from a real render" in r["note"] and "placeholder" not in r["note"], r["note"]
