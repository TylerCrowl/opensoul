"""Camera lock is the default for a2v (ltx_av) talk takes: native LTXVAddGuide + LTXVCropGuides, cam gate after a2v
and again after LatentSync. METHOD ONLY / plan tests: no GPU, nothing queued. OPENSOUL_A2V_CAMLOCK=off restores the
old graph and skips the gate."""
import json
from pathlib import Path

import pytest

from opensoul import cam_lock as C
from opensoul import lipsync as L

ROOT = Path(__file__).resolve().parents[1]
A2V = json.loads((ROOT / L.A2V_WORKFLOW).read_text())


def _fail(scale=1.2, trans=5.0):
    return {"cam_verdict": "FAIL", "scale_drift_max_pct": scale, "trans_max_px": trans}


def _pass(scale=0.01, trans=0.1):
    return {"cam_verdict": "PASS", "scale_drift_max_pct": scale, "trans_max_px": trans}


def _seed(seed, metrics, cam=None):
    return {"seed": seed, "file": f"s{seed}.mp4", "metrics": metrics, "error": None, "cam": cam}


def _look(c=6.0, off=0, opn=0.8, grin=0.1, gwin=0.05, eyes=0.9, **kw):
    return {"lse_c": c, "lse_d": 7.0, "offset": off, "open_frac": opn, "grin_frac": grin, "grin_win_max": gwin,
            "grin_def": "v2_blendshape_smile", "eyes_open_frac": eyes, **kw}


# ---------------------------------------------------------------- graph
def test_cam_lock_default_on_and_env_off(monkeypatch):
    monkeypatch.delenv(C.CAMLOCK_ENV, raising=False)
    assert C.cam_lock_enabled() and L.cam_lock_enabled()
    assert L.a2v_stage(prompt="p", audio_s=1.0, seed=1)["cam_lock"] is True
    monkeypatch.setenv(C.CAMLOCK_ENV, "off")
    assert not C.cam_lock_enabled() and L.a2v_stage(prompt="p", audio_s=1.0, seed=1)["cam_lock"] is False
    monkeypatch.setenv(C.CAMLOCK_ENV, "0")
    assert not C.cam_lock_enabled()


def test_apply_cam_lock_adds_guide_with_frame_idx_neg1_strength_1_same_start_image():
    g = C.apply_cam_lock(A2V)
    assert C.is_cam_locked(g) and C.add_guide_ok(g)
    ag = g["93"]["inputs"]
    assert ag["frame_idx"] == -1 and ag["strength"] == 1.0 and ag["image"] == ["3", 0]
    assert g["31"]["inputs"]["strength"] == 0.85  # stage-1 i2v strength unchanged
    assert g["31"]["inputs"]["image"] == ["3", 0]  # same preprocess as the guide image
    assert g["33"]["inputs"]["video_latent"] == ["93", 2]
    assert g["34"]["inputs"]["positive"] == ["93", 0] and g["34"]["inputs"]["negative"] == ["93", 1]
    assert (g["34"]["inputs"]["video_cfg"], g["34"]["inputs"]["audio_cfg"]) == (1.0, 1.0)


def test_crop_guides_comes_before_the_upsampler_and_stage2_uses_cropped_conds():
    g = C.apply_cam_lock(A2V)
    assert C.crop_guides_before_upsampler(g)
    assert g["40"]["inputs"]["samples"] == ["94", 2]
    assert g["94"]["class_type"] == "LTXVCropGuides"
    assert g["95"]["class_type"] == "LTXVDualCFGGuider"
    assert g["95"]["inputs"]["positive"] == ["94", 0] and g["95"]["inputs"]["negative"] == ["94", 1]
    assert (g["95"]["inputs"]["video_cfg"], g["95"]["inputs"]["audio_cfg"]) == (1.0, 1.0)
    assert g["46"]["inputs"]["guider"] == ["95", 0]
    # SeparateAV still feeds CropGuides' latent
    assert g["94"]["inputs"]["latent"] == ["39", 0]


def test_override_restores_the_old_graph(monkeypatch):
    monkeypatch.setenv(C.CAMLOCK_ENV, "off")
    assert not L.a2v_stage(prompt="p", audio_s=1.0, seed=1)["cam_lock"]
    # The committed workflow file is the old graph (no AddGuide); render skips apply_cam_lock when cam_lock is false.
    assert "93" not in A2V and A2V["33"]["inputs"]["video_latent"] == ["31", 0]
    assert A2V["40"]["inputs"]["samples"] == ["39", 0]
    assert A2V["46"]["inputs"]["guider"] == ["34", 0]
    locked = C.apply_cam_lock(A2V)
    assert C.is_cam_locked(locked)
    # Applying is opt-in at render: with the override off, the stage does not ask for it.
    st = L.a2v_stage(prompt="p", audio_s=1.0, seed=1)
    assert st["cam_lock"] is False


def test_apply_cam_lock_is_idempotent_and_keeps_frozen_audio():
    g = C.apply_cam_lock(C.apply_cam_lock(A2V))
    assert L.frozen_audio_feeds(g) == {"33": True, "42": True}
    assert list(g["93"]["inputs"]["image"]) == ["3", 0]


# ---------------------------------------------------------------- stage-1 cam gate
def test_cam_gate_rejects_drift_over_0_5_pct_or_1_px_and_reseeds():
    # seed 77 cam-fails, 78 passes look+cam -> pick 78 (re-seed), never LatentSync on 77
    rows = [
        _seed(77, _look(c=9.0, eyes=0.99), _fail(scale=1.2, trans=0.1)),   # scale 1.2% > 0.5%
        _seed(78, _look(c=5.0, eyes=0.8), _pass()),
        _seed(79, _look(c=4.0, eyes=0.7), _pass()),
    ]
    r = L.choose_base(rows, cam_lock=True)
    assert r["status"] == "picked" and r["seed"] == 78 and r["order_seeds"] == [78, 79]
    assert any("camera drift" in x for x in r["seeds"][0]["reasons"])
    assert r["seeds"][0]["rejected"] and not r["seeds"][1]["rejected"]
    assert r["cam_lock"] is True and r["latentsync_fallback_allowed"] is False


def test_cam_gate_rejects_translation_over_1_px():
    rows = [_seed(1, _look(), _fail(scale=0.1, trans=1.5)), _seed(2, _look(eyes=0.5), _pass())]
    r = L.choose_base(rows, cam_lock=True)
    assert r["seed"] == 2 and any("camera drift" in x for x in r["seeds"][0]["reasons"])


def test_cam_verdict_thresholds_match_g8():
    assert C.cam_verdict_of(0.5, 1.0) == "PASS"   # at the limit: still pass (gate is >)
    assert C.cam_verdict_of(0.51, 0.0) == "FAIL"
    assert C.cam_verdict_of(0.0, 1.01) == "FAIL"
    assert C.cam_verdict_of(0.01, 0.10) == "PASS"


def test_cam_lock_off_skips_the_gate_even_when_cam_fails():
    rows = [_seed(1, _look(eyes=0.99), _fail(scale=9.0, trans=20.0)), _seed(2, _look(eyes=0.5), _pass())]
    r = L.choose_base(rows, cam_lock=False)
    assert r["seed"] == 1 and not r["seeds"][0]["rejected"]  # cam ignored; best eyes win


def test_missing_cam_when_lock_on_is_not_a_reject():
    # tests / dry-run may omit cam; only an explicit FAIL/ERROR rejects
    rows = [_seed(1, _look(eyes=0.9), None), _seed(2, _look(eyes=0.5), _pass())]
    r = L.choose_base(rows, cam_lock=True)
    assert r["seed"] == 1


# ---------------------------------------------------------------- post-LatentSync cam re-check
class _Fake:
    def __init__(self, cam_by_seed=None):
        self.cam_by_seed = cam_by_seed or {}
        self.calls = []

    def frames_of(self, p):
        return 50

    def trim(self, b, n, seed):
        return Path(f"trim_{seed}.mp4")

    def ls(self, t, seed):
        self.calls.append(("latentsync", seed))
        return Path(f"ls_{seed}.mp4"), None

    def im(self, synced, raw, seed):
        return Path(f"mouth_{seed}.mp4")

    def score(self, v, ref):
        return _look(c=7.0, grin=0.1)

    def cam(self, v):
        seed = int(str(v).split("_")[1].split(".")[0])
        return self.cam_by_seed.get(seed, _pass())


def test_post_latentsync_cam_fail_repicks_base_without_rerunning_other_settings():
    base = L.choose_base([_seed(77, _look(eyes=0.9), _pass()), _seed(78, _look(eyes=0.8), _pass()),
                          _seed(79, _look(eyes=0.7), _pass())], cam_lock=True)
    fake = _Fake(cam_by_seed={77: _fail(scale=2.0, trans=0.2), 78: _pass()})
    rec = L.run_l1c_stage2(base, audio_s=2.0, frames_of=fake.frames_of, trim=fake.trim, latentsync=fake.ls,
                           inner_mouth=fake.im, score=fake.score, cam=fake.cam, cam_lock=True)
    assert rec["kept_base_seed"] == 78 and rec["repicks"] == 1
    assert [c for c in fake.calls if c[0] == "latentsync"] == [("latentsync", 77), ("latentsync", 78)]
    assert rec["attempts"][0]["cam_fail"] and "camera drift after LatentSync" in rec["attempts"][0]["result"]
    assert rec["cam"]["cam_verdict"] == "PASS"
    assert "Camera after LatentSync: PASS" in L.l1c_note(rec)


def test_post_latentsync_cam_fail_on_every_base_keeps_first_and_flags():
    base = L.choose_base([_seed(77, _look(eyes=0.9), _pass()), _seed(78, _look(eyes=0.8), _pass())], cam_lock=True)
    fake = _Fake(cam_by_seed={77: _fail(), 78: _fail()})
    rec = L.run_l1c_stage2(base, audio_s=2.0, frames_of=fake.frames_of, trim=fake.trim, latentsync=fake.ls,
                           inner_mouth=None, score=fake.score, cam=fake.cam, cam_lock=True)
    assert rec["kept_base_seed"] == 77 and rec["needs_review"]
    assert any("camera drift" in r for r in rec["needs_review_reasons"])


def test_with_loras_updates_both_guiders_when_cam_locked():
    from opensoul.shot import with_loras

    g = C.apply_cam_lock(A2V)
    out = with_loras(g, [{"name": "cam.safetensors", "strength": 0.8}])
    assert out["34"]["inputs"]["model"] == ["70", 0]
    assert out["95"]["inputs"]["model"] == ["70", 0]


def test_dialogue_stages_note_mentions_camera_lock(monkeypatch):
    monkeypatch.delenv(C.CAMLOCK_ENV, raising=False)
    _st, notes, _mode = L.dialogue_stages(line="Hi.", voice="tara", quality="final", backend="ltx_av", prompt="p",
                                          speaker="Lumi", seed=1, best_of=3, latentsync_installed=True)
    assert any("Camera lock on" in n for n in notes)
    monkeypatch.setenv(C.CAMLOCK_ENV, "off")
    _st2, notes2, _ = L.dialogue_stages(line="Hi.", voice="tara", quality="final", backend="ltx_av", prompt="p",
                                        speaker="Lumi", seed=1)
    assert not any("Camera lock on" in n for n in notes2)


def test_preset_cam_thresholds():
    cfg = L.best_of_config()
    assert cfg.l1c["cam"]["scale_drift_max_pct"] == 0.5
    assert cfg.l1c["cam"]["trans_max_px"] == 1.0
    assert "camera-locked" in cfg.l1c["summary"]
