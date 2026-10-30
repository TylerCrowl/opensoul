"""Create after the v3 visual review: old Lumi/Mio/Ren pictures never show as current, Look and Outfit are kept
apart, a big change under a saved name says it's a new look, a photo start needs a photo, and a fresh profile lands
on Describe."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "app/web"


@pytest.fixture()
def srv(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    monkeypatch.setenv("OPENSOUL_SHEET_SYNC", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    return TestClient(server.app), server, tmp_path


def _pack(root, folder, meta=None):
    d = root / "packs" / folder
    (d / "refs").mkdir(parents=True)
    (d / "refs" / "ref_00.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (d / "pack.json").write_text(json.dumps({"name": folder.split("_")[0], "prompt_lock": "old words", "ref_images": [str(d / "refs/ref_00.png")], "meta": meta or {}}))
    return d


def test_old_designs_show_the_card_picture(srv):
    _c, server, tmp = srv
    from opensoul.demo_images import cast_card, pre_rebuild_name

    for rel, who in (("assets/lumi/lumi_character_sheet_v1.jpg", "lumi"), ("assets/mio/mio_ref_00.jpg", "mio"),
                     ("assets/ren/ren_character_sheet_v1.jpg", "ren")):
        assert pre_rebuild_name(ROOT / rel, tmp) == who
        assert server._file_url(ROOT / rel) == cast_card(who)["card_url"]
    old = _pack(tmp, "Lumi_3")
    assert server._file_url(old / "refs/ref_00.png") == cast_card("lumi")["card_url"]
    new = _pack(tmp, "Lumi_4", {"origin": {"kind": "text"}})  # a Lumi made from words now is current
    assert server._file_url(new / "refs/ref_00.png").startswith("/api/file?path=")
    other = _pack(tmp, "Kai")
    assert server._file_url(other / "refs/ref_00.png").startswith("/api/file?path=")
    assert pre_rebuild_name(ROOT / "assets/demo_audited/placeholder_mio.svg", tmp) is None


def test_hide_list_is_logged_in_the_swap_list():
    cfg = json.loads((ROOT / "presets/demo_images.json").read_text())["pre_rebuild_hide"]
    assert set(cfg["pack_names"]) == {"lumi", "mio", "ren"} and "assets/mio" in cfg["dirs"]


def test_look_and_outfit_are_saved_apart_and_come_back(srv):
    c, server, tmp = srv
    r = c.post("/api/character", data={"name": "Kai", "prompt_lock": "a tall courier, wearing a teal raincoat",
                                       "look": "a tall courier", "outfit": "a teal raincoat"})
    assert r.status_code == 200, r.text
    meta = json.loads((Path(r.json()["pack_dir"]) / "pack.json").read_text())["meta"]
    assert meta["fields"] == {"look": "a tall courier", "outfit": "a teal raincoat"}
    lib = c.get("/api/look", params={"name": "Kai"}).json()["library"]
    assert lib["fields"]["look"] == "a tall courier" and lib["fields"]["outfit"] == "a teal raincoat"
    _pack(tmp, "Old")  # an older pack: no fields, its whole description goes in Look
    assert c.get("/api/look", params={"name": "Old"}).json()["library"]["fields"] is None


def test_create_page_copy_and_wiring():
    html, js = (WEB / "index.html").read_text(), (WEB / "static/app.js").read_text()
    uj = (WEB / "static/unified.js").read_text()
    assert '"Included above"' in js and "f ? f.look : lib.prompt_lock" in js
    assert 'if ($("mOutfit").placeholder === "Included above") $("mOutfit").placeholder = OUTFIT_HINT;' in js
    assert "`Placeholder: we are rebuilding ${name}`" in js and "is a placeholder until we rebuild ${who}" in js
    assert 'id="newLookNote"' in html and 'id="newLookName"' in html and "New look for ${n}; your saved ${n} stays." in js
    assert "is one of your saved characters: their description is filled in" not in js  # the blue box says it once
    assert "Start a new version instead" in html
    assert "(optional)" not in html.split('id="photoField"')[1].split("</div>")[0]
    assert html.count("Add a photo to start") + js.count("Add a photo to start") == 1  # once: the hint under the button
    assert 'id="fileName">No photo chosen<' in html and 'id="toDescribe"' in html and "No photo? Describe your character instead" in html
    assert 'return "Add a photo to start."' in js
    assert 'id="masterProgress"' in html and 'id="btnMasterStop"' in html.split('id="masterProgress"')[1].split("</div>")[0]
    assert "Stopped. Showing your last master (seed ${state.stopped.seed})." in js
    css = (WEB / "static/app.css").read_text()
    assert ".uf-badge { white-space: nowrap; }" in css
    rule = css.split(".master-progress {")[1].split("}")[0]  # fully opaque over the whole preview: no name card shows through
    assert "background: var(--bg)" in rule and "rgb" not in rule  # --bg is opaque in both themes (tests/test_theme_tokens.py)
    assert "function fitMasterProgress()" in js and 'height: `${box.offsetHeight}px`' in js  # exactly the preview card's box
    assert 'return `Drawing ${esc(charName())}’s master…`' in js  # the intro while a master is drawing
    assert 'fd.append("master_id", state.master.id)' in js
    for f in ("index.html", "static/app.js", "static/unified.js", "static/storyboard.js"):
        assert "studio computer" not in (WEB / f).read_text(), f
    assert 'id="ufDescribe"' in html and 'localStorage.getItem("os_landed")' in uj and "CR().newCharacter()" in uj
    assert all(o in html for o in (">Photo<", ">Film still<", ">Editorial<"))


def test_preview_sheet_line():
    import app.server as server

    assert server.PREVIEW_SHEET_LINE == "Preview mode: stand-in angles. Real angles are drawn and checked against the master when a studio is set up."


def test_sheet_is_built_from_the_master_that_is_showing(srv):
    c, server, tmp = srv
    ids = []
    for seed in (7, 8):
        r = c.post("/api/master", data={"name": "Kai", "look": "a tall courier with copper hair", "outfit": "a teal raincoat", "seed": seed})
        assert r.status_code == 200, r.text
        ids.append(r.json()["master_id"])
    first = tmp / "outputs/masters" / ids[0] / "master.png"
    r = c.post("/api/sheet", data={"name": "Kai", "prompt_lock": "x", "master_id": ids[0]})
    assert r.status_code == 200, r.text
    pack = Path(r.json()["pack_dir"])
    assert server._md5(pack / "refs/ref_00.png") == server._md5(first)
    r2 = c.post("/api/sheet", data={"name": "Kai", "prompt_lock": "x", "master_id": ids[1], "pack_dir": str(pack)})
    if server._md5(tmp / "outputs/masters" / ids[1] / "master.png") != server._md5(first):
        assert r2.status_code == 409


def test_look_flags_a_pre_rebuild_placeholder(srv):
    c, _server, tmp = srv
    _pack(tmp, "Mio")
    r = c.get("/api/look", params={"name": "Mio"}).json()
    assert r["placeholder"] is bool(r["still_url"] or r["sheet_url"])  # whatever picture shows for Mio is the placeholder
    if r["sheet_url"] or r["still_url"]:
        assert "placeholder_mio" in (r["sheet_url"] or r["still_url"])
    _pack(tmp, "Kai")
    assert c.get("/api/look", params={"name": "Kai"}).json()["placeholder"] is False
