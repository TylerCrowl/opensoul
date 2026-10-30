"""Pack voice_label (lip-sync metadata only; the TTS never reads it) and the scorer's eyeline_drift_warn flag."""
import json
from pathlib import Path

import pytest

from opensoul import lipsync as L
from opensoul import shot as S

ROOT = Path(__file__).resolve().parents[1]
W = L.EYELINE_WARNING
NOTES = {"engine": "an open TTS model", "license": "Apache-2.0"}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in (L.RECIPE_ENV, L.STAGE2_ENV, L.STAGE2_VOICES_ENV, L.STAGE2_REBUILT_ENV, L.INNER_MOUTH_ENV, L.BEST_OF_ENV):
        monkeypatch.delenv(k, raising=False)


def m(c=6.0, **kw):
    d = {"lse_c": c, "lse_d": 7.0, "offset": 0, "open_frac": 0.8, "grin_frac": 0.1, "grin_win_max": 0.05,
         "eyes_open_frac": 0.9}
    d.update(kw)
    return d


# ---------------------------------------------------------------- voice_label
@pytest.mark.parametrize("pack,label,canon", [
    ({"voice_label": "F"}, "F", "F"),
    ({"voice_label": " clip_F "}, "clip_F", "F"),
    ({"meta": {"voice_label": "qwen3_f"}}, "qwen3_f", "F"),
    ({"voice_label": "tara"}, "tara", "tara"),
])
def test_voice_label_resolves_through_the_aliases(pack, label, canon):
    vl = L.voice_label_of(pack)
    assert vl["voice_label"] == label and vl["voice_canonical"] == canon


@pytest.mark.parametrize("pack", [None, {}, {"voice_label": ""}, {"voice_label": 3}, {"meta": "x"}])
def test_no_label_is_empty(pack):
    assert L.voice_label_of(pack) == {}


def test_both_notes_key_names_are_accepted():
    assert L.voice_label_of({"voice_label": "F", "voice_label_notes": NOTES})["voice_label_notes"] == NOTES
    assert L.voice_label_of({"voice_label": "F", "voice_notes": NOTES})["voice_label_notes"] == NOTES
    assert L.voice_label_of({"voice_label": "F"})["voice_label_notes"] is None


def _plan(rebuilt, label="F", voice="tara"):
    return L.dialogue_stages(line="Have a good night.", voice=voice, quality="final", backend="ltx_av", prompt="p",
                             speaker="Lumi", seed=7, best_of=3, latentsync_installed=True, listener="Ren",
                             rebuilt=rebuilt, voice_meta=L.voice_label_of({"voice_label": label,
                                                                           "voice_label_notes": NOTES}))


def test_tts_keeps_the_voice_and_records_get_the_label():
    st, notes, _ = _plan(rebuilt=False)
    assert st[0]["stage"] == "voice" and st[0]["inputs"]["voice"] == "tara" and "voice_label" not in st[0]
    assert st[1]["voice_label"] == "F" and st[1]["voice_canonical"] == "F"
    lip = st[-1]
    assert lip["voice"] == "tara" and lip["voice_label"] == "F" and lip["voice_canonical"] == "F"
    assert lip["voice_label_notes"] == NOTES
    assert "Lip-sync voice label: F (metadata; the voice is made with tara)." in notes


def test_stage2_reasoning_names_the_label():
    st, _, _ = _plan(rebuilt=False)
    assert st[-1]["stage2_default_on"] and st[-1]["stage2_default_why"] == "on by default for voice F (voice_label F)"
    st, _, _ = _plan(rebuilt=True)
    assert st[-1]["stage2_default_why"] == "on by default for rebuilt characters (voice F (voice_label F))"
    good = L.choose_base([{"seed": 7, "file": "s7.mp4", "metrics": m()}])
    assert L.l1c_stage2_decision(good, st[-1]) == (True, st[-1]["stage2_default_why"])
    st, _, _ = _plan(rebuilt=False, label="tara", voice="leo")  # a label outside the voice list changes nothing
    assert not st[-1]["stage2_default_on"] and st[-1]["voice_canonical"] == "tara"
    st, notes, _ = L.dialogue_stages(line="Hi.", voice="tara", quality="final", backend="ltx_av", prompt="p",
                                     speaker="Lumi", seed=7, best_of=3, latentsync_installed=True)
    assert st[-1]["voice_label"] is None and st[-1]["voice_canonical"] == "tara"
    assert not any(n.startswith("Lip-sync voice label") for n in notes)


def test_character_voice_resolution_ignores_the_label(tmp_path):
    from opensoul.character_voices import voice_for, voice_for_shot

    (tmp_path / "packs" / "Lumi").mkdir(parents=True)
    (tmp_path / "packs" / "Lumi" / "pack.json").write_text(json.dumps({"name": "Lumi", "voice_label": "F"}))
    assert voice_for(tmp_path, "Lumi") == "tara" and voice_for_shot(tmp_path, "Lumi") == ("tara", "character")
    assert not (tmp_path / "character_voices.json").exists()


def test_storyboard_dialogue_and_cast_show_the_label_read_only(monkeypatch):
    import app.storyboard_api as A
    from opensoul import storyboard as sb

    monkeypatch.setattr(A, "_speaker_pack", lambda who: {"rebuilt": True, "voice_label": "F",
                                                         "voice_label_notes": NOTES})
    monkeypatch.setattr(L, "scorer_enabled", lambda: True)  # best-of needs the scorer (OS-057)
    monkeypatch.setattr(A, "_shot_voice", lambda s: ("tara", "character"))
    monkeypatch.setattr(L, "latentsync_installed", lambda: True)
    s = sb.Shot(id="s1", beat="b", characters=["Lumi"], line="Have a good night.", speaker="Lumi")
    d = A._dialogue(s, prompt="p", quality="final", seed=1, size=(704, 1280), position=1)
    assert d["voice"] == "tara" and d["voice_label"] == "F" and d["voice_canonical"] == "F"
    assert d["stages"][0]["inputs"]["voice"] == "tara"
    lip = next(x for x in d["stages"] if x.get("only_if") == L.ONLY_IF_L1C_STAGE2)
    assert lip["voice_canonical"] == "F" and d["stage2_default_on"]
    monkeypatch.setattr(A, "_card", lambda name: {})
    card = A._cast_json({"name": "Lumi", "prompt_lock": "", "voice_label": "F"})
    assert card["voice_label"] == "F" and card["voice"] != "F"
    js = (ROOT / "app/web/static/storyboard.js").read_text()
    assert "c.voice_label" in js and "lip-sync label:" in js


def test_take_record_carries_the_voice_block(tmp_path):
    st, _, _ = _plan(rebuilt=True)
    res = L.choose_base([{"seed": 7, "file": "s7.mp4", "metrics": m()}])
    res["stage2"] = {"ran": False}
    out = {}
    S._write_l1c_record(res, tmp_path / "t.mp4", lambda r, f: r, lambda p, r: out.update(rec=r), st[-1])
    v = out["rec"]["voice"]
    assert v["voice"] == "tara" and v["voice_label"] == "F" and v["voice_canonical"] == "F"
    assert v["voice_label_notes"] == NOTES and v["rebuilt"] is True


# ---------------------------------------------------------------- eyeline_drift_warn
def test_scorer_flag_wins_both_ways():
    assert L.eyeline_of({"eyeline_drift_warn": True, "start_eye_look_listener": 0.9, "end_eye_look_listener": 0.9})[
        "warn"] is True
    e = L.eyeline_of({"eyeline_drift_warn": False, "start_eye_look_listener": 0.68, "end_eye_look_listener": 0.19})
    assert e["warn"] is False and e["from"] == "scorer_flag" and e["drop"] == 0.49 and e["scorer_flag"] is False


def test_flag_alone_and_binary_frames_with_nulls():
    e = L.eyeline_of({"eyeline_drift_warn": True})
    assert e["warn"] and e["start"] is None and e["end"] is None and e["drop"] is None
    frames = [1, 1, None, 1, 1, 1] + [1] * 36 + [None, 0, 0, 0, None, 0]
    e = L.eyeline_of({"eye_look_listener_frames": frames, "fps": 24})
    assert e["from"] == "frames" and e["start"] == 1.0 and e["end"] == 0.0 and e["warn"]
    e = L.eyeline_of({"eye_look_listener_frames": frames, "fps": 24, "eyeline_drift_warn": False})
    assert e["warn"] is False and e["end"] == 0.0
    assert L.eyeline_of({"eye_look_listener_frames": [None] * 10, "fps": 24}) is None
    assert L.eyeline_of({"eyeline_drift_warn": None}) is None   # not a bool: ignored, no data -> skipped
    assert L.best_of_config().field("eyeline_drift_warn") == "eyeline_drift_warn"


def test_scorer_flag_is_still_warn_only():
    res = L.choose_base([{"seed": 1, "file": "a.mp4", "metrics": m(eyeline_drift_warn=True)},
                         {"seed": 2, "file": "b.mp4", "metrics": m(5.0)}])
    assert res["status"] == "picked" and res["seed"] == 1 and not res["needs_review"] and W in res["warnings"]
    assert not res["seeds"][0]["rejected"] and not res["latentsync_fallback_allowed"]


def test_documented():
    doc = (ROOT / "docs" / "LIPSYNC_SCORER.md").read_text(encoding="utf-8")
    assert "eyeline_drift_warn" in doc and "the scorer wins" in doc
    assert "`voice_label`" in doc and "`voice_label_notes`" in doc and "`voice_notes`" in doc
    assert "The TTS never reads it" in doc


@pytest.fixture(autouse=True)
def _no_cam_lock(monkeypatch):
    # These cover the Stage 2 defaults (rebuilt / voice F / a failing base). Since the review ruling, a
    # camera-locked (AddGuide) take keeps Stage 2 off unless 'Mouth refine' is ticked (tests/test_mouth_refine.py),
    # so they run on the takes the defaults still apply to: camera lock off.
    monkeypatch.setenv("OPENSOUL_A2V_CAMLOCK", "off")
