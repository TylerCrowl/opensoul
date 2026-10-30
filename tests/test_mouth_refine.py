"""Review ruling: LatentSync Stage 2 pales the lips on camera-locked (AddGuide) bases, so it is OFF by default on
those takes, rebuilt characters and voice F included. 'Mouth refine (LatentSync), may pale lips' opts a shot in;
OPENSOUL_MOUTH_REFINE=on opts every shot in."""
from __future__ import annotations

import pytest

from opensoul import lipsync as L
from opensoul import storyboard as sb


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k in ("OPENSOUL_A2V_CAMLOCK", "OPENSOUL_MOUTH_REFINE", "OPENSOUL_L1C_STAGE2"):
        monkeypatch.delenv(k, raising=False)


def _stage2(voice="F", rebuilt=True, **kw):
    st, notes, _ = L.dialogue_stages(line="Have a good night.", voice=voice, quality="final", backend="ltx_av",
                                     prompt="Lumi waves", speaker="Lumi", seed=77, pronoun="she", best_of=3,
                                     latentsync_installed=True, listener="Ren", rebuilt=rebuilt, **kw)
    assert st[1]["cam_lock"] is True  # camera lock is the default a2v graph
    return next(x for x in st if x.get("only_if") == L.ONLY_IF_L1C_STAGE2), notes


PASSING = {"status": "ok", "stage1_passes_all_gates": False, "seeds": [{"chosen": True, "gate_reasons": ["offset"]}]}


def test_camera_locked_takes_keep_stage2_off_by_default():
    s2, notes = _stage2()
    assert s2["stage2_default_on"] is False and s2["stage2_mode"] == "off" and s2["mouth_refine"] is False
    run, why = L.l1c_stage2_decision(PASSING, s2)  # even a base that fails a check isn't re-mouthed
    assert run is False and "pales the lips" in why and L.MOUTH_REFINE_LABEL in why
    assert any("pales the lips" in n for n in notes)


def test_mouth_refine_opts_a_shot_in(monkeypatch):
    s2, _ = _stage2(mouth_refine=True)
    assert s2["stage2_default_on"] and s2["stage2_mode"] == "on" and s2["mouth_refine"]
    assert L.l1c_stage2_decision(PASSING, s2)[0] is True
    monkeypatch.setenv("OPENSOUL_MOUTH_REFINE", "on")  # the env override opts every shot in
    assert _stage2(voice="tara", rebuilt=False)[0]["stage2_mode"] == "on"


def test_shot_field_round_trips_and_defaults_off():
    assert sb.Shot.__dataclass_fields__["mouth_refine"].default is False
    assert sb.clean_dialogue({"mouth_refine": 1}) == {"mouth_refine": True}
    assert L.MOUTH_REFINE_LABEL == "Mouth refine (LatentSync), may pale lips"
