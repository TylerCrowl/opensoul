"""L1c stage 2 (the LatentSync mouth pass) is on by default for any rebuilt character's ltx_av talk take, whatever the
voice id (rebuilt = the best-of test: pack rebuilt: true, or meta.origin.kind == 'text'). Characters that aren't
rebuilt keep the voice list (F and its aliases); the take note says why stage 2 ran; the env overrides still work."""
import json
from pathlib import Path

import pytest

from opensoul import lipsync as L

def _patch_cam_pass(monkeypatch):
    monkeypatch.setattr(L, "score_cam", lambda v, face_box=None, cfg_cam=None: {
        "cam_verdict": "PASS", "scale_drift_max_pct": 0.01, "trans_max_px": 0.1, "video": str(v)})

from test_lipsync_l1c import FakeLS, FakeTTS, FakeVideo, m, needs_ffmpeg

ROOT = Path(__file__).resolve().parents[1]
REBUILT = "on by default for rebuilt characters"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in (L.RECIPE_ENV, L.STAGE2_ENV, L.STAGE2_VOICES_ENV, L.STAGE2_REBUILT_ENV, L.INNER_MOUTH_ENV, L.BEST_OF_ENV):
        monkeypatch.delenv(k, raising=False)


def _plan(voice="tara", rebuilt=True):
    st, notes, _mode = L.dialogue_stages(line="Have a good night.", voice=voice, quality="final", backend="ltx_av",
                                         prompt="Lumi waves", speaker="Lumi", seed=77, pronoun="she", best_of=3,
                                         latentsync_installed=True, listener="Ren", rebuilt=rebuilt)
    return st, notes


def _passing():
    return L.choose_base([{"seed": 7, "file": "s7.mp4", "error": None, "metrics": m(6.0)}])


def test_preset_turns_it_on_for_rebuilt_characters():
    s2 = L.best_of_config().l1c["stage2"]
    assert s2["default_on_rebuilt"] is True and s2["default_on_voices"] == ["F"]
    assert s2["voice_aliases"]["F"] == ["clip_F", "revoice_F", "qwen3_F"]
    assert "default_on_rebuilt" in json.loads((ROOT / "presets/lipsync_best_of.json").read_text())["l1c"]["_doc"]


@pytest.mark.parametrize("voice,rebuilt,why", [
    ("tara", True, REBUILT),
    ("leo", True, REBUILT),
    ("", True, REBUILT),
    ("clip_F", True, REBUILT + " (voice F (clip_F))"),
    ("F", True, REBUILT + " (voice F)"),
    ("clip_F", False, "on by default for voice F (clip_F)"),
    ("F", False, "on by default for voice F"),
    ("tara", False, ""),
])
def test_why_stage2_is_on(voice, rebuilt, why):
    assert L.stage2_default_why(voice, rebuilt) == why
    st, notes = _plan(voice, rebuilt)
    s2 = st[-1]
    assert s2["only_if"] == L.ONLY_IF_L1C_STAGE2 and s2["rebuilt"] is rebuilt
    assert s2["stage2_default_on"] is bool(why) and s2["stage2_default_why"] == why
    assert s2["voice"] == voice and s2["voice_canonical"] == L.voice_canonical(voice)
    note = next(n for n in notes if n.startswith("L1c mouth pass"))
    assert note.endswith(f"{why}.") if why else note.endswith("runs only if the base fails a check.")


def test_rebuilt_runs_even_when_the_base_passes_and_others_still_skip():
    good = _passing()
    assert good["stage1_passes_all_gates"]
    assert L.l1c_stage2_decision(good, _plan("tara", True)[0][-1]) == (True, REBUILT)
    assert L.l1c_stage2_decision(good, _plan("qwen3_F", True)[0][-1]) == (True, REBUILT + " (voice F (qwen3_F))")
    assert L.l1c_stage2_decision(good, _plan("tara", False)[0][-1]) == (False, "stage 1 already passes every check")
    assert L.l1c_stage2_decision(good, _plan("revoice_F", False)[0][-1]) == (True, "on by default for voice F (revoice_F)")
    # unchanged: a dry run, or no base passing the look checks, never runs it
    st = _plan("tara", True)[0][-1]
    assert not L.l1c_stage2_decision({"status": "dry_run"}, st)[0]
    grin = L.choose_base([{"seed": 7, "file": "s7.mp4", "error": None, "metrics": m(6.0, grin=0.9)}])
    assert not L.l1c_stage2_decision(grin, st)[0]


def test_env_overrides_still_work(monkeypatch):
    good = _passing()
    monkeypatch.setenv(L.STAGE2_ENV, "off")
    assert L.l1c_stage2_decision(good, {**_plan("tara", True)[0][-1], "stage2_mode": None}) == (False, "off by setting")
    monkeypatch.setenv(L.STAGE2_ENV, "on")
    assert L.l1c_stage2_decision(good, {**_plan("tara", False)[0][-1], "stage2_mode": None}) == (True, "on by setting")
    monkeypatch.delenv(L.STAGE2_ENV)
    monkeypatch.setenv(L.STAGE2_REBUILT_ENV, "off")   # back to the voice list for rebuilt characters too
    assert L.stage2_default_why("tara", True) == "" and not _plan("tara", True)[0][-1]["stage2_default_on"]
    assert L.stage2_default_why("clip_F", True) == "on by default for voice F (clip_F)"
    monkeypatch.setenv(L.STAGE2_REBUILT_ENV, "on")
    monkeypatch.setenv(L.STAGE2_VOICES_ENV, "tara")
    assert L.stage2_default_why("tara", False) == "on by default for voice tara"
    assert L.stage2_default_why("leo", True) == REBUILT


@pytest.mark.parametrize("pack,rebuilt", [({"rebuilt": True}, True), ({"meta": {"origin": {"kind": "text"}}}, True),
                                          ({"meta": {"rebuilt": True}}, True),
                                          ({"rebuilt": False, "meta": {"origin": {"kind": "text"}}}, False),
                                          ({}, False)])
def test_storyboard_uses_the_best_of_rebuilt_test(monkeypatch, pack, rebuilt):
    import app.storyboard_api as A
    from opensoul import storyboard as sb

    monkeypatch.setattr(L, "scorer_enabled", lambda: True)  # best-of needs the scorer (OS-057)
    monkeypatch.setenv(L.BEST_OF_ENV, "on")   # best-of for everyone, so the stage-2 default alone is under test
    monkeypatch.setattr(A, "_speaker_pack", lambda who: pack)
    monkeypatch.setattr(A, "_shot_voice", lambda s: ("tara", "character"))
    monkeypatch.setattr(L, "latentsync_installed", lambda: True)
    s = sb.Shot(id="s1", beat="b", characters=["Lumi"], line="Have a good night.", speaker="Lumi")
    d = A._dialogue(s, prompt="p", quality="final", seed=1, size=(704, 1280), position=1)
    lip = next(x for x in d["stages"] if x.get("only_if") == L.ONLY_IF_L1C_STAGE2)
    assert lip["rebuilt"] is rebuilt and d["stage2_default_on"] is rebuilt
    assert d["stage2_default_why"] == (REBUILT if rebuilt else "")


@needs_ffmpeg
def test_run_shot_rebuilt_any_voice_runs_the_mouth_pass_over_a_passing_base(tmp_path, monkeypatch):
    from opensoul import shot as S

    monkeypatch.setenv("OPENSOUL_DRY_RUN", "0")
    _patch_cam_pass(monkeypatch)
    st, notes = _plan("tara", True)
    ls = FakeLS()
    res = S.run_shot({"stages": st, "notes": notes}, tmp_path / "still.png", tmp_path / "take",
                     video_backend=FakeVideo(), tts=FakeTTS(), lipsync=ls, motion_check=False,
                     scorer=lambda v: m(6.0))
    assert len(ls.ran) == 1 and res.video.name == "latentsync.mp4"
    side = json.loads(Path(str(res.video) + ".best_of.json").read_text())
    assert side["stage1"]["passes_all_gates"] is True and side["stage2"]["ran"] is True
    assert side["stage2"]["decision"] == REBUILT
    note = next(n for n in res.notes if n.startswith("L1c mouth pass: LatentSync"))
    assert f"Ran because: {REBUILT}." in note


def test_documented():
    doc = (ROOT / "docs" / "LIPSYNC_SCORER.md").read_text(encoding="utf-8")
    assert "default_on_rebuilt" in doc and "OPENSOUL_L1C_STAGE2_REBUILT" in doc and "rebuilt characters" in doc
    assert 'meta.origin.kind == "text"' in doc and "stage2_default_why" in doc


@pytest.fixture(autouse=True)
def _no_cam_lock(monkeypatch):
    # These cover the Stage 2 defaults (rebuilt / voice F / a failing base). Since the review ruling, a
    # camera-locked (AddGuide) take keeps Stage 2 off unless 'Mouth refine' is ticked (tests/test_mouth_refine.py),
    # so they run on the takes the defaults still apply to: camera lock off.
    monkeypatch.setenv("OPENSOUL_A2V_CAMLOCK", "off")
