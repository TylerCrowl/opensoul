"""Licensing guard: the LatentSync lip-sync path must never import InsightFace or download buffalo_l
(InsightFace model packs are licensed for non-commercial research only). Also checks the runner contract
(--face-box, exit codes, <out>.lipsync.json sidecar) against a fake LatentSync checkout. CPU only."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "custom_nodes" / "opensoul_nodes" / "runners"
LIPSYNC_FILES = [RUN / "latentsync_run.py", RUN / "latentsync_infer.py", RUN / "ls_face_detector.py",
                 # the app side of the same path: the ComfyUI node, the lip-sync planner and the Speak backends
                 ROOT / "custom_nodes" / "opensoul_nodes" / "nodes.py", ROOT / "opensoul" / "lipsync.py",
                 ROOT / "opensoul" / "speak.py"]

UPSTREAM_DETECTOR = "from insightface.app import FaceAnalysis\nFaceAnalysis(name='buffalo_l')\n"


def fake_latentsync(tmp_path: Path, inference_body: str) -> Path:
    ls = tmp_path / "LatentSync"
    (ls / "latentsync" / "utils").mkdir(parents=True)
    (ls / "scripts").mkdir()
    (ls / "latentsync" / "__init__.py").write_text("")
    (ls / "latentsync" / "utils" / "__init__.py").write_text("")
    # what upstream ships: importing it would build FaceAnalysis and fetch buffalo_l
    (ls / "latentsync" / "utils" / "face_detector.py").write_text(UPSTREAM_DETECTOR)
    # the modules latentsync_infer patches in memory (source fps, landmark priming): minimal stand-ins
    (ls / "latentsync" / "utils" / "util.py").write_text(
        "def read_video(video_path, change_fps=True, use_decord=True):\n    return []\n")
    (ls / "latentsync" / "pipelines").mkdir()
    (ls / "latentsync" / "pipelines" / "__init__.py").write_text("")
    (ls / "latentsync" / "pipelines" / "lipsync_pipeline.py").write_text(
        "from ..utils.util import read_video\n"
        "class LipsyncPipeline:\n"
        "    def __call__(self, video_path, audio_path, video_out_path, video_fps=25, **k):\n        return video_fps\n"
        "    def affine_transform_video(self, video_frames):\n        return None\n")
    (ls / "latentsync" / "whisper").mkdir()
    (ls / "latentsync" / "whisper" / "__init__.py").write_text("")
    (ls / "latentsync" / "whisper" / "audio2feature.py").write_text(
        "class Audio2Feature:\n    def feature2chunks(self, feature_array, fps):\n        return list(feature_array)\n")
    (ls / "scripts" / "__init__.py").write_text("")
    (ls / "scripts" / "inference.py").write_text(inference_body)
    return ls


def run_infer(ls: Path, *args, env=None):
    e = dict(os.environ, **(env or {}))
    return subprocess.run([sys.executable, str(RUN / "latentsync_infer.py"), *args], cwd=ls, env=e,
                          capture_output=True, text=True, timeout=60)


def test_lipsync_code_never_imports_insightface():
    for f in LIPSYNC_FILES:
        src = f.read_text()
        assert not re.search(r"^\s*(import insightface|from insightface)", src, re.M), f
        assert "FaceAnalysis(" not in src, f


def test_runner_goes_through_the_blocking_wrapper():
    src = (RUN / "latentsync_run.py").read_text()
    assert "latentsync_infer.py" in src
    assert '"-m", "scripts.inference"' not in src and "'-m', 'scripts.inference'" not in src


def test_download_group_lipsync_has_no_buffalo():
    sh = (ROOT / "scripts" / "download_models.sh").read_text()
    body = re.search(r"^lipsync\(\) \{(.*?)^\}", sh, re.S | re.M).group(1)
    code = "\n".join(l for l in body.splitlines() if not l.strip().startswith("#"))
    assert "buffalo" not in code.lower() and "insightface" not in code.lower()
    assert "face_landmarker.task" in code and "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff" in code
    default = re.search(r"SEL=\(([^)]*)\)", sh).group(1).split()
    assert "arcface" not in default


def test_wrapper_blocks_insightface_and_replaces_detector(tmp_path):
    ls = fake_latentsync(tmp_path, (
        "import sys\n"
        "from latentsync.utils import face_detector as m\n"
        "print('DETECTOR', m.__file__)\n"
        "try:\n    import insightface\n    print('INSIGHTFACE_IMPORTED')\n"
        "except ImportError as e:\n    print('BLOCKED', e)\n"
        "try:\n    import insightface.app\n    print('INSIGHTFACE_IMPORTED')\n"
        "except ImportError:\n    print('BLOCKED_SUB')\n"))
    # even a stub 'insightface' package on sys.path must not load
    (ls / "insightface").mkdir()
    (ls / "insightface" / "__init__.py").write_text("print('INSIGHTFACE_IMPORTED')\n")
    r = run_infer(ls)
    assert r.returncode == 0, r.stderr
    assert "INSIGHTFACE_IMPORTED" not in r.stdout
    assert "BLOCKED" in r.stdout and "BLOCKED_SUB" in r.stdout
    assert "ls_face_detector.py" in r.stdout


def test_no_buffalo_files_created(tmp_path):
    ls = fake_latentsync(tmp_path, "from latentsync.utils.face_detector import FaceDetector\n")
    home = tmp_path / "home"
    home.mkdir()
    r = run_infer(ls, env={"HOME": str(home)})
    assert r.returncode == 0, r.stderr
    hits = [p for p in list(tmp_path.rglob("*")) if "buffalo" in p.name.lower() or p.name in ("det_10g.onnx", "2d106det.onnx")]
    assert not hits and not (home / ".insightface").exists()


@pytest.mark.parametrize("raise_stmt,code,tag", [
    ("raise m.AmbiguousFace('ambiguous_face: 2 faces')", 3, "ambiguous_face"),
    ("raise RuntimeError('Face not detected')", 4, "no_face"),
])
def test_exit_codes(tmp_path, raise_stmt, code, tag):
    ls = fake_latentsync(tmp_path, f"from latentsync.utils import face_detector as m\n{raise_stmt}\n")
    stats = tmp_path / "s.json"
    r = run_infer(ls, env={"OPENSOUL_LS_STATS": str(stats)})
    assert r.returncode == code
    assert f"OPENSOUL_LIPSYNC_ERROR {tag}" in r.stderr
    assert json.loads(stats.read_text())["error"] == tag


FAKE_RUN = (
    "import sys, os, json\n"
    "from latentsync.utils import face_detector as m\n"
    "class D:\n"
    "    frames = 10\n"
    "    def report(self):\n"
    "        return {'frames': 10, 'face_found_ratio': RATIO, 'held_frames': 1,\n"
    "                'detector_counts': {'mediapipe': 8, 'anime_fallback': 1, 'held': 1, 'none': 0},\n"
    "                'face_px_median': 240.0, 'face_px_min': 200.0, 'multi_face_frames': 0, 'style': 'auto',\n"
    "                'face_box_env': os.environ.get('OPENSOUL_LS_FACE_BOX')}\n"
    "m.INSTANCES.append(D())\n"
    "out = sys.argv[sys.argv.index('--video_out_path') + 1]\n"
    "open(out, 'wb').write(b'mp4')\n"
    "print('ARGS', json.dumps(sys.argv))\n"
)


def run_runner(tmp_path, ratio, extra=("--fps-mode", "25")):
    """Sidecar / exit-code contract with a fake LatentSync that writes a dummy file (upstream 25 fps mode, so no
    real video is needed; the source-fps path is covered in test_ls_fps_conform.py)."""
    ls = fake_latentsync(tmp_path, FAKE_RUN.replace("RATIO", str(ratio)))
    out = tmp_path / "o" / "take.mp4"
    out.parent.mkdir()
    r = subprocess.run([sys.executable, str(RUN / "latentsync_run.py"), "--latentsync-dir", str(ls), "--video", "v.mp4",
                        "--audio", "a.wav", "--out", str(out), "--steps", "20", "--guidance", "1.5", "--seed", "7", *extra],
                       capture_output=True, text=True, timeout=60)
    return r, out


def test_runner_writes_sidecar(tmp_path):
    r, out = run_runner(tmp_path, 0.9, ("--fps-mode", "25", "--face-box", "10,20,100,120"))
    assert r.returncode == 0, r.stderr
    sc = json.loads((out.parent / "take.mp4.lipsync.json").read_text())
    for k in ("face_found_ratio", "held_frames", "frames", "detector_counts", "face_px_median", "face_px_min",
              "multi_face_frames", "backend", "steps", "guidance", "seed"):
        assert k in sc, k
    assert set(sc["detector_counts"]) == {"mediapipe", "anime_fallback", "held", "none"}
    assert sc["backend"] == "latentsync" and sc["steps"] == 20 and sc["guidance"] == 1.5 and sc["seed"] == 7
    assert sc["status"] == "ok" and sc["face_box"] == [10, 20, 100, 120]


def test_runner_low_found_ratio_is_no_face(tmp_path):
    r, out = run_runner(tmp_path, 0.4)
    assert r.returncode == 4 and "no_face" in r.stderr
    sc = json.loads((out.parent / "take.mp4.lipsync.json").read_text())
    assert sc["status"] == "error" and sc["error"] == "no_face"
    assert out.exists()  # the failed take stays visible


# ---------------------------------------------------------------- app side: fail closed without the MediaPipe sidecar
def _fake_sdk(report):
    """What comfy_client does: the node's stats text lands in node3_report.txt, SaveVideo writes the take."""
    def run(wf, inputs, node, dest, what):
        if report is not None:
            (dest.parent / "node3_report.txt").write_text(report if isinstance(report, str) else json.dumps(report))
        saved = dest.parent / "opensoul_lipsync_00001_.mp4"
        saved.write_bytes(b"mp4")
        return saved
    return run


@pytest.mark.parametrize("report", [
    None,                                                                    # old runner: no sidecar at all
    "not json",                                                              # unreadable stats
    {"frames": 121, "detector_counts": {"mediapipe": 0, "anime_fallback": 0, "held": 0, "none": 121}},
    {"frames": 121},                                                         # no detector_counts
])
def test_latentsync_take_without_mediapipe_evidence_is_refused(monkeypatch, tmp_path, report):
    from opensoul import lipsync as L
    from opensoul import speak

    monkeypatch.setattr(speak, "_run_sdk", _fake_sdk(report))
    src = tmp_path / "in.mp4"
    src.write_bytes(b"ltx")
    with pytest.raises(L.LipSyncError) as e:
        speak.LatentSyncLipSync(dry_run=False).sync(src, tmp_path / "a.wav", tmp_path / "lipsync.mp4")
    assert e.value.code == "runner_failed"
    saved = tmp_path / "opensoul_lipsync_00001_.mp4"
    assert not saved.exists() and not Path(str(saved) + ".lipsync.json").exists()   # the take is dropped
    assert src.read_bytes() == b"ltx"                                                 # the LTX input is kept
    # the stage runner passes it on as the user-facing error (not swallowed as a no_face note)
    monkeypatch.setattr(speak, "_run_sdk", _fake_sdk(report))
    with pytest.raises(L.LipSyncError):
        L.run_latentsync_stage(speak.LatentSyncLipSync(dry_run=False), src, tmp_path / "a.wav",
                               tmp_path / "lipsync.mp4", {"speaker": "Lumi"})


@pytest.mark.parametrize("counts", [{"mediapipe": 118, "anime_fallback": 0, "held": 3, "none": 0},
                                    {"mediapipe": 0, "anime_fallback": 40, "held": 0, "none": 0}])
def test_latentsync_take_with_detector_counts_is_kept(monkeypatch, tmp_path, counts):
    from opensoul import speak

    monkeypatch.setattr(speak, "_run_sdk", _fake_sdk({"frames": 121, "detector_counts": counts}))
    out = speak.LatentSyncLipSync(dry_run=False).sync(tmp_path / "in.mp4", tmp_path / "a.wav", tmp_path / "o.mp4")
    assert out.is_file() and Path(str(out) + ".lipsync.json").is_file()


def test_dry_run_latentsync_needs_no_sidecar(monkeypatch, tmp_path):
    from opensoul import media, speak

    monkeypatch.setattr(media, "mux", lambda v, a, d: Path(d))
    assert speak.LatentSyncLipSync(dry_run=True).sync(tmp_path / "v.mp4", tmp_path / "a.wav", tmp_path / "o.mp4") \
        == tmp_path / "o.mp4"


def test_latentsync_is_not_offered_without_the_mediapipe_task(monkeypatch, tmp_path):
    import yaml

    from opensoul import models_registry as R

    reg = yaml.safe_load((ROOT / "presets" / "models.yaml").read_text())
    ls = next(b for s in reg["stages"] if s["id"] == "lipsync" for b in s["backends"] if b["id"] == "latentsync")
    assert "$OPENSOUL_HOME/models/mediapipe/face_landmarker.task" in ls["files"]

    monkeypatch.setenv("OPENSOUL_HOME", str(tmp_path))

    def offered():
        row = next(c for c in R.backend_choices() if c["stage"] == "lipsync")
        return any(o["id"] == "latentsync" and o["available"] for o in row["options"])

    unet = tmp_path / "LatentSync" / "checkpoints" / "latentsync_unet.pt"
    unet.parent.mkdir(parents=True)
    unet.write_bytes(b"u")
    assert not offered()                                   # UNet alone: not offered
    task = tmp_path / "models" / "mediapipe" / "face_landmarker.task"
    task.parent.mkdir(parents=True)
    task.write_bytes(b"t")
    assert offered()
