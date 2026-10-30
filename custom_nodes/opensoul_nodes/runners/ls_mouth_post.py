"""Optional mouth post-processing for LatentSync output (CPU; numpy + OpenCV; MediaPipe only for the lip points).

LatentSync regenerates the lower face at 512 px and pastes it back. On medium shots that mouth is softer than the
raw take, open mouths can read as a flat dark void, and some lines over-articulate. Two local fixes, both limited
to a feathered mask around the lips (union of the raw and the synced lip outline, so a wider synced mouth is
covered too):

* ``raw_frac``: mix that fraction of the raw take's mouth back in (0 = pure LatentSync, 0.5 = halfway). Brings
  back raw texture / teeth and damps over-articulation; at high values the raw mouth shape shows through.
* ``sharpen``: unsharp mask (amount, Gaussian sigma ``sharpen_sigma`` px) inside the same mask.

Frames must correspond 1:1 (same fps and frame count: the runner checks that before calling this).
"""
from __future__ import annotations

import hashlib
import os

import numpy as np

# Same pin as ls_face_detector.MP_TASK_SHA256 / scripts/download_models.sh lipsync: the task is a local file only.
MP_TASK_SHA256 = "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff"


def check_task(task) -> str:
    """``task`` as str if it is a file with the pinned sha256, else RuntimeError (never fetched from anywhere)."""
    if not os.path.isfile(task):
        raise RuntimeError(f"MediaPipe face_landmarker.task not found at {task} (scripts/download_models.sh lipsync)")
    h = hashlib.sha256()
    with open(task, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    if h.hexdigest() != MP_TASK_SHA256:
        raise RuntimeError(f"MediaPipe face_landmarker.task {task}: sha256 {h.hexdigest()} != pinned {MP_TASK_SHA256}")
    return str(task)

# MediaPipe FaceMesh outer-lip ring (same set the detector maps to the 2d106 mouth points)
MP_LIPS_OUTER = [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 409, 270, 269, 267, 0, 37, 39, 40, 185]


def mouth_mask(shape, polys, grow: float = 0.30, feather: float = 0.35) -> np.ndarray:
    """Float32 (H, W) mask in [0, 1]: filled hull of all ``polys`` (N, 2 point arrays), grown by ``grow`` and
    feathered by ``feather`` (both in mouth widths)."""
    import cv2

    h, w = shape[:2]
    pts = np.concatenate([np.asarray(p, np.float32) for p in polys if p is not None and len(p)], axis=0) if polys else None
    m = np.zeros((h, w), np.float32)
    if pts is None or not len(pts):
        return m
    mw = float(np.ptp(pts[:, 0])) or 1.0
    hull = cv2.convexHull(pts.astype(np.int32))
    cv2.fillConvexPoly(m, hull, 1.0)
    g = max(1, int(round(grow * mw)))
    m = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * g + 1, 2 * g + 1)))
    s = max(0.5, feather * mw / 2)
    m = cv2.GaussianBlur(m, (0, 0), s)
    return np.clip(m / max(float(m.max()), 1e-6), 0, 1)


def blend(ls: np.ndarray, raw: np.ndarray, mask: np.ndarray, raw_frac: float) -> np.ndarray:
    a = (np.clip(raw_frac, 0, 1) * mask)[..., None]
    return np.clip(ls.astype(np.float32) * (1 - a) + raw.astype(np.float32) * a + 0.5, 0, 255).astype(np.uint8)


def unsharp(img: np.ndarray, mask: np.ndarray, amount: float, sigma: float = 1.2) -> np.ndarray:
    import cv2

    if amount <= 0:
        return img
    f = img.astype(np.float32)
    sharp = f + amount * (f - cv2.GaussianBlur(f, (0, 0), sigma))
    m = mask[..., None]
    return np.clip(f * (1 - m) + sharp * m + 0.5, 0, 255).astype(np.uint8)


def laplacian_var(img: np.ndarray, box) -> float:
    """Variance of the Laplacian of the grey image inside box (x1, y1, x2, y2): the sharpness measure."""
    import cv2

    x1, y1, x2, y2 = (int(round(v)) for v in box)
    roi = img[max(0, y1):y2, max(0, x1):x2]
    if roi.size == 0:
        return float("nan")
    g = cv2.cvtColor(roi, cv2.COLOR_RGB2GRAY) if roi.ndim == 3 else roi
    return float(cv2.Laplacian(g, cv2.CV_64F).var())


def mouth_box(poly, pad: float = 0.25):
    p = np.asarray(poly, np.float64)
    x1, y1, x2, y2 = p[:, 0].min(), p[:, 1].min(), p[:, 0].max(), p[:, 1].max()
    px, py = pad * (x2 - x1), pad * (x2 - x1)
    return x1 - px, y1 - py, x2 + px, y2 + py


class LipFinder:
    """Outer-lip polygon of the face nearest a reference point, per RGB frame (MediaPipe FaceLandmarker)."""

    def __init__(self, task_path=None):
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision

        from_env = os.environ.get("OPENSOUL_MP_FACE_TASK")
        task = task_path or from_env or os.path.join(os.environ.get("OPENSOUL_HOME", os.path.expanduser("~/OpenSoul")),
                                                    "models/mediapipe/face_landmarker.task")
        task = check_task(task)
        self._mp = mp
        self._lm = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=task), num_faces=4,
            min_face_detection_confidence=0.3, min_face_presence_confidence=0.3))

    def __call__(self, rgb: np.ndarray, near=None):
        h, w = rgb.shape[:2]
        r = self._lm.detect(self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)))
        faces = [np.array([[p.x * w, p.y * h] for p in f]) for f in r.face_landmarks]
        if not faces:
            return None
        lips = [f[MP_LIPS_OUTER] for f in faces]
        if near is None:
            return max(lips, key=lambda l: np.ptp(l[:, 0]))
        return min(lips, key=lambda l: np.linalg.norm(l.mean(0) - np.asarray(near)))


def process_frames(ls_frames, raw_frames, lips, raw_frac=0.0, sharpen=0.0, sharpen_sigma=1.2, near=None):
    """Apply the mouth fixes frame by frame. ``lips(rgb, near)`` returns a lip polygon or None (frame unchanged).
    Returns (frames, stats) with the sharpness of raw / LatentSync / result in the raw lip box."""
    out, st = [], {"frames": 0, "fixed": 0, "lap_raw": [], "lap_ls": [], "lap_out": []}
    for ls, raw in zip(ls_frames, raw_frames):
        st["frames"] += 1
        pr = lips(raw, near)
        pl = lips(ls, pr.mean(0) if pr is not None else near)
        if pr is None and pl is None:
            out.append(ls)
            continue
        near = (pr if pr is not None else pl).mean(0)
        m = mouth_mask(ls.shape, [pr, pl])
        o = blend(ls, raw, m, raw_frac) if raw_frac > 0 else ls
        o = unsharp(o, m, sharpen, sharpen_sigma) if sharpen > 0 else o
        if pr is not None:
            b = mouth_box(pr)
            st["lap_raw"].append(laplacian_var(raw, b)); st["lap_ls"].append(laplacian_var(ls, b)); st["lap_out"].append(laplacian_var(o, b))
        st["fixed"] += 1
        out.append(o)
    summ = {"frames": st["frames"], "fixed": st["fixed"]}
    for k in ("lap_raw", "lap_ls", "lap_out"):
        summ[k + "_median"] = round(float(np.median(st[k])), 2) if st[k] else None
    if summ["lap_raw_median"]:
        summ["sharpness_ls_vs_raw"] = round(summ["lap_ls_median"] / summ["lap_raw_median"], 3)
        summ["sharpness_out_vs_raw"] = round(summ["lap_out_median"] / summ["lap_raw_median"], 3)
    return out, summ
