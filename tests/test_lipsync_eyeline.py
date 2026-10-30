"""Warn-only first/last eyeline check: a take whose eyes drift from the listener to the lens by the end gets the note
'eyeline drifts to lens at end'. It never rejects, never adds a review reason, never re-picks or falls back, and is
skipped quietly when there is no look data."""
import json
from pathlib import Path

import pytest

from opensoul import lipsync as L
from opensoul import shot as S

ROOT = Path(__file__).resolve().parents[1]
W = "eyeline drifts to lens at end"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in (L.RECIPE_ENV, L.STAGE2_ENV, L.STAGE2_VOICES_ENV, L.INNER_MOUTH_ENV, L.BEST_OF_ENV):
        monkeypatch.delenv(k, raising=False)
    for k in L.EYELINE_FIELDS:
        monkeypatch.delenv(f"OPENSOUL_BEST_OF_FIELD_{k.upper()}", raising=False)


def m(c=6.0, off=0, opn=0.8, grin=0.1, gwin=0.05, eyes=0.9, **kw):
    d = {"lse_c": c, "lse_d": 7.0, "offset": off, "open_frac": opn, "grin_frac": grin, "grin_win_max": gwin,
         "eyes_open_frac": eyes}
    d.update(kw)
    return d


DRIFT = {"start_eye_look_listener": 0.68, "end_eye_look_listener": 0.19}
HOLD = {"start_eye_look_listener": 0.70, "end_eye_look_listener": 0.62}


def base(*metrics):
    return L.choose_base([{"seed": 77 + i, "file": f"s{77 + i}.mp4", "metrics": x, "error": None}
                          for i, x in enumerate(metrics)])


# ---------------------------------------------------------------- the check itself
def test_preset_thresholds_are_provisional_and_field_names_match_the_scorer_style():
    cfg = L.best_of_config()
    assert cfg.eyeline == {"window_s": 0.25, "drop_warn": 0.3, "end_warn": 0.3}
    raw = json.loads((ROOT / "presets" / "lipsync_best_of.json").read_text(encoding="utf-8"))
    assert "provisional" in raw["eyeline"]["_doc"].lower() and W in raw["eyeline"]["_doc"]
    for k in L.EYELINE_FIELDS:   # same style as start_eye_blink / eye_blink_frames
        assert cfg.field(k) == k and raw["fields"][k] == k
    assert L.EYELINE_WARNING == W


def test_drop_from_068_to_019_warns():
    e = L.eyeline_of(m(**DRIFT))
    assert e["warn"] and e["start"] == 0.68 and e["end"] == 0.19 and e["drop"] == 0.49 and e["from"] == "scorer"
    assert len(e["why"]) == 2


@pytest.mark.parametrize("start,end,warn", [(0.70, 0.62, False), (0.60, 0.30, True), (0.59, 0.30, False),
                                            (0.40, 0.29, True), (None, 0.25, True), (None, 0.5, False),
                                            (0.9, 0.55, True)])
def test_thresholds(start, end, warn):
    d = {"end_eye_look_listener": end}
    if start is not None:
        d["start_eye_look_listener"] = start
    assert L.eyeline_of(d)["warn"] is warn


def test_per_frame_series_uses_short_windows_and_skips_no_face_frames():
    series = [0.7] * 6 + [0.6] * 36 + [None, 0.2, 0.15, 0.2, 0.18, 0.2]   # 48 frames at 24 fps, window 6 frames
    e = L.eyeline_of({"eye_look_listener_frames": series, "fps": 24})
    assert e["from"] == "frames" and e["window_frames"] == 6 and e["start"] == 0.7 and e["end"] == 0.186
    assert e["warn"]
    steady = L.eyeline_of({"eye_look_listener_frames": [0.7] * 48, "fps": 24})
    assert steady["warn"] is False and steady["drop"] == 0.0
    no_fps = L.eyeline_of({"eye_look_listener_frames": [0.7, 0.7, 0.1]})   # first / last frame only
    assert no_fps["window_frames"] == 1 and no_fps["warn"]


@pytest.mark.parametrize("metrics", [None, {}, m(), {"eye_look_listener_frames": []},
                                     {"eye_look_listener_frames": [None, None], "fps": 24},
                                     {"start_eye_look_listener": 0.7}, {"end_eye_look_listener": "n/a"}])
def test_missing_data_is_skipped_quietly(metrics):
    assert L.eyeline_of(metrics) is None
    if metrics is not None:
        res = base({**m(), **metrics})
        assert W not in res["warnings"] and W not in L.best_of_note(res)


def test_field_names_can_be_mapped_and_a_preset_without_eyeline_skips(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_BEST_OF_FIELD_END_EYE_LOOK_LISTENER", "look_end")
    assert L.eyeline_of({"look_end": 0.1})["warn"]
    monkeypatch.delenv("OPENSOUL_BEST_OF_FIELD_END_EYE_LOOK_LISTENER")
    raw = json.loads((ROOT / "presets" / "lipsync_best_of.json").read_text(encoding="utf-8"))
    raw.pop("eyeline")
    for k in L.EYELINE_FIELDS:
        raw["fields"].pop(k)
    p = tmp_path / "p.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    cfg = L.best_of_config(path=p)
    assert cfg.eyeline == {} and L.eyeline_of(m(**DRIFT), cfg) is None
    assert W not in L.choose_base([{"seed": 1, "file": "a.mp4", "metrics": m(**DRIFT)}], cfg)["warnings"]


# ---------------------------------------------------------------- warn only, everywhere
def test_l1c_base_warns_but_never_rejects_or_reviews():
    res = base(m(6.0, **DRIFT), m(5.0, eyes=0.8, **HOLD))
    clean = base(m(6.0), m(5.0, eyes=0.8))
    for k in ("status", "seed", "order", "needs_review", "needs_review_reasons", "stage1_passes_all_gates", "flags",
              "latentsync_fallback_allowed"):
        assert res[k] == clean[k], k
    assert res["seed"] == 77 and W in res["warnings"]
    assert res["seeds"][0]["eyeline"]["warn"] and not res["seeds"][1]["eyeline"]["warn"]
    assert not res["seeds"][0]["rejected"]
    assert f"Warning: {W}." in L.best_of_note(res)
    assert L.l1c_stage2_decision(res, {"stage2_mode": "auto", "stage2_default_on": False}) == \
        L.l1c_stage2_decision(clean, {"stage2_mode": "auto", "stage2_default_on": False})


def test_legacy_pick_warns_but_never_falls_back(monkeypatch):
    monkeypatch.setenv(L.RECIPE_ENV, "best_of_fallback")
    seeds = [{"seed": 1, "file": "a.mp4", "metrics": m(7.0, **DRIFT)}, {"seed": 2, "file": "b.mp4", "metrics": m(5.0)}]
    res = L.choose_seed(seeds)
    assert res["status"] == "picked" and res["seed"] == 1 and not res["latentsync_fallback_allowed"]
    assert not res["needs_review"] and W in res["warnings"]


class Fake:
    def __init__(self, out_metrics):
        self.out, self.calls = out_metrics, []

    def frames_of(self, p):
        return 50

    def trim(self, b, n, seed):
        return Path(f"trim_{seed}.mp4")

    def ls(self, t, seed):
        self.calls.append(seed)
        return Path(f"ls_{seed}.mp4"), None

    def score(self, v, ref):
        return self.out


def _run(res, fake):
    return L.run_l1c_stage2(res, audio_s=2.0, frames_of=fake.frames_of, trim=fake.trim, latentsync=fake.ls,
                            inner_mouth=None, score=fake.score,
                            cam=lambda v: {"cam_verdict": "PASS", "scale_drift_max_pct": 0.01, "trans_max_px": 0.1})


def test_mouth_pass_output_warns_but_never_repicks():
    res = base(m(6.0), m(5.0, eyes=0.8))
    fake = Fake(m(7.0, **DRIFT))
    rec = _run(res, fake)
    assert fake.calls == [77] and rec["repicks"] == 0 and rec["kept_base_seed"] == 77
    assert not rec["needs_review"] and rec["warnings"] == [W] and rec["eyeline"]["drop"] == 0.49
    assert rec["attempts"][0]["eyeline"]["warn"]
    assert L.l1c_note(rec).endswith(f"Warning: {W}.")
    quiet = _run(res, Fake(m(7.0)))
    assert quiet["warnings"] == [] and quiet["eyeline"] is None and "Warning" not in L.l1c_note(quiet)


def _record(best_of, final, tmp_path):
    out = {}
    S._write_l1c_record(best_of, final, lambda rec, f: rec, lambda p, rec: out.update(path=p, rec=rec))
    return out["rec"]


def test_record_carries_the_eyeline_of_the_file_that_ships(tmp_path):
    final = tmp_path / "take.mp4"
    res = base(m(6.0, **HOLD))
    res["stage2"] = _run(res, Fake(m(7.0, **DRIFT)))
    rec = _record(res, final, tmp_path)
    assert rec["warnings"] == [W] and rec["stage2"]["warnings"] == [W] and rec["stage1"]["warnings"] == []
    assert rec["stage1"]["eyeline"]["warn"] is False and rec["stage2"]["eyeline"]["warn"] is True
    res = base(m(6.0, **DRIFT))
    res["stage2"] = {"ran": False, "skip_reason": "stage 1 already passes every check"}
    rec = _record(res, final, tmp_path)
    assert rec["warnings"] == [W] and rec["stage1"]["eyeline"]["end"] == 0.19
    res = base(m(6.0))
    res["stage2"] = {"ran": False}
    assert _record(res, final, tmp_path)["warnings"] == []


def test_documented_as_warn_only_and_provisional():
    doc = (ROOT / "docs" / "LIPSYNC_SCORER.md").read_text(encoding="utf-8")
    assert W in doc and "provisional" in doc and "eye_look_listener_frames" in doc
    assert "never rejects" in doc and "never triggers a fallback" in doc
