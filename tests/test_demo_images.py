"""Shot Auditor round (Oct 18): the default UI shows only passed pictures, from one swappable mapping file
(presets/demo_images.json); everything else is a stylised placeholder or a glyph card."""
import json
import re
from pathlib import Path

from PIL import Image

from opensoul import demo_images
from release_assets import requires_demo_asset

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "presets" / "demo_images.json").read_text())
JS = (ROOT / "app/web/static/storyboard.js").read_text()


def _client(monkeypatch):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    import app.server as server
    from fastapi.testclient import TestClient

    return TestClient(server.app)


def _all_entries():
    for name, c in CFG["cast"].items():
        yield f"cast/{name}", c.get("card"), c
    yield "tile_still", CFG["tile_still"]["image"], CFG["tile_still"]
    yield "first_run_still", CFG["first_run_still"]["image"], CFG["first_run_still"]
    yield "talking_lumi", CFG["talking_lumi"]["card"], CFG["talking_lumi"]
    for pid, p in CFG["projects"].items():
        for beat, c in p["shot_cards"].items():
            yield f"{pid}/{beat}", c.get("card"), c
        for loc, st in p["stage"].items():
            yield f"{pid}/{loc}/master", st["master"], {"source": st["master_source"], "verdict": st["master_verdict"],
                                                         "placeholder": st.get("placeholder")}
            yield f"{pid}/{loc}/sheet", st["sheet"]["image"], st["sheet"]
            for a, m in st["angles"].items():
                yield f"{pid}/{loc}/{a}", m["image"], m


@requires_demo_asset()
def test_every_listed_picture_ships_and_records_its_source():
    for slot, rel, meta in _all_entries():
        assert rel and rel.startswith("assets/demo_audited/") and (ROOT / rel).is_file(), slot
        if not meta.get("placeholder"):
            assert meta.get("source") and "AUDIT" in (meta.get("verdict") or ""), f"{slot}: no source or verdict"


APPROVED = ("production/takes/SHOT01_doodling_v8f.mp4",  # AUDIT_v8f_20261018_2254: whole clip
            "production/takes/SHOT01_doodling_v8e.mp4",
            "production/takes/stage_konbini_sheet_v6.jpg",
            "production/setbible/MASTER_PLATE_konbini.png",
            "production/lipsync/L1/out/l04_verdict_s171_ls2.0_mp.mp4")  # approved for a still only
BANNED = ("TALK_v8", "ls2.0", "l04_s71", "l07", "l08", "CONTINUITY_after_v8", "DAYDREAM_panels_v8", "v8b", "v8c", "v8d", "preset_thumbs")


def test_sources_are_only_the_approved_files_and_frames():
    import re

    for slot, rel, meta in _all_entries():
        src = meta.get("source")
        if not src:
            assert meta.get("placeholder") or rel.endswith(".svg"), slot
            continue
        assert src.startswith(APPROVED), slot
        first = src.split(",")[0].split(" ")[0]
        if not first.endswith("l04_verdict_s171_ls2.0_mp.mp4"):
            assert not any(b in first or b in rel for b in BANNED), slot
        if "SHOT01_doodling_v8e" in src:  # frames 12-34 (0.50-1.42 s) only
            f = int(re.search(r"frame (\d+)", src).group(1))
            assert 12 <= f <= 34 and f"{f / 24:.3f} s" in src, slot
        if "SHOT01_doodling_v8f" in src and "frame" in src:  # stills before the f72 tag notch, hand still on the page
            f = int(re.search(r"frame (\d+)", src).group(1))
            assert 0 <= f <= 30 and f"{f / 24:.3f} s" in src, slot  # Content CEO: f0-f30 only


def test_shipped_pictures_carry_no_metadata():
    for f in (ROOT / "assets/demo_audited").glob("*.jpg"):
        im = Image.open(f)
        assert not im.getexif() and "comment" not in im.info, f.name


@requires_demo_asset()
def test_mio_and_ren_are_stylised_placeholders_and_pixel_is_a_more_example(monkeypatch):
    cast = {c["name"].lower(): c for c in _client(monkeypatch).get("/api/cast").json()["cast"]}
    assert cast["lumi"]["card_url"] == "/assets/demo_audited/placeholder_lumi.svg" and cast["lumi"]["card_placeholder"]  # neutral until the rebuild
    for n in ("mio", "ren"):
        assert cast[n]["card_url"].endswith(f"placeholder_{n}.svg") and cast[n]["card_placeholder"]
        assert cast[n]["picture_url"]  # the pack itself is kept (renders still use it)
    assert demo_images.cast_card("Pixel")["more_example"]


def test_pixel_has_its_own_voice(tmp_path):
    from opensoul.character_voices import voice_for

    assert voice_for(tmp_path, "Pixel") not in {voice_for(tmp_path, n) for n in ("Lumi", "Mio", "Ren")}


@requires_demo_asset()
def test_no_unpassed_tile_clip_is_shown(monkeypatch):
    data = _client(monkeypatch).get("/api/presets").json()
    allowed = set(CFG["preset_clips"]["allowed"])
    for p in data["camera"] + data["effects"]:
        assert not p["thumb_ready"] or p["id"] in allowed, p["id"]
        assert p["thumb_ready"] or p["tile_still"] == "/assets/demo_audited/placeholder_tile.jpg"  # placeholder + glyph


@requires_demo_asset()
def test_demo_story_cards_and_stage_use_the_mapping():
    d = {"id": "lumi-night-shift", "shots": [
        {"beat": "Cold open", "keeper": "v4", "versions": [{"id": "v4", "poster_url": "/api/file?path=old_cat.jpg"}]},
        {"beat": "Real coffee", "keeper": "v5", "versions": [{"id": "v5", "poster_url": "/api/file?path=elf_ears.jpg"}]},
        {"beat": "Doors chime", "keeper": None, "versions": []}],
        "locations": [{"name": "Konbini interior", "image_url": "/api/file?path=v8b_redbook.png", "sheet_url": "/api/file?path=v5.jpg", "angles": [
            {"name": "window side", "image_url": "/api/file?path=a.png"}, {"name": "back shelves", "image_url": "/api/file?path=b.png"},
            {"name": "not made yet", "image_url": None}]}]}
    demo_images.apply_project(d)
    a, b, c = d["shots"]
    k = next(v for v in a["versions"] if v["id"] == a["keeper"])
    assert not k["card_url"] and k["card_blank"] and k["card_placeholder"]  # the labelled "No take yet" tile
    assert b["versions"][0]["poster_url"] is None and b["versions"][0]["card_blank"] and b["versions"][0]["unapproved"]
    assert a["versions"][-1]["unapproved"] and a["versions"][-1]["video_url"] is None  # the stored v4 is kept, hidden
    assert "keeper_poster_url" not in c
    loc = d["locations"][0]
    # the konbini stage plate descends from closed-generator concepts: neutral placeholders until the rebuild
    assert loc["image_url"] == "/assets/demo_audited/placeholder_stage.jpg" and loc["placeholder"]
    assert loc["sheet_url"] == "/assets/demo_audited/placeholder_stage.jpg" and loc["status"] == "Plate being rebuilt"
    assert [x["image_url"] for x in loc["angles"]] == ["/assets/demo_audited/placeholder_frame.svg",
                                                        "/assets/demo_audited/placeholder_frame.svg", None]
    other = {"id": "my-story", "shots": [{"beat": "Cold open", "keeper": "v1", "versions": [{"id": "v1", "poster_url": "/x.jpg"}]}]}
    assert demo_images.apply_project(other)["shots"][0]["versions"][0]["poster_url"] == "/x.jpg"  # only the demo story


def test_header_counts_are_true_and_previews_never_show_their_text():
    head = JS[JS.index("function render() {"):JS.index("const empty = p.shots.length === 0;")]
    # P1-01: one keeper count (Preview takes are keepers too, and say so), never "0 keepers" next to "✓ Keeper"
    assert "!k.placeholder && !k.missing" in head and 'plural(kept.length, "keeper")' in head and "from Preview mode" in head
    assert 'k && k.placeholder && !k.card_audited && !isSample(k) ? `<div class="sb-thumb blank"' in JS


def test_shot_row_has_fade_and_scroll_arrows():
    html = (ROOT / "app/web/index.html").read_text()
    assert 'id="sbStripR"' in html and 'id="sbStripL"' in html and "function stripArrows()" in JS
    css = (ROOT / "app/web/static/storyboard.css").read_text()
    assert ".sb-strip.more-right" in css and ".sb-strip-arrow" in css


@requires_demo_asset()
def test_approved_takes_allow_list_keeps_data_and_shows_listed_takes():
    cfg = {"projects": {"lumi-night-shift": {"approved_takes": {"Ending": ["v9"]}}}}
    d = {"id": "lumi-night-shift", "shots": [{"beat": "Ending", "keeper": "v9", "versions": [
        {"id": "v4", "poster_url": "/p4.jpg", "video_url": "/v4.mp4"}, {"id": "v9", "poster_url": "/p9.jpg", "video_url": "/v9.mp4"}]}]}
    demo_images.apply_project(d, cfg)
    v4, v9 = d["shots"][0]["versions"]
    assert len(d["shots"][0]["versions"]) == 2  # nothing is dropped
    assert v4["unapproved"] and v4["video_url"] is None and not v9.get("unapproved") and v9["video_url"] == "/v9.mp4"
    assert v9["card_url"] == "/p9.jpg" and not v9["card_blank"]
    shipped = CFG["projects"]["lumi-night-shift"]["approved_takes"]
    assert shipped == {"Cold open": []}  # Shot 1's v8f take is paused until the open-model rebuild (closed lineage)
    paused = CFG["projects"]["lumi-night-shift"]["approved_takes_paused"]["Cold open"]
    assert paused[0]["id"] == "v8f" and (ROOT / paused[0]["video"]).is_file()  # kept on disk, not served


def test_ui_shows_no_approved_take_states():
    uni = (ROOT / "app/web/static/unified.js").read_text()
    assert "No approved take yet" in JS and "v.unapproved" in JS and "No approved take yet" in uni
    assert "real && real.card_blank ? null : real" in JS  # blank keeper -> the plain 'No take yet' card
    assert 'class="uf-ph-tag">Placeholder<' in uni and "fr.still" in uni


@requires_demo_asset()
def test_talking_still_is_recorded_but_not_wired():
    t = CFG["talking_lumi"]
    assert t["wired"] is False and t["placeholder"] and "placeholder_" in t["card"] and "lumi_talk_l04" in t["replaced"]
    assert (ROOT / t["card"]).is_file()
    web = "".join((ROOT / "app/web/static" / f).read_text() for f in ("unified.js", "storyboard.js", "app.js", "tiles.js"))
    assert "lumi_talk" not in web and "talking_lumi" not in (ROOT / "opensoul/demo_images.py").read_text()


@requires_demo_asset()
def test_first_run_still_reaches_bootstrap(monkeypatch):
    fr = _client(monkeypatch).get("/api/bootstrap").json()["first_run"]
    assert fr["still"]["image_url"] == "/assets/demo_audited/placeholder_shot.jpg"  # a clapper, not a person


def test_export_skips_unapproved_demo_keepers():
    plan = {"project": "lumi-night-shift", "items": [{"index": 1, "shot_id": "a", "beat": "Cold open", "take": "v4", "placeholder": False},
                                                     {"index": 2, "shot_id": "b", "beat": "Ending", "take": "v9", "placeholder": False}], "skipped": []}
    cfg = {"projects": {"lumi-night-shift": {"approved_takes": {"Ending": ["v9"]}}}}
    out = demo_images.filter_export_plan(plan, cfg)
    assert [i["take"] for i in out["items"]] == ["v9"] and out["skipped"][0]["reason"] == "no approved take yet"
    other = {"project": "my-story", "items": [{"index": 1, "shot_id": "a", "beat": "x", "take": "v1", "placeholder": False}], "skipped": []}
    assert len(demo_images.filter_export_plan(other, cfg)["items"]) == 1


def test_unapproved_keeper_gets_no_keeper_mark():
    assert "v.id === s.keeper && v.unapproved" in JS and "Keeper (pending review)" in JS
    assert "v.id === s.keeper && !v.unapproved ? '<span class=\"sb-badge\">Keeper</span>'" in JS
    assert 'v.id === s.keeper && !v.unapproved ? `<span class="sb-pill right keeper">Keeper</span>`' in JS


def test_length_copy_matches_the_move_count():
    assert "Final: at least 5 s, so both moves have room." in JS and "Draft lengthened to 5 s, so both moves have room." in JS
    assert "moves.length > 2 ? `Final: at least 7 s, so all ${moves.length} moves have room.`" in JS  # 'all N' only for 3


def test_greyed_tiles_have_no_tooltip_over_the_hint_line():
    tiles = (ROOT / "app/web/static/tiles.js").read_text()
    assert '${why ? "" : `title="${esc(p.blurb || "")}"`}' in tiles and 'title="${esc(why' not in tiles


def test_shot_titles_wrap_to_two_lines_with_a_full_name_tooltip():
    css = (ROOT / "app/web/static/storyboard.css").read_text()
    uni = (ROOT / "app/web/static/unified.js").read_text()
    reel = css.split(".sb-reel-b {")[1].split("}")[0]
    assert "-webkit-line-clamp: 2" in reel and "nowrap" not in reel
    assert '<p class="sb-reel-b" title="${esc(s.beat)}">' in JS and 'title="${esc(s.beat)}" maxlength="120"' in JS
    assert uni.count('<strong title="${esc(s.beat)}">') == 2


SHIP = {"projects": {"lumi-night-shift": {"approved_takes": {"Cold open": [
    {"id": "v8f", "video": "assets/demo_audited/shot01_doodling_v8f.mp4", "poster": "assets/demo_audited/shot01_cold_open_v8f_f28.jpg"}]}}}}


@requires_demo_asset()
def test_a_shipped_approved_take_comes_first_and_stands_in_as_keeper(monkeypatch):
    monkeypatch.setattr(demo_images, "_stand_in", lambda rel, kind: None)  # a future rebuilt take (the v8f file is only a fixture)
    d = {"id": "lumi-night-shift", "shots": [
        {"beat": "Cold open", "keeper": "v4", "versions": [{"id": "v4", "poster_url": "/p4.jpg", "video_url": "/v4.mp4"}]},
        {"beat": "Ending", "keeper": "v2", "versions": [{"id": "v2", "poster_url": "/p2.jpg", "video_url": "/v2.mp4"}]}]}
    demo_images.apply_project(d, SHIP)
    a, b = d["shots"]
    assert [v["id"] for v in a["versions"]] == ["v8f", "v4"] and a["keeper"] == "v8f" and a["stored_keeper"] == "v4"
    v = a["versions"][0]
    assert v["video_url"] == "/assets/demo_audited/shot01_doodling_v8f.mp4" and v["shipped"] and not v.get("unapproved")
    assert v["settings"]["quality"] == "final" and v["status"] == "ready"
    assert a["versions"][1]["unapproved"] and a["versions"][1]["video_url"] is None  # kept, hidden
    assert b["keeper"] == "v2" and b["versions"][0]["unapproved"]  # other shots: still no approved take


@requires_demo_asset()
def test_export_uses_a_shipped_take_that_may_be_exported_and_skips_the_rest(monkeypatch):
    monkeypatch.setattr(demo_images, "_no_export", lambda path: False)  # a future shipped take outside the deny list
    monkeypatch.setattr(demo_images, "_stand_in", lambda rel, kind: None)
    ship = SHIP
    plan = {"project": "lumi-night-shift", "skipped": [{"index": 3, "shot_id": "c", "beat": "Canned coffee", "reason": "no keeper take yet"}],
            "items": [{"index": 1, "shot_id": "a", "beat": "Cold open", "take": "v4", "placeholder": False, "source": "data/x.mp4"},
                      {"index": 2, "shot_id": "b", "beat": "Ending", "take": "v2", "placeholder": False, "source": "data/y.mp4"}]}
    out = demo_images.filter_export_plan(plan, ship)
    assert [(i["index"], i["take"], i["source"]) for i in out["items"]] == [(1, "v8f", "assets/demo_audited/shot01_doodling_v8f.mp4")]
    assert [(x["index"], x["reason"]) for x in out["skipped"]] == [(2, "no approved take yet"), (3, "no keeper take yet")]


@requires_demo_asset()
def test_export_leaves_the_v8f_demo_preview_out():
    plan = {"project": "lumi-night-shift", "skipped": [{"index": 3, "shot_id": "c", "beat": "Canned coffee", "reason": "no keeper take yet"}],
            "items": [{"index": 1, "shot_id": "a", "beat": "Cold open", "take": "v4", "placeholder": False, "source": "data/x.mp4"},
                      {"index": 2, "shot_id": "b", "beat": "Ending", "take": "v2", "placeholder": False, "source": "data/y.mp4"}]}
    out = demo_images.filter_export_plan(plan, SHIP)
    assert out["items"] == [] and not out["placeholder"]
    # The old-design v8f take is no longer offered at all (demo_images.url() serves nothing for it), so shot 1 has no take.
    assert [(x["index"], x["reason"]) for x in out["skipped"]] == [
        (1, "no approved take yet"), (2, "no approved take yet"), (3, "no keeper take yet")]
    assert demo_images.url(SHIP["projects"]["lumi-night-shift"]["approved_takes"]["Cold open"][0]["video"]) is None


def test_shipped_take_is_never_sent_back_to_the_server_as_a_take():
    assert "v && !v.shipped ? v.id : null" in JS  # regenerate starts from the shot, not the shipped take
    assert '${v && !v.shipped ? `<button class="btn btn-sm-sb btn-danger-sb" id="sbDelTake"' in JS  # no Delete for it
    assert "!v.shipped" in JS.split("sbStageFromTake")[0][-400:]


def test_review_and_export_copy_for_the_approved_take():
    uni = (ROOT / "app/web/static/unified.js").read_text()
    assert 'q(v) === "final" && SB().kindLabel(v) !== "Final" ? " · Final"' in uni  # no "Final · Final"
    assert 'without ${unapproved ? "an approved" : "a"} keeper' in JS


def test_all_four_lumi_stills_are_v8f_and_never_the_v5b_remux():
    for slot, rel, meta in _all_entries():
        assert "v8f_v5b" not in (meta.get("source") or "") + rel, slot
    cold = CFG["projects"]["lumi-night-shift"]["shot_cards"]["Cold open"]
    assert cold["placeholder"] and "placeholder_" in cold["card"] and "_v8f_" in cold["replaced"]
    assert CFG["projects"]["lumi-night-shift"]["approved_takes"]["Cold open"] == []  # v8f paused, kept on disk
    assert CFG["projects"]["lumi-night-shift"]["approved_takes_paused"]["Cold open"][0]["id"] == "v8f"
    # the live app's Lumi card, first-run still and tile still are neutral placeholders (closed-generator lineage)
    for e in (CFG["cast"]["lumi"], CFG["tile_still"], CFG["first_run_still"]):
        rel = e.get("card") or e.get("image")
        assert e["placeholder"] and "placeholder_" in rel and "_v8" not in rel, rel
    assert "v8f_v5b" not in json.dumps(CFG["projects"]["lumi-night-shift"]["approved_takes"])


def test_only_pre_audit_takes_and_concepts_are_hidden():
    cfg = {"projects": {"lumi-night-shift": {"approved_takes": {}, "hide_takes_before": "2026-10-18T22:31:00-04:00"}}}
    d = {"id": "lumi-night-shift", "shots": [{"beat": "Ending", "keeper": "v9", "versions": [
        {"id": "v4", "kind": "render", "created": "2026-10-18T04:44:12+00:00", "video_url": "/old.mp4"},
        {"id": "v5", "kind": "concept", "created": "2026-10-19T09:00:00+00:00", "poster_url": "/cat.jpg"},
        {"id": "v9", "kind": "render", "created": "2026-10-19T09:00:00+00:00", "video_url": "/new.mp4"}]}]}
    demo_images.apply_project(d, cfg)
    v4, v5, v9 = d["shots"][0]["versions"]
    assert v4["unapproved"] and v5["unapproved"] and not v9.get("unapproved") and v9["video_url"] == "/new.mp4"
    plan = {"project": "lumi-night-shift", "skipped": [], "items": [
        {"index": 1, "shot_id": "a", "beat": "Ending", "take": "v4", "placeholder": False},
        {"index": 2, "shot_id": "b", "beat": "Ending", "take": "v9", "placeholder": False}]}
    vers = {("a", "v4"): {"kind": "render", "created": "2026-10-18T04:44:12+00:00"}, ("b", "v9"): {"kind": "render", "created": "2026-10-19T09:00:00+00:00"}}
    assert [i["take"] for i in demo_images.filter_export_plan(plan, cfg, vers)["items"]] == ["v9"]


def test_demo_shot_descriptions_match_the_script_and_user_edits_win():
    t = CFG["projects"]["lumi-night-shift"]["shot_text"]
    assert len(t) == 8
    for beat, e in t.items():
        low = e["prompt"].lower()
        assert not any(w in low for w in ("cat ", "ginger", "ancient", "kettle", "elf", " book")), beat
        assert "SCRIPT_v3.md" in e["source"] and e["replaces"], beat
    old = t["Cold open"]["replaces"][0]
    assert demo_images.shot_text("lumi-night-shift", "Cold open", old) == t["Cold open"]["prompt"]
    assert demo_images.shot_text("lumi-night-shift", "Cold open", "My own words.") == "My own words."
    assert demo_images.shot_text("other-story", "Cold open", old) == old


def test_demo_can_is_a_plain_slim_steel_can_and_the_glance_stays():
    t = CFG["projects"]["lumi-night-shift"]["shot_text"]
    s3, s5 = t["Canned coffee"]["prompt"], t["Sip and freeze"]["prompt"]
    assert s5.endswith("Lumi glances at the plain slim steel can. Says nothing.")  # SCRIPT_v3 §7 payoff
    for s in (s3, s5):
        for m in re.finditer(r"\bcans?\b", s):
            assert s[:m.end()].endswith("plain slim steel can"), s
    assert "no colors, no logos" in s3 and "eyes off camera" in s3
    for beat, e in t.items():  # the can never gets a color, brand or the old 'canned coffee' wording
        assert not re.search(r"canned coffee|maroon|red can|blue can|logo(?!s\))", e["prompt"], re.I), beat
    # old overlay wording still gets swapped
    assert demo_images.shot_text("lumi-night-shift", "Sip and freeze", "Mio and Ren lean in, suspicious, and sip. Their eyes go wide.") == s5


def test_hidden_takes_carry_no_old_wording():
    d = {"id": "lumi-night-shift", "shots": [{"beat": "Ending", "keeper": "v4", "prompt": "x", "versions": [
        {"id": "v4", "kind": "render", "created": "2026-10-18T04:44:12+00:00", "prompt": "the elf woman and the cat", "edit": "cat looks up", "note": "ancient book",
         "settings": {"quality": "draft", "job": {"stages": [{"inputs": {"20": {"text": "pointed elf ears"}}}]}}}]}]}
    demo_images.apply_project(d)
    v = d["shots"][0]["versions"][0]
    assert v["unapproved"] and v["prompt"] == v["edit"] == "" and "book" not in v["note"]
    assert v["settings"] == {"quality": "draft"}  # no job inputs (prompt locks) for a hidden take
    assert "!v.unapproved && v.kind !== \"concept\"" in JS  # no 'Render v4 in Final' for a hidden take


def test_review_tiles_are_16_9_for_16_9_stories():
    css = (ROOT / "app/web/static/storyboard.css").read_text()
    uni = (ROOT / "app/web/static/unified.js").read_text()
    assert 'uf-rv-takes${p.aspect === "9:16" ? "" : " wide"}' in uni and ".uf-rv-takes.wide video, .uf-rv-takes.wide img { aspect-ratio: 16 / 9" in css


def test_without_the_v8f_file_a_release_simply_has_no_shipped_take(monkeypatch):
    monkeypatch.setattr(demo_images, "url", lambda rel: None)  # release archive: the file is export-ignored
    plan = {"project": "lumi-night-shift", "skipped": [], "items": [
        {"index": 1, "shot_id": "a", "beat": "Cold open", "take": "v4", "placeholder": False, "source": "data/x.mp4"}]}
    out = demo_images.filter_export_plan(plan, SHIP)
    assert out["items"] == [] and [(x["index"], x["reason"]) for x in out["skipped"]] == [(1, "no approved take yet")]


def test_export_tab_and_api_say_the_demo_preview_is_not_exported():
    api = (ROOT / "app/storyboard_api.py").read_text()
    assert "The demo's Shot 1 take is a preview that stays in the app, so there's nothing to export yet." in api
    assert "aren't exported." in api
    assert "The demo’s Shot 1 take is a preview. It plays in the app, but the export skips it." in JS
    assert "Skipped · ${why}" in JS  # one status for every skipped shot (no approved take / no keeper)
