"""Commercial-OK face detector for LatentSync (drop-in for ``latentsync/utils/face_detector.py``).

Upstream LatentSync builds ``insightface.app.FaceAnalysis`` in its FaceDetector, which auto-downloads the
InsightFace ``buffalo_l`` pack (pretrained weights licensed for NON-COMMERCIAL research only). OpenSoul never
loads that file: ``latentsync_infer.py`` blocks ``import insightface`` and installs this module in its place.

Same interface as upstream: ``FaceDetector(device)(frame_rgb, threshold=0.5) -> (bbox, lmk106)`` or
``(None, None)``. ``lmk106`` is a (106, 2) int array in the InsightFace 2d106 index layout, filled at every index
LatentSync reads: the bbox subset (``LMK_ADAPT_ORIGIN_ORDER``), nose 73/74/77/83/86, image-left brow
43/48/49/50/51 and image-right brow 101-105 (the three affine points), and mouth 52-71. Other indices hold
the face centre so nothing downstream sees garbage.

Detectors (licenses are for code AND model files):
* MediaPipe FaceLandmarker (``face_landmarker.task``: BlazeFace short-range + FaceMesh-V2, Apache-2.0),
  loaded from the local file only after its sha256 matches the pin (``MP_TASK_SHA256``). Whole frame first; if that misses (BlazeFace short-range misses small faces), again on a crop around
  the last good face (or the anime detector's box).
* Anime landmarks, hysts ``anime-face-detector`` (code MIT, vendored OpenMMLab parts Apache-2.0; weights
  hysts/anime-face-detector-yolov3 + -hrnetv2 on Hugging Face, MIT). Optional: used only if installed.
  The weights are never fetched at runtime: :func:`create_anime_detector` loads only local files whose sha256
  matches the pinned revision (``ANIME_WEIGHTS``, the same pins as ``scripts/download_models.sh lipsync``), with
  network access blocked during the load. Missing or mismatched files = no anime model (MediaPipe + hold only).
  Files: ``OPENSOUL_ANIME_YOLOV3`` / ``OPENSOUL_ANIME_HRNET`` if set (then only that file), else
  ``$OPENSOUL_HOME/models/anime-face-detector/{yolov3,hrnetv2}.safetensors``, else the pinned-revision snapshot that
  ``download_models.sh`` leaves in the Hugging Face cache
  (``$HF_HUB_CACHE``/``$HF_HOME/hub``/``~/.cache/huggingface/hub``, ``models--hysts--anime-face-detector-<name>/
  snapshots/<revision>/model.safetensors``).
  28 points: 0-4 jaw, 5-7 / 8-10 brows, 11-22 eyes, 23 nose, 24-27 mouth.
* Hold: if every detector misses, the last good landmarks are reused for up to ``OPENSOUL_LS_HOLD`` frames
  (default 12) so one blurred frame does not abort the whole clip (upstream raises "Face not detected").

``OPENSOUL_LS_FACE_STYLE``: ``auto`` (default) = MediaPipe, cross-checked against the anime model; the anime
landmarks win only when both found the same face and disagree on the mouth (FaceMesh sometimes "succeeds"
on drawn faces with the mouth on the chin). ``anime`` = anime landmarks first. ``real`` = MediaPipe only.

Which face: ``face_box`` (x,y,w,h on frame 0; ``OPENSOUL_LS_FACE_BOX`` / ``--face-box``) picks the face with
the best IoU (else nearest centre); later frames track the face nearest the previous one. No box and more
than one significant face on frame 0 raises ``AmbiguousFace`` ("ambiguous_face"). No identity embedding.

Temporal smoothing (``OPENSOUL_LS_SMOOTH`` = Gaussian sigma in frames, default 1.0; 0 = off): LatentSync detects
every frame before it runs the model, so ``latentsync_infer.py`` calls :meth:`FaceDetector.prime` with all frames
first. The landmark tracks are smoothed over time (centred Gaussian, never across a track jump) and LatentSync's
per-frame calls are then answered from that queue. This removes frame-to-frame jitter of the affine crop (the
mouth "swimming"); real camera or head motion is kept.

Calibration: MediaPipe brow/nose points were chosen and
offset so the three affine points land where the 2d106 points did on real faces; the anime nose point is
moved along the brow->nose line (``ANIME_NOSE_K``) so the anime mouth sits at the same height in the
512 crop as a real mouth.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import sys
from pathlib import Path

import numpy as np

# Same constant as upstream (indices into the 106 layout used for the face box).
LMK_ADAPT_ORIGIN_ORDER = [1, 10, 12, 14, 16, 3, 5, 7, 0, 23, 21, 19, 32, 30, 28, 26, 17, 43, 48, 49, 51, 50,
                          102, 103, 104, 105, 101, 73, 74, 86]
LS_LEFT_BROW = [43, 48, 49, 51, 50]     # LatentSync pt_left_eye (image left)
LS_RIGHT_BROW = [101, 102, 103, 104, 105]
LS_NOSE = [74, 77, 83, 86]
LS_HALF = [73, 74]
LS_CONTOUR = [1, 10, 12, 14, 16, 3, 5, 7, 0, 23, 21, 19, 32, 30, 28, 26, 17]
LS_MOUTH = list(range(52, 72))

# MediaPipe FaceMesh (478) indices. "Subject right" is image left on an unmirrored frame.
MP_BROW_A = [70, 63, 105, 66, 107, 46, 53, 52, 65, 55]          # subject-right brow, upper + lower edge
MP_BROW_B = [300, 293, 334, 296, 336, 276, 283, 282, 295, 285]  # subject-left brow
MP_NOSE = [2, 168, 327, 64]                                     # best 4-point match to the 2d106 nose centre (calibration)
MP_HALF = [197, 195]
MP_JAW = [234, 93, 132, 58, 172, 136, 150, 149, 176, 148, 152, 377, 400, 378, 379, 365, 397, 288, 361, 323, 454]
MP_MOUTH = [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 185, 40, 39, 37, 0, 267, 269, 270, 409]

ANIME_NOSE_K = float(os.environ.get("OPENSOUL_LS_ANIME_NOSE_K", "0.68"))
DEFAULT_TASK = Path(os.environ.get("OPENSOUL_HOME", str(Path.home() / "OpenSoul"))) / "models/mediapipe/face_landmarker.task"

# Pinned model files (same pins as scripts/download_models.sh lipsync). Nothing here is ever downloaded at runtime.
MP_TASK_SHA256 = "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff"
ANIME_WEIGHTS = {
    "yolov3": {"env": "OPENSOUL_ANIME_YOLOV3", "repo": "hysts/anime-face-detector-yolov3",
               "revision": "afdd4226a79ae8bb81f334dbcffd34f8cc000c38",
               "sha256": "23bbc708146bcbc1c910f00fe152adbc70d7658d875a0121eaf4ee61d978b2c4"},
    "hrnetv2": {"env": "OPENSOUL_ANIME_HRNET", "repo": "hysts/anime-face-detector-hrnetv2",
                "revision": "9b3435248b26aeb82e2a8578fe9d86d5d57158af",
                "sha256": "e71271376406a743c01528a0460637fcc06e72aeeea583f85007cc72dc8b7a4a"},
}
ANIME_STATUS: dict = {"state": "not_loaded", "error": None, "files": {}}  # last create_anime_detector() outcome


class PinError(RuntimeError):
    """A model file is missing or its sha256 does not match the pin."""


_SHA_CACHE: dict = {}


def file_sha256(path) -> str:
    """sha256 hex of a file (cached per path, size and mtime within the process)."""
    p = Path(path)
    st = p.stat()
    key = (str(p.resolve()), st.st_size, st.st_mtime_ns)
    if key not in _SHA_CACHE:
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for b in iter(lambda: f.read(1 << 20), b""):
                h.update(b)
        _SHA_CACHE[key] = h.hexdigest()
    return _SHA_CACHE[key]


def verify_pinned(path, sha256: str, what: str) -> Path:
    """``path`` if it is a file whose sha256 equals ``sha256``, else :class:`PinError`."""
    p = Path(path)
    if not p.is_file():
        raise PinError(f"{what}: {p} not found")
    got = file_sha256(p)
    if got != sha256:
        raise PinError(f"{what}: {p} sha256 {got} != pinned {sha256}")
    return p


def _hf_cache_dir() -> Path:
    if os.environ.get("HF_HUB_CACHE"):
        return Path(os.environ["HF_HUB_CACHE"])
    return Path(os.environ.get("HF_HOME", str(Path.home() / ".cache" / "huggingface"))) / "hub"


def anime_weight_candidates(name: str) -> list:
    """Local files tried for one anime model, in order. An env override is the only candidate when set."""
    w = ANIME_WEIGHTS[name]
    if os.environ.get(w["env"]):
        return [Path(os.environ[w["env"]])]
    home = Path(os.environ.get("OPENSOUL_HOME", str(Path.home() / "OpenSoul")))
    snap = _hf_cache_dir() / ("models--" + w["repo"].replace("/", "--")) / "snapshots" / w["revision"] / "model.safetensors"
    return [home / "models" / "anime-face-detector" / f"{name}.safetensors", snap]


def resolve_anime_weight(name: str) -> Path:
    """The first local candidate whose sha256 matches the pin; :class:`PinError` when none does."""
    errs = []
    for c in anime_weight_candidates(name):
        try:
            return verify_pinned(c, ANIME_WEIGHTS[name]["sha256"], f"anime {name} weights")
        except PinError as e:
            errs.append(str(e))
    raise PinError("; ".join(errs))


@contextlib.contextmanager
def no_network():
    """Block downloads while a model loads: HF_HUB_OFFLINE=1, and torch.hub / huggingface_hub fetchers, urllib and
    outgoing INET socket connects raise. Everything is restored afterwards."""
    import socket
    import urllib.request

    def refuse(*a, **k):
        raise PinError("network access is blocked while loading local model files")

    undo = []

    def patch(obj, attr, new):
        if obj is not None and hasattr(obj, attr):
            undo.append((obj, attr, getattr(obj, attr)))
            setattr(obj, attr, new)

    orig_connect = socket.socket.connect

    def connect(self, address):
        if self.family in (socket.AF_INET, socket.AF_INET6):
            refuse()
        return orig_connect(self, address)

    old_env = os.environ.get("HF_HUB_OFFLINE")
    os.environ["HF_HUB_OFFLINE"] = "1"
    patch(socket.socket, "connect", connect)
    patch(urllib.request, "urlopen", refuse)
    for mod in ("torch.hub", "huggingface_hub", "huggingface_hub.file_download", "anime_face_detector.detector"):
        m = sys.modules.get(mod)
        for attr in ("download_url_to_file", "load_state_dict_from_url", "hf_hub_download", "snapshot_download"):
            patch(m, attr, refuse)
    try:
        yield
    finally:
        for obj, attr, old in reversed(undo):
            setattr(obj, attr, old)
        if old_env is None:
            os.environ.pop("HF_HUB_OFFLINE", None)
        else:
            os.environ["HF_HUB_OFFLINE"] = old_env


def _anime_unavailable(msg: str):
    ANIME_STATUS.update(state="unavailable", error=msg)
    print(f"OPENSOUL anime face model unavailable (MediaPipe only): {msg}", file=sys.stderr, flush=True)
    return None


def create_anime_detector(device: str = "cpu"):
    """The optional anime landmark model built from the pinned local weights only, or None (logged) when the
    package is not installed or a file is missing or does not match its pin. Never downloads anything."""
    ANIME_STATUS.update(state="not_loaded", error=None, files={})
    try:
        paths = {n: resolve_anime_weight(n) for n in ANIME_WEIGHTS}
    except PinError as e:
        return _anime_unavailable(str(e))
    dev = "cuda" if str(device).startswith("cuda") else "cpu"
    try:  # importing the package fetches nothing; imported first so no_network() can block its fetchers
        from anime_face_detector import LandmarkDetector
    except Exception as e:  # noqa: BLE001
        return _anime_unavailable(f"anime_face_detector not installed ({type(e).__name__}: {e})")
    try:
        with no_network():  # explicit local checkpoints (the package helper would ask the Hub for "main")
            det = LandmarkDetector(str(paths["hrnetv2"]), face_detector_name="yolov3",
                                   face_detector_checkpoint_path=str(paths["yolov3"]), device=dev)
    except Exception as e:  # noqa: BLE001 - optional model; MediaPipe alone still works
        return _anime_unavailable(f"{type(e).__name__}: {e}")
    ANIME_STATUS.update(state="loaded", error=None, files={n: str(p) for n, p in paths.items()})
    return det


def _int(p):
    return np.round(np.asarray(p, dtype=np.float64)).astype(np.int_)


def build_lmk106(brow_l, brow_r, nose, half, jaw, mouth, centre) -> np.ndarray:
    """Pack named point groups into a (106, 2) array in the 2d106 layout LatentSync indexes."""
    out = np.tile(np.asarray(centre, np.float64), (106, 1))
    for idx, pts in ((LS_LEFT_BROW, brow_l), (LS_RIGHT_BROW, brow_r)):
        pts = np.asarray(pts, np.float64)
        for i, k in enumerate(idx):
            out[k] = pts[i % len(pts)]
        # LatentSync averages these five, so make their mean exactly the group mean
        out[idx] += pts.mean(0) - out[idx].mean(0)
    nose = np.asarray(nose, np.float64)
    out[LS_NOSE] = nose
    # 74 is shared by the nose group and the "half face" pair: keep the nose mean exact, and set 73 so that
    # mean(73, 74) is the requested half-face point (only used for the box).
    out[73] = 2 * np.asarray(half, np.float64).mean(0) - out[74]
    jaw = np.asarray(jaw, np.float64)
    sel = np.linspace(0, len(jaw) - 1, len(LS_CONTOUR)).round().astype(int)
    out[LS_CONTOUR] = jaw[sel]
    mouth = np.asarray(mouth, np.float64)
    out[LS_MOUTH] = mouth[np.linspace(0, len(mouth) - 1, len(LS_MOUTH)).round().astype(int)]
    return _int(out)


def ls_box(lmk: np.ndarray, f_w: int, f_h: int):
    """Upstream LatentSync box rule from the 106 points (only checked for None by affine_transform)."""
    half = np.mean([lmk[74], lmk[73]], axis=0)
    sub = lmk[LMK_ADAPT_ORIGIN_ORDER]
    dist = np.max(sub[:, 1]) - half[1]
    x1, y1, x2, y2 = int(np.min(sub[:, 0])), int(half[1] - dist), int(np.max(sub[:, 0])), int(np.max(sub[:, 1]))
    y2 += int((x2 - x1) * 0.1)
    x1 -= int((x2 - x1) * 0.05)
    x2 += int((x2 - x1) * 0.05)
    return max(0, x1), max(0, y1), min(f_w, x2), min(f_h, y2)


def _order_lr(a, b):
    """Return (image-left group, image-right group)."""
    return (a, b) if np.mean(np.asarray(a)[:, 0]) <= np.mean(np.asarray(b)[:, 0]) else (b, a)


# Median offset of the 2d106 point from the MediaPipe point, in units of the brow-to-brow distance, along
# (brow line, perpendicular pointing down the face). Fitted on 33 validation frames where both agreed on the face:
# residual 2.1 / 1.8 / 1.2 % of brow distance (left brow / right brow / nose) vs 8.0 / 7.4 / 1.5 % uncorrected.
MP_OFFSETS = ((0.0674, -0.0371), (-0.0655, -0.0315), (0.0040, 0.0039))


def apply_offsets(bl: np.ndarray, br: np.ndarray, nose: np.ndarray, offsets=MP_OFFSETS):
    L, R = bl.mean(0), br.mean(0)
    ex = R - L
    s = float(np.linalg.norm(ex)) or 1.0
    ex = ex / s
    ey = np.array([-ex[1], ex[0]])
    sh = [s * (ox * ex + oy * ey) for ox, oy in offsets]
    return bl + sh[0], br + sh[1], nose + sh[2]


def from_mediapipe(pts: np.ndarray) -> np.ndarray:
    """(478, 2) MediaPipe pixel points -> lmk106."""
    bl, br = _order_lr(pts[MP_BROW_A], pts[MP_BROW_B])
    bl, br, nose = apply_offsets(bl, br, pts[MP_NOSE])
    return build_lmk106(bl, br, nose, pts[MP_HALF], pts[MP_JAW], pts[MP_MOUTH], pts[MP_NOSE].mean(0))


def from_anime(kp: np.ndarray, k: float = ANIME_NOSE_K) -> np.ndarray:
    """(28, 2) anime-face-detector points -> lmk106. ``k`` moves the nose along the brow-mid -> nose line."""
    kp = np.asarray(kp, np.float64)[:, :2]
    bl, br = _order_lr(kp[5:8], kp[8:11])
    mid = (bl.mean(0) + br.mean(0)) / 2
    nose = mid + k * (kp[23] - mid)
    eyes_mid = kp[11:23].mean(0)
    mouth = kp[24:28]
    jaw = kp[0:5]
    return build_lmk106(bl, br, np.tile(nose, (4, 1)), np.stack([(eyes_mid + nose) / 2, nose]), jaw, mouth, nose)


MOUTH_TOL = 0.12  # mouth-centre disagreement, in brow-to-brow distances, that makes "auto" trust the anime model


def kp_box(kp) -> tuple:
    kp = np.asarray(kp)[:, :2]
    return kp[:, 0].min(), kp[:, 1].min(), kp[:, 0].max(), kp[:, 1].max()


def _iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return float(inter / ua) if ua > 0 else 0.0


def smooth_landmarks(lmks: list, sigma: float, jump: float = 0.25) -> list:
    """Centred Gaussian smoothing over time of a list of (106, 2) landmark arrays (None = no face on that frame).

    Runs of consecutive frames are smoothed separately; a run is also split where the face centre jumps by more
    than ``jump`` face widths between frames (a track switch or a cut), so two faces are never averaged. Edges are
    renormalised (no pull toward zero). Returns float64 arrays (None stays None); ``sigma <= 0`` returns copies."""
    out = [None if l is None else np.asarray(l, np.float64).copy() for l in lmks]
    if sigma <= 0:
        return out
    r = max(1, int(round(3 * sigma)))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    runs, cur = [], []
    for i, l in enumerate(out):
        if l is None:
            if cur:
                runs.append(cur)
            cur = []
            continue
        if cur:
            p = out[cur[-1]]
            w = float(np.ptp(p[:, 0])) or 1.0
            if np.linalg.norm(l.mean(0) - p.mean(0)) > jump * w:
                runs.append(cur)
                cur = []
        cur.append(i)
    if cur:
        runs.append(cur)
    res = list(out)
    for run in runs:
        a = np.stack([out[i] for i in run])  # (T, 106, 2)
        T = len(run)
        for t in range(T):
            lo, hi = max(0, t - r), min(T, t + r + 1)
            ww = k[lo - t + r: hi - t + r]
            res[run[t]] = np.tensordot(ww / ww.sum(), a[lo:hi], axes=1)
    return res


class AmbiguousFace(RuntimeError):
    """Several faces on the first frame and no ``face_box`` to say which one speaks."""

    code = "ambiguous_face"


def parse_face_box(text: str | None):
    """"x,y,w,h" (first-frame pixels) -> (x1, y1, x2, y2), or None."""
    if not text:
        return None
    x, y, w, h = (float(v) for v in str(text).replace(" ", "").split(","))
    if w <= 0 or h <= 0:
        raise ValueError(f"face box needs a positive width and height, got {text!r}")
    return x, y, x + w, y + h


def _ext(pts) -> tuple:
    pts = np.asarray(pts)[:, :2]
    return float(pts[:, 0].min()), float(pts[:, 1].min()), float(pts[:, 0].max()), float(pts[:, 1].max())


def _centre(b):
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2


DUP_IOU = 0.5  # two detections overlapping this much are the same face (FaceLandmarker sometimes returns both)


def dedupe(boxes: list, iou: float = DUP_IOU) -> list:
    """Indices of ``boxes`` to keep after dropping duplicates of the same face (greedy, first one wins: the
    detectors list the most confident first). Without this a doubled face counted as a second face
    (multi_face_frames, a spurious ambiguous_face) and tracking could flip between the two copies."""
    keep: list = []
    for i, b in enumerate(boxes):
        if all(_iou(b, boxes[k]) < iou for k in keep):
            keep.append(i)
    return keep


SIGNIFICANT = 0.35  # a face counts as "another face" if it is at least this fraction of the largest face's height


def significant(boxes: list) -> list:
    if not boxes:
        return []
    hmax = max(b[3] - b[1] for b in boxes)
    return [i for i, b in enumerate(boxes) if (b[3] - b[1]) >= SIGNIFICANT * hmax]


class FaceDetector:
    """Drop-in for upstream ``FaceDetector``. No InsightFace anywhere.

    Face choice: frame 0 takes the face that best overlaps ``face_box`` (x1, y1, x2, y2; else the nearest centre).
    Without a box, more than one significant face on frame 0 raises :class:`AmbiguousFace`. After that the
    detector tracks the face nearest the previous one (IoU, then centre distance within one face width).
    No identity embedding is used (ArcFace / InsightFace weights are non-commercial).
    """

    def __init__(self, device: str = "cuda", task_path: str | os.PathLike | None = None, anime: bool | None = None,
                 hold: int | None = None, style: str | None = None, face_box=None):
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision

        task = Path(task_path or os.environ.get("OPENSOUL_MP_FACE_TASK", DEFAULT_TASK))
        if not task.is_file():
            raise FileNotFoundError(f"MediaPipe face_landmarker.task not found at {task} "
                                    "(scripts/download_models.sh lipsync, or set OPENSOUL_MP_FACE_TASK)")
        verify_pinned(task, MP_TASK_SHA256, "MediaPipe face_landmarker.task (scripts/download_models.sh lipsync)")
        self._mp = mp
        with no_network():  # local file only
            self._lm = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(task)), num_faces=4,
                min_face_detection_confidence=0.3, min_face_presence_confidence=0.3))
        self.style = (style or os.environ.get("OPENSOUL_LS_FACE_STYLE", "auto")).strip().lower()
        if self.style not in ("auto", "real", "anime"):
            raise ValueError(f"OPENSOUL_LS_FACE_STYLE must be auto, real or anime, not {self.style!r}")
        self._anime = None
        use_anime = (os.environ.get("OPENSOUL_LS_ANIME", "1") != "0") if anime is None else anime
        if use_anime and self.style != "real":
            self._anime = create_anime_detector(device)  # pinned local weights or None; never downloads
        if face_box is None:
            box = parse_face_box(os.environ.get("OPENSOUL_LS_FACE_BOX"))
        elif isinstance(face_box, str):
            box = parse_face_box(face_box)
        else:  # (x, y, w, h) on frame 0
            box = parse_face_box(",".join(str(float(v)) for v in face_box))
        self.target = box
        self.hold = int(os.environ.get("OPENSOUL_LS_HOLD", "12") if hold is None else hold)
        self._last = None      # (lmk106, ls_box)
        self._last_ext = None  # face extent of the tracked face
        self._miss = 0
        self.last_source = None
        self.smooth = float(os.environ.get("OPENSOUL_LS_SMOOTH", "1.0"))
        self._queue: list = []  # primed (box, lmk) answers, consumed in order by __call__
        self.rec = Record(self.style, self.target)
        INSTANCES.append(self.rec)  # the small stats record, not the detector (no model kept alive)

    # stats live on self.rec so the registry never holds the models
    frames = property(lambda s: s.rec.frames, lambda s, v: setattr(s.rec, "frames", v))
    multi_face_frames = property(lambda s: s.rec.multi_face_frames, lambda s, v: setattr(s.rec, "multi_face_frames", v))
    face_px = property(lambda s: s.rec.face_px)
    stats = property(lambda s: s.rec.stats)

    # -- detectors -------------------------------------------------------------------------------------------
    def _mp_points(self, rgb: np.ndarray, off=(0, 0)):
        res = self._lm.detect(self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)))
        h, w = rgb.shape[:2]
        return [np.array([[p.x * w + off[0], p.y * h + off[1]] for p in f]) for f in res.face_landmarks]

    def _anime_preds(self, frame: np.ndarray) -> list:
        if self._anime is None:
            return []
        return [p for p in self._anime(np.ascontiguousarray(frame[:, :, ::-1])) if p["bbox"][4] > 0.5]

    def _crop_box(self, frame, box, margin=0.6):
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = box
        mw, mh = (x2 - x1) * margin, (y2 - y1) * margin
        return int(max(0, x1 - mw)), int(max(0, y1 - mh)), int(min(w, x2 + mw)), int(min(h, y2 + mh))

    def _select(self, boxes: list):
        """Index of the face to use among ``boxes`` (x1, y1, x2, y2), or None (track lost)."""
        if not boxes:
            return None
        ref = self._last_ext if self._last_ext is not None else self.target
        if ref is not None:
            ious = [_iou(b, ref) for b in boxes]
            if max(ious) > 0.05:
                return int(np.argmax(ious))
            c = _centre(ref)
            d = [np.hypot(*np.subtract(_centre(b), c)) for b in boxes]
            if self._last_ext is not None and min(d) > (ref[2] - ref[0]):
                return None  # nearest face is more than a face width away: not the tracked face
            return int(np.argmin(d))
        sig = significant(boxes)
        if len(sig) > 1:
            raise AmbiguousFace(f"ambiguous_face: {len(sig)} faces on the first frame and no face box "
                                "(pass --face-box x,y,w,h for the speaker)")
        return max(range(len(boxes)), key=lambda i: (boxes[i][3] - boxes[i][1]) * (boxes[i][2] - boxes[i][0]))

    @staticmethod
    def mp_disagrees(mp_pts: np.ndarray, kp: np.ndarray, tol: float = MOUTH_TOL) -> bool:
        """True when MediaPipe put the mouth somewhere else than the anime landmark model (same face).
        On drawn anime faces FaceMesh often 'succeeds' with the mouth on the chin or collar."""
        if _iou(_ext(mp_pts), kp_box(kp)) < 0.1:
            return False
        brow = np.linalg.norm(mp_pts[MP_BROW_A].mean(0) - mp_pts[MP_BROW_B].mean(0)) or 1.0
        return float(np.linalg.norm(mp_pts[MP_MOUTH].mean(0) - np.asarray(kp)[24:28, :2].mean(0)) / brow) > tol

    def detect(self, frame: np.ndarray):
        """frame: RGB uint8 (as LatentSync passes it). Returns (lmk106, source, extent) or (None, 'miss', None).

        style "real": MediaPipe only. "anime": anime landmarks first, MediaPipe if none. "auto" (default):
        MediaPipe, cross-checked against the anime model when it is installed (anime wins only if both found
        the same face and disagree on where the mouth is)."""
        style = self.style
        preds = self._anime_preds(frame) if style in ("auto", "anime") else []
        faces = self._mp_points(frame)
        keep = dedupe([_ext(f) for f in faces])
        self.rec.dup_faces += len(faces) - len(keep)
        faces = [faces[i] for i in keep]
        mp_boxes = [_ext(f) for f in faces]
        an_all = [tuple(float(v) for v in p["bbox"][:4]) for p in preds]
        preds = [preds[i] for i in dedupe(an_all)]
        an_boxes = [tuple(float(v) for v in p["bbox"][:4]) for p in preds]
        n = max(len(significant(mp_boxes)), len(significant(an_boxes)))
        if n > 1:
            self.multi_face_frames += 1
        if n > 1 and self._last_ext is None and self.target is None:
            raise AmbiguousFace(f"ambiguous_face: {n} faces on the first frame and no face box "
                                "(pass --face-box x,y,w,h for the speaker)")
        pred = None
        if preds and (style == "anime" or not faces):
            j = self._select(an_boxes)
            pred = preds[j] if j is not None else None
        if style == "anime" and pred is not None:
            return from_anime(pred["keypoints"]), "anime", an_boxes[preds.index(pred)]
        src = "mediapipe"
        f = None
        if faces:
            i = self._select(mp_boxes)
            f = faces[i] if i is not None else None
        else:
            boxes = [self._last_ext if self._last_ext is not None else self.target]
            boxes = [b for b in boxes if b is not None] + ([an_boxes[preds.index(pred)]] if pred is not None else [])
            for bx in boxes:
                x1, y1, x2, y2 = self._crop_box(frame, bx, 0.6)
                if x2 - x1 > 32 and y2 - y1 > 32:
                    cands = self._mp_points(frame[y1:y2, x1:x2], off=(x1, y1))
                    k = self._select([_ext(c) for c in cands]) if cands else None
                    if k is not None:
                        f, src = cands[k], "mediapipe_crop"
                        break
        if f is not None:
            if preds and style == "auto":
                q = max(preds, key=lambda p: _iou(_ext(f), kp_box(p["keypoints"])))
                if self.mp_disagrees(f, q["keypoints"]):
                    return from_anime(q["keypoints"]), "anime_override", tuple(float(v) for v in q["bbox"][:4])
            return from_mediapipe(f), src, _ext(f)
        if pred is not None:
            return from_anime(pred["keypoints"]), "anime", an_boxes[preds.index(pred)]
        return None, "miss", None

    def prime(self, frames, sigma: float | None = None) -> int:
        """Detect on all ``frames`` now (stats are counted here, once), smooth the landmark tracks over time and
        queue the answers so the next ``len(frames)`` calls return them in order. Returns the number queued."""
        sigma = float(getattr(self, "smooth", 1.0) if sigma is None else sigma)
        raw = [self._detect_one(f) for f in frames]
        sm = smooth_landmarks([l for _, l in raw], sigma)
        q = []
        for (box, lmk), s_l in zip(raw, sm):
            if lmk is None:
                q.append((None, None))
                continue
            h, w = np.asarray(frames[0]).shape[:2]
            q.append((ls_box(_int(s_l), w, h), s_l))
        self._queue = q
        self.rec.smooth_sigma = sigma
        return len(q)

    def __call__(self, frame, threshold: float = 0.5):
        q = getattr(self, "_queue", None)
        if q:
            return q.pop(0)
        return self._detect_one(frame)

    def _detect_one(self, frame):
        frame = np.asarray(frame)
        if frame.dtype != np.uint8:
            frame = np.clip(frame, 0, 255).astype(np.uint8)
        f_h, f_w = frame.shape[:2]
        self.frames += 1
        lmk, src, ext = self.detect(frame)
        if lmk is not None:
            box = ls_box(lmk, f_w, f_h)
            if box[2] - box[0] <= 0 or box[3] - box[1] <= 0:
                lmk = None
        if lmk is None:
            if self._last is not None and self._miss < self.hold:
                self._miss += 1
                self.stats["hold"] += 1
                self.last_source = "hold"
                return self._last[1], self._last[0]
            self.stats["miss"] += 1
            self.last_source = "miss"
            return None, None
        self.stats[src] += 1
        self.last_source = src
        self._miss = 0
        self._last = (lmk, box)
        self._last_ext = ext
        self.face_px.append(float(ext[3] - ext[1]))
        return box, lmk

    def report(self) -> dict:
        """Detector part of the ``<out>.lipsync.json`` sidecar."""
        return self.rec.report()


class Record:
    """Per-detector counters (what the sidecar reports)."""

    def __init__(self, style="auto", target=None):
        self.style, self.target = style, target
        self.frames = 0
        self.smooth_sigma = 0.0
        self.dup_faces = 0
        self.multi_face_frames = 0
        self.face_px: list[float] = []
        self.stats = {"mediapipe": 0, "mediapipe_crop": 0, "anime": 0, "anime_override": 0, "hold": 0, "miss": 0}

    def report(self) -> dict:
        st = self.stats
        n = max(self.frames, 1)
        found = st["mediapipe"] + st["mediapipe_crop"] + st["anime"] + st["anime_override"]
        px = self.face_px
        return {
            "frames": self.frames,
            "face_found_ratio": round(found / n, 4) if self.frames else None,
            "held_frames": st["hold"],
            "detector_counts": {"mediapipe": st["mediapipe"] + st["mediapipe_crop"],
                                "anime_fallback": st["anime"] + st["anime_override"],
                                "held": st["hold"], "none": st["miss"]},
            "face_px_median": round(float(np.median(px)), 1) if px else None,
            "face_px_min": round(float(np.min(px)), 1) if px else None,
            "multi_face_frames": self.multi_face_frames,
            "duplicate_detections_dropped": self.dup_faces,
            "face_box": list(self.target) if self.target is not None else None,
            "style": self.style,
            "smooth_sigma": self.smooth_sigma,
        }


INSTANCES: list = []  # a Record per FaceDetector made in this process (latentsync_infer reads the stats here)


def cuda_to_int(cuda_str: str) -> int:  # kept for API parity with upstream
    if cuda_str == "cuda":
        return 0
    return int(str(cuda_str).split(":")[-1])
