"""Create and demo pictures after the v4 review: a Look with no real master (a pre-rebuild placeholder, or words
edited since the master) can't make a sheet, Generate master is the next tap, and no picture or clip whose look
descends from closed-generator concept art is served anywhere in the live app."""
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "app/web"
JS = (WEB / "static/app.js").read_text()


@pytest.fixture()
def srv(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    monkeypatch.setenv("OPENSOUL_SHEET_SYNC", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    return TestClient(server.app), server, tmp_path


def _pack(root, folder):
    d = root / "packs" / folder
    (d / "refs").mkdir(parents=True)
    (d / "refs" / "ref_00.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (d / "pack.json").write_text(json.dumps({"name": folder, "prompt_lock": "old words", "ref_images": [str(d / "refs/ref_00.png")], "meta": {}}))
    return d


LOOK = {"name": "Kai", "look": "a tall courier with copper hair", "outfit": "a teal raincoat", "seed": 7}


def test_sheet_refuses_a_stale_master(srv):
    c, _server, tmp = srv
    m = c.post("/api/master", data=LOOK).json()
    r = c.post("/api/sheet", data={"name": "Kai", "prompt_lock": "x", "master_id": m["master_id"],
                                   "look": "a short baker with black curls", "outfit": "a teal raincoat"})
    assert r.status_code == 409 and "Make 4 options (or Generate one)" in r.json()["detail"]
    assert not (tmp / "packs").exists() or not any((tmp / "packs").iterdir())  # refused before anything is saved
    r = c.post("/api/sheet", data={"name": "Kai", "prompt_lock": "x", "master_id": m["master_id"],
                                   "look": " a tall courier with  copper hair", "outfit": "a teal raincoat"})
    assert r.status_code == 200, r.text  # same words (spacing aside): the master that's showing


def test_sheet_refuses_a_pre_rebuild_placeholder(srv):
    c, _server, tmp = srv
    pack = _pack(tmp, "Mio")  # an old (pre-rebuild) Mio pack: its picture shows as a placeholder
    r = c.post("/api/sheet", data={"name": "Mio", "prompt_lock": "a kind barista", "pack_dir": str(pack)})
    assert r.status_code == 409 and "placeholder" in r.json()["detail"]
    r = c.post("/api/sheet", data={"name": "Mio", "image_path": str(ROOT / "assets/mio/character.json").replace(".json", ".jpg")})
    assert r.status_code in (400, 409)
    kai = _pack(tmp, "Kai")  # anyone else's pack is current
    assert c.post("/api/sheet", data={"name": "Kai", "prompt_lock": "a tall courier", "pack_dir": str(kai)}).status_code == 200


def test_step_one_is_the_primary_button_until_there_is_a_real_master():
    assert "function needsMaster()" in JS and "return !!state.look.placeholder || bigLookChange();" in JS
    assert "state.master.sig !== masterSig()" in JS and "saved: false, sig }" in JS
    assert 'if (needsMaster()) return state.master && state.master.url ?' in JS
    assert '$("btnMasterOptions").classList.toggle("btn-primary", step1);' in JS  # Make N options is the step-1 primary (auditor, v3)
    assert 'const sheetNext = !done && !step1 && !$("btnSheet").disabled;' in JS  # disabled: outline, never pale-filled
    assert '$("btnSheet").classList.toggle("btn-primary", sheetNext);' in JS and '$("btnSheet").classList.toggle("btn-outline", !sheetNext);' in JS


def test_library_note_says_the_picture_is_a_placeholder():
    html = (WEB / "index.html").read_text()
    assert 'using their <span id="libraryUsing">picture and description</span>.' in html
    assert '"description; picture is a placeholder" : "picture and description"' in JS


def test_qualifier_is_one_size_up():
    css = (WEB / "static/app.css").read_text()
    assert re.search(r"\.hero-qual \{[^}]*font-size: 0\.95rem", css)


def _served(c):
    """Every picture/clip URL the bootstrap, every GET route, the demo story, /api/look and the page hand out."""
    from app.server import app

    out = {}
    paths = sorted({r.path for r in app.routes if getattr(r, "methods", None) and "GET" in r.methods and "{" not in r.path
                    and not r.path.startswith(("/docs", "/redoc", "/openapi", "/api/file"))})
    bodies = [(p, c.get(p)) for p in paths]
    bodies.append(("demo story", c.get("/api/storyboard/projects/lumi-night-shift")))
    for n in ("Lumi", "Mio", "Ren", "Pixel"):
        bodies.append((n, c.get(f"/api/look?name={n}")))
    for p, r in bodies:
        if r.status_code == 200:
            for u in re.findall(r'"(/(?:assets|api/file)[^"\s]*)"', r.text):
                out.setdefault(u.replace("\\u0026", "&"), p)
    for u in re.findall(r'(?:src|href)="(/assets/[^"#?]+)"', c.get("/").text):
        out.setdefault(u, "/")
    return out


def _sha(b: bytes) -> str:
    import hashlib

    return hashlib.sha256(b).hexdigest()


def _banned() -> dict:
    """sha256 -> why, for every file that must never be served: export_guard's DERIVED / DERIVED_DIRS / PRE_REBUILD,
    concept files, every picture in pre_rebuild_hide, and the release gate's deny list when this machine has it."""
    import importlib.util

    from opensoul import export_guard as eg

    files = {ROOT / r for r in eg.DERIVED | eg.PRE_REBUILD}
    files |= {f for d in eg.DERIVED_DIRS for f in (ROOT / d).rglob("*")}
    files |= set(eg.concept_files())
    hide = json.loads((ROOT / "presets/demo_images.json").read_text())["pre_rebuild_hide"]["dirs"]
    for rel in hide:
        q = ROOT / rel
        files |= set(q.rglob("*")) if q.is_dir() else {q}
    out = {_sha(f.read_bytes()): f.relative_to(ROOT).as_posix() for f in files if f.is_file()}
    spec = importlib.util.spec_from_file_location("_eg_test", ROOT / "tests/test_export_guard.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    deny = Path(m.GATE) / "gate_hash_deny.txt"  # read only; it isn't part of the repo
    if deny.is_file():
        for line in deny.read_text(encoding="utf-8", errors="replace").splitlines():
            tok = line.split("#", 1)[0].split()
            if tok and re.fullmatch(r"[0-9a-f]{64}", tok[0]):
                out.setdefault(tok[0], "gate deny list: " + (tok[2] if len(tok) > 2 else ""))
    return out


def test_no_closed_generator_lineage_picture_or_clip_is_served(srv):
    c, _server, _tmp = srv
    c.get("/api/storyboard/projects")  # seeds the demo story
    served = _served(c)
    banned = _banned()
    assert len(banned) > 20
    hits, fetched = {}, 0
    for u, src in served.items():
        r = c.get(u)
        if r.status_code != 200:
            continue
        fetched += 1
        h = _sha(r.content)
        if h in banned:
            hits[u] = (src, banned[h])
    assert not hits, hits
    assert fetched >= 5 and any("placeholder_" in u for u in served)
    assert not [u for u in served if "/assets/preset_thumbs/" in u]  # unpassed tile clips aren't even sent


def test_a_demo_slot_pointed_at_an_old_design_still_serves_the_placeholder(srv, monkeypatch, tmp_path):
    """Regression (release check): repointing tile_still at lumi_sheet_preview.jpg must not serve the old file."""
    from opensoul import demo_images

    c, _server, _tmp = srv
    cfg = json.loads(demo_images.CONFIG.read_text())
    cfg["tile_still"]["image"] = "assets/demo_samples/lumi_sheet_preview.jpg"
    cfg["first_run_still"]["image"] = "assets/demo_audited/shot01_cold_open_v8f_f28.jpg"  # in export_guard DERIVED
    tmp_cfg = tmp_path / "demo_images.json"
    tmp_cfg.write_text(json.dumps(cfg))
    monkeypatch.setattr(demo_images, "CONFIG", tmp_cfg)
    if not (ROOT / "assets/demo_samples/lumi_sheet_preview.jpg").is_file():
        pytest.skip("release archives leave the old demo sheet out")
    boot = c.get("/api/bootstrap").json()
    assert boot["video"]["poster_url"] == "/assets/demo_audited/placeholder_tile.jpg"
    tiles = c.get("/api/presets").json()
    assert {t["tile_still"] for t in tiles["camera"] if not t["thumb_ready"]} == {"/assets/demo_audited/placeholder_tile.jpg"}
    still = boot["first_run"].get("still")
    if (ROOT / "assets/demo_audited/shot01_cold_open_v8f_f28.jpg").is_file():
        assert still and still["image_url"] == "/assets/demo_audited/placeholder_shot.jpg"
    assert demo_images.url("assets/demo_audited/shot01_doodling_v8f.mp4") is None  # a clip never stands in
    assert demo_images.url("assets/lumi/lumi_ref_00.jpg") == "/assets/demo_audited/placeholder_lumi.svg"  # a portrait
    assert demo_images.url("assets/lumi/lumi_ref_00.jpg", kind="stage") == "/assets/demo_audited/placeholder_stage.jpg"


def test_every_swap_is_listed_with_what_it_replaced():
    cfg = json.loads((ROOT / "presets/demo_images.json").read_text())
    pr = cfg["projects"]["lumi-night-shift"]
    st = pr["stage"]["Konbini interior"]
    assert st["placeholder"] and st["angles"] == {} and set(st["replaced"]) == {"master", "angles", "sheet", "empty"}
    assert pr["approved_takes"]["Cold open"] == [] and pr["approved_takes_paused"]["Cold open"]
    for n in ("lumi_still_01_front.png", "lumi_still_reject_demo.png", "lumi_video_poster.png"):
        assert cfg["pre_rebuild_hide"]["dirs"]["assets/demo_samples/" + n] == "lumi"
    for e in (pr["shot_cards"]["Cold open"], st["sheet"]):
        assert e["placeholder"] and "placeholder_" in (e.get("card") or e.get("image"))
