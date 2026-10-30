"""L1c stage 2 is on by default for voice F; 'clip_F', 'revoice_F' and 'qwen3_F' (any case) are aliases of it."""
from pathlib import Path

import pytest

from opensoul import lipsync as L

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in (L.RECIPE_ENV, L.STAGE2_ENV, L.STAGE2_VOICES_ENV, L.INNER_MOUTH_ENV, L.BEST_OF_ENV):
        monkeypatch.delenv(k, raising=False)


def _stage(voice):
    st, _n, _m = L.dialogue_stages(line="Hi there.", voice=voice, quality="final", backend="ltx_av", prompt="p",
                                   speaker="Lumi", seed=1, best_of=3, latentsync_installed=True)
    return st[-1]


def _passing_base():
    return L.choose_base([{"seed": 7, "file": "s7.mp4", "error": None,
                           "metrics": {"lse_c": 6.0, "offset": 0, "open_frac": 0.8, "grin_frac": 0.1,
                                       "grin_win_max": 0.05, "eyes_open_frac": 0.9}}])


def test_f_is_canonical_and_the_aliases_are_in_the_preset():
    s2 = L.best_of_config().l1c["stage2"]
    assert s2["default_on_voices"] == ["F"]
    assert s2["voice_aliases"]["F"] == ["clip_F", "revoice_F", "qwen3_F"]


@pytest.mark.parametrize("voice", ["F", "f", "clip_F", "CLIP_f", "revoice_F", "Revoice_f", "qwen3_F", "QWEN3_F",
                                   " qwen3_f "])
def test_aliases_count_as_voice_f_case_insensitive(voice):
    assert L.voice_canonical(voice) == "F"
    assert L.stage2_default_on(voice)
    st = _stage(voice)
    assert st["stage2_default_on"] and st["voice"] == voice and st["voice_canonical"] == "F"


@pytest.mark.parametrize("voice", ["tara", "", "clip_G", "F2", "qwen3_FF", "clipF"])
def test_other_voices_are_not_aliases(voice):
    assert not L.stage2_default_on(voice)
    assert L.voice_canonical(voice) == voice.strip()


def test_the_take_note_names_the_canonical_voice_and_the_alias():
    good = _passing_base()
    assert L.l1c_stage2_decision(good, _stage("clip_F")) == (True, "on by default for voice F (clip_F)")
    assert L.l1c_stage2_decision(good, _stage("F")) == (True, "on by default for voice F")
    assert L.l1c_stage2_decision(good, _stage("tara"))[0] is False


def test_voice_list_setting_keeps_the_aliases_of_a_listed_voice(monkeypatch):
    monkeypatch.setenv(L.STAGE2_VOICES_ENV, "tara")
    assert not L.stage2_default_on("qwen3_F") and L.stage2_default_on("tara")
    monkeypatch.setenv(L.STAGE2_VOICES_ENV, "F,tara")
    assert L.stage2_default_on("revoice_F") and L.stage2_default_on("TARA")


def test_aliases_are_documented():
    doc = (ROOT / "docs" / "LIPSYNC_SCORER.md").read_text(encoding="utf-8")
    assert all(a in doc for a in ("`clip_F`", "`revoice_F`", "`qwen3_F`", "voice_canonical"))


@pytest.fixture(autouse=True)
def _no_cam_lock(monkeypatch):
    # These cover the Stage 2 defaults (rebuilt / voice F / a failing base). Since the review ruling, a
    # camera-locked (AddGuide) take keeps Stage 2 off unless 'Mouth refine' is ticked (tests/test_mouth_refine.py),
    # so they run on the takes the defaults still apply to: camera lock off.
    monkeypatch.setenv("OPENSOUL_A2V_CAMLOCK", "off")
