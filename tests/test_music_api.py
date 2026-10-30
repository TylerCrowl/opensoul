"""Music tab API in preview mode: song job -> beat map -> cut -> shots in a story -> lip-sync take -> export."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
LYRICS = "[Verse]\nMy kettle hums a morning tune\nThe toast is cold, the bus is soon\n[Chorus]\nRUN RUN RUN to the bus\nNobody waits for us"


def _srv():
    import app.server as server

    return server


def _client(monkeypatch, tmp_path, dry="1"):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", dry)
    monkeypatch.setenv("OPENSOUL_SHEET_SYNC", "1")  # background jobs run inline (server._start)
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    monkeypatch.setattr(server, "LIBRARY", tmp_path / "library")
    if not any(getattr(r, "path", "") == "/api/music/models" for r in server.app.routes):
        from app.music_routes import router

        server.app.include_router(router)
    from app import music_routes

    music_routes._JOBS.clear()
    return TestClient(server.app)


@pytest.fixture
def c(monkeypatch, tmp_path):
    return _client(monkeypatch, tmp_path)


def _song(c, **kw):
    body = {"title": "Late for the Bus", "lyrics": LYRICS, "style": "bouncy pop, 120 BPM", "seconds": 24, "seed": 3, **kw}
    r = c.post("/api/music/songs", json=body)
    assert r.status_code == 200, r.text
    d = c.get(f"/api/music/songs/{r.json()['song_id']}").json()
    assert d["state"] == "done", d
    return d


def test_models_dropdown_in_preview(c):
    d = c.get("/api/music/models").json()
    assert d["preview"] is True and d["song"]["default"] == "preview_tone"
    assert {"preview_tone", "ace_step"} <= {o["id"] for o in d["song"]["options"]}
    assert d["stems"]["default"] == "preview_stem"


def test_song_job_makes_a_beat_map_and_a_cut(c, tmp_path):
    d = _song(c)
    bm = d["beatmap"]
    assert abs(bm["tempo_bpm"] - 120) < 3 and bm["bar_count"] >= 10 and d["preview"] and d["label"].endswith("· preview")
    assert d["lrc_source"] == "preview" and len(d["lines"]) == 4 and d["beat_backend"] == "opensoul_onset"
    assert any(s["name"] == "Chorus" for s in bm["sections"])
    assert d["cut"] and any(c_["lipsync"] for c_ in d["cut"])
    assert c.get(d["song_url"]).status_code == 200 and d["vocals_url"]
    assert (tmp_path / "music" / d["song_id"] / "song.json").is_file()
    songs = c.get("/api/music/songs").json()["songs"]
    assert songs[0]["song_id"] == d["song_id"]
    # cancelling a finished song changes nothing
    assert c.post(f"/api/music/songs/{d['song_id']}/cancel").json()["state"] == "done"


def test_song_validation(c):
    assert c.post("/api/music/songs", json={"lyrics": "", "style": ""}).status_code == 400
    r = c.post("/api/music/songs", json={"lyrics": LYRICS, "model": "heartmula"})
    assert r.status_code == 400 and "isn't ready" in r.json()["detail"]
    assert c.post("/api/music/songs", json={"lyrics": LYRICS, "seconds": 500}).status_code == 400
    assert c.post("/api/music/songs", json={"lyrics": "x" * 4000}).status_code == 400
    assert c.post("/api/music/songs", json={"lyrics": LYRICS, "quality": "ultra"}).status_code == 400
    assert c.get("/api/music/songs/0123456789").status_code == 404
    assert c.get("/api/music/songs/../../etc").status_code == 404
    assert c.get("/api/music/lipsync/0123456789").status_code == 404


def test_recut(c):
    d = _song(c)
    r = c.post(f"/api/music/songs/{d['song_id']}/cut", json={"quality": "draft"}).json()
    assert all(x["frames"] / 24 <= 4.1 for x in r["cut"]) and r["quality"] == "draft"
    r = c.post(f"/api/music/songs/{d['song_id']}/cut", json={"bars_per_shot": 1}).json()
    assert len(r["cut"]) >= len(d["cut"])
    assert c.post(f"/api/music/songs/{d['song_id']}/cut", json={"quality": "x"}).status_code == 400
    assert c.post(f"/api/music/songs/{d['song_id']}/cut", json={"bars_per_shot": 99}).status_code == 422


@needs_ffmpeg
def test_handoff_lipsync_and_export(c, tmp_path):
    d = _song(c)
    sid = d["song_id"]
    assert c.post(f"/api/music/songs/{sid}/handoff", json={"character": ""}).status_code == 400
    h = c.post(f"/api/music/songs/{sid}/handoff", json={"character": "Kestrel", "idea": "a rooftop at dusk"}).json()
    pid = h["project_id"]
    assert len(h["shots"]) == len(d["cut"]) and h["preview"]
    p = c.get(f"/api/storyboard/projects/{pid}").json()
    assert p["aspect"] == h["aspect"] == "16:9" and [s["id"] for s in p["shots"]] == [s["id"] for s in h["shots"]]
    assert all(s["characters"] == ["Kestrel"] for s in p["shots"])
    side = json.loads((tmp_path / "projects" / pid / "music" / f"{sid}.json").read_text())
    sung = [s for s in h["shots"] if s["lipsync"]]
    quiet = [s for s in h["shots"] if not s["lipsync"]]
    assert sung
    row = side["shots"][sung[0]["id"]]
    assert row["vocal_slice"] and (tmp_path / row["vocal_slice"].removeprefix("data/")).is_file() or Path(row["vocal_slice"]).is_file()
    assert row["render"]["workflow"].endswith("04b_a2v_ltx_api.json") and row["render"]["lipsync"] == "ltx_av"
    assert (row["render"]["frames"] - 1) % 8 == 0 and row["render"]["frames"] >= row["cut"]["frames"]
    # lip-sync job on a sung shot -> a preview take on that shot
    j = c.post(f"/api/music/songs/{sid}/lipsync", json={"project_id": pid, "shot_id": sung[0]["id"]}).json()
    j = c.get(f"/api/music/lipsync/{j['lipsync_id']}").json()
    assert j["state"] == "done", j
    assert j["video_url"] and c.get(j["video_url"]).status_code == 200
    shot = next(s for s in c.get(f"/api/storyboard/projects/{pid}").json()["shots"] if s["id"] == sung[0]["id"])
    v = shot["versions"][-1]
    assert v["placeholder"] and v["kind"] == "preview" and v["settings"]["music_song"] == sid
    # no vocal-only track is set up here: the take says it was synced to the song, not "the vocal"
    assert v["label"] == j["label"] == "Sung to the song · preview" and "vocal" not in v["label"]
    if quiet:
        assert c.post(f"/api/music/songs/{sid}/lipsync", json={"project_id": pid, "shot_id": quiet[0]["id"]}).status_code == 400
    assert c.post(f"/api/music/songs/{sid}/lipsync", json={"project_id": pid, "shot_id": "nope"}).status_code == 404
    # export: exactly the song's length, song as the audio
    e = c.post(f"/api/music/songs/{sid}/export", json={"project_id": pid})
    assert e.status_code == 200, e.text
    e = e.json()
    assert "no take yet" in e["note"] and "Preview export" in e["note"] and "shot(s)" not in e["note"]
    assert e["preview"] and e["aspect"] == "16:9" and e["poster_url"] is None
    assert j["placeholder"] and j["poster_url"]
    out = _srv().file_of_url(e["output_url"])
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out)],
                               capture_output=True, text=True).stdout)
    assert abs(dur - d["beatmap"]["duration_s"]) < 0.15 and abs(e["seconds"] - d["beatmap"]["duration_s"]) < 0.05
    streams = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(out)],
                             capture_output=True, text=True).stdout.split()
    assert sorted(streams) == ["audio", "video"]
    assert c.get(e["download_url"]).status_code == 200
    # into an existing story too
    h2 = c.post(f"/api/music/songs/{sid}/handoff", json={"character": "Kestrel", "project_id": pid}).json()
    assert h2["project_id"] == pid and len(c.get(f"/api/storyboard/projects/{pid}").json()["shots"]) == 2 * len(d["cut"])
    assert c.post(f"/api/music/songs/{sid}/handoff", json={"character": "Kestrel", "project_id": "no-such"}).status_code == 404


def test_export_and_lipsync_need_a_handoff(c):
    d = _song(c)
    assert c.post(f"/api/music/songs/{d['song_id']}/export", json={"project_id": "x"}).status_code == 404
    assert c.post(f"/api/music/songs/{d['song_id']}/lipsync", json={"project_id": "x", "shot_id": "y"}).status_code == 404


@needs_ffmpeg
def test_studio_mode_runs_the_registry_workflow_through_the_sdk(monkeypatch, tmp_path):
    """OPENSOUL_DRY_RUN=0 with a fake ComfyUI: ACE-Step's workflow gets the lyrics, then beats and cut as usual."""
    c = _client(monkeypatch, tmp_path, dry="0")
    from opensoul import comfy_client
    from opensoul.music import beats as B
    from test_music_registry import ACE_GRAPH

    wf = tmp_path / "ace_api.json"
    wf.write_text(json.dumps(ACE_GRAPH))
    monkeypatch.setenv("OPENSOUL_ACE_STEP_WORKFLOW", str(wf))
    seen = {}

    def fake_run(path, *, inputs, output_node_id, out_dir):
        seen.update(inputs=inputs, out=output_node_id)
        return [B.write_wav(Path(out_dir) / "song_00001.wav", B.click_track(bpm=118, bars=12, lead_in_s=0.5))]

    monkeypatch.setattr(comfy_client, "run_workflow_file", fake_run)
    from app import music_routes

    looks = iter([["mv_song", "other"], ["other"]])  # a music-video render first holds the GPU, then it's free
    monkeypatch.setattr(music_routes, "GATE_LISTER", lambda: next(looks, ["other"]))
    monkeypatch.setattr("opensoul.music.gpu_gate.time.sleep", lambda s: None)
    models = c.get("/api/music/models").json()
    assert models["preview"] is False and [o["id"] for o in models["song"]["options"]] == ["ace_step"]
    r = c.post("/api/music/songs", json={"lyrics": LYRICS, "style": "disco-pop, 118 BPM", "seconds": 30})
    import time

    for _ in range(200):  # studio jobs run on a thread
        d = c.get(f"/api/music/songs/{r.json()['song_id']}").json()
        if d["done"]:
            break
        time.sleep(0.05)
    assert d["state"] == "done", d
    assert seen["out"] == "10" and seen["inputs"]["5"]["lyrics"] == LYRICS and seen["inputs"]["7"]["seconds"] == 30.0
    assert d["model"] == "ace_step" and not d["preview"] and d["lrc_source"] == "estimated"
    assert "full song" in d["stems_note"] and abs(d["beatmap"]["tempo_bpm"] - 118) < 3
    assert c.post("/api/music/songs", json={"lyrics": LYRICS, "model": "preview_tone"}).status_code == 400


def test_the_main_app_mounts_the_music_tab():
    from fastapi.testclient import TestClient

    from app.server import app as main_app

    c = TestClient(main_app)
    assert c.get("/api/music/models").status_code == 200
    page = c.get("/").text
    assert 'id="ufMusicBtn"' in page and 'id="musicView"' in page and "/static/music.js" in page
    assert c.get("/static/music.js").status_code == 200 and c.get("/static/music.css").status_code == 200



@needs_ffmpeg
def test_the_shots_made_are_the_list_as_shown_draft_or_final(c):
    d = _song(c)
    sid = d["song_id"]
    draft = c.post(f"/api/music/songs/{sid}/cut", json={"quality": "draft"}).json()["cut"]
    h = c.post(f"/api/music/songs/{sid}/handoff", json={"character": "Kestrel"}).json()
    assert h["quality"] == "draft" and len(h["shots"]) == len(draft)
    assert [s["lipsync"] for s in h["shots"]] == [x["lipsync"] for x in draft]
    final = c.post(f"/api/music/songs/{sid}/cut", json={"quality": "final"}).json()["cut"]
    h2 = c.post(f"/api/music/songs/{sid}/handoff", json={"character": "Kestrel"}).json()
    assert len(h2["shots"]) == len(final)


def test_preview_song_is_whole_bars_and_the_list_adds_up(c):
    d = _song(c)
    bm = d["beatmap"]
    bar = 60 / bm["tempo_bpm"] * 4
    assert bm["bars"][0] < 0.05 and abs(bm["bar_count"] * bar - bm["duration_s"]) < 0.2
    for q in ("final", "draft"):
        cut = c.post(f"/api/music/songs/{d['song_id']}/cut", json={"quality": q}).json()["cut"]
        assert sum(x["bars"] for x in cut) == bm["bar_count"]
        for x in cut:
            assert x["extra_s"] == 0 and abs(x["frames"] / 24 - x["bars"] * 2.0) < 0.05, x
            assert x["bars_label"] == f"{x['bars']} bar{'' if x['bars'] == 1 else 's'}"
        lines = [i for x in cut for i in x["lines"]]
        assert len(lines) == len(set(lines)) == len(d["lines"])  # every line once, in one shot
        assert all(x["lipsync"] == bool(x["lines"]) for x in cut)


def test_draft_and_final_cut_sung_parts_the_same_way(c):
    """One lyric line per shot in both; Final cuts are Draft cuts, and Draft only adds a bar-line split inside a
    hold longer than a Draft clip (the 4-bar bridge)."""
    d = _song(c)
    sid = d["song_id"]
    final = c.post(f"/api/music/songs/{sid}/cut", json={"quality": "final"}).json()["cut"]
    draft = c.post(f"/api/music/songs/{sid}/cut", json={"quality": "draft"}).json()["cut"]
    for cut in (final, draft):
        assert all(len(x["lines"]) <= 1 for x in cut), [(x["section"], x["lines"]) for x in cut]
    f_cuts = {x["start_frame"] for x in final}
    d_cuts = {x["start_frame"] for x in draft}
    assert f_cuts <= d_cuts
    for x in final:
        inside = [y for y in draft if x["start_frame"] <= y["start_frame"] < x["start_frame"] + x["frames"]]
        if x["frames"] <= 4 * 24:
            assert len(inside) == 1 and inside[0]["frames"] == x["frames"] and inside[0]["lines"] == x["lines"]
        else:
            assert len(inside) > 1 and inside[0]["lines"] == x["lines"] and not any(y["lines"] for y in inside[1:])
    owner = lambda cut: {i: x["start_frame"] for x in cut for i in x["lines"]}  # noqa: E731
    assert owner(final) == owner(draft)
    verse = [x for x in final if x["section"].lower() == "verse"]
    assert verse and all(x["bars"] <= 2 for x in verse)  # Verse every 2 bars
    assert sum(len(x["lines"]) for x in verse) == 2 and all(len(x["lines"]) <= 1 for x in verse)  # each verse line in its own shot


def test_sync_wording_names_the_vocal_only_when_the_vocal_only_track_is_set_up():
    from opensoul.music import stems

    assert stems.sync_target(False) == "the song" and stems.sync_target(True) == "the vocal"
    js = (Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "music.js").read_text(encoding="utf-8")
    # OS-023: the Music rows render the sung take with LTX audio+video (no LatentSync)
    assert "Render sung take" in js and "/regenerate`" in js and "sync the singer to the vocal" not in js


def test_handoffs_come_back_after_a_reload(c):
    """OS-033: after a reload the page asks for the song's hand-offs and shows Export video again."""
    d = _song(c)
    sid = d["song_id"]
    assert c.get(f"/api/music/songs/{sid}/handoffs").json() == {"handoffs": []}
    h = c.post(f"/api/music/songs/{sid}/handoff", json={"character": "Kestrel"}).json()
    again = c.get(f"/api/music/songs/{sid}").json()
    assert again["handoffs"] and again["handoffs"][-1]["project_id"] == h["project_id"]
    r = c.get(f"/api/music/songs/{sid}/handoffs").json()["handoffs"]
    assert len(r) == 1 and r[0]["project_id"] == h["project_id"] and r[0]["restored"] is True
    assert [s["id"] for s in r[0]["shots"]] == [s["id"] for s in h["shots"]]
    assert c.post(f"/api/music/songs/{sid}/export", json={"project_id": r[0]["project_id"]}).status_code == 200


def test_music_page_restores_the_handoff():
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "app/web/static/music.js").read_text(encoding="utf-8")
    assert "/handoffs`" in js and "restoreHandoff(d)" in js
    assert "Add a second copy of every shot?" in js


def test_sung_music_shot_final_uses_the_song_slice(monkeypatch, tmp_path):
    """OS-023 / OS-034 / OS-043: a Music shot's take renders the cut's length; a sung Final renders LTX audio+video
    from its slice of the song (no LatentSync)."""
    c = _client(monkeypatch, tmp_path)
    d = _song(c)
    sid = d["song_id"]
    h = c.post(f"/api/music/songs/{sid}/handoff", json={"character": "Kestrel"}).json()
    pid = h["project_id"]
    from app import storyboard_api as A
    from opensoul import storyboard as sb
    from opensoul.presets import build_shot_plan

    p = A._store().load(pid)
    sung = next((s for s in p.shots if s.id in {x["id"] for x in h["shots"] if x["lipsync"]}), None)
    plain = next((s for s in p.shots if s.id in {x["id"] for x in h["shots"] if not x["lipsync"]}), None)
    proj = c.get(f"/api/storyboard/projects/{pid}").json()
    assert any("music" in s for s in proj["shots"])
    work = tmp_path / "w"
    work.mkdir()
    if plain is not None:
        plan = build_shot_plan(camera="static", character_prompt="x", seed=1)
        out, info = A._music_plan(pid, plain, plan, "x", 1, "final", work, (1280, 720))
        vid = next(x for x in out["stages"] if x["stage"] == "video")
        assert info and vid["inputs"]["30"]["length"] == info["frames"] and info["frames"] < 169
    if sung is not None:
        side, row = A._music_row(pid, sung.id)
        if row.get("vocal_slice") or (sb.abs_path(side.get("song")) and sb.abs_path(side.get("song")).is_file()):
            plan = build_shot_plan(camera="static", character_prompt="x", seed=1)
            out, info = A._music_plan(pid, sung, plan, "x", 1, "final", work, (1280, 720))
            assert info["sung"] is True
            assert out["stages"][0]["stage"] == "voice" and out["stages"][0]["source"] == "song"
            assert out["stages"][1].get("audio_from") == "voice" and out["stages"][1].get("lipsync") == "ltx_av"
            assert not any(x["stage"] == "lipsync" for x in out["stages"])
