"""Lip-sync provenance sidecars: <out>.lipsync.json (runners/latentsync_run.py) and <out>.inner_mouth.json
(runners/ls_inner_mouth.py) carry out_sha256 (sha256 hex of the final output file, taken after its last write) and
out_frames (frames decoded from that file). CPU only: LatentSync is a fake checkout, the lip tracker a stub."""
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

cv2 = pytest.importorskip("cv2")

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "custom_nodes" / "opensoul_nodes" / "runners"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_ls_fps_conform import make_take  # noqa: E402
from test_no_insightface_lipsync import fake_latentsync  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not on PATH")


def sha(p) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, RUN / file)
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


# A fake LatentSync that, like upstream in 25 fps mode, can loop the video to cover longer audio (FAKE_LOOP extra
# frames, ping-pong: the first looped frame repeats the last one) while its detector only saw the input frames.
FAKE_INFER = r"""
import os, sys, cv2
from latentsync.utils import face_detector as m
a = sys.argv
vid, out = (a[a.index(k) + 1] for k in ("--video_path", "--video_out_path"))
cap = cv2.VideoCapture(vid); fr = []
while True:
    ok, f = cap.read()
    if not ok: break
    fr.append(f)
n_in = len(fr)
fr = fr + fr[::-1][: int(os.environ.get("FAKE_LOOP", "0"))]
h, w_ = fr[0].shape[:2]
vw = cv2.VideoWriter(out, cv2.VideoWriter_fourcc(*"mp4v"), float(os.environ.get("FAKE_FPS", "24")), (w_, h))
for f in fr: vw.write(f)
vw.release()
class D:
    frames = n_in
    def report(self):
        return {"frames": n_in, "face_found_ratio": 1.0, "held_frames": 0,
                "detector_counts": {"mediapipe": n_in, "anime_fallback": 0, "held": 0, "none": 0},
                "face_px_median": 300.0, "face_px_min": 290.0, "multi_face_frames": 0, "style": "auto"}
m.INSTANCES.append(D())
"""


def run_runner(tmp_path, extra=(), env=None, audio_s=0.3, stale=False):
    ls = fake_latentsync(tmp_path, FAKE_INFER)
    v, a = make_take(tmp_path, audio_s=audio_s)
    out = tmp_path / "o" / "take_ls.mp4"
    out.parent.mkdir()
    if stale:
        out.write_bytes(b"an older take")
    r = subprocess.run([sys.executable, str(RUN / "latentsync_run.py"), "--latentsync-dir", str(ls), "--video", str(v),
                        "--audio", str(a), "--out", str(out), "--seed", "7", *extra],
                       capture_output=True, text=True, timeout=120, env=dict(os.environ, **(env or {})))
    return r, out, json.loads(Path(str(out) + ".lipsync.json").read_text())


@pytest.fixture(scope="module")
def run():
    return load("ls_run_provenance", "latentsync_run.py")


def test_file_sha256_and_atomic_sidecar(run, tmp_path):
    f = tmp_path / "x.mp4"
    f.write_bytes(os.urandom(3 << 20))
    assert run.file_sha256(str(f)) == sha(f)
    run.write_sidecar(str(f), {"a": 1})
    assert json.loads(Path(str(f) + ".lipsync.json").read_text()) == {"a": 1}
    assert not Path(str(f) + ".lipsync.json.tmp").exists()


def test_build_sidecar_passes_out_sha256_through(run):
    d = run.build_sidecar({"out_frames": 12, "out_sha256": "ab" * 32}, 20, 1.5, 7, 0)
    assert d["out_frames"] == 12 and d["out_sha256"] == "ab" * 32
    assert "out_sha256" not in run.build_sidecar({}, 20, 1.5, 7, 4)


@needs_ffmpeg
def test_source_mode_sidecar_hashes_the_muxed_output(tmp_path):
    r, out, sc = run_runner(tmp_path)
    assert r.returncode == 0, r.stderr
    assert sc["out_sha256"] == sha(out)            # the final (muxed) file, not LatentSync's intermediate
    assert sc["out_frames"] == 12 == sc["source_frames"] == sc["frames"]


@needs_ffmpeg
def test_25_mode_out_frames_counts_the_output_not_the_detector(tmp_path):
    r, out, sc = run_runner(tmp_path, extra=("--fps-mode", "25"), env={"FAKE_LOOP": "1"})
    assert r.returncode == 0, r.stderr
    assert sc["frames"] == 12                       # input frames the detector saw
    assert sc["out_frames"] == 13                   # the file: one looped frame more
    assert sc["out_sha256"] == sha(out)


@needs_ffmpeg
def test_failed_conform_still_describes_the_kept_mp4(tmp_path):
    r, out, sc = run_runner(tmp_path, env={"FAKE_FPS": "25"})
    assert r.returncode == 6 and out.exists()
    assert sc["out_sha256"] == sha(out) and sc["out_frames"] == 12


def test_no_hash_when_this_run_wrote_no_output(tmp_path):
    r, out, sc = run_runner(tmp_path, audio_s=0.8, stale=True)   # refused before inference: an old file is not ours
    assert r.returncode == 5 and sc["error"] == "length_mismatch"
    assert "out_sha256" not in sc and "out_frames" not in sc


# ------------------------------------------------------------------ inner-mouth sidecar
@pytest.fixture(scope="module")
def im():
    return load("ls_inner_mouth_provenance", "ls_inner_mouth.py")


class _NoFace:
    """Stub tracker: no landmarks anywhere, so the pass changes nothing (still writes, verifies and logs)."""

    def __init__(self, *a, **k):
        pass

    def track(self, frames, sigma=None):
        return [None] * len(frames)

    def report(self):
        return {"detector_counts": {"mediapipe": 0}}


def _src(tmp, name, n=12, fps=24):
    import numpy as np

    p = tmp / name
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "96x64",
                             "-r", str(fps), "-i", "-", "-f", "lavfi", "-i",
                             f"sine=frequency=440:sample_rate=24000:duration={n / fps}", "-c:v", "libx264", "-crf", "10",
                             "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(p)], stdin=subprocess.PIPE)
    for i in range(n):
        f = np.full((64, 96, 3), 20 + 15 * i, np.uint8)
        f[5:15, 5 + i:15 + i] = 255
        proc.stdin.write(f.tobytes())
    proc.stdin.close()
    assert proc.wait() == 0
    return p


@needs_ffmpeg
@pytest.mark.parametrize("with_parent", [True, False])
def test_inner_mouth_sidecar_has_out_sha256_out_frames_and_parent(im, tmp_path, monkeypatch, with_parent):
    monkeypatch.setattr(im, "LipTracker", _NoFace)
    syn, raw = _src(tmp_path, "synced.mp4"), _src(tmp_path, "raw.mp4")
    parent = Path(str(syn) + ".lipsync.json")
    if with_parent:
        parent.write_text(json.dumps({"backend": "latentsync", "out_frames": 12}))
    out = tmp_path / "o" / "OUT.mp4"
    assert im.main([str(syn), str(raw), "-o", str(out)]) == 0
    log = json.loads(Path(str(out) + ".inner_mouth.json").read_text())
    assert log["out_sha256"] == sha(out) and log["out_frames"] == 12 == log["conform"]["frames"]
    if with_parent:
        assert log["parent_sidecar"] == str(parent) and log["parent_sidecar_sha256"] == sha(parent)
    else:
        assert log["parent_sidecar"] is None and log["parent_sidecar_sha256"] is None


@needs_ffmpeg
def test_inner_mouth_dry_run_has_no_output_hash(im, tmp_path, monkeypatch):
    monkeypatch.setattr(im, "LipTracker", _NoFace)
    syn, raw = _src(tmp_path, "synced.mp4"), _src(tmp_path, "raw.mp4")
    out = tmp_path / "OUT.mp4"
    assert im.main([str(syn), str(raw), "-o", str(out), "--dry-run"]) == 0
    log = json.loads(Path(str(out) + ".inner_mouth.json").read_text())
    assert not out.exists() and log["out_sha256"] is None and log["out_frames"] is None


@needs_ffmpeg
def test_inner_mouth_sidecar_is_written_after_the_evidence(im, tmp_path, monkeypatch):
    monkeypatch.setattr(im, "LipTracker", _NoFace)
    syn, raw = _src(tmp_path, "synced.mp4"), _src(tmp_path, "raw.mp4")
    out = tmp_path / "OUT.mp4"
    assert im.main([str(syn), str(raw), "-o", str(out), "--evidence", str(tmp_path / "ev")]) == 0
    log_p = Path(str(out) + ".inner_mouth.json")
    log = json.loads(log_p.read_text())
    assert log["out_sha256"] == sha(out)
    assert log_p.stat().st_mtime_ns >= max(p.stat().st_mtime_ns for p in [out, *Path(tmp_path / "ev").rglob("*")])


def test_25_mode_unreadable_output_is_hashed_and_keeps_the_exit_code(tmp_path):
    ls = fake_latentsync(tmp_path, "import sys\nfrom latentsync.utils import face_detector as m\n"
                         "out = sys.argv[sys.argv.index('--video_out_path') + 1]\nopen(out, 'wb').write(b'mp4')\n")
    out = tmp_path / "o" / "take.mp4"
    out.parent.mkdir()
    r = subprocess.run([sys.executable, str(RUN / "latentsync_run.py"), "--latentsync-dir", str(ls), "--video", "v.mp4",
                        "--audio", "a.wav", "--out", str(out), "--fps-mode", "25"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    sc = json.loads(Path(str(out) + ".lipsync.json").read_text())
    assert sc["out_sha256"] == sha(out) and sc["out_frames"] is None and sc["out_frames_error"]
