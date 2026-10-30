"""Plate lock: keep the set pixel-identical across every shot of a location.

Two problems this fixes (see docs/VIDEO_QUALITY_FIXES.md section 7):
  * Image edits drift the set a little between shots (shelves move, lights change).
    `lock_frame` aligns an edited start frame to the location's master plate and copies
    the plate back everywhere except where the frame really differs (the actors and props).
  * Video models let a "static" set creep, breathe and smear (ghosting).
    `lock_video` composites each video frame's actors over the static plate with a
    temporally smoothed matte, so the set cannot move at all.

Pure OpenCV/numpy, CPU only.
"""
from __future__ import annotations

import cv2
import numpy as np


def _align(plate: np.ndarray, frame: np.ndarray) -> np.ndarray:
    """Warp `plate` onto `frame` (small affine shift/zoom). Falls back to identity."""
    g1 = cv2.cvtColor(cv2.resize(plate, (frame.shape[1], frame.shape[0])), cv2.COLOR_BGR2GRAY).astype(np.float32)
    g2 = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
    warp = np.eye(2, 3, dtype=np.float32)
    s = 0.25  # estimate at quarter scale for speed and robustness
    small = lambda g: cv2.GaussianBlur(cv2.resize(g, None, fx=s, fy=s), (5, 5), 0)
    try:
        _, warp = cv2.findTransformECC(small(g2), small(g1), warp, cv2.MOTION_AFFINE,
                                       (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 100, 1e-5), None, 5)
        warp[:, 2] /= s
    except cv2.error:
        warp = np.eye(2, 3, dtype=np.float32)
    big = cv2.resize(plate, (frame.shape[1], frame.shape[0]))
    warped = cv2.warpAffine(big, warp, (frame.shape[1], frame.shape[0]), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                            borderMode=cv2.BORDER_REPLICATE)
    # only accept the warp if it really fits the set better (median ignores the actors)
    err = lambda a: float(np.median(np.abs(cv2.cvtColor(a, cv2.COLOR_BGR2GRAY).astype(np.float32) - g2)))
    return warped if err(warped) < err(big) else big


def _align_like(ref: np.ndarray, other: np.ndarray, frame: np.ndarray) -> np.ndarray:
    """Warp `other` with the transform that maps `ref` onto `frame` (ref and other share framing)."""
    g1 = cv2.cvtColor(cv2.resize(ref, (frame.shape[1], frame.shape[0])), cv2.COLOR_BGR2GRAY).astype(np.float32)
    g2 = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
    warp = np.eye(2, 3, dtype=np.float32)
    s = 0.25
    small = lambda g: cv2.GaussianBlur(cv2.resize(g, None, fx=s, fy=s), (5, 5), 0)
    big_o = cv2.resize(other, (frame.shape[1], frame.shape[0]))
    try:
        _, warp = cv2.findTransformECC(small(g2), small(g1), warp, cv2.MOTION_AFFINE,
                                       (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 100, 1e-5), None, 5)
        warp[:, 2] /= s
    except cv2.error:
        return big_o
    big_r = cv2.resize(ref, (frame.shape[1], frame.shape[0]))
    fl = cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP
    wr = cv2.warpAffine(big_r, warp, (frame.shape[1], frame.shape[0]), flags=fl, borderMode=cv2.BORDER_REPLICATE)
    err = lambda a: float(np.median(np.abs(cv2.cvtColor(a, cv2.COLOR_BGR2GRAY).astype(np.float32) - g2)))
    if err(wr) >= err(big_r):
        return big_o
    return cv2.warpAffine(big_o, warp, (frame.shape[1], frame.shape[0]), flags=fl, borderMode=cv2.BORDER_REPLICATE)


def diff_mask(plate: np.ndarray, frame: np.ndarray, thresh: float = 18.0, min_area: float = 0.002,
              grow: int = 12) -> np.ndarray:
    """Binary uint8 mask (0/255) of where `frame` really differs from the aligned `plate`."""
    a = cv2.cvtColor(plate, cv2.COLOR_BGR2LAB).astype(np.float32)
    b = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB).astype(np.float32)
    d = np.sqrt(((cv2.GaussianBlur(a, (7, 7), 0) - cv2.GaussianBlur(b, (7, 7), 0)) ** 2).sum(-1))
    m = (d > thresh).astype(np.uint8) * 255
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    m = cv2.morphologyEx(cv2.morphologyEx(m, cv2.MORPH_OPEN, k), cv2.MORPH_CLOSE, k, iterations=3)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m)
    keep = np.zeros_like(m)
    for i in range(1, n):  # drop specks (rain, noise); keep people and props
        if stats[i, cv2.CC_STAT_AREA] >= min_area * m.size:
            keep[lab == i] = 255
    # fill holes so faces/clothes that happen to match the plate colour stay in the matte
    cnts, _ = cv2.findContours(keep, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(keep, cnts, -1, 255, cv2.FILLED)
    if grow:
        keep = cv2.dilate(keep, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 1, 2 * grow + 1)))
    return keep


def match_colors(img: np.ndarray, target: np.ndarray, ref: np.ndarray | None = None) -> np.ndarray:
    """Per-channel LAB median/spread transfer so `img` has `target`'s colour and contrast. With `ref`, the transfer
    is measured from ref -> target and applied to img (e.g. a cleaned copy of the plate)."""
    src = cv2.cvtColor(cv2.resize(ref if ref is not None else img, (target.shape[1], target.shape[0])), cv2.COLOR_BGR2LAB).astype(np.float32)
    tgt = cv2.cvtColor(target, cv2.COLOR_BGR2LAB).astype(np.float32)
    out = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
    for c in range(3):
        s_med, t_med = np.median(src[..., c]), np.median(tgt[..., c])
        s_sp = np.percentile(src[..., c], 90) - np.percentile(src[..., c], 10) + 1e-3
        t_sp = np.percentile(tgt[..., c], 90) - np.percentile(tgt[..., c], 10) + 1e-3
        out[..., c] = (out[..., c] - s_med) * (t_sp / s_sp) + t_med
    return cv2.cvtColor(out.clip(0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR)


def composite(plate: np.ndarray, frame: np.ndarray, mask: np.ndarray, feather: int = 21) -> np.ndarray:
    f = feather | 1
    alpha = cv2.GaussianBlur(mask.astype(np.float32) / 255.0, (f, f), 0)[..., None]
    return (frame.astype(np.float32) * alpha + plate.astype(np.float32) * (1 - alpha)).clip(0, 255).astype(np.uint8)


def lock_frame(frame: np.ndarray, plate: np.ndarray, **kw) -> tuple[np.ndarray, np.ndarray]:
    """Return (locked frame, mask). The set comes from the plate, actors from the frame."""
    p = _align(plate, frame)
    m = diff_mask(p, frame, **kw)
    return composite(p, frame, m), m


def lock_video(src: str, dst: str, plate_img: np.ndarray, window: int = 4, live_boxes=(), fill_img: np.ndarray | None = None,
               match_color: bool = True, **kw) -> dict:
    """Composite every frame's actors over the static plate.

    The matte for frame t is the union of the per-frame masks in [t-window, t+window], so a
    hand that moves fast never gets cut off and the edge does not flicker. The plate is aligned
    once to the first frame (the camera is meant to be locked). `live_boxes` are (x0, y0, x1, y1)
    fractions that always stay live (e.g. a rainy window that should keep moving). `fill_img` (same framing as the
    plate, e.g. a cleaned-up copy) is what gets composited; the matte is still measured against `plate_img`.
    """
    plate_img_orig = plate_img
    cap = cv2.VideoCapture(src)
    fps = cap.get(cv2.CAP_PROP_FPS) or 24
    frames = []
    while True:
        ok, im = cap.read()
        if not ok:
            break
        frames.append(im)
    if not frames:
        raise ValueError(f"no frames in {src}")
    h, w = frames[0].shape[:2]
    plate = _align(plate_img, frames[0])
    if match_color:  # the video model shifts colour/contrast; match the plate to the clip's own first frame
        plate_img = match_colors(plate_img, frames[0])
        if fill_img is not None:
            fill_img = match_colors(fill_img, frames[0], ref=plate_img_orig)
        plate = _align(plate_img, frames[0])
    masks = [diff_mask(plate, f, **kw) for f in frames]
    if fill_img is not None:
        plate = _align_like(plate_img, fill_img, frames[0])
    for (x0, y0, x1, y1) in live_boxes:
        for m in masks:
            m[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)] = 255
    out = cv2.VideoWriter(dst, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    cover = []
    for t, f in enumerate(frames):
        m = np.max(masks[max(0, t - window):t + window + 1], axis=0)
        cover.append(float((m > 0).mean()))
        out.write(composite(plate, f, m))
    out.release()
    return {"frames": len(frames), "fps": fps, "matte_cover_mean": round(float(np.mean(cover)), 3)}


def repeated_frame_share(path: str, eps: float = 0.15) -> float:
    """Share of frames identical to the previous one. Slow-mo by frame duplication reads as judder/ghosting."""
    cap = cv2.VideoCapture(path)
    prev, d = None, []
    while True:
        ok, im = cap.read()
        if not ok:
            break
        g = cv2.cvtColor(cv2.resize(im, (320, 176)), cv2.COLOR_BGR2GRAY).astype(np.float32)
        if prev is not None:
            d.append(float(np.abs(g - prev).mean()))
        prev = g
    return float(np.mean(np.array(d) < eps)) if d else 0.0


def stack_actors(plate: np.ndarray, frames: list[np.ndarray], feather: int = 15, **kw) -> tuple[np.ndarray, list[np.ndarray]]:
    """Build one start frame from several separately-generated frames of the SAME locked plate.

    Each frame holds one actor or group (e.g. the clerk alone, the couple alone), all edited from the stage plate.
    Their mattes (vs. the plate) are laid back-to-front over the plate in list order, so later frames are nearer
    the camera. This keeps each actor exactly as the image model drew them while the set stays the plate's, and
    side-steps edit models that squeeze several people into one spot. Returns (frame, mattes)."""
    out = plate.copy()
    masks = []
    for f in frames:
        p = _align(plate, f)
        m = diff_mask(p, f, **kw)
        masks.append(m)
        out = composite(out, f, m, feather=feather)
    return out, masks

