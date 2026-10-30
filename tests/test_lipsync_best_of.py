"""Best-of-3 seeds for ltx_a2v_artic on rebuilt characters (opensoul.lipsync best-of block, opensoul.shot): reject
rules, all-rejected -> needs_review + LatentSync fallback, no scorer -> seed 1 scorer_failed, missing fields, null
lse_c, the metadata and the take sidecar. Fake renders and a fake scorer only (no GPU)."""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from opensoul import lipsync as L

@pytest.fixture(autouse=True)
def _cam_pass_on_fake_files(monkeypatch):
    """best_of tests write stub bytes, not real mp4s; keep the cam gate from ERROR-rejecting every seed."""
    monkeypatch.setattr(L, "score_cam", lambda v, face_box=None, cfg_cam=None: {
        "cam_verdict": "PASS", "scale_drift_max_pct": 0.01, "trans_max_px": 0.1, "video": str(v)})

from opensoul import lipsync_scorer as SC

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")


def m(c=6.0, off=0, opn=0.8, grin=0.1, gwin=0.05, eyes=0.9, **kw):
    d = {"lse_c": c, "lse_d": 7.0, "offset": off, "open_frac": opn, "grin_frac": grin, "grin_win_max": gwin,
         "eyes_open_frac": eyes}
    d.update(kw)
    return d


def pick(*metrics, **kw):
    return L.choose_seed([{"seed": 77 + i, "file": f"s{77 + i}.mp4", "metrics": x, "error": None}
                          for i, x in enumerate(metrics)], **kw)


# ---------------------------------------------------------------- rules
@pytest.mark.parametrize("bad,why", [(m(9.0, off=3), "offset"), (m(9.0, off=-4), "offset"),
                                     (m(9.0, opn=0), "lips closed"), (m(9.0, grin=0.31), "grin"),
                                     (m(9.0, gwin=0.16), "grin burst")])
def test_each_reject_rule(bad, why):
    r = pick(bad, m(5.0))
    assert r["status"] == "picked" and r["seed"] == 78 and r["lse_c"] == 5.0
    s0 = r["seeds"][0]
    assert s0["rejected"] and any(why in x for x in s0["reasons"]) and not r["seeds"][1]["rejected"]


def test_rule_edges_pass():
    r = pick(m(6.0, off=2, opn=0.01, grin=0.3, gwin=0.15, eyes=0.1), m(4.0))
    assert r["seed"] == 77 and not r["seeds"][0]["rejected"] and not r["needs_review"]


def test_eyes_never_reject():
    r = pick(m(6.0, eyes=0.0), m(5.0, eyes=0.1), m(2.0, eyes=0.3))
    assert r["status"] == "picked" and not r["needs_review"] and not any(s["rejected"] for s in r["seeds"])
    assert "eyes_open_min" not in L.best_of_config().reject


def test_eyes_shut_flag_is_a_review_reason_not_a_reject():
    r = pick(m(6.0, eyes_shut_flag=True, eyes_shut_max_s=1.4), m(4.0))
    assert r["status"] == "picked" and r["seed"] == 77 and r["needs_review"] and not r["latentsync_fallback_allowed"]
    assert r["review"] == ["eyes shut 1.40 s (eyes_shut_flag)"] and "needs_review" in r["flags"]
    assert r["needs_review_reasons"] == ["eyes shut 1.40 s (eyes_shut_flag)"]
    assert r["seeds"][0]["eyes_shut_max_s"] == 1.4 and r["seeds"][0]["eyes_shut_from"] == "scorer"
    assert "Needs review: eyes shut 1.40 s" in L.best_of_note(r)
    assert not pick(m(6.0, eyes_shut_flag=False))["needs_review"]


def test_eyes_shut_flag_never_triggers_the_latentsync_fallback():
    r = pick(m(6.0, eyes_shut_flag=True), m(5.0, eyes_shut_flag=True), m(4.0, eyes_shut_flag=True))
    assert r["status"] == "picked" and r["needs_review"] and not r["latentsync_fallback_allowed"]
    r = pick(m(6.0, grin=0.9, eyes_shut_flag=True), m(5.0, off=5))  # only all-rejected opens the fallback
    assert r["status"] == "all_rejected" and r["latentsync_fallback_allowed"]
    assert r["needs_review_reasons"][0] == "every seed was rejected" and "eyes shut" in r["needs_review_reasons"][1]


def test_eyes_shut_config_numbers():
    t = L.best_of_config().eyes_shut
    assert (t["eye_blink_min"], t["look_down_max"], t["min_duration_s"], t["provisional"]) == (0.6, 0.3, 1.0, True)
    assert L.best_of_config().start_blink_warn == 0.5
    assert pick(m(6.0))["eyes_shut_thresholds"] == {"provisional": True, "eye_blink_min": 0.6, "look_down_max": 0.3,
                                                    "min_duration_s": 1.0}


def test_scorer_eyes_shut_fields_win_over_the_frames():
    cfg = L.best_of_config()
    frames = {"eye_blink_frames": [0.9] * 48, "eye_look_down_frames": [0.1] * 48, "fps": 24}  # 2 s shut
    assert L.eyes_shut_of({**frames, "eyes_shut_flag": False, "eyes_shut_max_s": 0.2}, cfg) == \
        {"flag": False, "max_s": 0.2, "from": "scorer"}
    assert L.eyes_shut_of({**frames, "eyes_shut_max_s": 1.2}, cfg) == {"flag": True, "max_s": 1.2, "from": "scorer_max_s"}
    assert L.eyes_shut_of({**frames, "eyes_shut_max_s": 1.0}, cfg)["flag"] is False  # "more than" 1.0 s
    assert L.eyes_shut_of(frames, cfg) == {"flag": True, "max_s": 2.0, "from": "frames"}
    assert L.eyes_shut_of({}, cfg) == {"flag": None, "max_s": None, "from": None}


def test_eyes_shut_from_frames_needs_blink_high_and_look_down_low_continuously():
    cfg = L.best_of_config()
    f = lambda b, d: L.eyes_shut_of({"eye_blink_frames": b, "eye_look_down_frames": d, "fps": 24}, cfg)  # noqa: E731
    assert f([0.9] * 48, [0.5] * 48)["flag"] is False                  # lids down toward the counter: look-down high
    assert f([0.59] * 48, [0.0] * 48)["max_s"] == 0.0                   # blink below 0.6
    assert f([0.6] * 25, [0.29] * 25) == {"flag": True, "max_s": 1.042, "from": "frames"}  # 25 f > 1.0 s
    assert f([0.6] * 24, [0.29] * 24)["flag"] is False                  # exactly 1.0 s is not "more than"
    broken = [0.9] * 20 + [None] + [0.9] * 20                          # a frame without a face breaks the run
    assert f(broken, [0.0] * 41)["max_s"] == round(20 / 24, 3) and f(broken, [0.0] * 41)["flag"] is False
    r = pick(m(6.0, eye_blink_frames=[0.9] * 30, eye_look_down_frames=[0.0] * 30, fps=24))
    assert r["needs_review"] and r["seeds"][0]["eyes_shut_from"] == "frames"


def test_eyes_open_frac_breaks_ties_within_the_lse_c_window():
    r = pick(m(6.0, eyes=0.4), m(5.8, eyes=0.95), m(5.5, eyes=1.0))  # 5.5 is outside 0.3 of 6.0
    assert r["seed"] == 78 and r["tiebreak_decided"] and r["tiebreak"]["by"] == "eyes_open_frac"
    assert r["tiebreak"]["candidates"] == [77, 78] and r["tiebreak"]["highest_lse_c_seed"] == 77
    r = pick(m(6.0, eyes=0.9), m(5.8, eyes=0.4))  # the tiebreak ran but kept the best LSE-C
    assert r["seed"] == 77 and r["tiebreak"] and not r["tiebreak_decided"] and r["tiebreak"]["by"] is None
    r = pick(m(6.0, eyes=0.4), m(5.6, eyes=1.0))  # outside the window: LSE-C decides
    assert r["seed"] == 77 and r["tiebreak"] is None and not r["tiebreak_decided"]
    r = pick(m(6.0, eyes=0.4), m(5.9, eyes=0.95, grin=0.5))  # a rejected seed never wins the tiebreak
    assert r["seed"] == 77
    r = pick(m(6.0, eyes=0.4), m(5.8, eyes=0.95), engine="latentsync")  # eyes only on ltx_av seeds
    assert r["seed"] == 77
    noeyes = m(5.9)
    del noeyes["eyes_open_frac"]
    r = pick(m(6.0, eyes=0.2), noeyes)
    assert r["seed"] == 77 and not r["scorer_failed"]  # no eyes field: not a rule, nothing undecided


def test_a_shut_eyes_seed_loses_ties_to_an_unflagged_one():
    r = pick(m(6.0, eyes=0.9, eyes_shut_flag=True), m(5.8, eyes=0.3, eyes_shut_flag=False))
    assert r["seed"] == 78 and r["tiebreak_decided"] and r["tiebreak"]["by"] == "eyes_shut_flag"
    assert not r["needs_review"]  # the kept seed isn't flagged
    r = pick(m(6.0, eyes=0.9, eyes_shut_flag=True), m(5.5, eyes=0.3))  # outside the window: flag doesn't move it
    assert r["seed"] == 77 and r["needs_review"] and not r["tiebreak_decided"]
    r = pick(m(6.0, eyes=0.5, eyes_shut_flag=True), m(5.9, eyes=0.9, eyes_shut_flag=True))  # both flagged: eyes
    assert r["seed"] == 78 and r["tiebreak"]["by"] == "eyes_open_frac"


def test_start_frame_closed_eyes_is_a_warning_only():
    r = pick(m(6.0, start_eye_blink=0.62), m(4.0, start_eye_blink=0.62))
    assert r["warnings"] == [L.START_FRAME_WARNING] == ["Eyes look closed in the start frame"]
    assert r["status"] == "picked" and r["seed"] == 77 and not r["needs_review"] and r["start_eye_blink"] == 0.62
    assert "Eyes look closed in the start frame." in L.best_of_note(r)
    assert pick(m(6.0, start_eye_blink=0.5))["warnings"] == [L.START_FRAME_WARNING]  # >= 0.5
    assert pick(m(6.0, start_eye_blink=0.49))["warnings"] == []
    assert pick(m(6.0))["warnings"] == [] and pick(m(6.0))["start_eye_blink"] is None  # no data: no warning
    r = pick(m(6.0, grin=0.9, start_eye_blink=0.9))
    assert r["status"] == "all_rejected" and "Eyes look closed in the start frame." in L.best_of_note(r)

def test_report_fields_are_recorded_but_never_gate():
    r = pick(m(6.0, eyes_closed_max_s=1.4, grin_smile_p90=0.2, grin_base_smile=0.05, grin_geom_frac=0.9,
               grin_geom_win_max=0.9, grin_def="v2_blendshape_smile"))
    s0 = r["seeds"][0]
    assert not s0["rejected"] and s0["report"]["eyes_closed_max_s"] == 1.4 and s0["report"]["grin_geom_frac"] == 0.9


def test_old_grin_definition_is_scorer_failed_not_a_reject():
    r = pick(m(7.0, grin=0.9, gwin=0.9, grin_def="v1_geometry"), m(5.0, off=9))
    assert r["seed"] == 77 and "scorer_failed:grin_def" in r["flags"] and not r["seeds"][0]["rejected"]


def test_grin_review_only_lines_flag_instead_of_reject():
    cfg = L.best_of_config()
    assert cfg.grin_review_only == ("l07",)
    assert L.grin_review_only_for("l07") and L.grin_review_only_for("L7") and L.grin_review_only_for("7")
    assert not L.grin_review_only_for("l08") and not L.grin_review_only_for("")
    r = pick(m(6.0, grin=0.5, gwin=0.4), m(4.0), grin_review_only=True)
    assert r["seed"] == 77 and r["status"] == "picked" and r["needs_review"] and not r["seeds"][0]["rejected"]
    assert any("grin" in x for x in r["review"]) and not r["latentsync_fallback_allowed"]
    # the other rules still reject on a review-only line
    r = pick(m(6.0, off=4, grin=0.5), m(4.0), grin_review_only=True)
    assert r["seed"] == 78
    # elsewhere grin rejects as before
    assert pick(m(6.0, grin=0.5), m(4.0))["seed"] == 78
    st, _n, _m = L.dialogue_stages(line="Real coffee.", voice="tara", quality="final", backend="ltx_av",
                                   prompt="p", speaker="Lumi", seed=1, best_of=3, line_ref={"position": 7})
    assert st[1]["grin_review_only"] is True and st[1]["line_id"] == "l07" and st[1]["line_id_from"] == "position"
    st, _n, _m = L.dialogue_stages(line="Hi.", voice="tara", quality="final", backend="ltx_av",
                                   prompt="p", speaker="Lumi", seed=1, best_of=3, line_ref={"position": 3})
    assert st[1]["grin_review_only"] is False
    env = {"OPENSOUL_BEST_OF_GRIN_REVIEW_ONLY": "l02, l09"}
    assert L.best_of_config(env=env).grin_review_only == ("l02", "l09")


def test_highest_lse_c_among_survivors():
    r = pick(m(6.12, grin=0.49), m(0.32, off=4, opn=0), m(4.64, off=-1, grin=0.58))  # G2nd l08: s77/s78/s79
    assert r["status"] == "all_rejected"
    r = pick(m(5.59, grin=0.36), m(6.27, off=-1, grin=0.36), m(4.63, off=-2, grin=0.09))  # l04: only s73 survives
    assert r["status"] == "picked" and r["seed"] == 79 and r["lse_c"] == 4.63


def test_all_rejected_keeps_least_bad_needs_review_and_allows_fallback():
    r = pick(m(6.1, grin=0.5), m(2.0, off=5), m(4.0, opn=0))
    assert r["status"] == "all_rejected" and r["seed"] == 77 and r["needs_review"]
    assert r["latentsync_fallback_allowed"] and "needs_review" in r["flags"] and not r["scorer_failed"]
    assert "Needs review" in L.best_of_note(r)


def test_fallback_only_when_all_rejected():
    assert not pick(m(5.0), m(6.0, grin=0.9))["latentsync_fallback_allowed"]


def test_missing_field_is_scorer_failed_for_that_rule():
    no_grin = m(7.0)
    del no_grin["grin_frac"]
    r = pick(no_grin, m(5.0))
    s0 = r["seeds"][0]
    assert not s0["rejected"] and s0["unknown"] == ["scorer_failed:grin_frac"]
    assert r["seed"] == 78  # a fully checked survivor ranks first
    r = pick(no_grin, m(5.0, off=9))
    assert r["seed"] == 77 and r["scorer_failed"] and "scorer_failed:grin_frac" in r["flags"]
    # a missing field never hides a rule that does fire
    bad = m(8.0, off=6)
    del bad["open_frac"]
    assert pick(bad)["status"] == "all_rejected"


def test_null_lse_c_is_scorer_failed():
    r = pick(m(None), m(4.0))
    assert r["seeds"][0]["rejected"] and r["seeds"][0]["reasons"][0].startswith("scorer_failed") and r["seed"] == 78
    r = pick(m(None), m(None), m(None))
    assert r["status"] == "scorer_failed" and r["seed"] == 77 and r["scorer_failed"] and not r["needs_review"]
    assert not r["latentsync_fallback_allowed"]


def test_config_file_holds_every_value_with_the_agreed_defaults(monkeypatch):
    for k in list(__import__("os").environ):
        if k.startswith("OPENSOUL_BEST_OF_"):
            monkeypatch.delenv(k)
    cfg = L.best_of_config()
    r = cfg.reject
    assert (r["abs_offset_min"], r["open_frac_max"], r["grin_frac_max"], r["grin_win_max"], cfg.seeds,
            cfg.eyes_window) == (3, 0.0, 0.3, 0.15, 3, 0.3)
    assert cfg.info["grin_def"] == "v2_blendshape_smile" and cfg.eyes_apply_to == ("ltx_av",)
    assert cfg.fields == {k: k for k in L.FIELD_KEYS} and cfg.seed_step == 1
    src = (Path(L.__file__)).read_text()
    for gone in ("REJECT_GRIN_FRAC =", "BEST_OF_SEEDS =", 'F_GRIN = "'):
        assert gone not in src  # no second copy of the values in code


def test_env_overrides_thresholds_seeds_and_field_names():
    env = {"OPENSOUL_BEST_OF_SEEDS": "5", "OPENSOUL_BEST_OF_GRIN_WIN_MAX": "0.8",
           "OPENSOUL_BEST_OF_EYES_TIEBREAK_WINDOW": "0.5",
           "OPENSOUL_BEST_OF_FIELD_GRIN_FRAC": "grin", "OPENSOUL_BEST_OF_ABS_OFFSET": "5"}
    cfg = L.best_of_config(env=env)
    assert cfg.seeds == 5 and cfg.reject["grin_win_max"] == 0.8 and cfg.field("grin_frac") == "grin"
    assert cfg.eyes_window == 0.5
    x = m(6.0, off=4, gwin=0.7)
    x["grin"] = x.pop("grin_frac")
    reasons, unknown, review = L.seed_checks(x, cfg)
    assert reasons == [] and unknown == [] and review == []
    assert L.best_of_for({"rebuilt": True}, env=env) == 5
    assert L.best_of_seed_list(10, cfg=cfg) == [10, 11, 12, 13, 14]


def test_config_file_override(tmp_path):
    f = tmp_path / "bo.json"
    d = json.loads(L.BEST_OF_CONFIG.read_text())
    d["reject"]["grin_frac_max"] = 0.5
    d["fields"]["grin_frac"] = "grin"
    f.write_text(json.dumps(d))
    cfg = L.best_of_config(env={"OPENSOUL_BEST_OF_CONFIG": str(f)})
    assert cfg.reject["grin_frac_max"] == 0.5
    r = L.choose_seed([{"seed": 1, "file": "a", "metrics": {**m(6.0), "grin": 0.45}, "error": None}], cfg)
    assert r["status"] == "picked" and r["seeds"][0]["grin_frac"] == 0.45 and r["fields"]["grin_frac"] == "grin"


@pytest.mark.parametrize("field", ["grin_win_max", "open_frac"])
def test_missing_new_field_is_scorer_failed_for_that_rule(field):
    x = m(7.0)
    del x[field]
    r = pick(x, m(5.0, off=9))
    assert r["seed"] == 77 and f"scorer_failed:{field}" in r["flags"] and r["seeds"][0]["unknown"] == [f"scorer_failed:{field}"]


# ---------------------------------------------------------------- render + score loop
def _stage(seed=77):
    st, _n, _m = L.dialogue_stages(line="Have a good night.", voice="tara", quality="final", backend="ltx_av",
                                   prompt="Lumi waves", speaker="Lumi", seed=seed, pronoun="she", best_of=3)
    return st[1]


def test_best_of_renders_three_seeds_and_scores_each(tmp_path):
    calls = []

    def render(stage, seed):
        assert stage["inputs"][L.N_NOISE_1]["noise_seed"] == stage["inputs"][L.N_NOISE_2]["noise_seed"] == seed
        calls.append(seed)
        f = tmp_path / f"s{seed}.mp4"
        f.write_bytes(b"x")
        return f

    table = {77: m(6.1, grin=0.49), 78: m(0.3, off=4, opn=0), 79: m(4.6, grin=0.2)}
    r = L.best_of_seeds(_stage(), render, lambda v: table[int(Path(v).stem[1:])])
    assert calls == [77, 78, 79] and r["seed"] == 79 and r["status"] == "picked"


def test_no_scorer_renders_seed_one_only_flagged_scorer_failed(tmp_path, monkeypatch):
    monkeypatch.delenv(SC.ENV_CLI, raising=False)
    calls = []
    r = L.best_of_seeds(_stage(), lambda st, sd: calls.append(sd) or tmp_path / "a.mp4")
    assert calls == [77] and r["status"] == "scorer_failed" and r["seed"] == 77 and r["skipped_seeds"] == [78, 79]
    assert r["scorer_failed"] and "isn't available" in L.best_of_note(r)


def test_scorer_errors_per_seed(tmp_path):
    def score(v):
        if "78" in str(v):
            raise SC.ScorerError("no_face", "lse_c null")
        return m(5.0)

    r = L.best_of_seeds(_stage(), lambda st, sd: tmp_path / f"s{sd}.mp4", score)
    assert r["seeds"][1]["error"].startswith("no_face") and r["seed"] == 77


# ---------------------------------------------------------------- setting: rebuilt characters only
def test_rebuilt_marking_and_setting():
    assert L.is_rebuilt({"rebuilt": True}) and L.is_rebuilt({"meta": {"rebuilt": True}})
    assert L.is_rebuilt({"meta": {"origin": {"kind": "text"}}})
    assert not L.is_rebuilt({"rebuilt": False, "meta": {"origin": {"kind": "text"}}})
    assert not L.is_rebuilt({}) and not L.is_rebuilt(None) and not L.is_rebuilt({"meta": {"origin": {"kind": "photo"}}})
    assert L.best_of_for({"rebuilt": True}, env={}) == 3 and L.best_of_for({}, env={}) == 1
    assert L.best_of_for({}, env={L.BEST_OF_ENV: "on"}) == 3
    assert L.best_of_for({"rebuilt": True}, env={L.BEST_OF_ENV: "off"}) == 1


def test_plan_marks_best_of_and_conditional_fallback(monkeypatch):
    monkeypatch.setenv(L.RECIPE_ENV, L.RECIPE_LEGACY)  # the older pick is reachable by setting only
    st, notes, mode = L.dialogue_stages(line="Hi.", voice="tara", quality="final", backend="ltx_av", prompt="p",
                                        speaker="Lumi", seed=10, best_of=3, latentsync_installed=True)
    assert st[1]["best_of"] == 3 and st[1]["seeds"] == [10, 11, 12] and st[1]["method"] == L.REBUILT_METHOD
    assert st[-1]["stage"] == "lipsync" and st[-1]["only_if"] == L.ONLY_IF_ALL_REJECTED and mode == "ltx_a2v"
    assert any(n.startswith("Best of 3 takes") for n in notes)
    st2, _n, _m = L.dialogue_stages(line="Hi.", voice="tara", quality="final", backend="ltx_av", prompt="p",
                                    speaker="Lumi", seed=10, best_of=3, latentsync_installed=False)
    assert all(s["stage"] != "lipsync" for s in st2)
    st3, _n, _m = L.dialogue_stages(line="Hi.", voice="tara", quality="final", backend="ltx_av", prompt="p",
                                    speaker="Lumi", seed=10)
    assert "best_of" not in st3[1]  # default: one seed, as before
    st4, _n, _m = L.dialogue_stages(line="Hi.", voice="tara", quality="draft", backend="ltx_av", prompt="p",
                                    speaker="Lumi", seed=10, best_of=3)
    assert all("best_of" not in s for s in st4)


# ---------------------------------------------------------------- run_shot: metadata, sidecar, fallback, dry-run
def _mp4(path: Path, color: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c={color}:s=64x64:r=24",
                    "-frames:v", "9", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


class FakeVideo:
    def __init__(self):
        self.calls = []

    def render(self, stage, image, dest):
        sd = stage["inputs"][L.N_NOISE_1]["noise_seed"]
        self.calls.append(sd)
        return _mp4(Path(dest), ["red", "green", "blue", "white"][len(self.calls) % 4])


class FakeTTS:
    name = "fake"

    def synthesize(self, text, voice, dest):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=220:sample_rate=16000",
                        "-t", "0.4", str(dest)], check=True)
        return Path(dest)


class FakeLS:
    name = "latentsync"
    face_box = None

    def __init__(self):
        self.ran = 0

    def sync(self, video, audio, dest):
        self.ran += 1
        return _mp4(Path(dest), "yellow")


def _plan(latentsync=True):
    st, notes, _mode = L.dialogue_stages(line="Have a good night.", voice="tara", quality="final", backend="ltx_av",
                                         prompt="Lumi waves", speaker="Lumi", seed=77, pronoun="she", best_of=3,
                                         latentsync_installed=latentsync)
    return {"stages": st, "notes": notes}


def _sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


@needs_ffmpeg
def test_run_shot_records_every_seed_and_stamps_the_chosen_file(tmp_path, monkeypatch):
    from opensoul import shot as S

    monkeypatch.setenv("OPENSOUL_DRY_RUN", "0")
    table = {77: m(6.1, grin=0.49), 78: m(0.3, off=4, opn=0), 79: m(4.6, grin=0.2)}
    vb, ls = FakeVideo(), FakeLS()
    res = S.run_shot(_plan(), tmp_path / "still.png", tmp_path / "take", video_backend=vb, tts=FakeTTS(), lipsync=ls,
                     motion_check=False, scorer=lambda v: table[int(Path(v).parent.name[1:])])
    assert vb.calls == [77, 78, 79] and ls.ran == 0  # a seed passed: no LatentSync
    assert res.video == tmp_path / "take" / "seeds" / "s79" / "video.mp4"
    bo = next(x for x in res.steps if x["stage"] == "best_of")
    assert bo["seed"] == 79 and [s["seed"] for s in bo["seeds"]] == [77, 78, 79]
    assert bo["seeds"][0]["reasons"] and bo["seeds"][1]["reasons"] and not bo["seeds"][2]["reasons"]
    assert all(Path(s["file"]).is_file() for s in bo["seeds"])  # the losers are kept in the take folder
    side = json.loads(Path(str(res.video) + ".best_of.json").read_text())
    assert side["out_sha256"] == _sha(res.video) and side["best_of"]["seeds"][1]["offset"] == 4
    assert any(n.startswith("Best of 3 takes: kept seed 79") for n in res.notes)
    assert not any("seeds are rendered" in n for n in res.notes)
    assert any(x["stage"] == "lipsync_skipped" for x in res.steps)


@needs_ffmpeg
def test_run_shot_all_rejected_runs_the_latentsync_fallback(tmp_path, monkeypatch):
    from opensoul import shot as S

    monkeypatch.setenv("OPENSOUL_DRY_RUN", "0")
    monkeypatch.setenv(L.RECIPE_ENV, L.RECIPE_LEGACY)  # L1c never re-mouths a rejected base (tests/test_lipsync_l1c.py)
    ls = FakeLS()
    res = S.run_shot(_plan(), tmp_path / "still.png", tmp_path / "take", video_backend=FakeVideo(), tts=FakeTTS(),
                     lipsync=ls, motion_check=False, scorer=lambda v: m(3.0, grin=0.9))
    assert ls.ran == 1 and res.video.name == "lipsync.mp4"
    bo = next(x for x in res.steps if x["stage"] == "best_of")
    assert bo["needs_review"] and bo["latentsync_fallback_allowed"]
    side = json.loads(Path(str(res.video) + ".best_of.json").read_text())  # the record follows the kept take
    assert side["out_sha256"] == _sha(res.video) and side["rewritten_by"] == ["latentsync"]


@needs_ffmpeg
def test_run_shot_without_scorer_keeps_seed_one(tmp_path, monkeypatch):
    from opensoul import shot as S

    monkeypatch.setenv("OPENSOUL_DRY_RUN", "0")
    monkeypatch.delenv(SC.ENV_CLI, raising=False)
    vb, ls = FakeVideo(), FakeLS()
    res = S.run_shot(_plan(), tmp_path / "still.png", tmp_path / "take", video_backend=vb, tts=FakeTTS(), lipsync=ls,
                     motion_check=False)
    bo = next(x for x in res.steps if x["stage"] == "best_of")
    assert vb.calls == [77] and ls.ran == 0 and bo["status"] == "scorer_failed" and bo["scorer_failed"]


@needs_ffmpeg
def test_dry_run_renders_one_and_never_scores(tmp_path, monkeypatch):
    from opensoul import shot as S

    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    _mp4(tmp_path / "still.mp4", "red")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp_path / "still.mp4"), "-frames:v", "1",
                    str(tmp_path / "still.png")], check=True)

    def boom(v):
        raise AssertionError("dry-run must not score")

    vb = FakeVideo()
    res = S.run_shot(_plan(), tmp_path / "still.png", tmp_path / "take", video_backend=vb, tts=FakeTTS(),
                     lipsync=FakeLS(), motion_check=False, scorer=boom)
    assert vb.calls == [77]
    bo = next(x for x in res.steps if x["stage"] == "best_of")
    assert bo["status"] == "dry_run" and bo["skipped_seeds"] == [78, 79]
    assert any("runs in Studio mode" in n for n in res.notes)


def test_take_metadata_gets_the_best_of_record(monkeypatch, tmp_path):
    import app.storyboard_api as A
    from opensoul.shot import ShotResult

    rec = pick(m(6.0, grin=0.5), m(5.0))
    res = ShotResult(video=tmp_path / "v.mp4", steps=[{"stage": "video"}, {"stage": "best_of", **rec}])
    got = A._best_of_record(res)
    assert got["seed"] == 78 and got["seeds"][0]["reasons"] and "stage" not in got
    assert A._best_of_record(ShotResult(video=tmp_path / "v.mp4", steps=[])) is None
    # the speaker's pack decides: rebuilt -> 3 seeds, else 1
    monkeypatch.delenv(L.BEST_OF_ENV, raising=False)
    monkeypatch.setattr(A, "_speaker_pack", lambda who: {"rebuilt": True} if who == "Lumi" else {})
    assert L.best_of_for(A._speaker_pack("Lumi")) == 3 and L.best_of_for(A._speaker_pack("Ren")) == 1
    src = Path(A.__file__).read_text()
    assert "best_of=L.best_of_for(_speaker_pack(who))" in src and '"lipsync_best_of": bo' in src



# ---------------------------------------------------------------- eyes in generated prompts
@pytest.mark.parametrize("text", ["Lumi gives a slow blink and smiles.", "She glances down, then speaks.",
                                  "Ren blinks slowly at the till.", "A slow-blink, then a nod."])
def test_generated_prompts_never_carry_slow_blink_or_glances_down(text):
    from opensoul.presets import NODE_TEXT, build_shot_plan

    p = L.speaker_prompt(text, "Lumi", "Hi.", "she")
    plan = build_shot_plan(camera="static", quality="final", character_prompt=text)
    talk = build_shot_plan(camera="static", quality="final", character_prompt=text, speaker="Lumi", pronoun="she")
    texts = [p] + [json.dumps(s.get("inputs", {})) for pl in (plan, talk) for s in pl["stages"]]
    for t in texts:
        low = t.lower()
        assert "slow blink" not in low and "slow-blink" not in low and "blinks slowly" not in low
        assert "glances down" not in low
    assert "Eyes open, holding on the camera." in p and "she speaks clearly, eyes open" in p.lower()
    assert L.eyes_safe(p) == p  # idempotent


def test_eyes_sentence_uses_the_shots_object_and_listener():
    assert L.eyes_sentence("the counter", "the customer") == \
        "eyes open, a brief glance down at the counter, then holds on the customer"
    assert L.eyes_sentence("", "Ren") == "eyes open, holding on Ren"
    assert L.eyes_sentence() == "eyes open, holding on the camera"
    p = L.speaker_prompt("Lumi gives a slow blink.", "Lumi", "Hi.", "she", look_at="the counter",
                         listener="the customer")
    # talk shots (L1c): no glance-down beat, the eyes hold on the listener
    assert "glance" not in p.lower() and "Eyes open, holding on the customer." in p
    assert "Head still, no tilt, eyes on the customer." in p
    assert "glances down" not in p.lower() and "slow blink" not in p.lower()


def test_storyboard_passes_the_listener_and_line_position():
    import app.storyboard_api as A
    from opensoul import storyboard as sb

    s = sb.Shot(id="s1", beat="b", characters=["Lumi", "Ren"], line="Hi.", speaker="Lumi")
    assert A._listener(s, "Lumi") == "Ren"
    assert A._listener(sb.Shot(id="s2", beat="b", characters=["Lumi"]), "Lumi") == ""
    assert A._listener(sb.Shot(id="s3", beat="b", characters=["Lumi", "Ren", "Ivy"]), "Lumi") == "Ren and Ivy"
    src = Path(A.__file__).read_text()
    assert "line_ref=_line_ref(s, position), listener=_listener(s, who)" in src


def test_line_id_order_explicit_then_name_then_wav():
    R = L.resolve_line_id
    assert R("l07", ["l03 shot"], "x_l05.wav", 9) == ("l07", "line")
    assert R("7", (), None, None) == ("l07", "line")
    assert R("", ["G2n_l07_soft_s75", "l03"], "l05.wav", 9) == ("l07", "name")  # take name before shot name
    assert R("", ["Real coffee", "s4"], "/tmp/voice_l07.wav", 9) == ("l07", "wav")
    assert R("", ["Real coffee"], "voice_padded.wav", 7) == ("l07", "position")
    assert R("", ["hello", "s4"], None, None) == ("", None)
    assert R("", ["l04mcu verdict"])[0] == "l04" and R("", ["bowl07"])[0] == ""  # 'l' must start a token
    assert R(None, "l12_take") == ("l12", "name")


def test_app_line_ref_mirrors_the_order():
    import app.storyboard_api as A
    from opensoul import storyboard as sb

    s = sb.Shot(id="s2", beat="l05 Real coffee", line_id="l07")
    assert L.resolve_line_id(**{"line": A._line_ref(s, 3)["line"], "names": A._line_ref(s, 3)["names"],
                                "position": 3}) == ("l07", "line")
    s = sb.Shot(id="s2", beat="l07 Real coffee")
    ref = A._line_ref(s, 3)
    assert L.resolve_line_id(ref["line"], ref["names"], None, ref["position"]) == ("l07", "name")
    s = sb.Shot(id="s2", beat="Real coffee")
    st, _n, _m = L.dialogue_stages(line="Real coffee.", voice="tara", quality="final", backend="ltx_av", prompt="p",
                                   speaker="Lumi", seed=1, best_of=3, line_ref=A._line_ref(s, 7))
    assert st[1]["line_id"] == "l07" and st[1]["line_id_from"] == "position" and st[1]["grin_review_only"]
    assert sb.Project.from_dict({"id": "p", "title": "t", "character": "c",
                                 "shots": [{"id": "s1", "beat": "b", "line_id": "l07"}]}).shots[0].line_id == "l07"


def test_render_time_wav_name_comes_before_the_position(tmp_path):
    st, _n, _m = L.dialogue_stages(line="Hi.", voice="tara", quality="final", backend="ltx_av", prompt="p",
                                   speaker="Lumi", seed=1, best_of=3, line_ref={"names": ["Real coffee"], "position": 3})
    assert st[1]["line_id"] == "l03" and not st[1]["grin_review_only"]
    stage = {**st[1], "inputs": {**st[1]["inputs"], L.N_LOAD_AUDIO: {"audio": str(tmp_path / "lumi_l07.wav")}}}
    r = L.best_of_seeds(stage, lambda stk, sd: tmp_path / f"s{sd}.mp4", lambda v: m(6.0, grin=0.5) if "s1" in str(v)
                        else m(4.0))
    assert r["line_id"] == "l07" and r["line_id_from"] == "wav" and r["grin_review_only"] and r["seed"] == 1
    named, _n, _m = L.dialogue_stages(line="Hi.", voice="tara", quality="final", backend="ltx_av", prompt="p",
                                      speaker="Lumi", seed=1, best_of=3, line_ref={"names": ["l04 verdict"]})
    stage = {**named[1], "inputs": {**named[1]["inputs"], L.N_LOAD_AUDIO: {"audio": "lumi_l07.wav"}}}
    r = L.best_of_seeds(stage, lambda stk, sd: tmp_path / f"s{sd}.mp4", lambda v: m(5.0))
    assert r["line_id"] == "l04" and r["line_id_from"] == "name"  # a name beats the wav


def test_other_eye_text_is_unchanged():
    assert L.eyes_safe("Lumi glances at the can. Says nothing.") == "Lumi glances at the can. Says nothing."
    assert L.eyes_safe("") == ""


def test_shipped_presets_and_generators_have_no_slow_blink():
    root = Path(L.__file__).resolve().parents[1]
    hits = []
    for d in ("presets", "opensoul", "app"):
        for f in (root / d).rglob("*"):
            if f.suffix in (".json", ".py", ".js") and "__pycache__" not in f.parts:
                t = f.read_text(errors="replace").lower()
                if "slow blink" in t or "glances down" in t or "blinks slowly" in t:
                    if f.name != "lipsync.py":  # the guard itself names them
                        hits.append(str(f.relative_to(root)))
    assert hits == []
