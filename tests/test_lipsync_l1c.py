"""L1c, the default lip-sync recipe for talking shots of rebuilt characters: grin-gated + camera-locked a2v base (eyes open, looking
at the listener) -> LatentSync, MediaPipe only. Base gated on look only, output scored with every gate, a grin in the
output re-picks the base, trim (never loop) + base_short, stage-2 params, voice-F default, framing warning, cost
hint, the talk prompt, the optional inner-mouth toggle and the stored record. Fake renders, fake LatentSync and a
fake scorer only (no GPU, no models)."""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from opensoul import lipsync as L

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in (L.RECIPE_ENV, L.STAGE2_ENV, L.STAGE2_VOICES_ENV, L.INNER_MOUTH_ENV, L.BEST_OF_ENV):
        monkeypatch.delenv(k, raising=False)


def m(c=6.0, off=0, opn=0.8, grin=0.1, gwin=0.05, eyes=0.9, **kw):
    d = {"lse_c": c, "lse_d": 7.0, "offset": off, "open_frac": opn, "grin_frac": grin, "grin_win_max": gwin,
         "eyes_open_frac": eyes}
    d.update(kw)
    return d


def base(*metrics, **kw):
    return L.choose_base([{"seed": 77 + i, "file": f"s{77 + i}.mp4", "metrics": x, "error": None}
                          for i, x in enumerate(metrics)], **kw)


# ---------------------------------------------------------------- default recipe and config
def test_l1c_is_the_default_and_the_old_pick_is_a_setting():
    cfg = L.best_of_config()
    assert cfg.recipe == "L1c" == L.RECIPE_L1C
    assert cfg.l1c["summary"] == "grin-gated + camera-locked a2v base (eyes open, looking at the listener) → LatentSync, MediaPipe only"
    assert L.best_of_config(env={L.RECIPE_ENV: "best_of_fallback"}).recipe == L.RECIPE_LEGACY
    with pytest.raises(ValueError):
        L.best_of_config(env={L.RECIPE_ENV: "nope"})
    st, _n, _m = L.dialogue_stages(line="Hi.", voice="tara", quality="final", backend="ltx_av", prompt="p",
                                   speaker="Lumi", seed=10, best_of=3, latentsync_installed=True)
    assert st[1]["recipe"] == "L1c" and st[-1]["only_if"] == L.ONLY_IF_L1C_STAGE2
    assert not any(x.get("only_if") == L.ONLY_IF_ALL_REJECTED for x in st)


# ---------------------------------------------------------------- stage 1: base gated on look only
def test_base_is_not_rejected_on_offset_or_lse_c():
    r = base(m(0.4, off=7, eyes=0.95), m(8.0, off=0, eyes=0.5))
    assert r["status"] == "picked" and not any(s["rejected"] for s in r["seeds"])
    assert r["seed"] == 77 and r["order_seeds"] == [77, 78]  # eyes first, though LSE-C 0.4 and offset 7
    assert not r["stage1_passes_all_gates"] and r["seeds"][0]["gate_reasons"]  # recorded, not a reject
    assert "eyes_open_frac" in r["pick_why"] and r["recipe"] == "L1c"
    r = base(m(None, off=9, eyes=0.7))  # no LSE-C at all still passes the look checks
    assert r["status"] == "picked" and r["seed"] == 77


def test_base_rejects_grin_and_closed_lips_and_ranks_eyes_then_lse_c():
    r = base(m(9.0, grin=0.31), m(9.0, gwin=0.16), m(9.0, opn=0), m(3.0, eyes=0.6), m(4.0, eyes=0.6))
    assert [s["rejected"] for s in r["seeds"]] == [True, True, True, False, False]
    assert r["order_seeds"] == [81, 80] and r["seed"] == 81  # same eyes: higher LSE-C
    r = base(m(6.0, eyes=0.99, eyes_shut_flag=True), m(5.0, eyes=0.4))
    assert r["seed"] == 78  # an eyes_shut_flag base ranks after an unflagged one
    r = base(m(6.0, eyes=0.99, eyes_shut_flag=True))
    assert r["needs_review"] and "eyes shut" in r["review"][0]  # still a review flag, never a reject
    r = base(m(6.0, grin=0.9), m(5.0, opn=0))
    assert r["status"] == "all_rejected" and r["needs_review"] and r["order"] == []
    assert not r["latentsync_fallback_allowed"]


def test_stage1_passing_every_gate():
    assert base(m(6.0, off=2))["stage1_passes_all_gates"]
    assert not base(m(6.0, off=3))["stage1_passes_all_gates"]


# ---------------------------------------------------------------- stage 2 (pure, fakes)
class Fake:
    def __init__(self, frames=50, grin_seeds=(), fail=None):
        self.frames, self.grin_seeds, self.calls = frames, set(grin_seeds), []

    def frames_of(self, p):
        return self.frames

    def trim(self, b, n, seed):
        self.calls.append(("trim", seed, n))
        return Path(f"trim_{seed}.mp4")

    def ls(self, t, seed):
        self.calls.append(("latentsync", seed))
        return Path(f"ls_{seed}.mp4"), None

    def im(self, synced, raw, seed):
        self.calls.append(("inner_mouth", seed))
        return Path(f"mouth_{seed}.mp4")

    def score(self, v, ref):
        seed = int(str(v).split("_")[1].split(".")[0])
        return m(7.0, grin=0.6 if seed in self.grin_seeds else 0.1)


def _cam_pass(v):
    return {"cam_verdict": "PASS", "scale_drift_max_pct": 0.01, "trans_max_px": 0.1}


def _run(res, fake, **kw):
    kw.setdefault("cam", _cam_pass)  # camera lock is on by default; fakes have no real video
    return L.run_l1c_stage2(res, audio_s=2.0, frames_of=fake.frames_of, trim=fake.trim, latentsync=fake.ls,
                            inner_mouth=fake.im, score=fake.score, **kw)


def test_grin_in_the_output_repicks_the_next_base_never_other_settings():
    res = base(m(5.0, eyes=0.9), m(6.0, eyes=0.8), m(7.0, eyes=0.7))
    fake = Fake(grin_seeds={77})
    rec = _run(res, fake)
    assert rec["kept_base_seed"] == 78 and rec["repicks"] == 1 and rec["file"] == "ls_78.mp4"
    assert [c for c in fake.calls if c[0] == "latentsync"] == [("latentsync", 77), ("latentsync", 78)]
    assert rec["attempts"][0]["grin"] and "re-picking" in rec["attempts"][0]["result"]
    assert rec["params"]["guidance"] == 2.0 and not rec["needs_review"]  # one fixed setting for every base
    fake = Fake(grin_seeds={77, 78, 79})
    rec = _run(res, fake)
    assert rec["kept_base_seed"] == 77 and rec["needs_review"]  # every base grinned: first output, review
    assert "grin after the mouth pass on every passing base" in rec["needs_review_reasons"]


def test_output_scored_with_every_gate():
    res = base(m(5.0))
    fake = Fake()
    fake.score = lambda v, ref: m(7.0, off=4)
    rec = _run(res, fake)
    assert rec["file"] and rec["needs_review"] and any("offset" in r for r in rec["output_reasons"])
    assert rec["repicks"] == 0  # only a grin or post-LS cam fail re-picks the base
    fake.score = lambda v, ref: m(7.0, opn=0)
    assert any("lips closed" in r for r in _run(res, fake)["output_reasons"])


def test_trim_to_the_voice_and_base_short_is_flagged_never_looped():
    res = base(m(5.0))
    fake = Fake(frames=60)
    rec = _run(res, fake)
    assert ("trim", 77, 48) in fake.calls and rec["audio_frames"] == 48 and rec["base_length"] == "trim"
    short = Fake(frames=40)
    rec = _run(res, short)
    assert rec["attempts"][0]["base_short"] and "base_short" in rec["flags"] and rec["needs_review"]
    assert not any(c[0] in ("trim", "latentsync") for c in short.calls) and rec["file"] is None
    src = Path(L.__file__).read_text()
    body = src.split("def trim_to_frames")[1].split("\ndef ")[0]
    assert "-frames:v" in body and "stream_loop" not in body and "loop" not in body.split('"""')[2]


@needs_ffmpeg
def test_trim_to_frames_keeps_the_first_frames(tmp_path):
    src = tmp_path / "b.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=s=64x64:r=24", "-frames:v",
                    "20", "-pix_fmt", "yuv420p", str(src)], check=True)
    from opensoul.speak import count_frames

    assert count_frames(L.trim_to_frames(src, tmp_path / "t.mp4", 12)) == 12


def test_stage2_params_mediapipe_guidance_2_50_steps_seed_1247():
    p = L.l1c_stage2_params()
    assert (p["backend"], p["version"], p["face_detector"], p["face_style"], p["guidance"], p["steps"], p["seed"]) == \
        ("latentsync", "1.6", "mediapipe", "real", 2.0, 50, 1247)
    from opensoul.speak import LatentSyncLipSync

    be = LatentSyncLipSync(dry_run=False)
    st = {"params": p, "face_box": [1, 2, 30, 40]}
    be.face_box = st["face_box"]
    for k, v in st["params"].items():
        if k in ("steps", "guidance", "seed", "face_style"):
            setattr(be, k, v)
    assert be.node_inputs() == {"face_box": "1,2,30,40", "inference_steps": 50, "guidance_scale": 2.0, "seed": 1247,
                                "face_style": "real"}
    assert LatentSyncLipSync().node_inputs() == {}  # unset: the workflow's own values
    from custom_nodes.opensoul_nodes import nodes as N

    assert N.latentsync_env("real", base={})["OPENSOUL_LS_FACE_STYLE"] == "real"
    assert "OPENSOUL_LS_FACE_STYLE" not in N.latentsync_env("", base={})
    assert "face_style" in N.OpenSoulLatentSync.INPUT_TYPES()["optional"]


def test_latentsync_stage_passes_the_params_to_the_backend(tmp_path):
    class BE:
        name, face_box, steps, guidance, seed, face_style = "latentsync", None, None, None, None, ""

        def sync(self, v, a, d):
            self.seen = (self.steps, self.guidance, self.seed, self.face_style)
            return Path(d)

    be = BE()
    L.run_latentsync_stage(be, tmp_path / "v.mp4", tmp_path / "a.wav", tmp_path / "o.mp4",
                           {"params": L.l1c_stage2_params()})
    assert be.seen == (50, 2.0, 1247, "real")


def test_inner_mouth_is_optional_and_off_by_default(monkeypatch):
    p = L.l1c_stage2_params()
    assert p["inner_mouth"]["enabled"] is False and p["inner_mouth"]["experimental"] and p["inner_mouth"]["args"] == []
    assert p["inner_mouth"]["settings"] == "L1c2"
    fake = Fake()
    rec = _run(base(m(5.0)), fake)
    assert not any(c[0] == "inner_mouth" for c in fake.calls) and rec["file"] == "ls_77.mp4"
    assert rec["attempts"][0]["inner_mouth"].startswith("off")
    monkeypatch.setenv(L.INNER_MOUTH_ENV, "on")
    fake = Fake()
    rec = _run(base(m(5.0)), fake)
    assert ("inner_mouth", 77) in fake.calls and rec["file"] == "mouth_77.mp4"
    assert "black voids" in L.INNER_MOUTH_CAVEAT and "pause" in L.INNER_MOUTH_CAVEAT


# ---------------------------------------------------------------- when stage 2 runs
def _stage(voice):
    st, _n, _m = L.dialogue_stages(line="Hi there.", voice=voice, quality="final", backend="ltx_av", prompt="p",
                                   speaker="Lumi", seed=1, best_of=3, latentsync_installed=True)
    return st[-1]


def test_voice_f_defaults_on_and_other_voices_skip_when_stage1_passes(monkeypatch):
    assert L.best_of_config().l1c["stage2"]["default_on_voices"] == ["F"]
    f, tara = _stage("F"), _stage("tara")
    assert f["stage2_default_on"] and not tara["stage2_default_on"] and _stage("f")["stage2_default_on"]
    good, bad = base(m(6.0)), base(m(6.0, off=5))
    assert L.l1c_stage2_decision(good, f) == (True, "on by default for voice F")
    run, why = L.l1c_stage2_decision(good, tara)
    assert not run and why == "stage 1 already passes every check"
    run, why = L.l1c_stage2_decision(bad, tara)
    assert run and "offset" in why
    assert not L.l1c_stage2_decision(base(m(6.0, grin=0.9)), f)[0]  # no passing base: LatentSync can't fix a grin
    assert not L.l1c_stage2_decision({"status": "dry_run"}, f)[0]
    monkeypatch.setenv(L.STAGE2_ENV, "off")
    assert L.l1c_stage2_decision(good, {**f, "stage2_mode": None})[0] is False
    monkeypatch.setenv(L.STAGE2_ENV, "on")
    assert L.l1c_stage2_decision(good, {**tara, "stage2_mode": None})[0] is True
    monkeypatch.setenv(L.STAGE2_VOICES_ENV, "tara")
    assert _stage("tara")["stage2_default_on"] and not _stage("F")["stage2_default_on"]


# ---------------------------------------------------------------- framing, cost, prompt
def test_framing_warning_only_when_data_is_there():
    w = L.framing_warnings(0.41, None)
    assert len(w) == 1 and "41%" in w[0] and "medium start frame (face about 25-30%" in w[0] and "cropped in" in w[0]
    assert L.framing_warnings(0.35, 0.15) == []  # edges pass
    assert "yaw +0.20" in L.framing_warnings(None, 0.2)[0] and L.framing_warnings(None, -0.2)
    assert L.framing_warnings(None, None) == [] and L.framing_from_face_box(None, 1280) == []
    st, notes, _m = L.dialogue_stages(line="Hi.", voice="tara", quality="final", backend="ltx_av", prompt="p",
                                      speaker="Lumi", seed=1, face_box=[0, 0, 300, 500], height=1280)
    assert any(n.startswith("Framing: the face is 39%") for n in notes)  # every Final talk shot, a note only
    r = base(m(6.0, start_face_h_frac=0.5, start_yaw=0.3))
    assert len([w for w in r["warnings"] if w.startswith("Framing")]) == 2 and r["status"] == "picked"


def test_cost_hint_16_frame_chunks_at_35_3_s():
    assert L.latentsync_cost_s(16) == 35.3 and L.latentsync_cost_s(17) == 70.6 and L.latentsync_cost_s(113) == 282.4
    assert L.latentsync_cost_s(0) == 0.0
    st = _stage("F")
    assert st["cost_est_s"] == L.latentsync_cost_s(st["frames_est"])
    notes = L.dialogue_stages(line="Hi there.", voice="F", quality="final", backend="ltx_av", prompt="p",
                              speaker="Lumi", seed=1, best_of=3, latentsync_installed=True)[1]
    assert any(f"about {st['cost_est_s']:.0f} s more" in n for n in notes)


# ---------------------------------------------------------------- run_shot: record, sidecar, seeds kept
def _mp4(path: Path, color: str, frames=24) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c={color}:s=64x64:r=24",
                    "-frames:v", str(frames), "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


class FakeVideo:
    def __init__(self):
        self.calls = []

    def render(self, stage, image, dest):
        self.calls.append(stage["inputs"][L.N_NOISE_1]["noise_seed"])
        return _mp4(Path(dest), ["red", "green", "blue"][len(self.calls) % 3])


class FakeTTS:
    name = "fake"

    def synthesize(self, text, voice, dest):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=220:sample_rate=16000",
                        "-t", "0.5", str(dest)], check=True)
        return Path(dest)


class FakeLS:
    name = "latentsync"
    face_box = steps = guidance = seed = None
    face_style = ""

    def __init__(self):
        self.ran, self.seen = [], []

    def sync(self, video, audio, dest):
        self.ran.append(Path(video))
        self.seen.append((self.steps, self.guidance, self.seed, self.face_style))
        return _mp4(Path(dest), "yellow", frames=12)


def _plan(voice="F"):
    st, notes, _mode = L.dialogue_stages(line="Have a good night.", voice=voice, quality="final", backend="ltx_av",
                                         prompt="Lumi waves", speaker="Lumi", seed=77, pronoun="she", best_of=3,
                                         latentsync_installed=True, listener="Ren")
    return {"stages": st, "notes": notes}


def _sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()



def _patch_cam_pass(monkeypatch):
    """Solid-color ffmpeg fakes have no background SIFT features; inject a PASS so cam lock does not reject them."""
    monkeypatch.setattr(L, "score_cam", lambda v, face_box=None, cfg_cam=None: {
        "cam_verdict": "PASS", "scale_drift_max_pct": 0.01, "trans_max_px": 0.1, "video": str(v)})

def _scorer(table):
    def score(v):
        p = Path(v)
        if p.name == "video.mp4":
            return table[int(p.parent.name[1:])]
        seed = int(p.parent.parent.name[1:])  # seeds/s<seed>/l1c/latentsync.mp4
        return m(7.0, grin=0.7 if seed == 77 else 0.1)
    return score


@needs_ffmpeg
def test_run_shot_l1c_records_and_repicks(tmp_path, monkeypatch):
    from opensoul import shot as S

    monkeypatch.setenv("OPENSOUL_DRY_RUN", "0")
    _patch_cam_pass(monkeypatch)
    table = {77: m(2.0, off=5, eyes=0.95), 78: m(6.0, eyes=0.8), 79: m(7.0, grin=0.5)}
    vb, ls = FakeVideo(), FakeLS()
    res = S.run_shot(_plan(), tmp_path / "still.png", tmp_path / "take", video_backend=vb, tts=FakeTTS(), lipsync=ls,
                     motion_check=False, scorer=_scorer(table))
    assert vb.calls == [77, 78, 79]
    assert [p.parent.parent.name for p in ls.ran] == ["s77", "s78"]  # grin in s77's output -> next base
    assert all(x == (50, 2.0, 1247, "real") for x in ls.seen)
    assert res.video == tmp_path / "take" / "seeds" / "s78" / "l1c" / "latentsync.mp4"
    from opensoul.speak import count_frames

    assert all(count_frames(p) == 12 for p in ls.ran)  # trimmed to the 0.5 s voice, not the padded base
    side = json.loads(Path(str(res.video) + ".best_of.json").read_text())
    assert side["recipe"] == "L1c" and side["out_sha256"] == _sha(res.video)
    assert side["stage1"]["seed"] == 77 and "eyes_open_frac" in side["stage1"]["why"]
    assert side["stage2"]["params"]["face_detector"] == "mediapipe" and side["stage2"]["kept_base_seed"] == 78
    assert side["stage2"]["repicks"] == 1 and side["stage2"]["output_scores"]["lse_c"] == 7.0
    assert all((tmp_path / "take" / "seeds" / f"s{s}" / "video.mp4").is_file() for s in (77, 78, 79))  # kept
    bo = next(x for x in res.steps if x["stage"] == "best_of")
    assert bo["recipe"] == "L1c" and bo["stage2"]["kept_base_seed"] == 78
    assert any(n.startswith("L1c mouth pass: LatentSync 1.6, MediaPipe only") for n in res.notes)


@needs_ffmpeg
def test_run_shot_other_voice_skips_stage2_when_the_base_passes(tmp_path, monkeypatch):
    from opensoul import shot as S

    monkeypatch.setenv("OPENSOUL_DRY_RUN", "0")
    _patch_cam_pass(monkeypatch)
    ls = FakeLS()
    res = S.run_shot(_plan("tara"), tmp_path / "still.png", tmp_path / "take", video_backend=FakeVideo(),
                     tts=FakeTTS(), lipsync=ls, motion_check=False, scorer=lambda v: m(6.0))
    assert ls.ran == [] and res.video.name == "video.mp4"
    skip = next(x for x in res.steps if x["stage"] == "lipsync_skipped")
    assert skip["reason"] == "stage 1 already passes every check" and skip["recipe"] == "L1c"
    side = json.loads(Path(str(res.video) + ".best_of.json").read_text())
    assert side["recipe"] == "L1c" and side["stage2"]["ran"] is False and side["out_sha256"] == _sha(res.video)


@needs_ffmpeg
def test_run_shot_base_short_is_flagged(tmp_path, monkeypatch):
    from opensoul import shot as S

    class LongTTS(FakeTTS):
        def synthesize(self, text, voice, dest):
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=220:sample_rate=16000",
                            "-t", "1.5", str(dest)], check=True)  # 36 frames > the 24-frame fake base
            return Path(dest)

    monkeypatch.setenv("OPENSOUL_DRY_RUN", "0")
    _patch_cam_pass(monkeypatch)
    ls = FakeLS()
    res = S.run_shot(_plan(), tmp_path / "still.png", tmp_path / "take", video_backend=FakeVideo(), tts=LongTTS(),
                     lipsync=ls, motion_check=False, scorer=lambda v: m(6.0))
    st2 = next(x for x in res.steps if x["stage"] == "l1c_stage2")
    assert ls.ran == [] and "base_short" in st2["flags"] and st2["needs_review"]
    assert res.video.name == "video.mp4"  # the base is kept as it is: never looped


@pytest.fixture(autouse=True)
def _no_cam_lock(monkeypatch):
    # These cover the Stage 2 defaults (rebuilt / voice F / a failing base). Since the review ruling, a
    # camera-locked (AddGuide) take keeps Stage 2 off unless 'Mouth refine' is ticked (tests/test_mouth_refine.py),
    # so they run on the takes the defaults still apply to: camera lock off.
    monkeypatch.setenv("OPENSOUL_A2V_CAMLOCK", "off")
