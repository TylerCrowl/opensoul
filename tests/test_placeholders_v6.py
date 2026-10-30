"""One clearly intentional placeholder system (v5 review): the person silhouette appears only where a character
portrait is expected; stages show a storefront plate icon and say "Plate being rebuilt", shots without a take all show
the same labelled "No take yet" tile, the demo frame on the start card is a film clapper, and Export uses one tile, one
status and one action. Also: Prompt strength says it isn't used for talking shots, and the plain Music stem note."""
import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "presets/demo_images.json").read_text())
SB = (ROOT / "app/web/static/storyboard.js").read_text()
PERSON = {"placeholder_lumi.svg", "placeholder_mio.svg", "placeholder_ren.svg", "placeholder_tile.jpg", "placeholder_wide.jpg"}


def _name(rel):
    return Path(rel or "").name


def _scene_slots():
    yield "first_run_still", CFG["first_run_still"]["image"]
    for pid, p in CFG["projects"].items():
        for beat, c in p.get("shot_cards", {}).items():
            yield f"{pid}/shot/{beat}", c.get("card")
        for beat, takes in {**p.get("approved_takes", {}), **{k: v for k, v in p.get("approved_takes_paused", {}).items() if isinstance(v, list)}}.items():
            for t in takes:
                if isinstance(t, dict):
                    yield f"{pid}/take/{beat}", t.get("poster")
        for loc, st in p.get("stage", {}).items():
            for k in ("master", "other_angles", "empty"):
                yield f"{pid}/stage/{loc}/{k}", st.get(k)
            yield f"{pid}/stage/{loc}/sheet", (st.get("sheet") or {}).get("image")
            for a, m in (st.get("angles") or {}).items():
                yield f"{pid}/stage/{loc}/{a}", m.get("image")


def test_stage_and_shot_slots_never_use_the_person_placeholder():
    for slot, rel in _scene_slots():
        assert _name(rel) not in PERSON, slot
    st = CFG["projects"]["lumi-night-shift"]["stage"]["Konbini interior"]
    assert _name(st["master"]) == "placeholder_stage.jpg" and st["placeholder"]
    assert _name(CFG["first_run_still"]["image"]) == "placeholder_shot.jpg"


def test_placeholder_art_is_original_and_clean():
    for n in ("placeholder_shot.jpg", "placeholder_stage.jpg"):
        im = Image.open(ROOT / "assets/demo_audited" / n)
        assert im.size == (960, 549) and not im.getexif() and "comment" not in im.info, n


def test_demo_story_cards_and_stage_read_as_intentional():
    from opensoul import demo_images

    d = {"id": "lumi-night-shift", "shots": [
        {"beat": "Cold open", "keeper": "v4", "versions": [{"id": "v4", "poster_url": "/p.jpg", "created": "2026-10-18T00:00:00-04:00"}]}],
        "locations": [{"name": "Konbini interior", "image_url": "/x.png", "sheet_url": "/y.png", "empty_url": "/z.png",
                       "angles": [{"name": "window side", "image_url": "/a.png"}]}]}
    demo_images.apply_project(d)
    k = d["shots"][0]["versions"][-1]
    assert k["card_blank"] and k["card_placeholder"] and not k["card_url"]  # the labelled "No take yet" tile
    loc = d["locations"][0]
    assert loc["status"] == "Plate being rebuilt" and loc["placeholder"]
    assert {_name(loc[k]) for k in ("image_url", "sheet_url", "empty_url")} == {"placeholder_stage.jpg"}
    assert all(_name(a["image_url"]) not in PERSON for a in loc["angles"])
    # the Stages card shows that status instead of "Ready", and the card shows no "ready" tick
    assert 'l.placeholder ? (l.status || "Rebuilding the plate")' in SB and 'l.ready && !l.placeholder ? " ready"' in SB


def test_export_uses_one_tile_one_status_one_action():
    head = SB[SB.index("function renderExport()"):SB.index("async function exportStory()")]
    assert "Skipped · ${why}" in head and '"no approved take" : "no keeper"' in head
    assert "Skipped · not approved" not in head and "demo preview, plays in the app only" not in head.split("$(\"sbReel\")")[1]
    assert '<button class="sb-link" type="button" data-open="${esc(s.id)}">Open shot</button></div></li>' in head
    assert '${k ? "" : `<button' not in head  # Open shot on every card
    # one status per card: the skipped tile is blank, only the status line says "Skipped · …"
    reel = head.split('$("sbReel")')[1]
    assert ': CLAPPER;' in reel and 'class="sb-reel-ph" aria-hidden="true"' in head  # a faint icon, no text
    assert '"No approved take"' not in reel and '"No keeper"' not in reel


def test_start_card_says_demo_frames_are_being_redrawn():
    fr = CFG["first_run_still"]
    assert fr["caption"].startswith("Demo frames are being redrawn.") and fr["placeholder"]
    origin = json.loads((ROOT / "presets/character_origin.json").read_text())["texts"]["start_caption"]["rebuild"]
    assert origin == fr["caption"]


def test_prompt_strength_says_it_is_not_used_for_talking_shots():
    html = (ROOT / "app/web/index.html").read_text()
    js = (ROOT / "app/web/static/app.js").read_text()
    assert '<span class="hint" id="advCfgNote" hidden>Not used for talking shots (except with LatentSync)</span>' in html
    fn = js[js.index("function syncCfgNote()"):js.index("function syncCfgNote()") + 400]
    assert '$("line").value.trim()' in fn and 'backend === "ltx_av"' in fn
    assert 'syncSelection(); syncCfgNote(); });' in js and '$("advLipsync").addEventListener("change", syncCfgNote);' in js
    from opensoul import lipsync as L

    assert L.DEFAULT_BACKEND == "ltx_av" and L.GUIDER_CFG == {"video_cfg": 1.0, "audio_cfg": 1.0}


def test_music_stem_note_is_plain():
    plain = "Syncing to the full song (this studio has no vocal-only track)."
    from opensoul.music import stems

    assert stems.FULL_MIX == plain  # the API note; the Music tab says it in its own words (OS-043)
    assert "This studio has no vocal-only track, so the full song drives the mouth." in (ROOT / "app/web/static/music.js").read_text()
    assert "Vocal separation needs" not in (ROOT / "app/web/static/music.js").read_text()
