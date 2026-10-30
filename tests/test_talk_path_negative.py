"""The a2v talk path (workflow 04b) runs its guider at video_cfg = audio_cfg = 1.0. At cfg 1 ComfyUI falls back to the
plain CFG guider and skips the unconditional pass, so 04b's negative prompt is never evaluated (adding negatives gave
framemd5-identical output). While that holds, the app must not offer a negative prompt as a control on that path,
and no doc may say the negatives steer the talking shot (the grin). If the cfg ever changes, this fails: revisit."""
import json
import re
from pathlib import Path

from opensoul import lipsync as L
from opensoul.presets import NODE_NEGATIVE, build_shot_plan

ROOT = Path(__file__).resolve().parents[1]
WF = json.loads((ROOT / L.A2V_WORKFLOW).read_text())
NOTE = "Not used at this guidance setting"


def _cfg():
    g = WF[L.N_GUIDER]["inputs"]
    return float(g["video_cfg"]), float(g["audio_cfg"])


def test_04b_guider_is_pinned_at_cfg_one():
    assert WF[L.N_GUIDER]["class_type"] == "LTXVDualCFGGuider"
    assert _cfg() == (1.0, 1.0) and L.GUIDER_CFG == {"video_cfg": 1.0, "audio_cfg": 1.0}, (
        "04b's guidance changed: its negative prompt may now be live. Revisit tests/test_talk_path_negative.py and "
        "decide whether the talk path should offer it.")


def test_talk_path_offers_no_negative_control_while_cfg_is_one():
    assert _cfg() == (1.0, 1.0)
    # the a2v stage never patches the negative node, so nothing the user types can reach it
    st = L.a2v_stage(prompt="x", audio_s=2.0, seed=1)
    assert NODE_NEGATIVE not in st["inputs"] and not any("negative" in str(k).lower() for v in st["inputs"].values() for k in v)
    plan = build_shot_plan(camera="static", line="Hi there", lipsync_backend="ltx_av")
    vid = next(s for s in plan["stages"] if s["stage"] == "video")
    assert vid["workflow"] == L.A2V_WORKFLOW and NODE_NEGATIVE not in vid["inputs"]
    # the UI: any negative-prompt field must be hidden on the talk path with the short note
    for f in [*(ROOT / "app/web").glob("*.html"), *(ROOT / "app/web/static").glob("*.js")]:
        t = f.read_text(encoding="utf-8")
        for m in re.finditer(r"negative", t, re.I):
            around = t[max(0, m.start() - 400): m.end() + 400]
            assert NOTE in around, f"{f.name}: a negative-prompt control near the talk path needs '{NOTE}'"
    # the API: neither a shot request nor its Advanced overrides can carry a negative
    from app.server import ShotRequest

    assert not any("neg" in k for k in ShotRequest.model_fields)
    plan = build_shot_plan(camera="static", line="Hi there", lipsync_backend="ltx_av", overrides={"negative": "grin"})
    assert "grin" not in json.dumps(next(s for s in plan["stages"] if s["stage"] == "video"))


def test_no_doc_says_the_negatives_control_the_talking_shot():
    talk = re.compile(r"\b(grin\w*|talk\w*|a2v|04b|lip-?sync\w*|lips|mouth|speak\w*)\b", re.I)
    ok = re.compile(r"never evaluate|not a control|not used|isn't used|no effect", re.I)
    files = [ROOT / "README.md", *(ROOT / "docs").rglob("*.md"), *(ROOT / "presets").rglob("*.md")]
    for f in files:
        t = f.read_text(encoding="utf-8")
        for m in re.finditer(r"negative", t, re.I):
            near = t[max(0, m.start() - 200): m.end() + 200]  # the same sentence or the next one
            if talk.search(near):
                assert ok.search(t[max(0, m.start() - 400): m.end() + 400]), f"{f.relative_to(ROOT)}: {near}"
