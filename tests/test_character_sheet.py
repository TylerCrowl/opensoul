"""Character Sheet maker: preset, workflow 07, gate + retry, grid, Soul Pack, API, policy."""
import importlib.util
import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from opensoul import character_sheet as cs
from opensoul import comfy_client
from opensoul.character_pack import CharacterPack
from demo_character import DEMO_NAME, DEMO_PACK  # noqa: E402
from release_assets import LUMI_REFS, requires_demo_asset

ROOT = Path(__file__).resolve().parents[1]
VIEW_IDS = ["full_front", "full_side", "full_back", "close_front", "close_side", "close_back"]
REF = ROOT / "assets" / "example_character" / "pixel_reference.png"


def test_close_up_views_are_framed_as_close_ups():
    p = cs.load_preset()
    for v in p["views"]:
        text = cs.view_prompt(v, p)
        if v["id"].startswith("close"):
            assert v["framing"] == "close" and "no waist, legs or shoes" in text and text.rstrip().endswith("upper chest.")
        else:
            assert v["framing"] == "full" and "head to the shoes" in text


def test_preset_has_six_views_on_light_gray():
    p = cs.load_preset()
    assert [v["id"] for v in p["views"]] == VIEW_IDS
    assert p["grid"]["cols"] * p["grid"]["rows"] == 6
    assert "light gray" in p["style"].lower() and "same lighting" in p["style"].lower().replace("identical lighting", "same lighting")
    assert "100%" in p["keep"] and "clothing" in p["keep"] and "hair" in p["keep"] and "face" in p["keep"]
    assert p["gate"]["backend"] == "patch" and p["gate"]["retries"] == 2
    assert p["workflow"] == "workflows/07_character_sheet_api.json"
    for v in p["views"]:
        prompt = cs.view_prompt(v, p, "red scarf")
        assert "{subject}" not in prompt and "red scarf" in prompt and p["keep"] in prompt


def test_workflow_07_is_qwen_bf16_lightning_with_gate():
    g = json.loads(cs.WORKFLOW.read_text())
    assert g["1"]["inputs"]["unet_name"] == "qwen_image_edit_2511_bf16.safetensors"
    assert "Lightning" in g["10"]["inputs"]["lora_name"]
    assert g[cs.NODE_GATE]["class_type"] == "OpenSoulIdentityGate"
    assert g[cs.NODE_GATE]["inputs"]["backend"] == "patch"
    assert g[cs.NODE_GATE]["inputs"]["anchor"] == [cs.NODE_IMAGE, 0]
    assert g[cs.NODE_OUT]["inputs"]["images"] == [cs.NODE_GATE, 0]
    assert g[cs.NODE_POS]["class_type"] == "TextEncodeQwenImageEditPlus"
    p = cs.load_preset()
    inputs = cs.view_inputs("/x.png", p["views"][0], p, seed=5)
    comfy_client.apply_inputs(g, inputs)  # every override names a real node + input
    assert inputs[cs.NODE_SEED]["seed"] == 5 and inputs[cs.NODE_SEED]["steps"] == 4


def test_workflow_07_in_allowlist_check():
    spec = importlib.util.spec_from_file_location("cw", ROOT / "scripts/check_workflows.py")
    cw = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cw)
    assert "07_character_sheet_api.json" in cw.REQUIRED
    assert cw.violations() == []
    allowed = cw.allowlist()
    for n in json.loads(cs.WORKFLOW.read_text()).values():
        assert n["class_type"] in allowed


def test_graph_without_gate_rewires_save():
    g = json.loads(cs.WORKFLOW.read_text())
    g2 = cs.graph_without_gate(g)
    assert cs.NODE_GATE not in g2 and cs.NODE_GATE in g
    assert g2[cs.NODE_OUT]["inputs"]["images"] == ["11", 0]
    p = cs.load_preset()
    comfy_client.apply_inputs(g2, cs.view_inputs("/x.png", p["views"][0], p, seed=1, gate_in_graph=False))


def test_consent_required(tmp_path):
    with pytest.raises(cs.ConsentRequired):
        cs.make_character_sheet(REF, tmp_path, consent=False, dry_run=True)


def test_dry_run_placeholder_grid_and_soul_pack(tmp_path):
    res = cs.make_character_sheet(REF, tmp_path / "out", consent=True, dry_run=True, pack_dir=tmp_path / "pack",
                                  name="Pixel", subject="round robot")
    assert res.dry_run and [v.id for v in res.views] == VIEW_IDS
    im = Image.open(res.sheet)
    g = cs.load_preset()["grid"]
    assert im.width > 3 * g["cell_width"] and im.height > 2 * g["cell_height"]
    assert im.getpixel((2, 2)) == (0xD8, 0xD8, 0xD8)  # light gray background
    man = json.loads(Path(res.manifest).read_text())
    assert man["consent"] is True and len(man["views"]) == 6
    pack = CharacterPack.load(tmp_path / "pack")
    assert len(pack.ref_images) == 7 and Path(pack.ref_images[0]).name == "ref_00.png"
    assert all(Path(r).is_file() for r in pack.ref_images)
    assert [v["id"] for v in pack.meta["soul_pack"]["views"]] == VIEW_IDS
    # a second sheet replaces the views instead of stacking them
    cs.make_character_sheet(REF, tmp_path / "out2", consent=True, dry_run=True, pack_dir=tmp_path / "pack")
    assert len(CharacterPack.load(tmp_path / "pack").ref_images) == 7


def _fake_runner(bad_first: set, calls: list):
    def run(workflow_path, *, inputs, output_node_id, out_dir, metadata=None):
        calls.append((Path(workflow_path).name, inputs))
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        pr = cs.load_preset()
        view = next(v["id"] for v in pr["views"] if cs.view_prompt(v, pr) == inputs[cs.NODE_POS]["prompt"])
        dest = out / "view.png"
        attempt = sum(1 for c in calls if c[1][cs.NODE_POS]["prompt"] == inputs[cs.NODE_POS]["prompt"]) - 1
        if view in bad_first and attempt == 0:
            Image.new("RGB", (64, 96), (255, 0, 255)).save(dest)  # clearly off-model
        else:
            shutil.copy2(inputs[cs.NODE_IMAGE]["image"], dest)
        return [dest]
    return run


@pytest.mark.parametrize("gate_mode,wf_name", [("graph", "07_character_sheet_api.json"), ("local", "07_character_sheet_api.json")])
def test_live_path_gates_and_retries_off_model_views_once(tmp_path, gate_mode, wf_name):
    calls: list = []
    stages: list = []
    res = cs.make_character_sheet(REF, tmp_path, consent=True, dry_run=False, gate_mode=gate_mode,
                                  runner=_fake_runner({"full_back"}, calls), max_parallel=1, autofix=False,
                                  progress=lambda v, s: stages.append(s))
    assert len(calls) == 7  # 6 views + exactly one retry
    pr = cs.load_preset()
    fb_prompt = cs.view_prompt(next(v for v in pr["views"] if v["id"] == "full_back"), pr)
    retried = [c for c in calls if c[1][cs.NODE_POS]["prompt"] == fb_prompt]
    assert len(retried) == 2 and retried[1][1][cs.NODE_SEED]["seed"] == retried[0][1][cs.NODE_SEED]["seed"] + 1009
    fb = next(v for v in res.views if v.id == "full_back")
    assert fb.attempts == 2 and fb.passed and len(fb.scores) == 2 and fb.scores[0] < fb.scores[1]
    assert all(v.passed for v in res.views)
    assert all((cs.NODE_GATE in c[1]) == (gate_mode == "graph") for c in calls)
    assert any("Fixing" in s for s in stages) and stages[-1] == "Sheet ready"


def test_off_model_after_retry_keeps_best_and_reports(tmp_path):
    calls: list = []

    def always_bad(workflow_path, *, inputs, output_node_id, out_dir, metadata=None):
        calls.append(1)
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (64, 96), (255, 0, 255)).save(out / "v.png")
        return [out / "v.png"]

    res = cs.make_character_sheet(REF, tmp_path, consent=True, dry_run=False, gate_mode="local", runner=always_bad,
                                  autofix=False)
    assert len(calls) == 12 and not any(v.passed for v in res.views) and Path(res.sheet).is_file()


def test_gate_score_matches_node_patch_backend(tmp_path):
    import numpy as np

    nodes = cs._nodes()
    a = np.asarray(Image.open(REF).convert("RGB"))
    rep = cs.gate_score(REF, REF, 0.7)
    assert rep["passed"] and rep["best_score"] == pytest.approx(1.0, abs=1e-5)
    assert nodes.GATE_THRESHOLDS["patch"] == cs.load_preset()["gate"]["threshold"]
    assert a.shape[2] == 3


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    monkeypatch.setenv("OPENSOUL_SHEET_SYNC", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    return TestClient(server.app)


def test_api_requires_consent(client):
    r = client.post("/api/sheet", data={"consent": "false"}, files={"image": ("me.png", REF.read_bytes(), "image/png")})
    assert r.status_code == 400 and "permission" in r.json()["detail"]


def test_api_one_upload_to_sheet_to_soul_pack(client, tmp_path):
    r = client.post("/api/sheet", data={"consent": "true", "name": "Pixel Test"},
                    files={"image": ("me.png", REF.read_bytes(), "image/png")})
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["state"] == "done", job
    assert job["done"] == 6 and job["total"] == 6 and job["sheet_url"].startswith("/api/file?path=")
    st = client.get(f"/api/sheet/{job['job_id']}").json()
    assert st["state"] == "done"
    d = client.get(job["download_url"])
    assert d.status_code == 200 and "attachment" in d.headers.get("content-disposition", "")
    pack = CharacterPack.load(job["pack_dir"])
    assert len(pack.ref_images) == 7 and pack.meta["soul_pack"]["sheet"] == "character_sheet.jpg"
    # the Soul Pack is ready for shots: the Shot step accepts it
    shot = client.post("/api/shot", json={"camera": "static", "pack_dir": job["pack_dir"]})
    assert shot.status_code in (200, 500)  # 500 only if ffmpeg is missing on the test box
    assert client.get("/api/sheet/nope").status_code == 404


@requires_demo_asset(*LUMI_REFS)
def test_api_demo_character_sheet_never_touches_assets(client):
    before = (DEMO_PACK / "pack.json").read_text()
    r = client.post("/api/sheet", data={"consent": "true", "name": DEMO_NAME, "pack_dir": ""})
    # the demo pack's pictures are a pre-rebuild design (a placeholder in the UI): never the source of a new sheet
    assert r.status_code == 409 and "placeholder" in r.json()["detail"]
    assert (DEMO_PACK / "pack.json").read_text() == before


def test_no_person_replacement_feature():
    """Policy: no route or function that swaps/replaces a person or face in a video."""
    import re

    import app.server as server

    bad = re.compile(r"swap|replace|deepfake", re.I)
    assert not [r.path for r in server.app.routes if bad.search(getattr(r, "path", ""))]
    for d in ("opensoul", "app"):
        for p in (ROOT / d).rglob("*.py"):
            assert not re.search(r"def \w*(swap|replace_person|replace_face)\w*", p.read_text()), p


# ---------------------------------------------------------------- auto-fix (mocked VLM)
from opensoul import sheet_check as sc  # noqa: E402

CAP_CHARACTER = {"gender_word": "man", "headwear": "baseball cap", "headwear_color": "grey", "headwear_orientation": "backward",
             "glasses": "eyeglasses", "glasses_color": "black", "sunglasses_on_headwear_or_head": True,
             "earbud_left": True, "earbud_right": False, "earring_left": False, "earring_right": False,
             "facial_hair": "stubble", "top_layers": [{"item": "quilted vest", "color": "navy"}],
             "bottom": {"item": "cargo pants", "color": "charcoal"}, "footwear": {"item": "work boots", "color": "brown"}}


class MockVLM:
    """Answers from the prompt the fake runner saved next to each image: the first try of a view gets the
    earbuds / cap orientation wrong, a try whose prompt carries the matching correction gets it right."""

    def __init__(self, stubborn=(), only_side=()):
        # stubborn: never fixed; only_side: corrective prompts don't help, rotating from the side view does
        self.asked, self.released, self.stubborn, self.only_side = [], 0, set(stubborn), set(only_side)

    def describe_json(self, image, prompt):
        assert "headwear_orientation" in prompt
        return dict(CAP_CHARACTER)

    def ask(self, image, questions):
        prompt = Path(image).with_suffix(".txt").read_text()
        view = Path(image).with_suffix(".view").read_text()
        self.asked.append((view, list(questions)))
        out = []
        from_side = Path(image).with_suffix(".src").read_text() != ""
        for q in questions:
            fixed = "CORRECTIONS" in prompt and view not in self.stubborn and view not in self.only_side
            rotated = from_side and "visor is visible" in prompt and view not in self.stubborn
            if "BOTH ears" in q:
                out.append(not ((fixed and "Only ONE earbud" in prompt) or rotated))
            elif "brim (visor) point toward the camera" in q:
                out.append(bool((fixed and "BACKWARDS" in prompt) or rotated) if view.endswith("back") else False)
            elif "strap opening visible" in q:
                out.append(not ((fixed and "no strap or strap opening" in prompt) or rotated))
            elif "legs, knees or shoes" in q or "face visible" in q or "waist visible" in q:
                out.append(False)
            else:
                out.append(True)
        return out

    def release(self):
        self.released += 1


def _autofix_runner(calls):
    def run(workflow_path, *, inputs, output_node_id, out_dir, metadata=None):
        pr = cs.load_preset()
        prompt = inputs[cs.NODE_POS]["prompt"]
        view = Path(out_dir).name.rsplit("_try", 1)[0]
        src = inputs.get(cs.NODE_SOURCE, {}).get("image", "")
        assert view in {v["id"] for v in pr["views"]}
        assert bool(src) == (Path(workflow_path).name == cs.WORKFLOW_BACK_FROM_SIDE.name)
        if not src and "visor is visible" not in prompt:  # normal views carry their own view prompt
            assert prompt.startswith(cs.view_prompt(next(v for v in pr["views"] if v["id"] == view), pr))
        calls.append((view, inputs[cs.NODE_SEED]["seed"], prompt, Path(workflow_path).name, src))
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        dest = out / "view.png"
        shutil.copy2(inputs[cs.NODE_IMAGE]["image"], dest)
        dest.with_suffix(".txt").write_text(prompt)
        dest.with_suffix(".view").write_text(view)
        dest.with_suffix(".src").write_text(src)
        return [dest]
    return run


def test_checklist_questions_are_view_aware():
    pr = {v["id"]: v for v in cs.load_preset()["views"]}
    by = lambda vid: {c.id: c for c in sc.checks_for_view(pr[vid], CAP_CHARACTER)}  # noqa: E731
    front, back, side, cfront = by("full_front"), by("full_back"), by("full_side"), by("close_front")
    assert front["cap_orientation"].expect is False and "cap_orientation" not in back
    assert "back of the person's head" in side["cap_orientation"].question and side["cap_orientation"].expect is True
    assert front["earbuds_both"].expect is False and "ONE earbud, in the person's left ear" in front["earbuds_both"].fix
    assert "earbuds_both" not in side  # a profile shows one ear only
    assert "glasses" not in back and "glasses" in front and "facing_side" in side
    assert "LEFT edge" in side["facing_side"].question
    assert "bottom" in front and "bottom" not in cfront and "framing_close" in cfront
    assert back["facing_back"].expect is False
    assert back["cap_strap"].expect is False and back["cap_strap"].label == "Cap orientation"
    assert "cap_strap" not in front and "cap_strap" not in side
    two = dict(CAP_CHARACTER, top_layers=[{"item": "quilted vest", "color": "navy"}, {"item": "henley", "color": "grey"}])
    assert "top:henley" not in {c.id for c in sc.checks_for_view(pr["full_back"], two)}
    side_q = {c.id: c.question for c in sc.checks_for_view(pr["full_side"], two)}["top:henley"]
    assert "under the quilted vest" in side_q


def test_autofix_retries_with_corrections_and_passes(tmp_path):
    calls, vlm = [], MockVLM()
    stages = []
    res = cs.make_character_sheet(REF, tmp_path, consent=True, dry_run=False, gate_mode="local",
                                  runner=_autofix_runner(calls), vlm=vlm, use_arcface=False, max_parallel=1,
                                  progress=lambda v, s: stages.append(s))
    assert res.checklist["headwear_orientation"] == "backward" and res.gate["autofix"]
    # round 1: all 6 have both earbuds -> fail (side views have no ear check -> pass); back views also cap
    first = {c[0] for c in calls[:6]}
    assert len(first) == 6
    retried = [c for c in calls[6:]]
    assert {c[0] for c in retried} == {"full_front", "full_back", "close_front", "close_back"}
    fb = next(c for c in retried if c[0] == "full_back")
    assert "Only ONE earbud, in the person's left ear" in fb[2] and "visor covers the back of the neck" in fb[2]
    assert all(v.passed and not v.note for v in res.views)
    v = next(v for v in res.views if v.id == "full_back")
    assert v.attempts == 2 and len(v.tries) == 2 and v.tries[0]["failed"] and v.tries[1]["passed"]
    assert all(c["passed"] for c in v.checks)
    assert vlm.released >= 2  # load-on-demand: released after every round
    assert any("Reading the reference" in s for s in stages) and any("Checking" in s for s in stages)
    man = json.loads(Path(res.manifest).read_text())
    assert man["checklist"]["earbud_left"] is True and man["views"][0]["checks"]


def test_autofix_gives_up_after_two_retries_and_flags_view(tmp_path):
    calls, vlm = [], MockVLM(stubborn={"close_back"})
    res = cs.make_character_sheet(REF, tmp_path, consent=True, dry_run=False, gate_mode="local",
                                  runner=_autofix_runner(calls), vlm=vlm, use_arcface=False, max_parallel=1)
    cb = next(v for v in res.views if v.id == "close_back")
    cbs = [c for c in calls if c[0] == "close_back"]
    assert len(cbs) == 3  # first try + 2 retries
    # the 3rd try (after two failures) is rotated from the passed close-up side view, without 'backwards' wording
    assert cbs[2][3] == cs.WORKFLOW_BACK_FROM_SIDE.name and "close_side" in cbs[2][4]
    assert "visor is visible" in cbs[2][2] and "backward" not in cbs[2][2].lower()
    assert [c[3] for c in cbs[:2]] == [cs.WORKFLOW.name] * 2
    assert not cb.passed and "Close-up · back" in cb.note and "Regenerate" in cb.note
    assert "cap orientation" in cb.note.lower()
    assert all(v.passed for v in res.views if v.id != "close_back")


def test_arcface_decides_identity_when_face_visible():
    pr = {v["id"]: v for v in cs.load_preset()["views"]}
    ev = sc.evaluate(pr["close_front"], REF, {}, None, patch=0.9, patch_ok=True, arcface=0.30)
    assert not ev.identity_ok and not ev.passed and "face match" in ev.note
    ev2 = sc.evaluate(pr["full_front"], REF, {}, None, patch=0.5, patch_ok=False, arcface=0.45)
    assert ev2.identity_ok  # full-body threshold 0.40; the failing patch gate is overruled
    ev3 = sc.evaluate(pr["full_back"], REF, {}, None, patch=0.5, patch_ok=False, arcface=None)
    assert not ev3.identity_ok  # no face -> patch gate decides
    assert sc.better(ev, ev2) and not sc.better(ev2, ev)


def test_regenerate_one_view_keeps_better_try(tmp_path):
    calls, vlm = [], MockVLM(stubborn={"close_back"})
    res = cs.make_character_sheet(REF, tmp_path, consent=True, dry_run=False, gate_mode="local",
                                  runner=_autofix_runner(calls), vlm=vlm, use_arcface=False, max_parallel=1)
    n = len(calls)
    vlm.stubborn.clear()  # now the fix works
    res2 = cs.regenerate_view(tmp_path, "close_back", runner=_autofix_runner(calls), vlm=vlm, dry_run=False,
                              use_arcface=False)
    new = calls[n:]
    assert new and {c[0] for c in new} == {"close_back"}
    assert new[0][3] == cs.WORKFLOW_BACK_FROM_SIDE.name and "visor is visible" in new[0][2]  # already failed 3x
    assert len({c[1] for c in calls if c[0] == "close_back"}) == len([c for c in calls if c[0] == "close_back"])  # fresh seeds
    cb = next(v for v in res2.views if v.id == "close_back")
    assert cb.passed and not cb.note and Path(res2.sheet).is_file()


def test_vlm_answer_parsing():
    assert sc._parse_json('Sure: ["yes", "no"]') == ["yes", "no"]
    assert [sc._yes_no(x) for x in ("Yes", "no.", True, "maybe")] == [True, False, True, None]


def test_api_regenerate_and_checks_in_status(client):
    r = client.post("/api/sheet", data={"consent": "true", "name": "Pixel R"},
                    files={"image": ("me.png", REF.read_bytes(), "image/png")})
    job = r.json()
    assert all("checks" in v and "note" in v for v in job["views"])
    r2 = client.post(f"/api/sheet/{job['job_id']}/regenerate/close_back")
    assert r2.status_code == 200 and r2.json()["state"] == "done"
    assert client.post(f"/api/sheet/{job['job_id']}/regenerate/nope").status_code == 400


def test_back_view_falls_back_to_side_view(tmp_path):
    """Corrective prompts don't fix the back view twice -> the 3rd try is rotated from the passed side view."""
    calls, vlm = [], MockVLM(only_side={"close_back"})
    stages = []
    res = cs.make_character_sheet(REF, tmp_path, consent=True, dry_run=False, gate_mode="local",
                                  runner=_autofix_runner(calls), vlm=vlm, use_arcface=False, max_parallel=1,
                                  progress=lambda v, s: stages.append(s))
    fb = [c for c in calls if c[0] == "close_back"]
    assert [c[3] for c in fb] == [cs.WORKFLOW.name, cs.WORKFLOW.name, cs.WORKFLOW_BACK_FROM_SIDE.name]
    side = next(v for v in res.views if v.id == "close_side")
    assert side.passed and Path(fb[2][4]).parent.name.startswith("close_side")
    v = next(v for v in res.views if v.id == "close_back")
    assert v.passed and not v.note and v.tries[-1]["strategy"] == "side" and v.tries[-1]["passed"]
    assert any("rotating from the side view" in s for s in stages)
    man = json.loads(Path(res.manifest).read_text())
    assert next(x for x in man["views"] if x["id"] == "close_back")["tries"][-1]["source"]


def test_full_back_fallback_uses_visor_wording_first(tmp_path):
    pr = cs.load_preset()
    ctx = cs._Ctx(REF, tmp_path, pr, "", None, "local", None, None, CAP_CHARACTER, False, lambda s: None)
    try:
        failed = [{"attempt": i, "path": "x", "passed": False} for i in range(2)]
        ctx.results = {"full_side": cs.ViewResult(id="full_side", label="s", path=str(REF), passed=True)}
        fb = cs.ViewResult(id="full_back", label="b", tries=list(failed))
        assert ctx.fallback(fb) == ("wording", None)
        fb.tries += [{"attempt": 2, "path": "y", "strategy": "wording"}] * 2
        assert ctx.fallback(fb) == ("side", REF)
    finally:
        ctx.cleanup()


def test_back_fallback_prompt_avoids_backwards_semantics():
    pr = cs.load_preset()
    v = {x["id"]: x for x in pr["views"]}
    subj = "man, grey baseball cap worn backwards with dark sunglasses on the brim, navy vest, cargo pants, boots"
    full = cs.back_fallback_prompt(v["full_back"], pr, subj, CAP_CHARACTER, "side")
    close = cs.back_fallback_prompt(v["close_back"], pr, subj, CAP_CHARACTER, "wording")
    for t in (full, close):
        assert "backward" not in t.lower() and "visor is visible" in t and "no strap" in t
        assert "sunglasses rest on top of the cap" in t and "brim" not in t
    assert "Picture 1" in full and "90 degrees" in full and "to the shoes" in full
    assert "Picture 1" not in close and "cargo pants" not in close and "upper chest" in close
    inp = cs.view_inputs(REF, v["full_back"], pr, seed=1, prompt=full, source=REF)
    assert inp[cs.NODE_SOURCE]["image"] == str(REF) and inp[cs.NODE_POS]["prompt"] == full


def test_back_fallback_uses_wording_when_side_view_failed(tmp_path):
    pr = cs.load_preset()
    ctx = cs._Ctx(REF, tmp_path, pr, "", None, "local", None, None, CAP_CHARACTER, False, lambda s: None)
    try:
        side = cs.ViewResult(id="close_side", label="side", path=str(REF), passed=False)
        back = cs.ViewResult(id="close_back", label="back",
                             tries=[{"attempt": 0, "path": "a", "passed": False}, {"attempt": 1, "path": "b", "passed": False}])
        ctx.results = {"close_side": side, "close_back": back}
        assert ctx.fallback(back) == ("wording", None)
        side.passed = True
        assert ctx.fallback(back) == ("side", REF)
        back.tries = back.tries[:1]
        assert ctx.fallback(back) is None  # only after two failed tries
        assert ctx.fallback(cs.ViewResult(id="full_front", label="f", tries=back.tries * 3)) is None
        back.tries = [{"attempt": 0, "path": "a", "passed": False, "failed": ["cap_orientation", "earbuds_both"]}]
        fixes = ctx.fallback_fixes(back)
        assert "ONE earbud" in fixes and "BACKWARDS" not in fixes
    finally:
        ctx.cleanup()


def test_best_try_weights_cap_errors_over_small_details():
    pr = {v["id"]: v for v in cs.load_preset()["views"]}

    class Fixed:  # answers every question as expected, except the one named
        def __init__(self, wrong):
            self.wrong = wrong

        def ask(self, image, questions):
            checks = sc.checks_for_view(pr["full_back"], CAP_CHARACTER)
            return [(not c.expect) if c.id == self.wrong else c.expect for c in checks]

    strap = sc.evaluate(pr["full_back"], REF, CAP_CHARACTER, Fixed("cap_strap"), patch=0.8)
    shades = sc.evaluate(pr["full_back"], REF, CAP_CHARACTER, Fixed("sunglasses_on_head"), patch=0.7)
    assert strap.failed == ["cap_strap"] and shades.failed == ["sunglasses_on_head"]
    assert sc.better(strap, shades) and not sc.better(shades, strap)  # a wrong cap is worse than missed shades


# ------------------------------------------------------------------ text-only start (workflow 07t) + fantasy checks
def test_workflow_07t_is_text_only_qwen_bf16():
    g = json.loads((ROOT / "workflows/07t_character_from_text_api.json").read_text())
    kinds = {n["class_type"] for n in g.values()}
    assert "LoadImage" not in kinds and "OpenSoulIdentityGate" not in kinds
    assert g["1"]["inputs"]["unet_name"] == "qwen_image_edit_2511_bf16.safetensors"
    assert "image1" not in g[cs.NODE_POS]["inputs"] and g[cs.NODE_OUT]["inputs"]["images"] == ["11", 0]
    import scripts.check_workflows as cw
    assert "07t_character_from_text_api.json" in cw.REQUIRED


def test_make_reference_from_text_runs_07t_per_seed(tmp_path):
    calls = []

    def run(workflow_path, *, inputs, output_node_id, out_dir, metadata=None):
        calls.append((Path(workflow_path).name, inputs))
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        dest = Path(out_dir) / "ref.png"
        Image.new("RGB", (32, 48), (200, 180, 160)).save(dest)
        return [dest]

    refs = cs.make_reference_from_text("an elf barista, silver-lavender hair", tmp_path, seeds=[7, 8], runner=run,
                                       dry_run=False)
    assert [p.name for p in refs] == ["reference_seed7.png", "reference_seed8.png"] and all(p.is_file() for p in refs)
    assert {c[0] for c in calls} == {"07t_character_from_text_api.json"}
    assert [c[1][cs.NODE_SEED]["seed"] for c in calls] == [7, 8]
    assert "silver-lavender hair" in calls[0][1][cs.NODE_POS]["prompt"] and cs.NODE_IMAGE not in calls[0][1]
    with pytest.raises(ValueError):
        cs.make_reference_from_text("  ", tmp_path, runner=run, dry_run=False)


def test_pointed_ears_and_hair_colour_checked_where_visible():
    pr = {v["id"]: v for v in cs.load_preset()["views"]}
    cl = {"gender_word": "woman", "headwear": "none", "glasses": "none", "pointed_ears": True,
          "hair_color": "silver-lavender", "earring_left": True, "earring_right": False,
          "top_layers": [{"item": "apron", "color": "dark brown"}]}
    ids = lambda vid: {c.id for c in sc.checks_for_view(pr[vid], cl)}  # noqa: E731
    for vid in ("full_front", "full_side", "close_front", "close_side"):
        assert {"pointed_ears", "hair_color"} <= ids(vid)
    assert "pointed_ears" not in ids("close_back") and "hair_color" in ids("close_back")
    assert "earrings_both" in ids("close_front") and "earrings_both" not in ids("close_side")
    no = dict(cl, pointed_ears=False, hair_color=None)
    assert not {"pointed_ears", "hair_color"} & {c.id for c in sc.checks_for_view(pr["full_front"], no)}
    # a lost elf ear outranks a missed tiny earring in the best-try ranking
    ear = [{"id": "pointed_ears", "passed": False}]
    ring = [{"id": "earrings_both", "passed": False}]
    assert sc.failure_weight(ear, True) > sc.failure_weight(ring, True)


def test_close_ups_check_the_waist_is_out_of_frame_and_aprons_are_extracted():
    pr = {v["id"]: v for v in cs.load_preset()["views"]}
    cl = {"gender_word": "woman", "headwear": "none", "glasses": "none",
          "top_layers": [{"item": "apron", "color": "dark brown"}, {"item": "sweater", "color": "cream"}]}
    for vid in ("close_front", "close_side", "close_back"):
        c = {c.id: c for c in sc.checks_for_view(pr[vid], cl)}["framing_waist"]
        assert c.expect is False and "upper chest" in c.fix
    assert "framing_waist" not in {c.id for c in sc.checks_for_view(pr["full_front"], cl)}
    back = {c.id for c in sc.checks_for_view(pr["full_back"], cl)}
    assert "top:apron" in back and "top:sweater" not in back  # outermost layer is the one seen from behind
    assert "apron" in sc.EXTRACT_PROMPT and "OUTERMOST first" in sc.EXTRACT_PROMPT


def test_reused_views_are_checked_in_one_vlm_round(tmp_path):
    """--reuse-from: the kept views are re-checked together (one VLM load), not one load per view."""
    calls, vlm = [], MockVLM()
    keep = tmp_path / "keep"
    keep.mkdir()
    reuse = {}
    for vid in ("full_front", "full_side", "full_back"):
        p = keep / f"{vid}.png"
        shutil.copy2(REF, p)
        p.with_suffix(".txt").write_text("CORRECTIONS Only ONE earbud BACKWARDS no strap or strap opening")
        p.with_suffix(".view").write_text(vid)
        p.with_suffix(".src").write_text("")
        reuse[vid] = p
    cs.make_character_sheet(REF, tmp_path / "out", consent=True, dry_run=False, gate_mode="local", reuse=reuse,
                            runner=_autofix_runner(calls), vlm=vlm, use_arcface=False, max_parallel=1)
    assert {c[0] for c in calls} == {"close_front", "close_side", "close_back"}
    reused_rounds = [i for i, (view, _) in enumerate(vlm.asked) if view.startswith("full_")]
    assert reused_rounds == [0, 1, 2]
    # 1 release after the checklist + 1 for the reused round + 1 per render round (close views only)
    render_rounds = len({c[1] - cs.view_seed(next(v for v in cs.load_preset()["views"] if v["id"] == c[0]),
                                              cs.load_preset(), None, 0) for c in calls})
    assert vlm.released == 2 + render_rounds


def test_close_ups_from_a_full_body_reference_start_from_a_head_crop(tmp_path):
    calls = []
    tall = tmp_path / "tall.png"
    Image.new("RGB", (400, 600), (180, 170, 160)).save(tall)
    cl = dict(CAP_CHARACTER)  # has footwear -> the reference shows the whole figure
    cs.make_character_sheet(tall, tmp_path / "out", consent=True, dry_run=False, gate_mode="local",
                            runner=_autofix_runner(calls), vlm=MockVLM(), checklist=cl, use_arcface=False,
                            max_parallel=1)
    pr = cs.load_preset()
    box = pr["close_ref_crop"]["box"]
    # the runner copies the image it was given, so each view's first try shows what the model saw
    out = tmp_path / "out" / "views"
    for vid in ("close_front", "close_side"):
        assert Image.open(next((out / f"{vid}_try0").glob("*.png"))).size == (
            round(box[2] * 400) - round(box[0] * 400), round(box[3] * 600) - round(box[1] * 600))
    assert Image.open(next((out / "full_front_try0").glob("*.png"))).size == (400, 600)
    # a portrait reference (no footwear) is used as is for the close-ups
    assert not cs.is_full_body_reference(tall, dict(cl, footwear=None), pr["close_ref_crop"])
    sq = tmp_path / "sq.png"
    Image.new("RGB", (400, 420)).save(sq)
    assert not cs.is_full_body_reference(sq, None, pr["close_ref_crop"])
    assert cs.is_full_body_reference(tall, None, pr["close_ref_crop"])


class LooseCropVLM:
    """Gives the expected answer to every check, except that close-ups are waist-up until cropped (the Lumi case)."""

    def __init__(self, checklist):
        self.expect = {c.question: c.expect for v in cs.load_preset()["views"] for c in sc.checks_for_view(v, checklist)}
        self.released = 0

    def describe_json(self, image, prompt):
        raise AssertionError("checklist is given")

    def ask(self, image, questions):
        cropped = "_chestcrop" in Path(image).name
        return [(not cropped) if "waist visible" in q else self.expect[q] for q in questions]

    def release(self):
        self.released += 1


def test_close_up_that_only_fails_its_crop_is_cut_to_chest_up_and_rechecked(tmp_path):
    cl = dict(CAP_CHARACTER)
    pr = cs.load_preset()
    pr.pop("back_fallback")
    pr["gate"]["threshold"] = 0.5  # the toy reference is a flat robot image; this test is about the crop step
    res = cs.make_character_sheet(REF, tmp_path / "o", consent=True, dry_run=False, gate_mode="local",
                                  runner=_autofix_runner([]), vlm=LooseCropVLM(cl), checklist=cl, preset=pr,
                                  use_arcface=False, max_parallel=1)
    by = {v.id: v for v in res.views}
    size = Image.open(REF).size
    for vid in ("close_front", "close_side", "close_back"):
        vr = by[vid]
        assert vr.passed and vr.tries[-1]["strategy"] == "chest_crop" and vr.attempts == 3, vr.tries
        assert all(t["failed"] == ["framing_waist"] for t in vr.tries[:-1])
    assert Image.open(by["close_front"].path).size == Image.open(next((tmp_path / "o/views/close_front_try0").glob("*.png"))).size
    for vid in ("full_front", "full_side", "full_back"):
        assert by[vid].passed and by[vid].attempts == 1 and all(t.get("strategy") != "chest_crop" for t in by[vid].tries)
    assert size


def test_apron_is_not_expected_in_a_chest_up_back_view():
    pr = {v["id"]: v for v in cs.load_preset()["views"]}
    cl = {"gender_word": "woman", "headwear": "none", "glasses": "none",
          "top_layers": [{"item": "apron", "color": "dark brown"}, {"item": "sweater", "color": "cream"}]}
    assert "top:apron" not in {c.id for c in sc.checks_for_view(pr["close_back"], cl)}
    assert "top:apron" in {c.id for c in sc.checks_for_view(pr["full_back"], cl)}
    assert "top:apron" in {c.id for c in sc.checks_for_view(pr["close_front"], cl)}


def test_subtle_ears_checked_in_every_view_and_overrides_win(tmp_path):
    pr = {v["id"]: v for v in cs.load_preset()["views"]}
    cl = {"gender_word": "woman", "headwear": "none", "glasses": "none", "pointed_ears": True, "ear_style": "subtle"}
    for vid in pr:
        checks = {c.id: c for c in sc.checks_for_view(pr[vid], cl)}
        assert "ears_too_long" in checks and checks["ears_too_long"].expect is False  # back views too
        assert "small, short pointed ear tip" in checks["ears_too_long"].fix and "spike" not in checks["ears_too_long"].fix
        assert checks["ears_stick_out"].expect is False
    front = {c.id: c for c in sc.checks_for_view(pr["full_front"], cl)}
    assert "long" not in front["pointed_ears"].question and front["pointed_ears"].fix == sc.SUBTLE_EARS_FIX
    assert "ears_too_long" not in {c.id for c in sc.checks_for_view(pr["full_front"], dict(cl, ear_style=None))}
    assert sc.failure_weight([{"id": "ears_too_long", "passed": False}], True) == 2.0
