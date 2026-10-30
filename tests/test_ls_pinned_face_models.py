"""Face models for LatentSync / the inner-mouth pass are local and pinned: the anime landmark weights load only from
files whose sha256 matches the pinned revision (never downloaded, network blocked during the load), and the
MediaPipe face_landmarker.task is sha256-checked before use. CPU only; the anime package, torch hub, Hugging Face
hub and MediaPipe are replaced by recording fakes."""
import hashlib
import importlib.util
import os
import socket
import sys
import types
import urllib.request
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "custom_nodes" / "opensoul_nodes" / "runners"


@pytest.fixture
def fd(tmp_path, monkeypatch):
    for k in ("OPENSOUL_ANIME_YOLOV3", "OPENSOUL_ANIME_HRNET", "HF_HUB_CACHE", "HF_HUB_OFFLINE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("OPENSOUL_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    spec = importlib.util.spec_from_file_location("ls_fd_pinned_under_test", RUN / "ls_face_detector.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def net(monkeypatch):
    """Fake hub modules and socket/urllib spies: every attempted fetch or connect is recorded."""
    calls = []
    hub = types.SimpleNamespace(
        download_url_to_file=lambda *a, **k: calls.append(("torch.hub.download_url_to_file", a)),
        load_state_dict_from_url=lambda *a, **k: calls.append(("torch.hub.load_state_dict_from_url", a)))
    torch = types.ModuleType("torch"); torch.hub = hub
    hf = types.ModuleType("huggingface_hub")
    hf.hf_hub_download = lambda *a, **k: calls.append(("hf_hub_download", a)) or "/nonexistent"
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "torch.hub", hub)
    monkeypatch.setitem(sys.modules, "huggingface_hub", hf)
    built = []

    class LandmarkDetector:
        def __init__(self, landmark_checkpoint_path, face_detector_name=None, face_detector_checkpoint_path=None,
                     device="cuda:0", **k):
            built.append({"hrnet": landmark_checkpoint_path, "yolo": face_detector_checkpoint_path, "device": device,
                          "offline": os.environ.get("HF_HUB_OFFLINE")})
            for fetch in (lambda: sys.modules["torch.hub"].download_url_to_file("https://x/y.pth", "/tmp/y"),
                          lambda: sys.modules["huggingface_hub"].hf_hub_download("hysts/x", "model.safetensors"),
                          lambda: urllib.request.urlopen("https://huggingface.co"),
                          lambda: socket.create_connection(("192.0.2.1", 443), timeout=0.01)):
                try:
                    fetch()
                    built[-1].setdefault("leaked", 0)
                    built[-1]["leaked"] += 1
                except Exception as e:  # noqa: BLE001
                    built[-1].setdefault("blocked", []).append(type(e).__name__)

    afd = types.ModuleType("anime_face_detector")
    afd.LandmarkDetector = LandmarkDetector
    afd.create_detector = lambda *a, **k: calls.append(("create_detector", a))
    monkeypatch.setitem(sys.modules, "anime_face_detector", afd)
    return types.SimpleNamespace(calls=calls, built=built)


def _weights(tmp_path, fd, monkeypatch, good=True):
    """Two small files under $OPENSOUL_HOME/models/anime-face-detector/, pinned (good) or not."""
    d = tmp_path / "home" / "models" / "anime-face-detector"
    d.mkdir(parents=True)
    for n in fd.ANIME_WEIGHTS:
        p = d / f"{n}.safetensors"
        p.write_bytes(f"weights {n}".encode())
        sha = hashlib.sha256(p.read_bytes()).hexdigest() if good else "0" * 64
        monkeypatch.setitem(fd.ANIME_WEIGHTS, n, dict(fd.ANIME_WEIGHTS[n], sha256=sha))
    return d


def test_pins_match_download_models_sh(fd):
    sh = (ROOT / "scripts" / "download_models.sh").read_text()
    for n, w in fd.ANIME_WEIGHTS.items():
        assert f"{n}:{w['revision']}:{w['sha256']}" in sh
    assert fd.MP_TASK_SHA256 in sh


def test_missing_files_make_no_network_call_and_no_model(fd, net):
    assert fd.create_anime_detector("cpu") is None
    assert net.calls == [] and net.built == []                 # nothing fetched, nothing built
    assert fd.ANIME_STATUS["state"] == "unavailable" and "not found" in fd.ANIME_STATUS["error"]


def test_hash_mismatch_is_rejected(fd, net, tmp_path, monkeypatch):
    _weights(tmp_path, fd, monkeypatch, good=False)
    assert fd.create_anime_detector("cpu") is None
    assert net.built == [] and net.calls == []
    assert "sha256" in fd.ANIME_STATUS["error"] and "pinned" in fd.ANIME_STATUS["error"]


def test_env_override_is_the_only_candidate(fd, net, tmp_path, monkeypatch):
    _weights(tmp_path, fd, monkeypatch, good=True)
    bad = tmp_path / "other.safetensors"; bad.write_bytes(b"a different file")
    monkeypatch.setenv("OPENSOUL_ANIME_YOLOV3", str(bad))
    assert fd.anime_weight_candidates("yolov3") == [bad]
    assert fd.create_anime_detector("cpu") is None and net.built == []   # no fallback to the good default


def test_pinned_local_files_load_with_network_blocked(fd, net, tmp_path, monkeypatch):
    d = _weights(tmp_path, fd, monkeypatch, good=True)
    connect_before, urlopen_before = socket.socket.connect, urllib.request.urlopen
    det = fd.create_anime_detector("cuda")
    assert det is not None and fd.ANIME_STATUS["state"] == "loaded"
    b = net.built[0]
    assert b["hrnet"] == str(d / "hrnetv2.safetensors") and b["yolo"] == str(d / "yolov3.safetensors")
    assert b["device"] == "cuda" and b["offline"] == "1"
    assert "leaked" not in b and len(b["blocked"]) == 4          # torch.hub, hf_hub, urllib, socket all refused
    assert net.calls == []                                       # create_detector (unpinned Hub lookup) never used
    # everything restored after the load
    assert socket.socket.connect is connect_before and urllib.request.urlopen is urlopen_before
    assert "HF_HUB_OFFLINE" not in os.environ
    assert sys.modules["huggingface_hub"].hf_hub_download("a", "b") == "/nonexistent"


def test_hf_cache_snapshot_at_the_pinned_revision_is_found(fd, net, tmp_path, monkeypatch):
    for n, w in list(fd.ANIME_WEIGHTS.items()):
        p = (tmp_path / "hf" / "hub" / ("models--" + w["repo"].replace("/", "--")) / "snapshots" / w["revision"]
             / "model.safetensors")
        p.parent.mkdir(parents=True)
        p.write_bytes(f"snap {n}".encode())
        monkeypatch.setitem(fd.ANIME_WEIGHTS, n, dict(w, sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
    assert fd.create_anime_detector("cpu") is not None
    assert "/snapshots/" in net.built[0]["yolo"] and fd.ANIME_WEIGHTS["yolov3"]["revision"] in net.built[0]["yolo"]


def test_no_unpinned_create_detector_call_left_in_the_runners():
    for f in ("ls_face_detector.py", "ls_inner_mouth.py"):
        src = (RUN / f).read_text()
        assert "create_detector(" not in src.replace("create_anime_detector(", ""), f
    assert "create_anime_detector(" in (RUN / "ls_inner_mouth.py").read_text()


# ------------------------------------------------------------------ MediaPipe task
@pytest.fixture
def fake_mp(monkeypatch):
    made = []

    class FaceLandmarker:
        @staticmethod
        def create_from_options(opts):
            made.append(opts)
            return object()

    vision = types.SimpleNamespace(FaceLandmarker=FaceLandmarker, FaceLandmarkerOptions=lambda **k: k)
    py = types.ModuleType("mediapipe.tasks.python")
    py.BaseOptions = lambda model_asset_path: {"path": model_asset_path}
    py.vision = vision
    for name, mod in (("mediapipe", types.ModuleType("mediapipe")), ("mediapipe.tasks", types.ModuleType("mediapipe.tasks")),
                      ("mediapipe.tasks.python", py)):
        monkeypatch.setitem(sys.modules, name, mod)
    return made


def test_mediapipe_task_with_wrong_hash_is_refused(fd, fake_mp, tmp_path):
    task = tmp_path / "face_landmarker.task"; task.write_bytes(b"not the pinned task")
    with pytest.raises(fd.PinError, match="sha256"):
        fd.FaceDetector("cpu", task_path=task, style="real")
    assert fake_mp == []


def test_mediapipe_task_with_pinned_hash_loads_locally(fd, fake_mp, tmp_path, monkeypatch):
    task = tmp_path / "face_landmarker.task"; task.write_bytes(b"task bytes")
    monkeypatch.setattr(fd, "MP_TASK_SHA256", hashlib.sha256(b"task bytes").hexdigest())
    d = fd.FaceDetector("cpu", task_path=task, style="real")
    assert fake_mp[0]["base_options"] == {"path": str(task)} and d._anime is None


def test_style_auto_without_pinned_anime_files_runs_mediapipe_only(fd, fake_mp, net, tmp_path, monkeypatch):
    task = tmp_path / "face_landmarker.task"; task.write_bytes(b"task bytes")
    monkeypatch.setattr(fd, "MP_TASK_SHA256", hashlib.sha256(b"task bytes").hexdigest())
    monkeypatch.delenv("OPENSOUL_LS_ANIME", raising=False)
    d = fd.FaceDetector("cpu", task_path=task, style="auto")
    assert d._anime is None and net.calls == [] and net.built == []


def test_mouth_post_lipfinder_checks_the_same_task_pin(fd, fake_mp, tmp_path):
    spec = importlib.util.spec_from_file_location("ls_post_pinned_under_test", RUN / "ls_mouth_post.py")
    post = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(post)
    assert post.MP_TASK_SHA256 == fd.MP_TASK_SHA256
    bad = tmp_path / "t.task"; bad.write_bytes(b"x")
    with pytest.raises(RuntimeError, match="sha256"):
        post.LipFinder(task_path=str(bad))
    with pytest.raises(RuntimeError, match="not found"):
        post.LipFinder(task_path=str(tmp_path / "missing.task"))
    assert fake_mp == []
