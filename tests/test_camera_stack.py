"""Stacked camera moves (camera_plan.md §4, steps 3-4): up to 3 per shot, in order, prompt-only, clashes refused."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opensoul import camera_moves as cm
from opensoul.presets import build_shot_plan, load_presets

ROOT = Path(__file__).resolve().parents[1]


def test_every_camera_preset_has_a_phrase_and_the_rules_name_real_moves():
    ids = {c["id"] for c in load_presets()["camera"]}
    assert all(c.get("phrase") for c in load_presets()["camera"])
    r = cm.rules()
    assert r["max_moves"] == 3 and set(r["alone"]) <= ids
    for c in r["conflicts"]:
        assert set(c["a"]) | set(c["b"]) <= ids and c["why"].endswith(".")


def test_a_single_move_renders_exactly_as_before():
    for cam in ("dolly_in", "orbit", "jib_down", "static"):
        a, b = build_shot_plan(camera=cam, seed=7), build_shot_plan(camera_moves=[cam], seed=7)
        assert a["prompt"] == b["prompt"] and a["stages"] == b["stages"] and a["expect_motion"] == b["expect_motion"]


def test_a_stack_joins_the_phrases_in_order_prompt_only():
    p = build_shot_plan(camera="dolly_in", camera_moves=["dolly_in", "orbit", "jib_up"], seed=7)
    cams = {c["id"]: c for c in load_presets()["camera"]}
    txt = p["prompt"]
    i, o, j = (txt.index(cams[m]["phrase"]) for m in ("dolly_in", "orbit", "jib_up"))
    assert i < o < j and "First " in txt and "; then " in txt and "; finally " in txt
    assert p["stages"][0]["loras"] == []                  # no LoRA for a stack
    assert p["expect_motion"] == cams["dolly_in"]["expect_motion"]  # the first move drives the motion check
    assert p["camera_moves"] == ["dolly_in", "orbit", "jib_up"] and p["title"] == "Dolly in → Orbit → Jib up"
    assert any("prompt only" in n for n in p["notes"])
    two = build_shot_plan(camera_moves=["dolly_left", "jib_up"], seed=7)["prompt"]
    assert "finally" not in two and "; then " in two


@pytest.mark.parametrize("moves,why", [
    (["dolly_in", "dolly_out"], "Can't push in and pull back in one shot."),
    (["orbit", "orbit"], "Orbit is already in this shot."),
    (["dolly_left", "dolly_right"], "Can't move left and right in one shot."),
    (["static", "dolly_in"], "Static means no camera move"),
    (["jib_down", "orbit"], "Jib down is rendered in reverse"),
    (["dolly_in", "push_in_gentle"], "same move at two speeds"),
    (["dolly_left", "jib_up", "orbit", "dolly_in"], "Up to 3 camera moves per shot."),
])
def test_clashes_are_blocked_in_plain_english(moves, why):
    with pytest.raises(cm.MoveError, match=why.replace("(", r"\(").replace(".", r"\.")):
        cm.check(moves)


def test_experimental_when_any_move_is_or_when_stacked():
    assert cm.experimental(["orbit"]) and cm.experimental(["dolly_in", "jib_up"]) and not cm.experimental(["dolly_in"])


def test_an_effect_cant_join_a_stack():
    with pytest.raises(cm.MoveError):
        build_shot_plan(camera_moves=["dolly_in", "jib_up"], effect="day_to_night")


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    import app.server as server
    from opensoul import storyboard as sb
    monkeypatch.setattr(server, "DATA", tmp_path)
    sb.set_data_dir(tmp_path)
    return TestClient(server.app)


def test_the_shot_api_stores_validates_and_clears_a_stack(client):
    pid = client.post("/api/storyboard/projects", json={"title": "Stack"}).json()["id"]
    p = client.post(f"/api/storyboard/projects/{pid}/shots", json={"beat": "Walk in", "characters": []}).json()
    sid = p["shots"][0]["id"]
    base = f"/api/storyboard/projects/{pid}/shots/{sid}"
    s = client.patch(base, json={"camera_moves": ["dolly_left", "jib_up"]}).json()["shots"][0]
    assert s["camera_moves"] == ["dolly_left", "jib_up"] and s["camera"] == "dolly_left"
    r = client.patch(base, json={"camera_moves": ["dolly_in", "dolly_out"]})
    assert r.status_code == 400 and r.json()["detail"] == "Can't push in and pull back in one shot."
    take = client.post(f"{base}/regenerate", json={"quality": "draft"}).json()["shots"][0]["versions"][-1]
    assert take["settings"]["camera_moves"] == ["dolly_left", "jib_up"] and "; then " in take["settings"]["camera_prompt"]
    s = client.patch(base, json={"camera": "orbit"}).json()["shots"][0]
    assert s["camera"] == "orbit" and s["camera_moves"] == []    # one move = no stack
    s = client.patch(base, json={"camera_moves": ["fpv"]}).json()["shots"][0]
    assert s["camera"] == "fpv" and s["camera_moves"] == []


def test_presets_api_ships_the_rules_for_the_shot_sheet(client):
    d = client.get("/api/presets").json()
    assert d["camera_rules"] == json.loads((ROOT / "presets" / "camera_rules.json").read_text())


def test_the_shot_sheet_and_card_use_the_stack_ui():
    tiles = (ROOT / "app" / "web" / "static" / "tiles.js").read_text()
    sbjs = (ROOT / "app" / "web" / "static" / "storyboard.js").read_text()
    assert "multiHTML, wireMulti, blockedReason, clash" in tiles and 'BADGE = ["①", "②", "③"' in tiles
    assert "Click up to ${max} moves in the order you want them." in sbjs
    assert "{ camera_moves: moves } : { camera: moves[0] }" in sbjs and "${movesChipsHTML(s)}" in sbjs
    assert "Stacked moves are new, and we did not check them on the GPU" in sbjs


# ---------------------------------------------------------------- length rules (camera_plan §4 rule 7)
def _video(plan):
    return next(x for x in plan["stages"] if x["stage"] == "video")


def test_a_two_move_draft_is_lengthened_to_5_s_with_a_note():
    one = build_shot_plan(camera_moves=["dolly_left"], quality="draft", seed=3)
    two = build_shot_plan(camera_moves=["dolly_left", "jib_up"], quality="draft", seed=3)
    assert one["stages"][0]["params"].get("duration_s", 0) <= 4.05          # a single-move draft stays short
    assert two["stages"][0]["params"]["duration_s"] >= 5.0
    lat = [v["length"] for v in _video(two)["inputs"].values() if isinstance(v, dict) and "length" in v]
    assert lat and min(lat) == cm.frames_for(5) == 121
    assert "Lengthened to 5 s for 2 moves." in two["notes"]


def test_a_draft_takes_two_moves_at_most():
    with pytest.raises(cm.MoveError, match="Drafts take up to 2 camera moves"):
        build_shot_plan(camera_moves=["dolly_left", "jib_up", "orbit"], quality="draft")


def test_final_already_has_room_for_three_moves():
    p = build_shot_plan(camera_moves=["dolly_left", "jib_up", "orbit"], quality="final", seed=3)
    assert not any(n.startswith("Lengthened") for n in p["notes"])  # the workflow's 169 frames = 7.04 s


def test_a_short_spoken_line_is_padded_up_to_the_stack_minimum():
    p = build_shot_plan(camera_moves=["dolly_left", "jib_up", "orbit"], quality="final", line="Hi.", lipsync_backend="ltx_av", seed=3)
    v = _video(p)
    assert v["frames"] >= cm.frames_for(7) and v["pad_audio_to_s"] >= 7.0
    assert "Lengthened to 7 s for 3 moves." in p["notes"]


def test_frames_for_is_the_smallest_ltx_length_that_lasts():
    for s in (1, 4, 5, 7):
        f = cm.frames_for(s)
        assert (f - 1) % 8 == 0 and f / 24 >= s and (f - 8) / 24 < s


def test_the_server_refuses_a_three_move_draft_and_notes_the_lengthened_one(client):
    pid = client.post("/api/storyboard/projects", json={"title": "Len"}).json()["id"]
    sid = client.post(f"/api/storyboard/projects/{pid}/shots", json={"beat": "Run", "characters": []}).json()["shots"][0]["id"]
    base = f"/api/storyboard/projects/{pid}/shots/{sid}"
    client.patch(base, json={"camera_moves": ["dolly_left", "jib_up", "orbit"]})
    r = client.post(f"{base}/regenerate", json={"quality": "draft"})
    assert r.status_code == 400 and r.json()["detail"].startswith("Drafts take up to 2 camera moves")
    assert client.post(f"{base}/regenerate", json={"quality": "final"}).status_code == 200
    client.patch(base, json={"camera_moves": ["dolly_left", "jib_up"]})
    v = client.post(f"{base}/regenerate", json={"quality": "draft"}).json()["shots"][0]["versions"][-1]
    assert v["settings"]["length_note"] == "Lengthened to 5 s for 2 moves." and "Lengthened to 5 s" in v["note"]


def test_the_sheet_hint_is_calm_and_chips_scroll_to_their_tile():
    sbjs = (ROOT / "app" / "web" / "static" / "storyboard.js").read_text()
    css = (ROOT / "app" / "web" / "static" / "storyboard.css").read_text()
    tiles = (ROOT / "app" / "web" / "static" / "tiles.js").read_text()
    assert "onBlocked" not in sbjs and 'onHint: (why) => { const w = $("sbCamWhy"); if (w) w.textContent = why || ""; }' in sbjs
    assert '["mouseleave", "blur"].forEach((ev) => t.addEventListener(ev, () => hint(null)))' in tiles
    why = next(l for l in css.splitlines() if l.startswith(".sb-cam-why {"))
    assert "var(--text-secondary)" in why and "#b3541e" not in why
    assert 'data-move="${esc(c.id)}"' in sbjs and 'scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" })' in sbjs
    assert "draftTooMany" in sbjs and "Draft lengthened to 5 s, so both moves have room." in sbjs
