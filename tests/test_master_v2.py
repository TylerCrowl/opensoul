"""Text-only master v2: the 07z prompt carries the spec on its own (cfg 1, so the negative never runs), and the master
step can draw N options (opensoul/best_of.py) shown as one pick-one grid. Preview mode / a fake ComfyUI only."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opensoul import best_of as bo
from opensoul import text_master as tm
from opensoul import zimage_master as zm

from test_zimage_master import FakeComfy  # noqa: E402  (fake ComfyUI: no GPU)

ROOT = Path(__file__).resolve().parents[1]
MARLOWE = {"look": "a tall woman with a long silver-grey braid, weathered tan skin, laugh lines and a small gap between her front teeth",
           "outfit": "a mustard oilskin coat over a navy cable-knit sweater", "age": "51-65", "style": "natural"}


def _prompt(f):
    parts = tm.master_parts(f)
    return zm.master_prompt(parts.pop("description"), zm.load_config(env={}), **parts)


MARLOWE_V3 = {"look": "a tall woman with a long silver-grey braid, deeply sun-tanned, wind-weathered outdoor skin, laugh lines "
                      "and a clearly visible gap between her two upper front teeth",
              "outfit": "a hip-length mustard-yellow waxed-cotton field jacket with a slightly shiny waxed finish, zip front with a "
                        "snap storm flap, brown corduroy collar and large flap pockets, open over a navy cable-knit sweater",
              "age": "51-65", "style": "natural"}


def test_outfit_comes_right_after_the_subject_word_for_word_and_once_more_short_at_the_end():
    p = _prompt(MARLOWE)
    assert p.startswith("Photorealistic three-quarter-length reference photo of a tall woman wearing "
                        "a mustard oilskin coat over a navy cable-knit sweater, in her fifties to early sixties, with a long silver-grey braid")
    assert p.count(MARLOWE["outfit"]) == 2 and p.endswith("soft even light. She wears a mustard oilskin coat over a navy cable-knit sweater.")
    assert "Outfit exactly as written" not in p
    assert p.index(MARLOWE["outfit"]) < p.index("silver-grey braid") < p.index("Standing upright")
    # a long outfit: verbatim first, then the main garment (as written) and what it's over, nothing paraphrased
    v3 = _prompt(MARLOWE_V3)
    assert v3.count(MARLOWE_V3["outfit"]) == 1 and v3.index(MARLOWE_V3["outfit"]) < v3.index("in her fifties")
    assert v3.endswith(" She wears a hip-length mustard-yellow waxed-cotton field jacket over a navy cable-knit sweater.")
    assert "coat" not in v3
    assert tm.outfit_short("a flour-dusted denim apron with brass buttons") == "a flour-dusted denim apron"
    assert tm.outfit_short("a teal raincoat") == "a teal raincoat"
    assert tm.outfit_short("a grey suit, white shirt and a red tie") == "a grey suit"
    assert tm.wearing_line("a teal raincoat", "they") == " They wear a teal raincoat." and tm.wearing_line("", "he") == ""
    for f in ({"look": "a baker", "outfit": "a flour-dusted denim apron with brass buttons"},
              {"look": "a courier, freckles", "outfit": "a teal raincoat"}):
        assert f"wearing {f['outfit']}" in _prompt(f)
        for short in tm.outfit_short(f["outfit"]).split(" over "):
            assert short in f["outfit"]  # the user's own words only


def test_the_age_words_use_the_characters_own_pronoun():
    assert "a tall woman wearing a mustard oilskin coat over a navy cable-knit sweater, in her fifties to early sixties," in _prompt(MARLOWE)
    assert "their" not in _prompt(MARLOWE)
    he = {"look": "a stocky man with a red beard", "outfit": "a canvas work jacket", "age": "36-50"}
    assert "in his late thirties to forties" in _prompt(he) and "their" not in _prompt(he)
    they = {"look": "a lanky courier with short copper hair", "outfit": "a teal raincoat", "age": "26-35"}
    assert "in their late twenties to early thirties" in _prompt(they)
    # the pack's pronoun wins over the words; both or neither word sets read as 'they'
    assert tm.master_parts(they, "she/her")["description"].endswith("in her late twenties to early thirties, with short copper hair")
    assert "in his late" in tm.master_parts(they, ["he", "him"])["description"]
    assert "in their fifties" in tm.master_parts({**MARLOWE, "look": "a woman and her son"})["description"]
    assert tm.pronoun_for({"look": "a woman and her son"}) == "they" and tm.pronoun_for({"look": "a fisherman"}) == "they"
    assert tm.pronoun_for({"look": "a tall courier"}, "they") == "they" and tm.pronoun_for({"look": "a weathered sailor"}) == "they"
    assert tm.age_words("65+", "she") == "in her late sixties or older" and tm.age_words("", "he") == ""
    # the look lock (sheet subject, Create) keeps its shared words; only the 07z prompt is pronoun-aware
    assert "in their fifties" in tm.compose(**MARLOWE)


def test_no_master_smiles_and_a_teeth_trait_is_shown_with_lips_just_slightly_apart():
    calm = "Serious calm face, mouth relaxed and closed at the corners"
    p = _prompt(MARLOWE)
    assert f"{calm}, lips just slightly apart, eyes looking into the lens" in p
    assert p.count("a small gap between her front teeth") == 1  # the trait: in the description only
    v3 = _prompt(MARLOWE_V3)
    assert f"{calm}, lips just slightly apart," in v3 and v3.count("gap between her two upper front teeth") == 1
    assert tm.master_parts({"look": "a grinning rogue, gap-toothed"})["expression"] == tm.TEETH_SHOWN == \
        f"{calm}, lips just slightly apart"
    # lip / mouth words without teeth keep the plain neutral face (the trait stays in the description)
    sailor = {"look": "a sailor with a scar across his upper lip"}
    assert tm.master_parts(sailor)["expression"] == tm.NEUTRAL == calm
    assert "a scar across his upper lip" in tm.master_parts(sailor)["description"]
    for look in ("a tall courier with short copper hair", "a baker with freckles", "", "a singer with full red lips"):
        assert tm.master_parts({"look": look, "outfit": "a coat"})["expression"] == tm.NEUTRAL
    for f in (MARLOWE, MARLOWE_V3, sailor, {"look": "a baker"}, {"look": "a vampire with fangs"}):
        e = tm.master_parts(f)["expression"].lower()
        assert e.startswith(calm.lower()) and "smile" not in e and "closed-mouth" not in e
        assert not tm.SMILE_ANY.search(_prompt(f))


def test_ears_are_tucked_back_when_the_spec_has_ears_or_hair_that_would_hide_them():
    tucked = (", hair slicked straight back from the forehead and temples, both ears completely exposed{}, "
              "both ears clearly visible")
    cases = {"a keeper with short subtle pointed elf ears": "", "a pilot with gold hoop earrings": "", "an elf archer": "",
             "a man with long wavy black hair": "",
             "a woman with a long silver-grey braid": ", the long silver-grey braid hidden behind her back, not over her shoulder",
             "a rider with a high ponytail": ", the high ponytail hidden behind their back, not over their shoulder",
             "a man with a ponytail": ", the ponytail hidden behind his back, not over his shoulder",
             "a dancer with a neat bun, she/her": ", the neat bun at the back of her head",
             "a girl with two braids": ", the two braids hidden behind her back, not over her shoulder"}
    for look, tie in cases.items():
        assert tm.master_parts({"look": look})["hair"] == tucked.format(tie), look
        assert _prompt({"look": look}).endswith("the whole face clearly visible" + tucked.format(tie) + ". Plain light grey studio background, soft even light.")
    assert tm.master_parts({"look": "a rider with a high ponytail"}, "he")["hair"].endswith(
        "hidden behind his back, not over his shoulder, both ears clearly visible")
    for look in ("a courier with a shaved head", "a baker with short copper hair", "a librarian with a bob"):
        assert tm.master_parts({"look": look})["hair"] == tm.EARS_SEEN == ", both ears clearly visible", look
    assert "the long silver-grey braid hidden behind her back, not over her shoulder, both ears clearly visible" in \
        _prompt(MARLOWE_V3)
    for f in (MARLOWE, MARLOWE_V3, {"look": "a baker"}, {"look": "an elf archer"}, {}):
        assert "both ears clearly visible" in _prompt(f)


def test_07z_runs_at_cfg_1_whatever_the_preset_says_and_the_prompt_never_leans_on_the_negative():
    cfg = zm.load_config(env={})
    assert cfg["sampler"]["cfg"] == 1.0 and zm.CFG_PIN == 1.0
    g = zm.build_graph("x", 1, {**cfg, "sampler": {**cfg["sampler"], "cfg": 4.5}})
    assert g["8"]["inputs"]["cfg"] == 1.0
    p = _prompt(MARLOWE)
    for must in ("wearing a mustard oilskin coat", "both ears completely exposed", "lips just slightly apart",
                 "mouth relaxed and closed at the corners"):
        assert must in p and must not in cfg["negative"]
    assert "{" not in p and "}" not in p
    # the old single-description call still works (studio runners that load the file by path)
    assert zm.master_prompt("a tall courier.", cfg).startswith("Photorealistic three-quarter-length reference photo of a tall courier.")
    assert ("Serious calm face, mouth relaxed and closed at the corners, eyes looking into the lens, the whole face "
            "clearly visible, both ears clearly visible.") in zm.master_prompt("a tall courier", cfg)
    assert ("full figure from the top of the head down to just below the knees, with a little space above the head."
            in zm.master_prompt("a tall courier", cfg))


# ---------- best of N (generic) ----------

def test_best_of_keeps_every_option_records_seeds_and_a_failed_seed_does_not_lose_the_rest(tmp_path):
    rec = bo.new_record("master", bo.seeds(33, 4))
    assert rec["seeds"] == [33, 34, 35, 36] and bo.seeds(1, 99) == list(range(1, 9))

    def render(seed, out):
        if seed == 35:
            raise RuntimeError("out of memory")
        out.write_bytes(b"img%d" % seed)
        return out
    bo.run(rec, tmp_path, render)
    assert [c["state"] for c in rec["candidates"]] == ["done", "done", "error", "done"] and rec["pick"] is None
    assert sorted(p.name for p in tmp_path.iterdir()) == ["option_33.png", "option_34.png", "option_36.png"]
    bo.pick(rec, 34)
    assert rec["pick"]["seed"] == 34 and rec["pick"]["by"] == "user"
    with pytest.raises(ValueError):
        bo.pick(rec, 35)  # the failed one can't be picked
    assert len(list(tmp_path.iterdir())) == 3  # picking deletes nothing


def test_best_of_auto_pick_uses_the_scorer_and_skips_rejects_and_a_cancel_keeps_what_was_drawn(tmp_path):
    scores = {1: (0.7, ""), 2: (0.95, "face cropped"), 3: (0.9, "")}
    rec = bo.run(bo.new_record("still", [1, 2, 3]), tmp_path, lambda s, o: o.write_bytes(b"x") or o,
                 scorer=lambda p: scores[int(p.stem.split("_")[1])])
    assert rec["pick"]["seed"] == 3 and rec["pick"]["by"] == "score" and rec["candidates"][1]["reject"] == "face cropped"
    stop = {"n": 0}

    def render(seed, out):
        stop["n"] += 1
        out.write_bytes(b"x")
        return out
    rec2 = bo.run(bo.new_record("master", [5, 6, 7]), tmp_path / "c", render, should_cancel=lambda: stop["n"] >= 1)
    assert [c["state"] for c in rec2["candidates"]] == ["done", "cancelled", "cancelled"]


# ---------- the master step: Make 4 options ----------

@pytest.fixture
def c(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    monkeypatch.setenv("OPENSOUL_SHEET_SYNC", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    monkeypatch.setattr(server, "LIBRARY", tmp_path / "library")
    return TestClient(server.app)


LOOK = {"name": "Tamsin", "look": "a lanky lighthouse keeper with a grey braid", "outfit": "a mustard oilskin coat"}


def test_make_4_options_pick_one_and_keep_the_others_with_the_character(c, tmp_path):
    assert c.get("/api/bootstrap").json()["master_batch"] == 4
    m = c.post("/api/master", data={**LOOK, "seed": "33", "options": "4"}).json()
    assert m["state"] == "done" and m["url"] is None and m["pick"] is None  # nothing is the master until picked
    assert [o["seed"] for o in m["options"]] == [33, 34, 35, 36] and all(o["url"] for o in m["options"])
    assert m["next_seed"] == 37 and "wearing a mustard oilskin coat" in m["prompt"]
    work = tmp_path / "outputs" / "masters" / m["master_id"]
    assert c.post(f"/api/master/{m['master_id']}/save", data={"name": "Tamsin"}).status_code == 404  # pick first
    assert c.post(f"/api/master/{m['master_id']}/pick", data={"seed": "99"}).status_code == 400
    p = c.post(f"/api/master/{m['master_id']}/pick", data={"seed": "35"}).json()
    assert p["seed"] == 35 and p["pick"] == 35 and p["url"].endswith("master.png")
    assert (work / "master.png").read_bytes() == (work / "option_35.png").read_bytes()
    assert json.loads((work / "master.json").read_text())["seed"] == 35  # the job's own record follows the pick too
    s = c.post(f"/api/master/{m['master_id']}/save", data={"name": "Tamsin"}).json()
    pack = Path(s["pack_dir"])
    meta = json.loads((pack / "pack.json").read_text())["meta"]["origin"]
    assert meta["seed"] == 35 and meta["master_prompt"] == m["prompt"]
    b = meta["best_of"]
    assert b["seeds"] == [33, 34, 35, 36] and b["pick"] == {**b["pick"], "seed": 35, "file": "options/option_35.png", "by": "user"}
    assert sorted(x.name for x in (pack / "options").iterdir()) == [f"option_{n}.png" for n in (33, 34, 35, 36)]
    assert (pack / "refs" / "ref_00.png").read_bytes() == (pack / "options" / "option_35.png").read_bytes()
    assert sorted(x.name for x in work.glob("option_*.png")) == [f"option_{n}.png" for n in (33, 34, 35, 36)]  # nothing deleted
    assert c.post("/api/master", data={**LOOK, "options": "9"}).status_code == 400


def test_studio_options_queue_one_07z_job_per_seed_at_cfg_1(c, monkeypatch):
    import app.server as server

    comfy = FakeComfy()
    try:
        monkeypatch.setattr(server, "_dry", lambda: False)
        monkeypatch.setenv("OPENSOUL_COMFYUI_URL", comfy.url)
        monkeypatch.delenv("OPENSOUL_MASTER_BACKEND", raising=False)
        m = c.post("/api/master", data={**LOOK, "seed": "33", "options": "4"}).json()
        assert m["state"] == "done", m
        sent = [x["prompt"] for x in comfy.posted]
        assert [g["8"]["inputs"]["seed"] for g in sent] == [33, 34, 35, 36]  # one job at a time, in order
        assert {g["8"]["inputs"]["cfg"] for g in sent} == {1.0} and {g["5"]["inputs"]["text"] for g in sent} == {m["prompt"]}
    finally:
        comfy.close()


def test_create_shows_one_grid_and_one_use_this_one_button():
    html = (ROOT / "app/web/index.html").read_text()
    js = (ROOT / "app/web/static/app.js").read_text()
    assert '<button class="btn btn-primary" id="btnMasterOptions" type="button">1 · Make 4 options</button>' in html
    row = html[html.index('<div class="actions master-actions">'):html.index('<div class="master-row"')]
    assert row.index('id="btnMasterOptions"') < row.index('id="btnMaster"')  # same row: the primary first, then the link
    assert '<button class="btn-link" id="btnMaster" type="button">Generate one</button>' in row
    css = (ROOT / "app/web/static/app.css").read_text()
    rule = css.split("#step1 .row > div:first-child .master-actions {")[1].split("}")[0]
    assert "flex-direction: row" in rule and "flex-wrap: nowrap" in rule  # beats the stacked step-1 .actions column
    assert '$("btnMasterOptions").disabled = true;' in js and '$("btnMasterOptions").disabled = false;' in js
    assert js.count('id="btnUseOption"') == 1 and ">Use this one</button>" in js
    assert 'class="option-grid" role="radiogroup"' in js and 'fd.append("options", String(n))' in js
    assert "/pick`" in js and "Pick one of the options. Then click Use this one" in js
    assert "state.masterBatch = Math.max(2, Math.min(8, Number(data.master_batch) || 4));" in js


def test_auditor_fixes_hierarchy_copy_captions_hint_badge_outfit_and_shot_gate():
    html = (ROOT / "app/web/index.html").read_text()
    js = (ROOT / "app/web/static/app.js").read_text()
    css = (ROOT / "app/web/static/app.css").read_text()
    # 1) Make 4 options is the primary step-1 button; the single draw is a link; the step copy names the primary
    assert "Generate master" not in html and "Generate master" not in js
    assert html.count("Then click <strong>1 · Make 4 options</strong>. No photo needed.") == 1
    assert js.count("Then click <strong>1 · ${makeOptions()}</strong>. No photo needed.") == 2
    assert '$("btnMasterOptions").classList.toggle("btn-primary", step1);' in js
    assert '"btnMaster").classList.toggle("btn-primary"' not in js and '"Try another" : "Generate one"' in js
    # 2) legible captions "Option 2 · #34" (13 px), no tiny text drawn into an option card; Variation # = the pick
    assert "return `Option ${o.items.findIndex((x) => x.seed === seed) + 1} · #${seed}`;" in js
    assert '<span class="option-cap">${optionName(o, x.seed)}</span>' in js
    cap = css.split(".option-cap {")[1].split("}")[0]
    assert int(cap.split("font-size:")[1].split("px")[0]) >= 12
    use = js.split("async function useOption()")[1].split("\n  }\n")[0]
    assert '$("mSeed").value = String(m.seed);' in use
    # 3) the hint once a tile is picked; a check badge and aria-checked on the selected tile
    assert '"Click Use this one to continue."' in js
    assert 'role="radio" aria-checked="${o.chosen === x.seed}"' in js and 'class="option-check" aria-hidden="true"' in js
    assert ".option-tile.on .option-check { display: flex; }" in css
    # nits: Outfit is a 2-line textarea; Choose a shot is gated with the sheet button's reason
    assert '<textarea id="mOutfit" rows="2"' in html and "#mOutfit { min-height: 0;" in css
    assert 'id="toStep2" type="button" aria-describedby="shotReason"' in html
    assert 'const shotWhy = state.isDemo || (state.packDir && !state.dirty) ? "" : why;' in js and '$("toStep2").disabled = !!shotWhy;' in js


def test_an_option_card_carries_no_tiny_caption_but_a_single_preview_master_does(c, tmp_path):
    from PIL import Image

    m = c.post("/api/master", data={**LOOK, "seed": "33", "options": "2"}).json()
    one = c.post("/api/master", data={**LOOK, "seed": "40"}).json()
    def strip(mid, f):  # the band where the card's small subtitle sits
        im = Image.open(tmp_path / "outputs" / "masters" / mid / f).convert("L")
        w, h = im.size
        return im.crop((0, int(h * 0.90), w, int(h * 0.94))).getextrema()
    assert strip(m["master_id"], "option_33.png")[0] > 200  # plain background, no text
    assert strip(one["master_id"], "master.png")[0] < 200


def _fn(src: str, name: str) -> str:
    i = src.index(f"function {name}(")
    depth, j = 0, src.index("{", i)
    for k in range(j, len(src)):
        depth += {"{": 1, "}": -1}.get(src[k], 0)
        if depth == 0:
            return src[i:k + 1]
    raise AssertionError(name)


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_variation_follows_the_selected_tile_and_cancel_restores_the_previous_value():
    js_src = (ROOT / "app/web/static/app.js").read_text()
    js = """
const els = {mSeed: {value: "33"}, mSeedNote: {hidden: false}};
const $ = (id) => els[id];
const state = {master: null, options: {items: [33, 34, 35, 36].map((seed) => ({seed})), chosen: null, prevSeed: "33"}};
const renderCharPreview = () => {}, syncSheetButton = () => {};
%s
%s
%s
const out = [];
out.push(nextSeed());                                         // a re-run from the open grid goes on after option 4
selectOption(35); out.push([els.mSeed.value, state.options.chosen, els.mSeedNote.hidden]);
selectOption(34); out.push([els.mSeed.value, state.options.chosen]);
closeOptions(); out.push([els.mSeed.value, state.options]);   // closed without picking: the value from before the grid
closeOptions(); out.push(els.mSeed.value);                    // a second close is a no-op
els.mSeed.value = "34"; state.master = {url: "u", seed: 34}; out.push(nextSeed());  // Try another: the next number
els.mSeed.value = "50"; out.push(nextSeed());                                         // a typed number is used as is
console.log(JSON.stringify(out));
""" % (_fn(js_src, "selectOption"), _fn(js_src, "closeOptions"), _fn(js_src, "nextSeed"))
    out = json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)
    assert out == [37, ["35", 35, True], ["34", 34], ["33", None], "33", 35, 50]
    # the grid remembers the value from before it opened (a re-run keeps the first), shows it until a tile is tapped,
    # and every way of closing it without a pick goes through closeOptions (Cancel, edits, new character, photo mode)
    assert "const prevSeed = state.options ? state.options.prevSeed : $(\"mSeed\").value;" in js_src
    assert 'chosen: null, prevSeed };\n        $("mSeed").value = prevSeed;' in js_src
    assert 'id="btnCancelOptions" type="button">Cancel</button>' in js_src
    assert 'if (e.target.closest("#btnCancelOptions")) { closeOptions();' in js_src
    assert js_src.count("closeOptions();") >= 5 and "state.options = null;" in _fn(js_src, "useOption")
    assert js_src.count("state.options = null") == 3  # closeOptions, useOption, and a new single master drawn over the grid
    # typing an option's number in Variation # selects that tile
    assert '$("mSeed").addEventListener("input", onCharacterEdited);' in js_src
    assert "state.options.chosen = hit ? hit.seed : null;" in js_src


def test_choose_a_shot_shows_the_visible_reason_line_not_only_a_tooltip():
    html = (ROOT / "app/web/index.html").read_text()
    js = (ROOT / "app/web/static/app.js").read_text()
    assert '<span class="reason" id="shotReason"></span>' in html
    assert 'id="toStep2" type="button" aria-describedby="shotReason">Choose a shot</button>' in html
    assert '$("shotReason").textContent = shotWhy === "Working on it…" ? "" : shotWhy;' in js
    assert '<p class="reason" id="sheetReason"' in html  # the same style as the sheet button's line


def test_one_reason_line_outline_sheet_button_when_disabled_and_no_caption_under_a_picked_grid():
    js = (ROOT / "app/web/static/app.js").read_text()
    css = (ROOT / "app/web/static/app.css").read_text()
    sync = _fn(js, "syncSheetButton")
    # the footer line next to Choose a shot is the one kept; the line under the step buttons empties when it would repeat it
    assert sync.index('$("shotReason").textContent =') < sync.index('$("sheetReason").textContent === $("shotReason").textContent) $("sheetReason").textContent = "";')
    assert 'const footer = !document.body.classList.contains("ui-unified");' in sync
    assert "body.ui-unified #shotReason { display: none; }" in css  # the six-tab shell keeps the one under the buttons
    # 2 · Make character sheet: filled only when it can be tapped
    assert sync.index('$("btnSheet").disabled = !!why;') < sync.index("const sheetNext = !done && !step1 && !$(\"btnSheet\").disabled;")
    # a picked grid: the tile's own label says which, nothing under the grid
    assert '`Pick the one that looks most like ${name}.` : "";' in js and "optionName(o, o.chosen)" not in js
