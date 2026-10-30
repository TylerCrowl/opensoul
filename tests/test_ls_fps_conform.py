"""LatentSync runner: source frame rate end to end (no 25 fps resample, no repeated frames), exact frame count,
audio padded to the take, loud failure on any mismatch; landmark smoothing; mouth post-processing. CPU only:
LatentSync is replaced by a fake checkout, MediaPipe by synthetic points."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "custom_nodes" / "opensoul_nodes" / "runners"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_no_insightface_lipsync import fake_latentsync  # noqa: E402

cv2 = pytest.importorskip("cv2")


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, RUN / file)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def inf():
    return load("ls_infer_under_test", "latentsync_infer.py")


@pytest.fixture(scope="module")
def run():
    return load("ls_run_under_test", "latentsync_run.py")


@pytest.fixture(scope="module")
def fd():
    return load("ls_fd_under_test2", "ls_face_detector.py")


@pytest.fixture(scope="module")
def post():
    return load("ls_post_under_test", "ls_mouth_post.py")


# ------------------------------------------------------------------ pure helpers
def test_fit_chunks_gives_one_chunk_per_source_frame(inf):
    assert inf.fit_chunks(list(range(13)), 10) == list(range(10))           # upstream overshoot trimmed
    assert inf.fit_chunks(list(range(9)), 10) == list(range(9)) + [8]       # one short: repeat the silent tail
    with pytest.raises(RuntimeError):
        inf.fit_chunks([], 3)


def test_writer_fps(inf):
    assert inf.writer_fps(24.0) == 24 and isinstance(inf.writer_fps(24.0004), int)
    assert inf.writer_fps(23.976) == pytest.approx(23.976)


def test_plan_audio_pads_short_audio_and_refuses_long_audio(run):
    assert run.plan_audio(1.5, 24, 48) == pytest.approx(0.5)
    assert run.plan_audio(2.0, 24, 48) == 0.0
    assert run.plan_audio(2.03, 24, 48) == 0.0          # within one frame: trimmed to the take
    with pytest.raises(ValueError):
        run.plan_audio(2.2, 24, 48)


def test_check_conform(run):
    assert run.check_conform(24, 169, 24.0, 169) is None
    assert run.check_conform(24, 169, 25.0, 176) == "fps_mismatch"
    assert run.check_conform(24, 169, 24.0, 172) == "frame_count_mismatch"
    assert run.check_conform(23.976, 10, 23.98, 10) is None


# ------------------------------------------------------------------ in-memory LatentSync patches
PATCH_CHECK = r"""
import sys, json
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[2])
import latentsync_infer as I
I.install(sys.argv[1])
I.install_source_fps(24.0, 10)
I.install_prime()
import latentsync.pipelines.lipsync_pipeline as P
import latentsync.utils.util as U
from latentsync.whisper.audio2feature import Audio2Feature
seen = {}
U.read_video = lambda p, change_fps=True, use_decord=True: seen.setdefault("change_fps", change_fps) or []
P.read_video("x.mp4")
a = Audio2Feature()
class Det:
    def prime(self, frames): seen["primed"] = len(frames)
class IP: face_detector = Det()
pl = P.LipsyncPipeline(); pl.image_processor = IP()
pl.affine_transform_video([0] * 7)
print(json.dumps({"change_fps": seen["change_fps"], "n_long": len(a.feature2chunks(list(range(13)), fps=24)),
                  "n_short": len(a.feature2chunks(list(range(8)), fps=24)), "fps": pl(video_path="v", audio_path="a",
                  video_out_path="o"), "primed": seen["primed"], "state": I.FPS_STATE}))
"""


def test_source_fps_patches(tmp_path):
    ls = fake_latentsync(tmp_path, "")
    r = subprocess.run([sys.executable, "-c", PATCH_CHECK, str(ls), str(RUN)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout.strip().splitlines()[-1])
    assert d["change_fps"] is False                 # never re-encoded to 25 fps
    assert d["n_long"] == 10 and d["n_short"] == 10  # exactly one audio chunk per source frame
    assert d["fps"] == 24                           # written at the source rate
    assert d["primed"] == 7                          # all frames detected (and smoothed) before the affine pass
    assert d["state"]["source_frames"] == 10 and d["state"]["chunks_raw"] == 8


# ------------------------------------------------------------------ runner end to end (fake LatentSync)
FAKE_INFER = r"""
import os, sys, wave, cv2
from latentsync.utils import face_detector as m
a = sys.argv
vid, aud, out = (a[a.index(k) + 1] for k in ("--video_path", "--audio_path", "--video_out_path"))
with wave.open(aud) as w:
    print("AUDIO_S", w.getnframes() / w.getframerate())
cap = cv2.VideoCapture(vid); fr = []
while True:
    ok, f = cap.read()
    if not ok: break
    fr.append(f)
fr = fr[: len(fr) - int(os.environ.get("FAKE_DROP", "0"))]
h, w_ = fr[0].shape[:2]
vw = cv2.VideoWriter(out, cv2.VideoWriter_fourcc(*"mp4v"), float(os.environ.get("FAKE_FPS", "24")), (w_, h))
for f in fr: vw.write(f)
vw.release()
class D:
    frames = len(fr)
    def report(self):
        return {"frames": len(fr), "face_found_ratio": 1.0, "held_frames": 0,
                "detector_counts": {"mediapipe": len(fr), "anime_fallback": 0, "held": 0, "none": 0},
                "face_px_median": 300.0, "face_px_min": 290.0, "multi_face_frames": 2, "style": "auto", "smooth_sigma": 1.0}
m.INSTANCES.append(D())
"""


def make_take(d: Path, n=12, fps=24, audio_s=0.3, sr=24000):
    v, a = d / "take.mp4", d / "line.wav"
    vw = cv2.VideoWriter(str(v), cv2.VideoWriter_fourcc(*"mp4v"), fps, (64, 48))
    for i in range(n):
        vw.write(np.full((48, 64, 3), i * 20 % 255, np.uint8))
    vw.release()
    with wave.open(str(a), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((np.sin(np.arange(int(audio_s * sr)) / 8) * 9000).astype("<i2").tobytes())
    return v, a


needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not on PATH")


def run_source(tmp_path, env=None, audio_s=0.3, extra=()):
    ls = fake_latentsync(tmp_path, FAKE_INFER)
    v, a = make_take(tmp_path, audio_s=audio_s)
    out = tmp_path / "o" / "take_ls.mp4"
    out.parent.mkdir()
    r = subprocess.run([sys.executable, str(RUN / "latentsync_run.py"), "--latentsync-dir", str(ls), "--video", str(v),
                        "--audio", str(a), "--out", str(out), "--steps", "20", "--guidance", "1.5", "--seed", "7", *extra],
                       capture_output=True, text=True, timeout=120, env=dict(os.environ, **(env or {})))
    sc = json.loads((out.parent / "take_ls.mp4.lipsync.json").read_text())
    return r, out, sc


@needs_ffmpeg
def test_runner_keeps_source_fps_and_frame_count_and_pads_audio(tmp_path, inf):
    r, out, sc = run_source(tmp_path)
    assert r.returncode == 0, r.stderr
    assert "AUDIO_S 0.5" in r.stdout                 # 0.3 s line padded to the 12-frame / 0.5 s take
    assert sc["status"] == "ok" and sc["fps_mode"] == "source"
    assert sc["source_fps"] == 24 and sc["source_frames"] == 12 and sc["out_fps"] == 24 and sc["out_frames"] == 12
    assert sc["audio_pad_s"] == pytest.approx(0.2, abs=1e-3)
    assert sc["multi_face_frames"] == 2 and sc["face_px_median"] == 300.0  # detector stats passed through as-is
    assert inf.video_info(str(out)) == (24.0, 12)


@needs_ffmpeg
@pytest.mark.parametrize("env,code", [({"FAKE_FPS": "25"}, "fps_mismatch"), ({"FAKE_DROP": "1"}, "frame_count_mismatch")])
def test_runner_fails_loudly_on_fps_or_count_mismatch(tmp_path, env, code):
    r, out, sc = run_source(tmp_path, env)
    assert r.returncode == 6 and f"OPENSOUL_LIPSYNC_ERROR {code}" in r.stderr
    assert sc["status"] == "error" and sc["error"] == code and out.exists()


def test_runner_refuses_audio_longer_than_the_take(tmp_path):
    r, out, sc = run_source(tmp_path, audio_s=0.8)
    assert r.returncode == 5 and "length_mismatch" in r.stderr and sc["error"] == "length_mismatch"


# ------------------------------------------------------------------ landmark smoothing
def lmk_at(x, y):
    return np.tile([x, y], (106, 1)).astype(float) + np.c_[np.linspace(0, 100, 106), np.zeros(106)]


def test_smooth_landmarks_reduces_jitter_and_keeps_gaps_and_jumps(fd):
    rng = np.random.default_rng(0)
    seq = [lmk_at(200 + rng.normal(0, 2), 100 + rng.normal(0, 2)) for _ in range(30)]
    sm = fd.smooth_landmarks(seq, 1.5)
    jit = lambda s: np.std(np.diff([l.mean(0) for l in s], axis=0))
    assert jit(sm) < 0.5 * jit(seq)
    gap = fd.smooth_landmarks([lmk_at(0, 0), None, lmk_at(10, 0)], 2.0)
    assert gap[1] is None and np.allclose(gap[0], lmk_at(0, 0))      # never smoothed across a missing frame
    jump = fd.smooth_landmarks([lmk_at(0, 0)] * 5 + [lmk_at(500, 0)] * 5, 2.0)
    assert np.allclose(jump[4], lmk_at(0, 0)) and np.allclose(jump[5], lmk_at(500, 0))  # track switch kept sharp
    assert np.allclose(fd.smooth_landmarks(seq, 0)[3], seq[3])


def test_prime_counts_once_and_answers_in_order(fd):
    d = object.__new__(fd.FaceDetector)
    d.rec = fd.Record()
    calls = []

    def one(frame):
        calls.append(1)
        d.frames += 1
        x = float(np.asarray(frame).flat[0])
        l = lmk_at(100 + x, 100)
        return fd.ls_box(fd._int(l), 640, 480), l
    d._detect_one = one
    frames = [np.full((480, 640, 3), v, np.uint8) for v in (0, 4, 0, 4, 0)]
    assert d.prime(frames, 1.0) == 5 and len(calls) == 5 and d.rec.report()["frames"] == 5
    xs = [d(f)[1].mean(0)[0] for f in frames]
    assert len(calls) == 5                          # answered from the queue, not detected again
    assert max(xs) - min(xs) < 4                     # the 4 px zig-zag is damped
    assert d.rec.report()["smooth_sigma"] == 1.0
    d(frames[0])
    assert len(calls) == 6                           # queue empty: back to live detection


# ------------------------------------------------------------------ mouth post-processing
def test_mouth_mask_blend_and_unsharp(post):
    poly = np.array([[40, 60], [60, 55], [80, 60], [60, 70]], float)
    m = post.mouth_mask((120, 120, 3), [poly])
    assert m.shape == (120, 120) and m.max() == pytest.approx(1.0) and m[62, 60] > 0.9 and m[5, 5] < 1e-3
    ls, raw = np.zeros((120, 120, 3), np.uint8), np.full((120, 120, 3), 200, np.uint8)
    b = post.blend(ls, raw, m, 0.5)
    assert 90 <= b[62, 60, 0] <= 110 and b[5, 5, 0] == 0
    rng = np.random.default_rng(1)
    tex = cv2.GaussianBlur(rng.integers(0, 255, (120, 120, 3)).astype(np.uint8), (0, 0), 2)
    sh = post.unsharp(tex, m, 1.0)
    box = (45, 55, 75, 68)
    assert post.laplacian_var(sh, box) > 1.5 * post.laplacian_var(tex, box)
    assert np.array_equal(sh[:20, :20], tex[:20, :20])   # outside the mouth untouched


def test_process_frames_reports_sharpness_vs_raw(post):
    rng = np.random.default_rng(2)
    raw = [rng.integers(0, 255, (120, 120, 3)).astype(np.uint8) for _ in range(3)]
    soft = [cv2.GaussianBlur(f, (0, 0), 1.5) for f in raw]
    poly = np.array([[40, 60], [60, 55], [80, 60], [60, 70]], float)
    out, st = post.process_frames(soft, raw, lambda rgb, near: poly, raw_frac=0.0, sharpen=1.0)
    assert st["frames"] == 3 and st["fixed"] == 3
    assert st["sharpness_ls_vs_raw"] < 0.5 and st["sharpness_out_vs_raw"] > st["sharpness_ls_vs_raw"]
    out2, st2 = post.process_frames(soft, raw, lambda rgb, near: None)
    assert st2["fixed"] == 0 and np.array_equal(out2[0], soft[0])


# ------------------------------------------------------------------ duplicate detections (multi-face stats)
def test_doubled_face_is_one_face_not_multi_face_or_ambiguous(fd):
    from test_ls_face_detector import FRAME, make_detector
    lumi, dup, other = (475, 163, 144, 172), (464, 148, 155, 193), (900, 150, 140, 170)  # dup = l08 frame 10
    assert fd.dedupe([(475, 163, 619, 335), (464, 148, 619, 341)]) == [0]
    d = make_detector(fd, [[lumi, dup]] * 3)            # no face box: a real second face would raise
    for _ in range(3):
        box, lmk = d(FRAME)
        assert box is not None
    rep = d.rec.report()
    assert rep["multi_face_frames"] == 0 and rep["duplicate_detections_dropped"] == 3
    d2 = make_detector(fd, [[lumi, other]] * 2, face_box=lumi)
    d2(FRAME)
    assert d2.rec.report()["multi_face_frames"] == 1   # a genuinely separate face still counts
