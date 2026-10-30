"""Describe your character: a text-only master (no photo, no reference image of anyone) becomes the pack's ref_00,
and the sheet / angles / shots start from it. Preview mode only here: no GPU, no model runs."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opensoul import text_master as tm

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "app/web/static/app.js").read_text()
HTML = (ROOT / "app/web/index.html").read_text()
LOOK = {"name": "Quilla", "look": "a tall courier with short copper hair", "outfit": "a teal raincoat",
        "age": "26-35", "style": "natural"}


@pytest.fixture
def c(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    monkeypatch.setenv("OPENSOUL_SHEET_SYNC", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    monkeypatch.setattr(server, "LIBRARY", tmp_path / "library")
    return TestClient(server.app)


def test_fields_compose_one_look_lock_adults_and_known_styles_only():
    assert tm.compose(**{k: v for k, v in LOOK.items() if k != "name"}) == (
        "a tall courier with short copper hair, in their late twenties to early thirties, wearing a teal raincoat, "
        "natural photo look")
    assert tm.compose("  a  baker. ", "", "", "") == "a baker"
    assert tm.fields(age="12", style="vaporwave") == {"look": "", "outfit": "", "age": "", "style": ""}  # unknown: dropped
    assert tm.fields(style="anime")["style"] == "anime" and tm.compose("a baker", style="anime") == "a baker"  # OS-006
    assert all(k == "" or k[0].isdigit() and int(k.rstrip("+").split("-")[0]) >= 18 for k in tm.AGE_RANGES)
    assert tm.problem("short") and not tm.problem("a tall courier")
    for k, words in tm.AGE_RANGES.items():  # the page composes with the same words
        assert not words or f'"{words}"' in JS, k
    for k, words in tm.STYLES.items():
        assert not words or f'"{words}"' in JS, k


def test_generate_master_in_preview_needs_no_photo_or_rights_tick_and_try_another_changes_seed(c):
    a = c.post("/api/master", data={**LOOK, "seed": "7"})
    assert a.status_code == 200, a.text
    m = a.json()
    assert m["preview"] and m["seed"] == 7 and m["next_seed"] == 8 and m["label"] == "Master · variation 7 · preview"
    assert m["state"] == "done" and m["done"] and c.get(f"/api/master/{m['master_id']}").json()["state"] == "done"
    assert m["prompt_lock"] == tm.compose(LOOK["look"], LOOK["outfit"], LOOK["age"], LOOK["style"])
    assert c.get(m["url"]).status_code == 200
    b = c.post("/api/master", data={**LOOK, "seed": str(m["next_seed"])}).json()
    assert b["master_id"] != m["master_id"] and b["seed"] == 8
    assert c.get(b["url"]).content != c.get(m["url"]).content  # the seed is on the preview card


def test_master_validation_is_a_clear_400_never_a_500(c):
    assert c.post("/api/master", data={"name": "Q", "look": "hi"}).json()["detail"].startswith("Describe your character")
    assert c.post("/api/master", data={**LOOK, "seed": "-1"}).status_code == 400
    assert c.post("/api/master/not-an-id/save").status_code == 404
    assert c.post("/api/master/0123456789/save").status_code == 404


def test_saved_master_is_ref_00_with_text_origin_and_the_sheet_starts_from_it(c):
    m = c.post("/api/master", data={**LOOK, "seed": "11"}).json()
    s = c.post(f"/api/master/{m['master_id']}/save", data={"name": "Quilla"})
    assert s.status_code == 200, s.text
    pack = Path(s.json()["pack_dir"])
    d = json.loads((pack / "pack.json").read_text())
    assert d["ref_images"] == ["refs/ref_00.png"] and (pack / "refs/ref_00.png").is_file()
    assert d["seed"] == 11 and d["prompt_lock"] == m["prompt_lock"]
    o = d["meta"]["origin"]
    assert o["kind"] == "text" and o["seed"] == 11 and o["prompt"] == m["prompt_lock"] and o["master"] == "refs/ref_00.png"
    assert o["fields"]["age"] == "26-35" and o["reference_image"] is None and o["preview"] is True
    assert "07z" in o["workflow"]  # the default master backend: Z-Image-Turbo
    # saving again never overwrites: the next free folder
    again = c.post(f"/api/master/{m['master_id']}/save", data={"name": "Quilla"}).json()
    assert Path(again["pack_dir"]).name == "Quilla_2"
    # the existing sheet flow uses ref_00 as its anchor and keeps it first
    sh = c.post("/api/sheet", data={"name": "Quilla", "prompt_lock": m["prompt_lock"], "pack_dir": str(pack)})
    assert sh.status_code == 200 and sh.json()["state"] == "done", sh.text
    d = json.loads((pack / "pack.json").read_text())
    assert d["ref_images"][0] == "refs/ref_00.png" and d["meta"]["soul_pack"]["anchor"] == "refs/ref_00.png"
    assert len(d["ref_images"]) == 7 and d["meta"]["origin"]["kind"] == "text"


def test_sheet_from_words_alone_records_text_origin(c):
    r = c.post("/api/sheet", data={"name": "Mossy", "prompt_lock": "a short gardener with a moss-green beanie"})
    assert r.status_code == 200 and r.json()["state"] == "done", r.text
    d = json.loads((Path(r.json()["pack_dir"]) / "pack.json").read_text())
    assert d["meta"]["origin"]["kind"] == "text" and d["meta"]["origin"]["master"] == d["ref_images"][0]


def test_real_mode_master_runs_07t_with_the_users_seed(c, monkeypatch, tmp_path):
    """Fallback backend (OPENSOUL_MASTER_BACKEND=qwen07t). Wiring only: the 07t call is faked (no GPU)."""
    import app.server as server

    monkeypatch.setenv("OPENSOUL_MASTER_BACKEND", "qwen07t")
    from opensoul import character_sheet as cs
    from PIL import Image

    monkeypatch.setattr(server, "_dry", lambda: False)
    seen = []

    def fake(description, out_dir, *, seeds=None, **_k):
        seen.append((description, seeds))
        p = Path(out_dir) / f"reference_seed{seeds[0]}.png"
        Image.new("RGB", (8, 12), (90, 80, 70)).save(p)
        return [p]

    monkeypatch.setattr(cs, "make_reference_from_text", fake)
    m = c.post("/api/master", data={**LOOK, "seed": "21"}).json()
    assert seen == [(m["prompt_lock"], [21])] and not m["preview"] and m["label"] == "Master · variation 21"
    assert m["state"] == "done" and m["backend"] == "qwen07t"


def test_a_pack_with_no_pictures_never_breaks_the_app(c):
    made = c.post("/api/character", data={"name": "Wren", "prompt_lock": "a lanky courier in a teal raincoat"}).json()
    pd = made["pack_dir"]
    assert json.loads((Path(pd) / "pack.json").read_text())["ref_images"] == []
    for path in ("/api/bootstrap", "/api/cast", f"/api/look?name=Wren", "/api/presets"):
        assert c.get(path).status_code == 200, path
    r = c.post("/api/photos", data={"pack_dir": pd})
    assert r.status_code == 400 and "no picture yet" in r.json()["detail"]
    shot = c.post("/api/shot", json={"name": "Wren", "pack_dir": pd, "camera": "static"})
    assert shot.status_code < 500


def test_create_page_offers_describe_next_to_upload():
    assert 'data-cmode="describe"' in HTML and ">Describe your character<" in HTML and ">Start from a photo<" in HTML
    for el in ('id="mOutfit"', 'id="mAge"', 'id="mStyle"', 'id="mSeed"', 'id="btnMaster"', 'id="btnMasterStop"', 'id="masterRow"'):
        assert el in HTML, el
    assert ">1 · Make 4 options<" in HTML and ">Generate one<" in HTML and "btnMasterAgain" not in HTML  # the single draw reads "Try another" once a master exists
    assert '"Try another"' in JS and "/cancel`" in JS
    assert 'id="photoField" hidden' in HTML  # describe is the default; the rights tick only comes with a photo
    assert "fetch(\"/api/master\"" in JS and "/save`" in JS and 'document.querySelectorAll(".seg[data-tab]")' in JS


def test_text_made_characters_carry_the_made_from_text_badge(c):
    m = c.post("/api/master", data={**LOOK, "seed": "4"}).json()
    c.post(f"/api/master/{m['master_id']}/save", data={"name": "Quilla"})
    c.post("/api/character", data={"name": "Wren", "prompt_lock": "a lanky courier in a teal raincoat"})
    cast = {x["name"]: x for x in c.get("/api/cast").json()["cast"]}
    assert cast["Quilla"]["made_from_text"] is True and cast["Wren"]["made_from_text"] is False
    ujs = (ROOT / "app/web/static/unified.js").read_text()
    assert "c.made_from_text" in ujs and ">Made from text<" in ujs


def test_first_run_new_character_and_demo_open_on_describe():
    nc = JS[JS.index("function newCharacter(boot)"):JS.index("function onCharacterEdited")]
    ld = JS[JS.index("function loadDemo(which)"):JS.index("function newCharacter(boot)")]
    assert 'setCharMode("describe")' in nc and 'setCharMode("describe")' in ld
    assert 'class="seg active" data-cmode="describe"' in HTML
