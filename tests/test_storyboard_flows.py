"""Storyboard adapts to what each user makes: inline names, add/delete (Undo)/reorder, cast from the user's
own characters, new character in the flow, new story (blank / template / script), Export view."""
import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opensoul import storyboard as sb
from opensoul.script_split import short_name, split_script, suggest_camera
from release_assets import LUMI_REFS, requires_demo_asset

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "app" / "web" / "static" / "storyboard.js").read_text()
HTML = (ROOT / "app" / "web" / "index.html").read_text()


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    monkeypatch.setenv("OPENSOUL_SHEET_SYNC", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    monkeypatch.setattr(server, "LIBRARY", tmp_path / "library")  # only the user's own characters, nothing hardcoded
    return TestClient(server.app)


@pytest.fixture()
def store(tmp_path):
    return sb.Store(tmp_path / "projects")


def _png(color=(120, 160, 200)) -> bytes:
    from PIL import Image

    b = io.BytesIO()
    Image.new("RGB", (64, 96), color).save(b, format="PNG")
    return b.getvalue()


def _story(client, **kw):
    r = client.post("/api/storyboard/projects", json={"title": "Mine", **kw})
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- 1. names, add, delete + undo, reorder
def test_rename_shot_inline_trims_and_refuses_empty(client):
    p = _story(client)
    p = client.post(f"/api/storyboard/projects/{p['id']}/shots", json={"beat": "Shot 1"}).json()
    sid = p["shots"][0]["id"]
    r = client.patch(f"/api/storyboard/projects/{p['id']}/shots/{sid}", json={"beat": "  The   doorstep  "})
    assert r.json()["shots"][0]["beat"] == "The doorstep"
    assert client.patch(f"/api/storyboard/projects/{p['id']}/shots/{sid}", json={"beat": "   "}).status_code == 400


def test_rename_story_keeps_its_id_and_takes(client):
    p = _story(client)
    p = client.post(f"/api/storyboard/projects/{p['id']}/shots", json={"beat": "A"}).json()
    client.post(f"/api/storyboard/projects/{p['id']}/shots/{p['shots'][0]['id']}/regenerate", json={})
    r = client.patch(f"/api/storyboard/projects/{p['id']}", json={"title": "The Last Bus"})
    assert r.status_code == 200 and r.json()["title"] == "The Last Bus" and r.json()["id"] == p["id"]
    assert len(r.json()["shots"][0]["versions"]) == 1
    assert client.patch(f"/api/storyboard/projects/{p['id']}", json={"title": " "}).status_code == 400


def test_delete_then_undo_puts_the_shot_back_in_place_with_its_takes(client):
    p = _story(client)
    pid = p["id"]
    for b in ("A", "B", "C"):
        p = client.post(f"/api/storyboard/projects/{pid}/shots", json={"beat": b}).json()
    b_id = p["shots"][1]["id"]
    client.post(f"/api/storyboard/projects/{pid}/shots/{b_id}/regenerate", json={"edit": "x"})
    assert client.delete(f"/api/storyboard/projects/{pid}/shots/{b_id}").status_code == 400  # still needs a confirm
    p = client.delete(f"/api/storyboard/projects/{pid}/shots/{b_id}?confirm=1").json()
    assert [s["beat"] for s in p["shots"]] == ["A", "C"]
    p = client.post(f"/api/storyboard/projects/{pid}/shots/{b_id}/restore", json={"index": 1}).json()
    assert [s["beat"] for s in p["shots"]] == ["A", "B", "C"]
    assert [v["id"] for v in p["shots"][1]["versions"]] == ["v1"]
    assert client.post(f"/api/storyboard/projects/{pid}/shots/{b_id}/restore", json={}).status_code == 404  # only once


def test_restore_clamps_index_and_reorder_still_works(store):
    p = store.create_project("T", "")
    ids = [store.add_shot(p.id, b).id for b in ("A", "B")]
    store.delete_shot(p.id, ids[0], confirm=True)
    store.restore_shot(p.id, ids[0], index=99)
    assert [s.beat for s in store.load(p.id).shots] == ["B", "A"]
    store.reorder(p.id, ids)
    assert [s.beat for s in store.load(p.id).shots] == ["A", "B"]


# ---------------------------------------------------------------- 2. cast from the user's own characters
def test_shots_can_have_no_cast_and_names_are_cleaned(store):
    p = store.create_project("T", "")
    assert p.character == ""
    assert store.add_shot(p.id, "Empty street").characters == []           # no lead: nobody by default
    s = store.add_shot(p.id, "Two", characters=[" Kai ", "kai", "Ada", ""])
    assert s.characters == ["Kai", "Ada"]
    assert store.update_shot(p.id, s.id, characters=[]).characters == []    # a scene-only shot is allowed
    q = store.create_project("Lead", "Kai")
    assert store.add_shot(q.id, "A").characters == ["Kai"]


@requires_demo_asset(*LUMI_REFS)
def test_cast_is_the_users_own_library_not_hardcoded(client):
    assert client.get("/api/storyboard/cast").json()["cast"] == []  # empty library: no Lumi/Mio/Ren appear
    r = client.post("/api/storyboard/cast", data={"name": "Kai", "consent": "true", "kind": "reference",
                                                  "description": "a tall courier in a yellow rain jacket"},
                    files={"image": ("kai.png", _png(), "image/png")})
    assert r.status_code == 200, r.text
    cast = r.json()["cast"]
    assert [c["name"] for c in cast] == ["Kai"] and cast[0]["picture_url"] and cast[0]["source"] == "app"
    assert client.get("/api/storyboard/cast").json()["cast"][0]["name"] == "Kai"
    # the same name twice is refused, and so is a bundled demo picture under another name
    assert client.post("/api/storyboard/cast", data={"name": "kai", "description": "someone else entirely"}).status_code == 400
    from demo_character import demo_ref

    r = client.post("/api/storyboard/cast", data={"name": "Zed", "kind": "reference", "consent": "true"},
                    files={"image": ("z.png", demo_ref().read_bytes(), "image/png")})
    assert r.status_code == 400 and "demo character" in r.json()["detail"]


def test_new_character_from_a_sheet_needs_consent_and_saves_the_sheet(client, tmp_path):
    files = {"image": ("sheet.png", _png((200, 180, 160)), "image/png")}
    r = client.post("/api/storyboard/cast", data={"name": "Ada", "kind": "sheet"}, files=files)
    assert r.status_code == 400 and "permission" in r.json()["detail"]
    r = client.post("/api/storyboard/cast", data={"name": "Ada", "kind": "sheet", "consent": "true"},
                    files={"image": ("sheet.png", _png((200, 180, 160)), "image/png")})
    assert r.status_code == 200, r.text
    c = r.json()["character"]
    assert c["sheet_url"] and c["picture_url"]
    assert (tmp_path / "packs" / "Ada" / "character_sheet.png").is_file()
    # text only works too (the picture can come later), a bad file does not
    assert client.post("/api/storyboard/cast", data={"name": "Bo", "description": "short"}).status_code == 400
    assert client.post("/api/storyboard/cast", data={"name": "Bo", "consent": "true"},
                       files={"image": ("x.png", b"not an image", "image/png")}).status_code == 400


def test_new_cast_member_can_star_in_a_start_frame(client):
    client.post("/api/storyboard/cast", data={"name": "Kai", "consent": "true"}, files={"image": ("k.png", _png(), "image/png")})
    p = _story(client)
    p = client.post(f"/api/storyboard/projects/{p['id']}/shots", json={"beat": "Doorstep", "characters": ["Kai", "Ada"]}).json()
    s = p["shots"][0]
    assert s["characters"] == ["Kai", "Ada"]  # Ada isn't saved yet: kept as a name, shown as "not in your characters"
    r = client.post(f"/api/storyboard/projects/{p['id']}/shots/{s['id']}/frame", json={"seed": 3})
    assert r.status_code == 200, r.text
    v = r.json()["shots"][0]["versions"][0]
    assert v["kind"] == "frame" and v["settings"]["cast"] == ["Kai"] and "Ada" in v["prompt"]


def test_regenerate_prompt_uses_the_shots_cast_lock(client):
    client.post("/api/storyboard/cast", data={"name": "Kai", "consent": "true", "description": "yellow rain jacket, short black hair"},
                files={"image": ("k.png", _png(), "image/png")})
    p = _story(client)
    p = client.post(f"/api/storyboard/projects/{p['id']}/shots", json={"beat": "A", "prompt": "rings the bell", "characters": ["Kai"]}).json()
    r = client.post(f"/api/storyboard/projects/{p['id']}/shots/{p['shots'][0]['id']}/regenerate", json={"seed": 1})
    v = r.json()["shots"][0]["versions"][0]
    assert v["prompt"].startswith("yellow rain jacket") and "rings the bell" in v["prompt"]


# ---------------------------------------------------------------- 3. new story: blank or template
def test_templates_list_blank_lumi_and_preset_files(client):
    t = client.get("/api/storyboard/templates").json()["templates"]
    ids = [x["id"] for x in t]
    assert ids[0] == "blank" and ids[1] == sb.LUMI_TEMPLATE and "three-beat" in ids and "character-intro" in ids
    assert next(x for x in t if x["id"] == sb.LUMI_TEMPLATE)["beats"][0] == "Cold open"


def test_blank_story_is_empty_and_from_template_fills_in_the_lead(client):
    p = _story(client, template="blank")
    assert p["shots"] == [] and p["character"] == ""
    q = client.post("/api/storyboard/projects", json={"title": "Kai's day", "template": "three-beat", "character": "Kai"}).json()
    assert [s["beat"] for s in q["shots"]] == ["Hook", "Twist", "Payoff"]
    assert all(s["characters"] == ["Kai"] for s in q["shots"]) and "Kai" in q["shots"][0]["prompt"]
    assert "{lead}" not in json.dumps(q)
    r = client.post("/api/storyboard/projects", json={"template": "three-beat"}).json()
    assert r["title"] == "Three-beat short" and all(s["characters"] == [] for s in r["shots"])
    assert client.post("/api/storyboard/projects", json={"template": "nope"}).status_code == 404


def test_lumi_template_makes_a_copy_and_never_touches_the_demo(client, tmp_path):
    client.get("/api/storyboard/projects")  # seeds the demo
    demo_file = tmp_path / "projects" / sb.DEMO_ID / "project.json"
    before = demo_file.read_text()
    c = client.post("/api/storyboard/projects", json={"title": "My Night Shift", "template": sb.LUMI_TEMPLATE}).json()
    assert c["id"] != sb.DEMO_ID and [s["beat"] for s in c["shots"]][:2] == ["Cold open", "Doors chime"]
    sid = c["shots"][0]["id"]
    client.patch(f"/api/storyboard/projects/{c['id']}/shots/{sid}", json={"beat": "Rainy open"})
    client.delete(f"/api/storyboard/projects/{c['id']}/shots/{c['shots'][1]['id']}?confirm=1")
    assert demo_file.read_text() == before
    listed = client.get("/api/storyboard/projects").json()["projects"]
    assert [x["demo"] for x in listed if x["id"] == sb.DEMO_ID] == [True]


def test_real_demo_project_file_still_loads():
    """The real Lumi demo data (data/projects/lumi-night-shift) reads with the new model, unchanged."""
    f = ROOT / "data" / "projects" / sb.DEMO_ID / "project.json"
    if not f.is_file():
        pytest.skip("no local demo data")
    p = sb.Project.from_dict(json.loads(f.read_text()))
    assert p.shots and p.shots[0].beat


# ---------------------------------------------------------------- 3b. start from a script
SCRIPT = """# The Last Bus
INT. BUS STOP - NIGHT
Rain. Kai waits alone under a flickering light. Close on his tired face.
KAI
Come on, come on.

EXT. EMPTY ROAD - CONTINUOUS
The bus appears. The camera pulls back to reveal the empty city.

INT. BUS - LATER
Kai sits by the window. ADA: Last stop is the sea. [camera: orbit]
"""


def test_split_screenplay_into_named_shots_with_cast_and_camera():
    r = split_script(SCRIPT, ["Kai", "Lumi"])
    assert r["title"] == "The Last Bus"
    assert [s["beat"] for s in r["shots"]] == ["Bus Stop", "Empty Road", "Bus"]
    a, b, c = r["shots"]
    assert a["characters"] == ["Kai"] and a["camera"] == "push_in_gentle" and a["line"] == "Come on, come on."
    assert b["characters"] == [] and b["camera"] == "dolly_out"
    assert c["characters"] == ["Kai", "Ada"] and c["camera"] == "orbit" and "[camera" not in c["prompt"]


def test_split_numbered_lines_paragraphs_and_sentences():
    r = split_script("1. Nova laces her shoes\n2. She sprints down the hill, the drone follows her\n3. Nova: Made it.", ["Nova"])
    assert [s["beat"] for s in r["shots"]] == ["Nova laces her shoes", "She sprints down the hill", "Nova – Made it"]
    assert r["shots"][1]["characters"] == ["Nova"] and r["shots"][1]["camera"] == "fpv"  # "she" carries the cast
    r = split_script("Lumi wipes the counter.\n\nMio and Ren stumble in, laughing.", ["lumi", "Mio", "Ren"])
    assert [s["characters"] for s in r["shots"]] == [["lumi"], ["Mio", "Ren"]]
    r = split_script("A cat sleeps on a windowsill. The sun rises. It wakes and stretches.")
    assert len(r["shots"]) == 3 and all(s["camera"] == "static" for s in r["shots"])
    assert split_script("   ")["shots"] == [] and split_script("   ")["notes"]


def test_split_caps_long_scripts_and_helpers():
    r = split_script("\n".join(f"{i}. Shot number {i}" for i in range(1, 80)))
    assert len(r["shots"]) == 40 and r["notes"]
    assert suggest_camera("slow dolly zoom on her face")[0] == "dolly_zoom"
    assert suggest_camera("nothing special")[0] == "static"
    assert short_name("The camera circles around Lumi as she pours.") == "Circles around Lumi"


def test_script_api_suggests_then_makes_an_editable_story(client):
    assert client.post("/api/storyboard/script/split", json={"text": ""}).status_code == 400
    r = client.post("/api/storyboard/script/split", json={"text": SCRIPT}).json()
    shots = r["shots"]
    shots[1]["beat"] = "The bus arrives"   # the user edits before the story is made
    shots.pop(2)
    body = {"title": r["title"], "shots": [{k: s[k] for k in ("beat", "prompt", "characters", "camera")} for s in shots]}
    p = client.post("/api/storyboard/projects", json=body).json()
    assert p["title"] == "The Last Bus" and [s["beat"] for s in p["shots"]] == ["Bus Stop", "The bus arrives"]
    assert p["shots"][0]["camera"] == "push_in_gentle" and p["shots"][0]["characters"] == ["Kai"]
    sid = p["shots"][1]["id"]  # still editable afterwards
    q = client.patch(f"/api/storyboard/projects/{p['id']}/shots/{sid}", json={"characters": ["Kai"], "camera": "static"}).json()
    assert q["shots"][1]["characters"] == ["Kai"] and q["shots"][1]["camera"] == "static"
    bad = {"title": "x", "shots": [{"beat": "A", "camera": "warp_speed"}]}
    assert client.post("/api/storyboard/projects", json=bad).status_code == 400


def test_add_shots_from_a_script_to_an_existing_story(client):
    p = _story(client)
    p = client.post(f"/api/storyboard/projects/{p['id']}/shots", json={"beat": "Mine first"}).json()
    r = client.post(f"/api/storyboard/projects/{p['id']}/shots/batch",
                    json={"shots": [{"beat": "Two", "camera": "orbit"}, {"beat": "Three"}]}).json()
    assert [s["beat"] for s in r["shots"]] == ["Mine first", "Two", "Three"]
    assert client.post(f"/api/storyboard/projects/{p['id']}/shots/batch", json={"shots": [{"beat": " "}]}).status_code == 400


def test_script_split_needs_no_model_or_network(monkeypatch):
    import socket

    def no_net(*a, **k):
        raise AssertionError("script split must not touch the network (no LLM server)")

    monkeypatch.setattr(socket, "create_connection", no_net)
    monkeypatch.setattr(socket.socket, "connect", no_net)
    assert split_script(SCRIPT, ["Kai"])["shots"]


# ---------------------------------------------------------------- 4. the UI wiring (no browser on CI)
def test_ui_has_the_create_storyboard_export_flow_and_new_controls():
    for v in ('data-view="create"', 'data-view="storyboard"', 'data-view="export"'):
        assert v in HTML
    for el in ('id="sbTitle"', 'id="sbNewStory"', 'id="sbFromScript"', 'id="sbScriptFirst"', 'id="sbExportPane"', 'id="sbReel"'):
        assert el in HTML
    for needle in ("/restore", "/shots/batch", "/script/split", "/templates", 'api("/cast", { method: "POST"',
                   "Undo", 'class="sb-beat"', "New character", "Start from"):
        assert needle in JS, needle
    import re

    assert not re.search(r"\b(Lumi|Mio|Ren)\b", JS)  # no hardcoded cast in the UI


# --- three varied sample scripts (tests/fixtures/scripts) -------------------------------------------------------------
FIX = Path(__file__).parent / "fixtures" / "scripts"


def _split_fixture(name, cast=("Lumi", "Mio", "Ren", "Juno")):
    return split_script((FIX / name).read_text(), list(cast))


def test_sample_screenplay_lighthouse():
    r = _split_fixture("screenplay_lighthouse.txt")
    assert r["title"] == "The Lighthouse Keeper's Cat"
    beats = [s["beat"] for s in r["shots"]]
    # transitions (FADE IN:, CUT TO:) are not shots; a repeated place gets its time of day
    assert beats == ["Lighthouse", "Lighthouse Kitchen", "Lamp Room", "Rocks", "Lighthouse Kitchen, Morning"]
    assert not any("CUT TO" in s["prompt"] or "FADE" in s["prompt"] for s in r["shots"])
    kitchen, lamp, rocks = r["shots"][1], r["shots"][2], r["shots"][3]
    assert kitchen["characters"] == ["Margot", "Biscuit"]  # CAPS introductions count as cast
    assert kitchen["line"].startswith("You'll eat") and "(dry)" not in kitchen["line"]
    assert lamp["line"].startswith("Forty years") and lamp["camera"] == "orbit"  # NAME (V.O.): line
    assert rocks["characters"] == ["Biscuit"]
    assert r["shots"][0]["camera"] == "fpv"
    assert r["shots"][4]["camera"] == "static"  # "She pulls back the curtain" is not a camera move


def test_sample_paragraphs_bakery():
    r = _split_fixture("paragraphs_bakery.txt")
    assert len(r["shots"]) == 6 and r["title"] == ""
    s = r["shots"]
    assert s[0]["beat"] == "Juno unlocks the bakery" and s[0]["characters"] == ["Juno"]
    assert s[1]["characters"] == ["Juno"] and s[1]["camera"] == "push_in_gentle"  # "She ...", "Tight on"
    # mixed-case "Juno: ..." mid-paragraph is dialogue; two speakers -> one shot per line, each with its speaker
    # each turn: its speaker first, plus anyone named in the action ("Theo, her neighbour, leans in")
    assert s[2]["characters"] == ["Juno", "Theo"] and s[3]["characters"] == ["Theo"]
    assert (s[2]["speaker"], s[2]["line"]) == ("Juno", "You're early.")
    assert (s[3]["speaker"], s[3]["line"]) == ("Theo", "You're always earlier.")
    # OS-052: the line stays in What they say; What happens never repeats it (the frame drew it as text)
    assert all("says:" not in x["prompt"] for x in s)
    assert s[4]["camera"] == "dolly_in" and s[5]["camera"] == "dolly_out" and s[5]["characters"] == []


def test_sample_numbered_skate():
    r = _split_fixture("numbered_skate.txt")
    assert r["title"] == "Skate Day" and len(r["shots"]) == 6
    s = r["shots"]
    # "Wide establishing shot: ..." is a shot description, not someone talking
    assert s[0]["beat"] == "Empty concrete skatepark" and s[0]["characters"] == [] and s[0]["line"] == ""
    assert s[1]["beat"] == "Rio drops" and s[1]["characters"] == ["Rio"] and s[1]["camera"] == "fpv"
    assert s[2]["camera"] == "crash_zoom" and s[2]["characters"] == ["Rio"]
    assert s[3]["characters"] == ["Sam", "Rio"] and s[3]["line"] == "Never better."
    assert "Never better" not in s[3]["prompt"] and '""' not in s[3]["prompt"]  # OS-052
    assert s[4]["camera"] == "static" and s[5]["camera"] == "jib_up"
    assert all(len(x["beat"].split()) <= 5 for x in s)


def test_split_camera_words_need_the_camera():
    assert suggest_camera("She pulls back the curtain.")[0] == "static"
    assert suggest_camera("The camera pulls back on the road.")[0] == "dolly_out"
    assert suggest_camera("Pull back to reveal the city.")[0] == "dolly_out"
    assert suggest_camera("He moves in with his aunt.")[0] == "static"
    assert short_name("The camera pulls back on the empty road") == "Empty road"


def test_phone_width_css():
    css = (Path(__file__).resolve().parents[1] / "app/web/static/storyboard.css").read_text()
    phone = css[css.index("@media (max-width: 600px)"):]
    assert ".view-switch" in phone and "flex-wrap: wrap" in phone  # flow bar gets its own row
    assert ".sb-sheet" in phone and "bottom: 0" in phone  # shot sheet becomes a bottom sheet
    assert "@media (hover: none)" in css  # card move/delete buttons visible on touch screens
    assert "width: max-content" in css.split(".sb-toast {", 1)[1].split("}", 1)[0]


def test_refresh_demo_does_not_rewrite_an_up_to_date_demo(tmp_path):
    store = sb.Store(tmp_path / "projects")
    sb.seed_demo(store)
    sb.refresh_demo(store)
    f = tmp_path / "projects" / sb.DEMO_ID / "project.json"
    before = f.read_bytes()
    assert sb.refresh_demo(store) is False
    assert f.read_bytes() == before  # not even the "updated" time moves


def test_toast_sits_in_a_corner_not_over_the_actions():
    """QA round 2: the centred toast covered the shot's action buttons."""
    css = (ROOT / "app" / "web" / "static" / "storyboard.css").read_text()
    rule = css.split(".sb-toast {", 1)[1].split("}", 1)[0]
    assert "left: 24px" in rule and "translateX(-50%)" not in rule and "max-width: min(400px" in rule
