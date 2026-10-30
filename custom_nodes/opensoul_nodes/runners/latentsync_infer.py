#!/usr/bin/env python3
"""Run LatentSync's ``scripts.inference`` with the InsightFace face detector replaced (no buffalo_l, ever).

Usage (cwd = the LatentSync checkout, inside its venv): ``python latentsync_infer.py <scripts.inference args>``

1. ``import insightface`` (and any submodule) raises ImportError, so nothing can build ``FaceAnalysis`` and
   nothing can auto-download the non-commercial buffalo_l pack.
2. ``latentsync.utils.face_detector`` is pre-registered as OpenSoul's ``ls_face_detector`` (MediaPipe, Apache-2.0,
   with an optional MIT anime fallback), so LatentSync's own ImageProcessor / affine / restore code is unchanged.
3. ``OPENSOUL_LS_STATS=<path>``: the detector's numbers (frames, face_found_ratio, detector_counts, face_px_*,
   multi_face_frames, ...) are written there as JSON when inference ends, also when it fails.

4. Frame rate (``OPENSOUL_LS_FPS``, default ``source``): upstream re-encodes every input to 25 fps
   (``read_video(change_fps=True)``) and writes 25 fps. A 24 fps take then gets one repeated body/background frame
   per second. In ``source`` mode the frames are read as they are, the audio features are indexed at the source
   rate (Whisper features are 50 per second, so chunk i is centred on ``i * 50 / fps``: the audio timing follows
   the video, no frame is dropped or duplicated), exactly one chunk per source frame is kept, and the video is
   written at the source rate. ``25`` = upstream behaviour (only for comparisons).
5. Landmark smoothing: all frames are detected first (``FaceDetector.prime``) and the landmark tracks are
   smoothed over time (``OPENSOUL_LS_SMOOTH`` sigma in frames, default 1.0; 0 = off).

Exit codes: 0 ok, ``EXIT_AMBIGUOUS`` (3) = "ambiguous_face" (several faces, no face box), ``EXIT_NO_FACE`` (4) =
"no_face" (no face on a frame and nothing to hold), anything else = LatentSync's own failure.
"""
from __future__ import annotations

import importlib.abc
import importlib.util
import os
import runpy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BLOCKED = ("insightface",)
EXIT_AMBIGUOUS = 3
EXIT_NO_FACE = 4
ERROR_TAG = "OPENSOUL_LIPSYNC_ERROR"


class _Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in BLOCKED:
            raise ImportError(f"{name} is blocked in OpenSoul: InsightFace model packs are non-commercial "
                              "(LatentSync uses OpenSoul's MediaPipe face detector instead)")
        return None


def install(latentsync_dir: str | os.PathLike = ".") -> object:
    """Block InsightFace and register the replacement detector. Returns the detector module."""
    for m in [m for m in sys.modules if m.split(".")[0] in BLOCKED]:
        del sys.modules[m]
    if not any(isinstance(f, _Block) for f in sys.meta_path):
        sys.meta_path.insert(0, _Block())
    root = str(Path(latentsync_dir).resolve())
    if root not in sys.path:
        sys.path.insert(0, root)
    spec = importlib.util.spec_from_file_location("latentsync.utils.face_detector", HERE / "ls_face_detector.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    import latentsync.utils as lu  # package only; its face_detector submodule is never executed

    sys.modules["latentsync.utils.face_detector"] = mod
    lu.face_detector = mod
    return mod


def video_info(path: str) -> tuple[float, int]:
    """(fps, frame count) of a video, counting decoded frames (container frame counts can be off by one)."""
    import cv2

    cap = cv2.VideoCapture(str(path))
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    n = 0
    while cap.grab():
        n += 1
    cap.release()
    if fps <= 0 or n == 0:
        raise RuntimeError(f"cannot read video {path} (fps={fps}, frames={n})")
    return fps, n


def writer_fps(fps: float):
    """Integral rates as int (24, 25, 30), others (23.976, 29.97) as float, for imageio / LatentSync."""
    return int(round(fps)) if abs(fps - round(fps)) < 1e-3 else float(fps)


def fit_chunks(chunks: list, n: int) -> list:
    """Exactly ``n`` audio chunks, one per source frame. Upstream's loop overshoots by 1-2 chunks (it stops one
    step after the end of the features); the runner pads the audio to the video length, so a shortfall can only
    be the last frame: it repeats the final (silent) chunk."""
    if not chunks:
        raise RuntimeError("no audio features")
    return list(chunks[:n]) + [chunks[-1]] * max(0, n - len(chunks))


FPS_STATE: dict = {}


def install_source_fps(fps: float, n_frames: int) -> None:
    """Patch LatentSync (in memory only) to keep the source frame rate end to end. See the module docstring."""
    import latentsync.pipelines.lipsync_pipeline as P
    import latentsync.utils.util as U
    from latentsync.whisper.audio2feature import Audio2Feature

    wfps = writer_fps(fps)
    FPS_STATE.update(mode="source", source_fps=fps, source_frames=n_frames, video_fps=wfps)

    def read_video(path, change_fps=True, use_decord=True):  # never resample to 25
        return U.read_video(path, change_fps=False, use_decord=use_decord)

    P.read_video = read_video
    if not getattr(Audio2Feature.feature2chunks, "_opensoul", False):
        orig_f2c = Audio2Feature.feature2chunks

        def feature2chunks(self, feature_array, fps):
            ch = orig_f2c(self, feature_array=feature_array, fps=fps)
            FPS_STATE["chunks_raw"] = len(ch)
            return fit_chunks(ch, FPS_STATE["source_frames"])

        feature2chunks._opensoul = True
        Audio2Feature.feature2chunks = feature2chunks
    if not getattr(P.LipsyncPipeline.__call__, "_opensoul", False):
        orig_call = P.LipsyncPipeline.__call__

        def call(self, *a, **k):
            k["video_fps"] = FPS_STATE["video_fps"]
            return orig_call(self, *a, **k)

        call._opensoul = True
        P.LipsyncPipeline.__call__ = call


def install_prime() -> None:
    """Detect all frames first and smooth the landmark tracks (FaceDetector.prime) before LatentSync's affine pass."""
    import latentsync.pipelines.lipsync_pipeline as P

    if getattr(P.LipsyncPipeline.affine_transform_video, "_opensoul", False):
        return
    orig = P.LipsyncPipeline.affine_transform_video

    def affine_transform_video(self, video_frames):
        det = self.image_processor.face_detector
        if hasattr(det, "prime"):
            det.prime(list(video_frames))
        return orig(self, video_frames)

    affine_transform_video._opensoul = True
    P.LipsyncPipeline.affine_transform_video = affine_transform_video


def _arg(argv: list[str], name: str):
    return argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) else None


def detector_report(mod) -> dict:
    """Stats of the detector LatentSync used (the record that saw the most frames)."""
    inst = [d for d in getattr(mod, "INSTANCES", []) if d.frames]
    return max(inst, key=lambda d: d.frames).report() if inst else {"frames": 0}


def _write_stats(mod, error: str | None) -> None:
    path = os.environ.get("OPENSOUL_LS_STATS")
    if not path:
        return
    import json

    rep = detector_report(mod)
    rep.update({f"fps_{k}" if k == "mode" else k: v for k, v in FPS_STATE.items()})
    rep["error"] = error
    with open(path, "w") as f:
        json.dump(rep, f, indent=1)


def classify(exc: BaseException, mod) -> tuple[int, str] | None:
    if isinstance(exc, getattr(mod, "AmbiguousFace", ())):
        return EXIT_AMBIGUOUS, "ambiguous_face"
    if isinstance(exc, RuntimeError) and "Face not detected" in str(exc):
        return EXIT_NO_FACE, "no_face"
    return None


def main(argv: list[str]) -> int:
    mod = install(os.getcwd())
    mode = os.environ.get("OPENSOUL_LS_FPS", "source").strip().lower()
    if mode not in ("source", "25"):
        raise SystemExit(f"OPENSOUL_LS_FPS must be 'source' or '25', not {mode!r}")
    video = _arg(argv, "--video_path")
    if video:  # scripts.inference always gets one; without it there is nothing to conform or track
        if mode == "source":
            fps, n = video_info(video)
            install_source_fps(fps, n)
        else:
            FPS_STATE.update(mode="25")
        install_prime()
    sys.argv = ["scripts.inference", *argv]
    try:
        runpy.run_module("scripts.inference", run_name="__main__", alter_sys=True)
    except BaseException as e:  # noqa: BLE001 - classify, record, re-raise the rest
        c = classify(e, mod)
        _write_stats(mod, c[1] if c else type(e).__name__)
        if c is None:
            raise
        print(f"{ERROR_TAG} {c[1]}: {e}", file=sys.stderr, flush=True)
        return c[0]
    _write_stats(mod, None)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
