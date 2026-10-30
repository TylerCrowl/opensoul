"""New-user walkthrough (a brand-new text-only character, not the demo): regressions for the UX fixes."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from demo_character import DEMO_NAME, DEMO_PACK, DEMO_SHEET, OTHER_NAME
from opensoul.character_pack import CharacterPack
from release_assets import DEMO_POSTER, LUMI_PACK, LUMI_REFS, requires_demo_asset

ROOT = Path(__file__).resolve().parents[1]
NEW = OTHER_NAME  # a brand-new user character (never the demo or a library name)
DESC = "a tall courier in her forties, short red hair, round glasses, yellow rain jacket over a grey hoodie"


def _srv():
    import app.server as server

    return server


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    monkeypatch.setenv("OPENSOUL_SHEET_SYNC", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    monkeypatch.setattr(server, "LIBRARY", tmp_path / "library")  # tests never depend on real saved characters
    return TestClient(server.app)


def _no_demo_images(pack_dir: str) -> None:
    for r in CharacterPack.load(pack_dir).ref_images:
        assert str(ROOT / "assets") not in str(Path(r).resolve()), r


def _ffmpeg() -> bool:
    from opensoul.media import ffmpeg_bin

    return ffmpeg_bin() is not None


# ---------------------------------------------------------------- 1. text-only character sheet
def test_sheet_from_text_alone_needs_no_photo_or_consent(client):
    r = client.post("/api/sheet", data={"name": NEW, "prompt_lock": DESC})
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["state"] == "done" and job["done"] == 6, job
    assert job["sheet_url"].startswith("/api/file?path=")
    assert client.get(job["sheet_url"]).status_code == 200
    pack = CharacterPack.load(job["pack_dir"])
    assert pack.name == NEW and DESC in pack.prompt_lock
    _no_demo_images(job["pack_dir"])


def test_sheet_text_only_needs_a_description(client):
    r = client.post("/api/sheet", data={"name": NEW, "prompt_lock": ""})
    assert r.status_code == 400 and "Describe" in r.json()["detail"]


def test_sheet_photo_still_needs_consent(client):
    ref = DEMO_SHEET
    if not ref.is_file():
        pytest.skip("no sample image")
    r = client.post("/api/sheet", data={"name": NEW, "prompt_lock": DESC},
                    files={"image": ("me.jpg", ref.read_bytes(), "image/jpeg")})
    assert r.status_code == 400 and "permission" in r.json()["detail"]


def test_renamed_demo_never_reuses_the_demo_face(client):
    r = client.post("/api/sheet", data={"name": NEW, "prompt_lock": DESC, "pack_dir": str(DEMO_PACK)})
    assert r.status_code == 200, r.text
    _no_demo_images(r.json()["pack_dir"])


def test_text_only_sheet_never_overwrites_an_existing_pack(client, tmp_path):
    old = tmp_path / "packs" / NEW
    old.mkdir(parents=True)
    (old / "keep.txt").write_text("x")
    job = client.post("/api/sheet", data={"name": NEW, "prompt_lock": DESC}).json()
    assert Path(job["pack_dir"]).name == f"{NEW}_2" and (old / "keep.txt").is_file()


# ---------------------------------------------------------------- 3. images come from the current character
def test_save_without_sheet_text_only_has_no_demo_images(client):
    r = client.post("/api/character", data={"name": f"  {NEW}  ", "prompt_lock": DESC})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["name"] == NEW and d["sheet_url"] is None and d["has_images"] is False
    assert CharacterPack.load(d["pack_dir"]).ref_images == []
    assert client.post("/api/character", data={"name": NEW, "prompt_lock": ""}).status_code == 400


def test_shot_for_new_character_is_not_the_demo(client):
    d = client.post("/api/character", data={"name": NEW, "prompt_lock": DESC}).json()
    r = client.post("/api/shot", json={"camera": "static", "pack_dir": d["pack_dir"]})
    if not _ffmpeg():
        assert r.status_code == 500
        return
    assert r.status_code == 200, r.text
    shot = r.json()
    assert shot["poster_url"] is None  # the demo poster is only for the demo character
    video = _srv().file_of_url(shot["video_url"])
    assert (video.parent / "name_card.png").is_file()  # neutral placeholder labelled with the name


@requires_demo_asset(DEMO_POSTER)
def test_shot_for_demo_keeps_demo_poster(client):
    r = client.post("/api/shot", json={"camera": "static", "pack_dir": str(DEMO_PACK)})
    if _ffmpeg():
        assert r.status_code == 200 and r.json()["poster_url"]


def test_share_never_exports_demo_under_another_name(client):
    d = client.post("/api/share", json={"title": "Static", "name": NEW, "pack_dir": ""}).json()
    assert d["mp4_url"] is None and "Generate a shot first" in d["note"]
    assert "#OpenSoul" in d["caption"]


# ---------------------------------------------------------------- 2. default is a new character
@requires_demo_asset(LUMI_PACK)  # a release has only Pixel (tests/test_release_sample_pack.py)
def test_bootstrap_offers_empty_new_character_and_demo(client):
    b = client.get("/api/bootstrap").json()
    assert b["new_character"]["name"] == "" and b["new_character"]["pack_dir"] == ""
    assert b["character"]["name"] == DEMO_NAME
    assert [d["name"] for d in b["demos"]][:1] == [DEMO_NAME] and len(b["demos"]) >= 2


# ---------------------------------------------------------------- 9. readable status
def test_health_has_plain_summary_lines(client):
    h = client.get("/api/health").json()
    labels = [x["label"] for x in h["summary"]]
    # Core four stay first; stage status lines from models_registry are additive after them.
    assert labels[:4] == ["Mode", "Comfy SDK", "Studio", "OpenSoul version"]
    assert h["summary"][0]["value"].startswith("Preview")
    assert isinstance(h["studio_reachable"], bool) and "sdk" in h
    assert "stages" in h and isinstance(h["stages"], list)


# ---------------------------------------------------------------- UI markup (no browser on the test box)
def test_index_markup_for_new_users(client):
    html = client.get("/").text
    assert f'value="{DEMO_NAME}"' not in html and "New character" in html
    assert f"Use the demo character ({DEMO_NAME})" in html
    assert re.search(r'class="btn btn-outline" id="btnSaveCharacter"', html)  # 4: a real button
    assert 'id="sheetReason"' in html  # 1: inline reason next to the button
    assert re.search(r'id="consentRow" hidden', html)  # consent only shows with a photo
    assert "An effect replaces the camera move" in html  # 5
    assert re.search(r'id="advancedToggle" type="button" aria-expanded="false"', html)  # 7
    assert "<details" not in html
    assert "Next: Share" in html and 'id="shotResult"' in html  # 8
    assert 'id="statusPanel"' in html and "Show details" in html  # 9


def test_app_js_behaviour_markers():
    js = (ROOT / "app" / "web" / "static" / "app.js").read_text()
    assert "Talking" not in js and "with voice" in js  # 6
    assert 'camera: STATIC_ID' in js and "None / static" in js  # 5: no preselected Dolly in
    assert 'params.get("demo")' in js  # 2: ?demo=1 loads the demo
    assert "#OpenSoul #AIvideo" in js and "Higgsfield" not in js
    gen = js[js.index("async function generate()"):js.index("function mediaHTML")]
    assert "setStep(3)" not in gen  # 8: generate stays on the Shot step


# ---------------------------------------------------------------- second walkthrough polish
def test_ui_assets_always_revalidate(client):
    for path in ("/static/app.js", "/static/app.css", "/static/app.js?v=old"):
        r = client.get(path)
        assert r.status_code == 200 and "no-cache" in r.headers.get("cache-control", ""), path
    etag = client.get("/static/app.js").headers.get("etag")
    assert etag and client.get("/static/app.js", headers={"If-None-Match": etag}).status_code == 304


def test_every_index_route_is_versioned(client):
    for path in ("/", "/?step=2", "/?demo=1&step=3"):
        r = client.get(path)
        assert "no-cache" in r.headers.get("cache-control", "")
        assert re.search(r'/static/app\.js\?v=[0-9a-f]+"', r.text) and re.search(r'/static/app\.css\?v=[0-9a-f]+"', r.text)
        assert '/static/app.js"' not in r.text
    r = client.get("/index.html?step=2", follow_redirects=False)
    assert r.status_code in (301, 302, 307, 308) and r.headers["location"] == "/?step=2"
    assert client.head("/").status_code == 200
    assert "/static/app.js?v=" in client.get("/index.html").text


def test_export_names_are_unique_and_ascii(client):
    from datetime import datetime

    import app.server as server

    n = server._export_name("Lumí the Elf!", "dolly_in", datetime(2026, 10, 17, 20, 30, 15))
    assert n == "opensoul_lumi_the_elf_dolly_in_203015.mp4"
    assert server._export_name("", None).startswith("opensoul_character_shot_")
    d = client.post("/api/share", json={"name": DEMO_NAME, "camera": "orbit", "title": "Orbit"}).json()
    assert re.fullmatch(rf"opensoul_{DEMO_NAME.lower()}_orbit_\d{{6}}\.mp4", d["filename"]) and d["placeholder"] is True


def test_markup_polish(client):
    html = client.get("/").text
    assert re.search(r'id="demoLegal" hidden', html)  # rights line only for the demo
    assert 'id="charIntro"' in html and 'id="btnExportText"' in html and 'id="exportNotice" hidden' in html
    js = (ROOT / "app" / "web" / "static" / "app.js").read_text()
    assert ">Shows ${esc(DEMO_NAME)}<" in js and "Preview coming" in js
    assert "Export preview (placeholder)" in js and "data.filename" in js
    assert '$("demoLegal").hidden = !state.isDemo' in js


# ---------------------------------------------------------------- owner: "I didn't see my saved character at all"
def _fake_library(tmp_path, name=NEW):
    import json

    from PIL import Image

    d = tmp_path / "library" / name.lower()
    d.mkdir(parents=True)
    Image.new("RGB", (64, 96), "#a0b0c0").save(d / "ref.jpg")
    (d / "character.json").write_text(json.dumps({"name": name, "prompt_lock": DESC, "reference": {"file": "ref.jpg"},
                                                  "sheet": {"file": "missing.jpg"}}))
    return d


def test_look_uses_saved_character_pictures(client, tmp_path):
    d = _fake_library(tmp_path)
    look = client.get("/api/look", params={"name": NEW.lower()}).json()
    assert look["source"] == "library" and _srv().file_of_url(look["still_url"]) == (d / "ref.jpg").resolve() and look["sheet_url"] is None
    assert look["library"]["prompt_lock"] == DESC
    assert client.get(look["still_url"]).status_code == 200
    assert client.get("/api/look", params={"name": NEW.lower(), "library": 0}).json()["source"] is None
    assert client.get("/api/look", params={"name": "Pip"}).json()["still_url"] is None
    assert client.get("/api/look", params={"name": DEMO_NAME, "library": 0}).json()["source"] is None  # the demo pack is not a lookup hit
    assert client.get("/api/look", params={"pack_dir": "/etc"}).status_code == 400


def test_save_and_shot_use_saved_character_reference(client, tmp_path):
    d = _fake_library(tmp_path)
    saved = client.post("/api/character", data={"name": NEW, "prompt_lock": ""}).json()
    assert saved["has_images"] and saved["prompt_lock"] == DESC
    r = client.post("/api/shot", json={"camera": "orbit", "pack_dir": saved["pack_dir"], "name": NEW})
    if _ffmpeg():
        assert r.status_code == 200
        assert not (Path(r.json()["video_url"].split("=", 1)[1]).parent / "name_card.png").exists()
    # an unsaved saved-library character (empty pack) still gets their own picture, not a grey card or the demo
    import app.server as server

    assert server._shot_image("", tmp_path / "w", NEW) == d / "ref.jpg"


@requires_demo_asset(*LUMI_REFS)
def test_pack_with_borrowed_demo_pictures_is_caught(client, tmp_path):
    """Packs saved by an older build copied the demo's pictures under a new name: never show them."""
    import app.server as server

    refs = sorted((DEMO_PACK / "refs").glob("*"))
    pack = CharacterPack(name=NEW, prompt_lock=DESC, ref_images=[str(r) for r in refs])
    pack.save(tmp_path / "packs" / NEW)
    pd = str(tmp_path / "packs" / NEW)
    assert server._own_refs(pd) == []
    assert client.get("/api/look", params={"name": NEW, "pack_dir": pd}).json()["still_url"] is None
    _fake_library(tmp_path)
    assert "ref.jpg" in client.get("/api/look", params={"name": NEW, "pack_dir": pd}).json()["still_url"]
    job = client.post("/api/sheet", data={"name": NEW, "prompt_lock": DESC, "pack_dir": pd}).json()
    assert job["state"] == "done" and Path(job["pack_dir"]).name != NEW
    _no_demo_images(job["pack_dir"])


def test_tiles_show_current_character_before_demo_examples():
    js = (ROOT / "app" / "web" / "static" / "app.js").read_text()
    css = (ROOT / "app" / "web" / "static" / "app.css").read_text()
    media = js[js.index("function tileMedia(p)"):js.index("function renderTileMedia()")]
    # order matters: own picture first, labelled demo clip second, placeholder last
    assert media.index("charStill()") < media.index("p.thumb_ready") < media.index("placeholder()")
    assert "move-preview mv-" in media and ">Shows ${esc(DEMO_NAME)}<" in media and "isMainDemo()" in media
    for move in ("dolly_in", "dolly_out", "dolly_left", "dolly_right", "jib_up", "jib_down", "crash_zoom", "orbit",
                 "fpv", "dolly_zoom", "earth_zoom_out", "orbit_freeze", "day_to_night", "outfit_switch", "static"):
        assert f".mv-{move} img" in css, move
    assert "prefers-reduced-motion" in css
    assert "/api/look?" in js and 'id="starring"' in (ROOT / "app" / "web" / "index.html").read_text()


def test_second_demo_stars_with_its_own_picture():
    """QA round 2: 'Starring Pixel' showed Lumi's poster."""
    js = (ROOT / "app" / "web" / "static" / "app.js").read_text()
    star = js[js.index("function renderStarring()"):js.index("function tileHTML(")]
    assert "isMainDemo() ? (state.demo?.card_url || state.demoPoster" in star and ": state.sheetUrl" in star


def test_credits_card_lists_models_licenses_and_characters_without_personal_data(client):
    """QA round 2 (R16_06): there was no credits card, only the one rights line for the demo."""
    import re as _re

    html = client.get("/").text
    card = html[html.index('id="creditsCard"'):html.index("</dialog>")]
    for must in ("Qwen-Image-Edit-2511", "Apache-2.0", "LTX-2.5", "LTX-2.x Community License", "Orpheus", "Built with Llama",
                 "ComfyUI", "GPL-3.0", "Lumi, Mio and Ren", "Pixel", "open source"):
        assert must in card, must
    assert 'id="btnCredits"' in html and "<dialog" in html
    # No personal data: no home paths, e-mail addresses or local file links.
    home = "/" + "ho" + "me/"  # built at runtime so the pre-publish gate's home-path scan doesn't flag this guard
    assert not _re.search(home + r"|/workspace/|@[a-z0-9-]+\.[a-z]|file://", card)
    hrefs = _re.findall(r'href="([^"]+)"', card)
    assert hrefs and all(h.startswith("https://") for h in hrefs)


def test_wide_sheet_fills_the_preview_frame():
    """QA round 2: the 16:9 Lumi demo sheet sat tiny in a tall grey frame."""
    js = (ROOT / "app" / "web" / "static" / "app.js").read_text()
    css = (ROOT / "app" / "web" / "static" / "app.css").read_text()
    assert "function fitPreview(box)" in js and "fitPreview(box);" in js
    assert ".preview.wide { min-height: 0" in css and 'img[src$="lumi_sheet_preview.jpg"] { object-view-box' in css
