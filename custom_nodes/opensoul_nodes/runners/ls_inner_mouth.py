"""Inner-mouth pass for LatentSync output (CPU only; numpy + OpenCV, MediaPipe via ``ls_face_detector``).

LatentSync 1.6 often renders an open mouth on stylised / painterly faces as a flat black void (no teeth or
tongue), or as a grey smeared band where teeth should be. This pass repairs only those frames, only inside the
synced frame's inner-lip outline, using the matching raw (pre-lip-sync) take as the source of teeth/interior:

1. Lips per frame (synced and raw): MediaPipe FaceLandmarker inner (20) + outer (20) lip ring, picked and tracked
   by OpenSoul's detector (``ls_face_detector.FaceDetector``: face box, tracking, crop retry, anime cross-check).
   When the detector falls back to the anime model there is no inner-lip ring; that frame is logged
   ``anime_fallback`` and, by default, left untouched (``anime_policy="skip"``; ``"approx"`` builds an inner ring
   from the mouth points).
2. Classification of every synced frame (thresholds in :class:`Config`, decisions logged per frame):
   * ``void``: inner ring open (openness = gap 13-14 / width 61-291 >= ``open_thr``) and >= ``void_frac`` of the
     interior near-black (luma < ``dark_rel`` x chin-skin luma) with almost nothing lit (> ``bright_rel`` x skin).
   * ``smear``: open, with a colourless grey band (pixels >= ``grey_rel`` x skin covering >= ``smear_area`` x mouth
     width^2, median Lab chroma < ``smear_chroma``, greener than the lips by ``smear_vs_lip``) and no clearly bright
     teeth (> ``teeth_rel`` x skin): LatentSync's grey smeared teeth.
   Flags are closed over one-frame gaps and dilated by ``dilate`` frames while the mouth is still open, then a
   per-frame strength is smoothed over time (``temporal_sigma``) so the fix fades in and out.
3. Source per flagged run: if the raw take is open with a lit interior on some frames of the run, the run follows
   the raw take (same index; the run's other frames hold the nearest such frame). Otherwise ONE donor for the
   whole run: the raw frame with clearly visible teeth nearest the run (stable, so no texture flicker). The source
   interior is warped onto the synced inner ring (thin-plate spline on inner + outer
   lip points, or affine), colour-matched (Lab mean/std of the lip + perioral ring, per run) and composited with
   a mask that is 0 on and outside the inner-lip outline and feathers inward, so lips are never overwritten.
4. Conformance: same fps, same frame count, the synced file's audio stream copied unchanged, no consecutive
   identical frames. Any mismatch raises :class:`ConformError` (CLI exit code 6).

CLI: ``python ls_inner_mouth.py SYNCED.mp4 RAW.mp4 -o OUT.mp4 [--log OUT.json] [--evidence DIR] [thresholds]``.

Sidecar (``OUT.mp4.inner_mouth.json``, written after the video and the conformance check, as the last step):
per-frame decisions plus ``out_frames`` (frames decoded from the written OUT.mp4) and ``out_sha256`` (sha256 hex of
OUT.mp4 as left on disk; both null on ``--dry-run``), and ``parent_sidecar`` / ``parent_sidecar_sha256``: the
synced take's ``SYNCED.mp4.lipsync.json`` and its sha256 (null when the synced take has none).

Defaults = the reviewer-approved "L1c2" settings (validated 2026-10-19): ``--lip-color-fix``
on with ``--lip-fix-mode blend``, ``--mask-erode 1``, near-closed frames (``--open-thr 0.06``) never composited,
``--dilate 1``; so running with no flags reproduces L1c2. Every bool setting has a ``--no-...`` switch.
``--face-style auto`` (default) is MediaPipe first; the anime landmark model is loaded lazily, only on the first
frame MediaPipe misses (loading it costs minutes on a CPU box), and used only for such frames. ``real`` never
loads it; ``anime`` loads it up front. MediaPipe ``face_landmarker.task``: ``--task``, else
``OPENSOUL_MP_FACE_TASK``, else the detector's default (``$OPENSOUL_HOME/models/mediapipe``), else
``./models/face_landmarker.task`` or ``./models/mediapipe/face_landmarker.task``.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent

# MediaPipe FaceMesh lip rings (ordered around the ring). INNER starts at the image-left corner 78.
INNER = [78, 191, 80, 81, 82, 13, 312, 311, 310, 415, 308, 324, 318, 402, 317, 14, 87, 178, 88, 95]
OUTER = [61, 185, 40, 39, 37, 0, 267, 269, 270, 409, 291, 375, 321, 405, 314, 17, 84, 181, 91, 146]
UPPER_MID, LOWER_MID, CORNER_L, CORNER_R = 13, 14, 61, 291
CHIN = (17, 152)


class ConformError(RuntimeError):
    """Output does not match the input (fps, frame count, audio, repeated frames)."""

    code = 6


@dataclasses.dataclass
class Config:
    # detection (luma is relative to the chin-skin luma, so dim night scenes and bright scenes read alike)
    open_thr: float = 0.06        # inner gap / mouth width: "open"
    min_area_px: int = 30         # smaller inner polygons are treated as closed
    dark_rel: float = 0.22        # near-black: luma < dark_rel x skin
    bright_rel: float = 0.45      # visible interior (teeth / tongue lit at all): luma > bright_rel x skin
    teeth_rel: float = 0.85       # clearly bright teeth: luma > teeth_rel x skin
    void_frac: float = 0.60       # void: >= this fraction of the interior is near-black ...
    void_teeth_max: float = 0.03  # ... and the visible (bright_rel) fraction is below this
    grey_rel: float = 0.30        # "grey" interior pixels: luma >= grey_rel x skin
    smear_area: float = 0.045     # smear: grey area / mouth width^2 at least this (a band, not a glint) ...
    smear_chroma: float = 22.0    # ... median Lab chroma of the grey pixels below this (colourless) ...
    smear_vs_lip: float = -11.5   # ... median a* of the grey pixels minus the lips' a* at most this (greener) ...
    smear_teeth_max: float = 0.05  # ... and almost no clearly bright (teeth_rel) pixels
    close_gaps: int = 1           # fill flag gaps up to this many frames
    dilate: int = 1               # extend flagged runs by this many frames while the mouth is open
    dilate_open: float = 0.03     # "still open" for dilation
    # source choice
    donor_open: float = 0.10      # a raw frame can be used if openness >= this ...
    same_grey: float = 0.20       # ... same index: at least this fraction of its interior is lit (grey_rel) ...
    donor_grey: float = 0.45      # ... borrowed by another run: clearly visible teeth (this lit fraction) ...
    donor_void_max: float = 0.70  # ... and it is not itself mostly near-black
    donor_balance: float = 0.05   # borrowed donor: lit area centred within this fraction of the mouth width
    donor_max_dist: int = 0       # 0 = any distance
    # warp / composite
    warp: str = "tps"             # tps | affine
    tps_reg: float = 1e-3
    src_shrink: float = 0.88      # sample the donor from inside its own inner ring (keeps donor lips out)
    feather: float = 0.22         # inward feather, fraction of the inner-ring height (min feather_min_px)
    feather_min_px: float = 1.5
    mask_erode: float = 1.0       # px: the mask starts this far inside the synced frame's own inner-lip outline
    strength: float = 1.0         # max opacity of the pasted interior
    temporal_sigma: float = 0.8   # Gaussian sigma (frames) for the strength curve
    lm_sigma: float = 0.7         # landmark smoothing sigma (frames), synced and raw
    colour: str = "lab"           # lab | none
    colour_gain_clip: tuple = (0.8, 1.25)
    interior_gain: float = 1.0    # optional extra luma gain of the pasted interior (< 1 darkens)
    anime_policy: str = "skip"    # skip | approx
    # lip colour/shape jump fix (ON by default since the reviewer-approved L1c2 validation render;
    # --no-lip-color-fix turns it off): LatentSync sometimes flashes the
    # lips for 1-3 frames
    lip_color_fix: bool = True
    lip_jump: float = 10.0        # a run is a jump if its worst frame is >= this Lab dE from the line between its neighbours
    lip_jump_min: float = 5.0     # ... every frame of the run >= this ...
    lip_ref_agree: float = 6.0    # ... the two neighbours agree within this dE ...
    lip_raw_max: float = 2.0      # ... and the raw take shows no such jump (<= this dE)
    lip_max_len: int = 3
    lip_fix_mode: str = "blend"   # colour: Lab-match the lip body to the neighbours | blend: replace the whole mouth by
                                  # the neighbours (a-1, b+1) warped to their interpolated lip geometry and cross-faded

    def to_dict(self):
        return dataclasses.asdict(self)


# ------------------------------------------------------------------------------------------------ geometry
def lip_rings(pts) -> tuple:
    """(478, 2) MediaPipe points -> (inner (20, 2), outer (20, 2)) float64."""
    p = np.asarray(pts, np.float64)
    return p[INNER], p[OUTER]


def openness(pts) -> float:
    p = np.asarray(pts, np.float64)
    return float(np.linalg.norm(p[UPPER_MID] - p[LOWER_MID]) / (np.linalg.norm(p[CORNER_L] - p[CORNER_R]) or 1.0))


def ring_openness(inner, outer) -> float:
    """Openness from the rings alone (works for the anime approximation too)."""
    inner = np.asarray(inner, np.float64)
    outer = np.asarray(outer, np.float64)
    return float(np.linalg.norm(inner[5] - inner[15]) / (np.linalg.norm(outer[0] - outer[10]) or 1.0))


def anime_rings(lmk106) -> tuple:
    """Approximate rings from the detector's 2d106 mouth points (52-71, interpolated from 4 anime points).
    The inner ring is the outer hull squeezed vertically toward the mouth line: a rough guess, logged as such."""
    m = np.asarray(lmk106, np.float64)[52:72]
    c = m.mean(0)
    ang = np.arctan2(m[:, 1] - c[1], m[:, 0] - c[0])
    outer_pts = m[np.argsort(ang)]
    t = np.linspace(np.pi, -np.pi, 20, endpoint=False)  # start at image-left, go over the top
    w = np.ptp(outer_pts[:, 0]) / 2 or 1.0
    h = np.ptp(outer_pts[:, 1]) / 2 or 1.0
    outer = np.stack([c[0] + w * np.cos(t), c[1] - h * np.sin(t)], 1)
    inner = np.stack([c[0] + 0.8 * w * np.cos(t), c[1] - 0.35 * h * np.sin(t)], 1)
    return inner, outer


def poly_area(poly) -> float:
    p = np.asarray(poly, np.float64)
    x, y = p[:, 0], p[:, 1]
    return float(0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def fill_mask(shape, poly, value=1.0) -> np.ndarray:
    import cv2

    m = np.zeros(shape[:2], np.float32)
    cv2.fillPoly(m, [np.round(np.asarray(poly) * 8).astype(np.int32)], value, lineType=cv2.LINE_8, shift=3)
    return m


def inner_mask(shape, inner, feather_px: float, erode_px: float = 0.0) -> np.ndarray:
    """Float32 alpha in [0, 1]: 0 on, outside and within ``erode_px`` of the inner-lip outline, rising inward over
    ``feather_px``. Built from the distance to the outline, so it can never reach the lips."""
    import cv2

    hard = fill_mask(shape, inner) > 0.5
    if not hard.any():
        return np.zeros(shape[:2], np.float32)
    ys, xs = np.nonzero(hard)
    y1, y2, x1, x2 = max(0, ys.min() - 2), min(shape[0], ys.max() + 3), max(0, xs.min() - 2), min(shape[1], xs.max() + 3)
    sub = hard[y1:y2, x1:x2].astype(np.uint8)
    d = cv2.distanceTransform(sub, cv2.DIST_L2, 5)
    a = np.clip((d - 0.5 - max(0.0, float(erode_px))) / max(float(feather_px), 1e-3), 0, 1).astype(np.float32)
    a[sub == 0] = 0
    out = np.zeros(shape[:2], np.float32)
    out[y1:y2, x1:x2] = a
    return out


def shrink(poly, k: float):
    p = np.asarray(poly, np.float64)
    c = p.mean(0)
    return c + k * (p - c)


# ------------------------------------------------------------------------------------------------ warps
def _tps_kernel(r2):
    with np.errstate(divide="ignore", invalid="ignore"):
        k = r2 * np.log(r2)
    return np.nan_to_num(k)


def tps_fit(ctrl, vals, reg: float = 1e-3):
    """Thin-plate spline f with f(ctrl) ~= vals (both (N, 2)). Returns a callable mapping (M, 2) -> (M, 2)."""
    c = np.asarray(ctrl, np.float64)
    v = np.asarray(vals, np.float64)
    mu, s = c.mean(0), (c.std() or 1.0)
    cn = (c - mu) / s
    n = len(cn)
    K = _tps_kernel(((cn[:, None] - cn[None]) ** 2).sum(-1)) + reg * np.eye(n)
    P = np.hstack([np.ones((n, 1)), cn])
    A = np.zeros((n + 3, n + 3))
    A[:n, :n], A[:n, n:], A[n:, :n] = K, P, P.T
    b = np.zeros((n + 3, 2))
    b[:n] = v
    sol = np.linalg.lstsq(A, b, rcond=None)[0]
    w, a = sol[:n], sol[n:]

    def f(x):
        xn = (np.asarray(x, np.float64) - mu) / s
        U = _tps_kernel(((xn[:, None] - cn[None]) ** 2).sum(-1))
        return U @ w + np.hstack([np.ones((len(xn), 1)), xn]) @ a
    return f


def affine_fit(ctrl, vals):
    c = np.asarray(ctrl, np.float64)
    v = np.asarray(vals, np.float64)
    X = np.hstack([c, np.ones((len(c), 1))])
    M = np.linalg.lstsq(X, v, rcond=None)[0]
    return lambda x: np.hstack([np.asarray(x, np.float64), np.ones((len(x), 1))]) @ M


def warp_patch(src_rgb, src_inner, src_outer, dst_inner, dst_outer, box, cfg: Config) -> np.ndarray:
    """Backward-warp the donor so its (shrunk) inner ring lands on the destination inner ring.
    Returns the patch for ``box`` = (x1, y1, x2, y2) in destination coordinates."""
    import cv2

    s_in = shrink(src_inner, cfg.src_shrink)
    d_in = np.asarray(dst_inner, np.float64)
    dst = np.vstack([d_in, dst_outer, d_in.mean(0, keepdims=True)])
    src = np.vstack([s_in, src_outer, np.asarray(s_in).mean(0, keepdims=True)])
    f = affine_fit(dst, src) if cfg.warp == "affine" else tps_fit(dst, src, cfg.tps_reg)
    x1, y1, x2, y2 = box
    gx, gy = np.meshgrid(np.arange(x1, x2, dtype=np.float64), np.arange(y1, y2, dtype=np.float64))
    m = f(np.stack([gx.ravel(), gy.ravel()], 1))
    mx = m[:, 0].reshape(gx.shape).astype(np.float32)
    my = m[:, 1].reshape(gx.shape).astype(np.float32)
    return cv2.remap(src_rgb, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


# ------------------------------------------------------------------------------------------------ measures
def skin_luma(gray, pts_or_chin, mouth_w: float) -> float:
    """Median luma of a small chin patch (between lower lip 17 and chin 152)."""
    c = np.asarray(pts_or_chin, np.float64)
    r = int(max(2, 0.12 * mouth_w))
    y, x = int(round(c[1])), int(round(c[0]))
    patch = gray[max(0, y - r):y + r, max(0, x - r):x + r]
    return float(np.median(patch)) if patch.size else 128.0


def interior_stats(rgb, inner, skin: float, cfg: Config, outer=None) -> dict:
    """Pixel statistics inside the inner ring (luma relative to the chin skin; colour of the grey pixels in Lab,
    compared with the lips when ``outer`` is given)."""
    import cv2

    m = fill_mask(rgb.shape, inner) > 0.5
    n = int(m.sum())
    out = {"area_px": n}
    if n < 4:
        return out
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32) / max(skin, 1.0)
    g = gray[m]
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    grey = m & (gray >= cfg.grey_rel)
    w = float(np.linalg.norm(np.asarray(outer)[0] - np.asarray(outer)[10])) if outer is not None else float(np.ptp(np.asarray(inner)[:, 0]))
    out.update(dark_frac=float((g < cfg.dark_rel).mean()), bright_frac=float((g > cfg.bright_rel).mean()),
               teeth_frac=float((g > cfg.teeth_rel).mean()), grey_frac=float(grey.sum() / n),
               grey_area_w2=float(grey.sum() / max(w, 1.0) ** 2),
               med=float(np.median(g)), p90=float(np.percentile(g, 90)), std=float(g.std()))
    if grey.sum() >= 5:
        ys, xs = np.nonzero(grey)
        iw = float(np.ptp(np.asarray(inner)[:, 0])) or 1.0
        out["grey_cx"] = float((xs.mean() - np.asarray(inner)[:, 0].mean()) / iw)  # lit-area balance, -0.5..0.5
        a, b = lab[..., 1][grey], lab[..., 2][grey]
        out["grey_chroma"] = float(np.median(np.hypot(a - 128, b - 128)))
        if outer is not None:
            lips = ring_region(rgb.shape, inner, outer, grow=0.0)
            if lips.any():
                out["grey_a_vs_lip"] = float(np.median(a) - np.median(lab[..., 1][lips]))
    return out


def classify(st: dict, op: float, cfg: Config) -> tuple:
    """(label, reason). Labels: noface, closed, void, smear, ok."""
    if st is None:
        return "noface", "no lips"
    if op < cfg.open_thr or st.get("area_px", 0) < cfg.min_area_px or "med" not in st:
        return "closed", f"open {op:.3f} < {cfg.open_thr} or area {st.get('area_px', 0)} < {cfg.min_area_px}"
    desc = f"dark {st['dark_frac']:.2f} lit {st['bright_frac']:.3f} med {st['med']:.2f}"
    if st["dark_frac"] >= cfg.void_frac and st["bright_frac"] < cfg.void_teeth_max:
        return "void", desc
    ch, av = st.get("grey_chroma"), st.get("grey_a_vs_lip")
    if (ch is not None and st["grey_area_w2"] >= cfg.smear_area and ch < cfg.smear_chroma
            and (av is None or av <= cfg.smear_vs_lip) and st["teeth_frac"] < cfg.smear_teeth_max):
        return "smear", f"grey band area {st['grey_area_w2']:.3f} w^2 chroma {ch:.1f} a-lip {av if av is None else round(av, 1)}"
    return "ok", desc


def is_donor(st: dict, op: float, cfg: Config, borrow: bool = False) -> bool:
    """Raw frame usable as an interior source: open, lit interior, not a void. ``borrow`` (for another run's frames)
    also needs clearly visible teeth (``donor_grey``) spread across the mouth (``donor_balance``)."""
    ok = bool(st is not None and "med" in st and op >= cfg.donor_open and st.get("area_px", 0) >= cfg.min_area_px
              and st["grey_frac"] >= (cfg.donor_grey if borrow else cfg.same_grey) and st["dark_frac"] <= cfg.donor_void_max)
    if ok and borrow:
        ok = abs(st.get("grey_cx", 1.0)) <= cfg.donor_balance
    return ok


# ------------------------------------------------------------------------------------------------ temporal
def runs(flags) -> list:
    """[(start, end_inclusive)] of True runs."""
    out, s = [], None
    for i, f in enumerate(list(flags) + [False]):
        if f and s is None:
            s = i
        elif not f and s is not None:
            out.append((s, i - 1))
            s = None
    return out


def expand_flags(det, opens, cfg: Config) -> np.ndarray:
    """Detected flags -> frames to fix: close short gaps, then dilate while the mouth is still open."""
    f = np.asarray(det, bool).copy()
    n = len(f)
    for a, b in runs(~f):
        if a > 0 and b < n - 1 and (b - a + 1) <= cfg.close_gaps:
            f[a:b + 1] = True
    g = f.copy()
    op = np.nan_to_num(np.asarray(opens, np.float64), nan=0.0)
    for a, b in runs(f):
        for k in range(1, cfg.dilate + 1):
            for j in (a - k, b + k):
                if 0 <= j < n and op[j] >= cfg.dilate_open:
                    g[j] = True
    return g


def strength_curve(fix, cfg: Config) -> np.ndarray:
    """Per-frame opacity: 1 on fixed frames, smoothed over time (never above 1, never on frames far away).
    Frames inside a fixed run keep full strength; the Gaussian only softens the run edges outward."""
    f = np.asarray(fix, np.float64)
    if cfg.temporal_sigma <= 0 or not f.any():
        return f * cfg.strength
    r = max(1, int(round(3 * cfg.temporal_sigma)))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / cfg.temporal_sigma) ** 2)
    k /= k.max()
    s = np.zeros_like(f)
    for i in np.nonzero(f)[0]:
        lo, hi = max(0, i - r), min(len(f), i + r + 1)
        s[lo:hi] = np.maximum(s[lo:hi], k[lo - i + r:hi - i + r])
    s[s < 0.1] = 0  # no faint tails: a fade frame is either a real crossfade step or untouched
    return np.clip(s, 0, 1) * cfg.strength


def choose_sources(fix, raw_same, raw_donor, cfg: Config) -> tuple:
    """Per frame to fix: the raw index to borrow the interior from, and why.

    * If any raw frame of the run is open with a lit interior (``raw_same``), the run follows the raw take: those
      frames use the same index (frames are aligned 1:1), and the run's other frames hold the nearest such frame
      of the run (ties to the later one).
    * Otherwise the whole run borrows ONE donor: the raw frame with clearly visible teeth (``raw_donor``) nearest
      the run's middle (ties to the later one), so the texture never switches mid-run."""
    n = len(fix)
    src = [None] * n
    why = [None] * n
    donors = np.nonzero(np.asarray(raw_donor, bool))[0]
    for a, b in runs(fix):
        same = [i for i in range(a, b + 1) if raw_same[i]]
        if same:
            for i in range(a, b + 1):
                if raw_same[i]:
                    src[i], why[i] = i, "same_index"
                else:
                    j = min(same, key=lambda k: (abs(k - i), -k))
                    src[i], why[i] = j, f"hold_f{j}"
            continue
        if not len(donors):
            for i in range(a, b + 1):
                why[i] = "no_donor"
            continue
        mid = (a + b) / 2
        j = int(donors[np.lexsort((-donors, np.abs(donors - mid)))[0]])
        dist = 0 if a <= j <= b else int(min(abs(j - a), abs(j - b)))
        if cfg.donor_max_dist and dist > cfg.donor_max_dist:
            for i in range(a, b + 1):
                why[i] = f"donor_too_far(f{j})"
            continue
        for i in range(a, b + 1):
            src[i], why[i] = j, f"donor_f{j}"
    return src, why


# ------------------------------------------------------------------------------------------------ colour
def ring_region(shape, inner, outer, grow: float = 0.25) -> np.ndarray:
    """Lips + perioral skin (outer ring grown by ``grow`` mouth widths) minus the mouth opening."""
    import cv2

    w = float(np.ptp(np.asarray(outer)[:, 0])) or 1.0
    m = fill_mask(shape, outer)
    g = max(1, int(round(grow * w)))
    m = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * g + 1, 2 * g + 1)))
    m[fill_mask(shape, inner) > 0.5] = 0
    return m > 0.5


def lab_stats(rgb, mask):
    import cv2

    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)[mask]
    return lab.mean(0), lab.std(0) + 1e-3


def colour_transfer(patch, src_stats, dst_stats, clip=(0.8, 1.25), gain: float = 1.0):
    import cv2

    (ms, ss), (md, sd) = src_stats, dst_stats
    k = np.clip(sd / ss, clip[0], clip[1])
    lab = cv2.cvtColor(patch, cv2.COLOR_RGB2LAB).astype(np.float32)
    lab = (lab - ms) * k + md
    lab[..., 0] *= gain
    return cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB)


# ------------------------------------------------------------------------------------------------ core
def analyse(frames, lms, cfg: Config) -> list:
    """Per-frame measures. ``lms``: list of dicts {inner, outer, chin, source} or None."""
    import cv2

    out = []
    for fr, lm in zip(frames, lms):
        if lm is None:
            out.append({"lips": False})
            continue
        inner, outer = np.asarray(lm["inner"]), np.asarray(lm["outer"])
        w = float(np.linalg.norm(outer[0] - outer[10])) or 1.0
        gray = cv2.cvtColor(fr, cv2.COLOR_RGB2GRAY)
        skin = skin_luma(gray, lm["chin"], w)
        st = interior_stats(fr, inner, skin, cfg, outer)
        op = ring_openness(inner, outer)
        out.append({"lips": True, "source": lm.get("source"), "open": op, "skin": skin, "mouth_w": w,
                    "inner_area": poly_area(inner), **st})
    return out


def frame_decisions(meas, cfg: Config):
    labels, reasons = [], []
    for m in meas:
        if not m.get("lips"):
            labels.append("noface"); reasons.append("no lips")
            continue
        if m.get("source") in ("anime", "anime_override") and cfg.anime_policy == "skip":
            labels.append("anime_fallback"); reasons.append("anime landmarks have no inner-lip ring (skipped)")
            continue
        lab, why = classify(m, m["open"], cfg)
        labels.append(lab); reasons.append(why)
    return labels, reasons


def process(syn_frames, raw_frames, syn_lms, raw_lms, cfg: Config | None = None, force=None):
    """Run the pass on in-memory RGB uint8 frames. Returns (out_frames, log dict).
    ``force``: optional iterable of frame indices to treat as flagged in addition to the detector."""
    cfg = cfg or Config()
    n = len(syn_frames)
    if len(raw_frames) != n or len(syn_lms) != n or len(raw_lms) != n:
        raise ConformError(f"frame count mismatch: synced {n}, raw {len(raw_frames)}, "
                           f"lms {len(syn_lms)}/{len(raw_lms)}")
    sm = analyse(syn_frames, syn_lms, cfg)
    rm = analyse(raw_frames, raw_lms, cfg)
    labels, reasons = frame_decisions(sm, cfg)
    det = np.array([l in ("void", "smear") for l in labels])
    if force:
        for i in force:
            if 0 <= i < n and labels[i] not in ("noface", "anime_fallback"):
                det[i] = True
    opens = [m.get("open", np.nan) for m in sm]
    fix = expand_flags(det, opens, cfg)
    skipped = {}
    for i in range(n):  # never fix a frame without usable lips, nor a (nearly) closed one, even via gap/dilate/force
        if labels[i] in ("noface", "anime_fallback") or sm[i].get("area_px", 0) < 4:
            fix[i] = False
        elif fix[i] and (sm[i].get("open", 0.0) < cfg.open_thr or sm[i].get("area_px", 0) < cfg.min_area_px):
            fix[i] = False
            skipped[i] = f"opening {sm[i].get('open', 0.0):.3f} < open_thr {cfg.open_thr}"
    raw_ok = [bool(rm[i].get("lips") and is_donor(rm[i], rm[i].get("open", 0), cfg)) for i in range(n)]
    raw_donor = [bool(rm[i].get("lips") and is_donor(rm[i], rm[i].get("open", 0), cfg, borrow=True)) for i in range(n)]
    src, why = choose_sources(fix, raw_ok, raw_donor, cfg)
    s = strength_curve(fix, cfg)
    out = [f.copy() for f in syn_frames]
    # per-run colour transfer (median of per-frame stats; stable within a run)
    col = {}
    for a, b in runs(fix):
        ss, ds = [], []
        for i in range(a, b + 1):
            if src[i] is None:
                continue
            j = src[i]
            rmask = ring_region(raw_frames[j].shape, raw_lms[j]["inner"], raw_lms[j]["outer"])
            dmask = ring_region(syn_frames[i].shape, syn_lms[i]["inner"], syn_lms[i]["outer"])
            ss.append(lab_stats(raw_frames[j], rmask)); ds.append(lab_stats(syn_frames[i], dmask))
        if ss:
            col[(a, b)] = ((np.median([x[0] for x in ss], 0), np.median([x[1] for x in ss], 0)),
                           (np.median([x[0] for x in ds], 0), np.median([x[1] for x in ds], 0)))
    run_of = {}
    for a, b in runs(fix):
        for i in range(a, b + 1):
            run_of[i] = (a, b)
    applied = np.zeros(n, bool)
    for i in range(n):
        if s[i] <= 0 or not sm[i].get("lips") or labels[i] in ("noface", "anime_fallback"):
            continue
        if fix[i]:
            j, key = src[i], run_of[i]
        else:  # fade frame next to a run: borrow the nearest fixed frame's source (never a closed raw mouth)
            if not run_of or labels[i] == "closed" or sm[i].get("open", 0.0) < cfg.open_thr:
                continue
            near = min(run_of, key=lambda k: (abs(k - i), k))
            j, key = src[near], run_of[near]
        if j is None:
            continue
        inner, outer = np.asarray(syn_lms[i]["inner"]), np.asarray(syn_lms[i]["outer"])
        h_in = float(np.ptp(inner[:, 1]))
        alpha = inner_mask(syn_frames[i].shape, inner, max(cfg.feather_min_px, cfg.feather * h_in), cfg.mask_erode) * float(s[i])
        if not alpha.any():
            continue
        ys, xs = np.nonzero(alpha)
        box = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
        patch = warp_patch(raw_frames[j], raw_lms[j]["inner"], raw_lms[j]["outer"], inner, outer, box, cfg)
        if cfg.colour == "lab" and key in col:
            patch = colour_transfer(patch, col[key][0], col[key][1], cfg.colour_gain_clip, cfg.interior_gain)
        x1, y1, x2, y2 = box
        a = alpha[y1:y2, x1:x2, None]
        roi = out[i][y1:y2, x1:x2].astype(np.float32)
        out[i][y1:y2, x1:x2] = np.clip(roi * (1 - a) + patch.astype(np.float32) * a + 0.5, 0, 255).astype(np.uint8)
        applied[i] = True
        if not fix[i]:
            src[i], why[i] = j, f"fade ({why[near]})"
    after = analyse(out, syn_lms, cfg)
    frames_log = []
    for i in range(n):
        frames_log.append({
            "i": i, "t": None, "label": labels[i], "reason": reasons[i], "detected": bool(det[i]),
            "fixed": bool(fix[i]), "applied": bool(applied[i]), "strength": round(float(s[i]), 3),
            "source": src[i] if applied[i] else None, "source_why": why[i] if applied[i] else None,
            "synced": _r(sm[i]), "raw": _r(rm[i]), "after": _r(after[i]), "raw_same_index_ok": raw_ok[i],
            "raw_donor_ok": raw_donor[i],
            "skipped": skipped.get(i)})
    log = {"config": cfg.to_dict(), "frames": n, "detected": [int(i) for i in np.nonzero(det)[0]],
           "fixed": [int(i) for i in np.nonzero(fix)[0]], "applied": [int(i) for i in np.nonzero(applied)[0]],
           "runs": [{"start": a, "end": b, "source": src[a], "why": why[a]} for a, b in runs(fix)],
           "skipped_below_open": sorted(skipped),
           "per_frame": frames_log}
    return out, log


def _r(d):
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in d.items()}


# ------------------------------------------------------------------------------------------------ lip colour jumps
def lip_region(shape, inner, outer, erode_px: int = 1) -> np.ndarray:
    """Lip body: outer ring minus the mouth opening, eroded to drop the rims."""
    import cv2

    m = ring_region(shape, inner, outer, grow=0.0).astype(np.uint8)
    if erode_px > 0:
        m = cv2.erode(m, np.ones((2 * erode_px + 1, 2 * erode_px + 1), np.uint8))
    return m > 0


def lip_colour(frame, lm) -> np.ndarray:
    """Median Lab of the lit lip body (top 60 % by L, so the seam / opening does not count)."""
    import cv2

    m = lip_region(frame.shape, lm["inner"], lm["outer"])
    if m.sum() < 10:
        return np.full(3, np.nan, np.float32)
    px = cv2.cvtColor(frame, cv2.COLOR_RGB2LAB).astype(np.float32)[m]
    px = px[px[:, 0] >= np.percentile(px[:, 0], 40)]
    return np.median(px, 0)


def detect_lip_jumps(syn_col, raw_col, cfg: Config) -> list:
    """Runs (a, b) of 1..lip_max_len frames whose lip colour leaves the line between the two neighbours
    (a-1, b+1) by >= lip_jump dE (every frame >= lip_jump_min) while the neighbours agree and the raw take stays put.
    Overlaps keep the run with the largest jump. Returns [{start, end, dev, ref_agree, raw_dev}]."""
    x, y = np.asarray(syn_col, np.float64), np.asarray(raw_col, np.float64)
    n = len(x)
    cands = []
    for L in range(1, cfg.lip_max_len + 1):
        for a in range(1, n - L):
            c = a + L
            if np.isnan(x[[a - 1, c]]).any():
                continue
            line = lambda z, i: (z[a - 1] * (c - i) + z[c] * (i - a + 1)) / (L + 1)
            dev = [float(np.linalg.norm(x[i] - line(x, i))) for i in range(a, c)]
            agree = float(np.linalg.norm(x[a - 1] - x[c]))
            rdev = max(float(np.linalg.norm(y[i] - line(y, i))) for i in range(a, c)) if not np.isnan(y[[a - 1, c]]).any() else 0.0
            if (np.nanmax(dev) >= cfg.lip_jump and np.nanmin(dev) >= cfg.lip_jump_min and agree <= cfg.lip_ref_agree
                    and rdev <= cfg.lip_raw_max):
                cands.append({"start": a, "end": c - 1, "dev": [round(d, 2) for d in dev], "ref_agree": round(agree, 2),
                              "raw_dev": round(rdev, 2), "score": float(np.nanmax(dev))})
    out, used = [], set()
    for c in sorted(cands, key=lambda c: (-c["score"], c["start"])):
        span = set(range(c["start"] - 1, c["end"] + 2))
        if span & used:
            continue
        used |= set(range(c["start"], c["end"] + 1))
        out.append(c)
    return sorted(out, key=lambda c: c["start"])


def _lip_mask(shape, outers, w):
    import cv2

    m = np.zeros(shape[:2], np.float32)
    for o in outers:
        m = np.maximum(m, fill_mask(shape, o))
    g = max(1, int(round(0.06 * w)))
    m = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * g + 1, 2 * g + 1)))
    return cv2.GaussianBlur(m, (0, 0), max(1.0, 0.04 * w))[..., None]


def lip_blend_fix(frames, lms, jumps, cfg: Config):
    """Replace the mouth on each jump frame by the two neighbours (a-1, b+1), each TPS-warped onto the linearly
    interpolated lip rings and cross-faded by time, inside a feathered mask covering both the frame's own lips and
    the interpolated lips. Returns (frames, per-frame log)."""
    out, log = list(frames), []
    for j in jumps:
        a, b = j["start"], j["end"]
        p, q = a - 1, b + 1
        rp = np.vstack([lms[p]["inner"], lms[p]["outer"]]).astype(np.float64)
        rq = np.vstack([lms[q]["inner"], lms[q]["outer"]]).astype(np.float64)
        for i in range(a, b + 1):
            t = (i - p) / (q - p)
            dst = (1 - t) * rp + t * rq
            ni = len(lms[p]["inner"])
            w = float(np.ptp(dst[ni:, 0])) or 1.0
            m = _lip_mask(frames[i].shape, [lms[i]["outer"], dst[ni:]], w)
            ys, xs = np.nonzero(m[..., 0] > 1e-3)
            box = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
            x1, y1, x2, y2 = box
            acc = np.zeros((y2 - y1, x2 - x1, 3), np.float32)
            for k, wk in ((p, 1 - t), (q, t)):
                src = np.vstack([lms[k]["inner"], lms[k]["outer"]]).astype(np.float64)
                f = tps_fit(dst, src, cfg.tps_reg)
                gx, gy = np.meshgrid(np.arange(x1, x2, dtype=np.float64), np.arange(y1, y2, dtype=np.float64))
                mm = f(np.stack([gx.ravel(), gy.ravel()], 1))
                import cv2
                acc += wk * cv2.remap(frames[k], mm[:, 0].reshape(gx.shape).astype(np.float32),
                                      mm[:, 1].reshape(gx.shape).astype(np.float32), cv2.INTER_LINEAR,
                                      borderMode=cv2.BORDER_REFLECT).astype(np.float32)
            a_ = m[y1:y2, x1:x2]
            roi = frames[i][y1:y2, x1:x2].astype(np.float32)
            out[i] = frames[i].copy()
            out[i][y1:y2, x1:x2] = np.clip(roi * (1 - a_) + acc * a_ + 0.5, 0, 255).astype(np.uint8)
            log.append({"i": i, "refs": [p, q], "mode": "blend", "t": round(t, 3),
                        "before": [round(float(v), 1) for v in lip_colour(frames[i], lms[i])],
                        "after": [round(float(v), 1) for v in lip_colour(out[i], {"inner": dst[:ni], "outer": dst[ni:]})]})
    return out, log


def lip_colour_fix(frames, lms, jumps, cfg: Config):
    """Fix lip flash runs. ``cfg.lip_fix_mode`` "blend" -> :func:`lip_blend_fix`; "colour" -> Lab mean/std transfer
    of the lip body on each jump frame toward the linear interpolation of the neighbours' lip stats (a-1, b+1),
    inside a softly feathered outer-lip mask. Returns (frames, per-frame log)."""
    import cv2

    if cfg.lip_fix_mode == "blend":
        return lip_blend_fix(frames, lms, jumps, cfg)

    out = list(frames)
    log = []

    def stats(i):
        m = lip_region(frames[i].shape, lms[i]["inner"], lms[i]["outer"])
        lab = cv2.cvtColor(frames[i], cv2.COLOR_RGB2LAB).astype(np.float32)[m]
        return lab.mean(0), lab.std(0) + 1e-3
    for j in jumps:
        a, b = j["start"], j["end"]
        p, q = a - 1, b + 1
        (mp_, sp), (mq, sq) = stats(p), stats(q)
        for i in range(a, b + 1):
            t = (i - p) / (q - p)
            mt, st = (1 - t) * mp_ + t * mq, (1 - t) * sp + t * sq
            ms, ss = stats(i)
            k = np.clip(st / ss, 0.6, 1.6)
            lab = cv2.cvtColor(frames[i], cv2.COLOR_RGB2LAB).astype(np.float32)
            new = cv2.cvtColor(np.clip((lab - ms) * k + mt, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB).astype(np.float32)
            w = float(np.ptp(np.asarray(lms[i]["outer"])[:, 0])) or 1.0
            m = fill_mask(frames[i].shape, lms[i]["outer"])
            g = max(1, int(round(0.04 * w)))
            m = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * g + 1, 2 * g + 1)))
            m = cv2.GaussianBlur(m, (0, 0), max(1.0, 0.03 * w))[..., None]
            out[i] = np.clip(frames[i].astype(np.float32) * (1 - m) + new * m + 0.5, 0, 255).astype(np.uint8)
            log.append({"i": i, "refs": [p, q], "mode": "colour", "before": [round(float(v), 1) for v in lip_colour(frames[i], lms[i])],
                        "after": [round(float(v), 1) for v in lip_colour(out[i], lms[i])],
                        "target": [round(float(v), 1) for v in ((1 - t) * lip_colour(frames[p], lms[p]) + t * lip_colour(frames[q], lms[q]))]})
    return out, log


# ------------------------------------------------------------------------------------------------ landmarks
def _load_detector_module():
    spec = importlib.util.spec_from_file_location("ls_face_detector_for_inner_mouth", HERE / "ls_face_detector.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_ANIME_CACHE: dict = {}


def _create_anime_detector():
    """The optional anime landmark model (hysts anime-face-detector, CPU), or None when it is not installed or its
    pinned local weights are missing / do not match. Created once per process (the synced and raw trackers share it)."""
    if "m" not in _ANIME_CACHE:
        try:  # pinned local weights only, sha256-checked, never downloaded (ls_face_detector.create_anime_detector)
            _ANIME_CACHE["m"] = _load_detector_module().create_anime_detector("cpu")
        except Exception:
            _ANIME_CACHE["m"] = None
    return _ANIME_CACHE["m"]


def resolve_task(task_path=None, fdm=None):
    """MediaPipe task path: explicit, env, detector default, then ./models/(mediapipe/)face_landmarker.task.
    Returns None (let the detector raise its own clear error) when nothing exists."""
    if task_path:
        return str(task_path)
    if os.environ.get("OPENSOUL_MP_FACE_TASK"):
        return os.environ["OPENSOUL_MP_FACE_TASK"]
    cands = []
    if fdm is not None and getattr(fdm, "DEFAULT_TASK", None):
        cands.append(Path(fdm.DEFAULT_TASK))
    cands += [Path.cwd() / "models" / "face_landmarker.task", Path.cwd() / "models" / "mediapipe" / "face_landmarker.task"]
    for c in cands:
        if c.is_file():
            return str(c)
    return None


class LipTracker:
    """Lip rings per frame through OpenSoul's detector (same face choice, tracking, crop retry).
    The detector's own answer is 2d106 (outer mouth only), so the 478 MediaPipe points it looked at are kept
    and the tracked face's points are matched back to its extent.

    style "auto" (default): MediaPipe only, and the anime model is created lazily the first time MediaPipe (incl.
    its crop retry) finds no face on a frame; it is then consulted only for frames MediaPipe misses. "real": never.
    "anime": the detector's own anime-first mode (model loaded up front)."""

    anime_factory = staticmethod(_create_anime_detector)

    def __init__(self, task_path=None, style=None, face_box=None, anime=None):
        self.fdm = _load_detector_module()
        self.style = (style or os.environ.get("OPENSOUL_LS_FACE_STYLE", "auto")).strip().lower()
        self.lazy_anime = self.style == "auto" and anime is not False and os.environ.get("OPENSOUL_LS_ANIME", "1") != "0"
        self.fd = self.fdm.FaceDetector("cpu", task_path=resolve_task(task_path, self.fdm), style=self.style,
                                        face_box=face_box, anime=False if self.style == "auto" else anime)
        self.anime_state = "not_needed" if self.lazy_anime else ("off" if self.style != "anime" else
                                                                  ("loaded" if self.fd._anime is not None else "unavailable"))
        self.anime_frames = 0
        self._anime_model = None
        if self.lazy_anime:
            orig_detect = self.fd.detect

            def detect(frame):
                r = orig_detect(frame)
                if r[0] is not None or self.anime_state == "unavailable":
                    return r
                if self._anime_model is None:
                    self._anime_model = self.anime_factory()
                    self.anime_state = "loaded" if self._anime_model is not None else "unavailable"
                    if self._anime_model is None:
                        return r
                self.anime_frames += 1
                self.fd._anime = self._anime_model
                try:
                    return orig_detect(frame)
                finally:
                    self.fd._anime = None
            self.fd.detect = detect
        self._seen = []
        orig = self.fd._mp_points

        def spy(rgb, off=(0, 0)):
            r = orig(rgb, off)
            self._seen.extend(r)
            return r
        self.fd._mp_points = spy

    def report(self) -> dict:
        return dict(self.fd.report(), anime_model=self.anime_state, anime_retry_frames=self.anime_frames)

    def track(self, frames, sigma: float = 0.7) -> list:
        out = []
        for fr in frames:
            self._seen = []
            box, lmk = self.fd._detect_one(fr)
            src = self.fd.last_source
            if lmk is None or src in ("miss",):
                out.append(None)
                continue
            if src in ("mediapipe", "mediapipe_crop", "hold") and self._seen:
                ext = self.fd._last_ext
                pts = max(self._seen, key=lambda p: self.fdm._iou(self.fdm._ext(p), ext))
                if self.fdm._iou(self.fdm._ext(pts), ext) > 0.5:
                    inner, outer = lip_rings(pts)
                    out.append({"pts": pts, "inner": inner, "outer": outer, "chin": (pts[CHIN[0]] + pts[CHIN[1]]) / 2,
                                "source": src})
                    continue
            if src == "hold" and out and out[-1] is not None:
                out.append(dict(out[-1], source="hold"))
                continue
            inner, outer = anime_rings(lmk)
            chin = np.asarray(lmk, np.float64)[[0, 16]].mean(0) if src.startswith("anime") else outer.mean(0)
            out.append({"inner": inner, "outer": outer, "chin": chin, "source": src})
        return smooth_rings(out, sigma, self.fdm.smooth_landmarks)


def smooth_rings(lms: list, sigma: float, smoother=None) -> list:
    """Temporal smoothing of inner+outer+chin (Gaussian, per run; the detector's smooth_landmarks splits runs at
    face jumps)."""
    if sigma <= 0:
        return lms
    if smoother is None:
        smoother = _load_detector_module().smooth_landmarks
    stacks = [None if l is None else np.vstack([l["inner"], l["outer"], np.asarray(l["chin"])[None]]) for l in lms]
    sm = smoother(stacks, sigma)
    out = []
    for l, s in zip(lms, sm):
        if l is None:
            out.append(None)
            continue
        out.append(dict(l, inner=s[:20], outer=s[20:40], chin=s[40]))
    return out


# ------------------------------------------------------------------------------------------------ video io
def ffprobe(path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "stream=index,codec_type,codec_name,r_frame_rate,avg_frame_rate,nb_frames,sample_rate,duration,width,height",
                        "-of", "json", str(path)], capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def _fps(s) -> float:
    a, b = s.split("/")
    return float(a) / float(b) if float(b) else 0.0


def video_info(path) -> dict:
    p = ffprobe(path)
    v = [s for s in p["streams"] if s["codec_type"] == "video"][0]
    a = [s for s in p["streams"] if s["codec_type"] == "audio"]
    return {"fps": _fps(v["r_frame_rate"]), "avg_fps": _fps(v["avg_frame_rate"]), "w": int(v["width"]),
            "h": int(v["height"]), "nb_frames": int(v.get("nb_frames", 0) or 0), "audio": a[0] if a else None}


def read_frames(path) -> list:
    info = video_info(path)
    w, h = info["w"], info["h"]
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0", "-vsync", "passthrough",
                        "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True)
    buf = np.frombuffer(r.stdout, np.uint8)
    if buf.size % (w * h * 3):
        raise ConformError(f"{path}: decoded byte count is not a whole number of frames")
    return [f.copy() for f in buf.reshape(-1, h, w, 3)]


def read_yuv(path) -> list:
    """Decoded yuv420p planes [(Y, U, V)] exactly as stored (no RGB round trip)."""
    info = video_info(path)
    w, h = info["w"], info["h"]
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0", "-vsync", "passthrough",
                        "-f", "rawvideo", "-pix_fmt", "yuv420p", "-"], capture_output=True, check=True)
    fs = w * h * 3 // 2
    buf = np.frombuffer(r.stdout, np.uint8)
    if buf.size % fs:
        raise ConformError(f"{path}: decoded yuv byte count is not a whole number of frames")
    out = []
    for k in range(buf.size // fs):
        f = buf[k * fs:(k + 1) * fs]
        out.append((f[:w * h].reshape(h, w).copy(), f[w * h:w * h * 5 // 4].reshape(h // 2, w // 2).copy(),
                    f[w * h * 5 // 4:].reshape(h // 2, w // 2).copy()))
    return out


def rgb_to_yuv(rgb) -> np.ndarray:
    """BT.601 limited range (what ffmpeg uses for untagged SD/HD yuv420p <-> rgb24 here), float (H, W, 3)."""
    x = np.asarray(rgb, np.float32) / 255.0
    r, g, b = x[..., 0], x[..., 1], x[..., 2]
    y = 16 + 65.481 * r + 128.553 * g + 24.966 * b
    u = 128 - 37.797 * r - 74.203 * g + 112.0 * b
    v = 128 + 112.0 * r - 93.786 * g - 18.214 * b
    return np.stack([y, u, v], -1)


def apply_delta_yuv(yuv, syn_rgb, out_rgb):
    """Carry the RGB edit (out - syn) into the stored yuv420p planes as a delta, so every pixel the pass did not
    touch keeps its exact decoded value (no RGB round-trip noise on the rest of the frame)."""
    if np.array_equal(syn_rgb, out_rgb):
        return yuv
    Y, U, V = yuv
    d = rgb_to_yuv(out_rgb) - rgb_to_yuv(syn_rgb)
    h, w = Y.shape
    dc = d[:h // 2 * 2, :w // 2 * 2].reshape(h // 2, 2, w // 2, 2, 3).mean((1, 3))
    rnd = lambda p, dd: np.clip(np.round(p.astype(np.float32) + dd), 0, 255).astype(np.uint8)
    return rnd(Y, d[..., 0]), rnd(U, dc[..., 1]), rnd(V, dc[..., 2])


def file_sha256(path) -> str:
    """sha256 hex digest of a file's bytes."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def parent_sidecar(synced) -> dict:
    """The synced take's LatentSync sidecar (``<synced>.lipsync.json``) and its sha256, or nulls without one."""
    p = Path(str(synced) + ".lipsync.json")
    if not p.is_file():
        return {"parent_sidecar": None, "parent_sidecar_sha256": None}
    return {"parent_sidecar": str(p), "parent_sidecar_sha256": file_sha256(p)}


def frame_md5s(frames) -> list:
    return [hashlib.md5(np.ascontiguousarray(f).tobytes()).hexdigest() for f in frames]


def repeated_frames(frames) -> list:
    m = frame_md5s(frames)
    return [i for i in range(1, len(m)) if m[i] == m[i - 1]]


def write_video(frames, fps: int, audio_from, out, crf: int = 12):
    """Encode RGB frames, or (Y, U, V) yuv420p plane tuples (written as is), with the audio stream of
    ``audio_from`` copied unchanged."""
    yuv = isinstance(frames[0], tuple)
    h, w = frames[0][0].shape[:2] if yuv else frames[0].shape[:2]
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.stem + ".tmp" + out.suffix)
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "yuv420p" if yuv else "rgb24",
           "-s", f"{w}x{h}", "-r", str(fps),
           "-i", "-", "-i", str(audio_from), "-map", "0:v:0", "-map", "1:a:0?", "-c:v", "libx264", "-preset", "slow",
           "-crf", str(crf), "-pix_fmt", "yuv420p", "-c:a", "copy", "-fps_mode", "passthrough", "-movflags", "+faststart",
           str(tmp)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for f in frames:
        if yuv:
            for plane in f:
                p.stdin.write(np.ascontiguousarray(plane, np.uint8).tobytes())
        else:
            p.stdin.write(np.ascontiguousarray(f, np.uint8).tobytes())
    p.stdin.close()
    if p.wait():
        raise RuntimeError(f"ffmpeg failed writing {out}")
    os.replace(tmp, out)


def audio_md5(path) -> str | None:
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-c", "copy", "-f", "md5", "-"],
                       capture_output=True, text=True)
    return r.stdout.strip() or None if r.returncode == 0 else None


def verify(out_path, ref_path, n_expected: int, fps_expected: float) -> dict:
    """Loud conformance check of a written file against the synced input. Raises ConformError."""
    oi, ri = video_info(out_path), video_info(ref_path)
    errs = []
    if abs(oi["fps"] - fps_expected) > 1e-3 or abs(oi["avg_fps"] - fps_expected) > 1e-3:
        errs.append(f"fps {oi['fps']}/{oi['avg_fps']} != {fps_expected}")
    dec = read_frames(out_path)
    if len(dec) != n_expected or (oi["nb_frames"] and oi["nb_frames"] != n_expected):
        errs.append(f"frame count {len(dec)} (container {oi['nb_frames']}) != {n_expected}")
    rep = repeated_frames(dec)
    if rep:
        errs.append(f"repeated frames at {rep}")
    am_o, am_r = audio_md5(out_path), audio_md5(ref_path)
    if ri["audio"] is not None and am_o != am_r:
        errs.append(f"audio stream differs from the synced input ({am_o} vs {am_r})")
    if errs:
        raise ConformError(f"{out_path}: " + "; ".join(errs))
    return {"fps": oi["fps"], "frames": len(dec), "repeated_frames": 0, "audio_md5": am_o,
            "audio_identical_to_input": am_o == am_r}


# ------------------------------------------------------------------------------------------------ evidence
def crop_box(lm, shape, pad: float = 0.9):
    o = np.asarray(lm["outer"])
    c = o.mean(0)
    w = float(np.ptp(o[:, 0])) * (1 + pad)
    h = w * 0.62
    x1, y1 = int(max(0, c[0] - w / 2)), int(max(0, c[1] - h / 2))
    return x1, y1, int(min(shape[1], x1 + w)), int(min(shape[0], y1 + h))


def write_evidence(dirpath, stem, syn, out, raw, lms, log, scale: int = 3):
    """Before/after crops of every applied frame, a contact sheet (L1b | L1c | raw rows) and an sbs mp4."""
    import cv2

    d = Path(dirpath)
    (d / "crops").mkdir(parents=True, exist_ok=True)
    idx = log["applied"]
    tiles = []
    for i in idx:
        x1, y1, x2, y2 = crop_box(lms[i], syn[i].shape)
        row = []
        for name, fr in (("L1b", syn[i]), ("L1c", out[i]), (f"raw f{i}", raw[i])):
            c = cv2.resize(fr[y1:y2, x1:x2], None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            c = np.ascontiguousarray(c[..., ::-1])
            cv2.rectangle(c, (0, 0), (150, 18), (0, 0, 0), -1)
            cv2.putText(c, f"{name} f{i}" if not name.startswith("raw") else name, (3, 13), cv2.FONT_HERSHEY_SIMPLEX,
                        0.45, (0, 255, 255), 1, cv2.LINE_AA)
            row.append(c)
        pf = log["per_frame"][i]
        lab = f"src f{pf['source']} ({pf['source_why']})" if pf["source"] is not None else ""
        cv2.putText(row[1], lab, (3, row[1].shape[0] - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1, cv2.LINE_AA)
        cv2.imwrite(str(d / "crops" / f"{stem}_f{i:03d}_L1b_L1c_raw.jpg"), np.hstack(row), [cv2.IMWRITE_JPEG_QUALITY, 92])
        tiles.append(row)
    sheets = []
    if tiles:
        th, tw = tiles[0][0].shape[:2]
        per = 8
        for k in range(0, len(tiles), per):
            chunk = tiles[k:k + per]
            cols = []
            for row in chunk:
                cols.append(np.vstack([cv2.resize(t, (tw, th)) for t in row]))
            sheet = np.hstack(cols + [np.zeros_like(cols[0])] * (per - len(cols))) if len(chunk) < per else np.hstack(cols)
            p = d / f"{stem}_contact_{k // per + 1:02d}.jpg"
            cv2.imwrite(str(p), sheet, [cv2.IMWRITE_JPEG_QUALITY, 90])
            sheets.append(str(p))
    return sheets


def write_sbs(syn, out, raw, fps, audio_from, path, crf: int = 16):
    import cv2

    fr = []
    for i, (a, b, c) in enumerate(zip(syn, out, raw)):
        row = np.hstack([a, b, c])
        h, w = row.shape[:2]
        row = cv2.resize(row, (w // 2 // 2 * 2, h // 2 // 2 * 2), interpolation=cv2.INTER_AREA)
        bgr = np.ascontiguousarray(row[..., ::-1])
        for k, name in enumerate(("L1b", "L1c (inner-mouth pass)", "raw")):
            cv2.putText(bgr, f"{name}  f{i}", (k * bgr.shape[1] // 3 + 6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                        (0, 255, 255), 1, cv2.LINE_AA)
        fr.append(bgr[..., ::-1])
    write_video(fr, fps, audio_from, path, crf=crf)


# ------------------------------------------------------------------------------------------------ cli
def parse_frames(text) -> list:
    out = []
    for part in (text or "").replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-")
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("synced", help="lip-synced take (LatentSync output)")
    ap.add_argument("raw", help="raw (pre-lip-sync) take, frame-aligned 1:1 with the synced take")
    ap.add_argument("-o", "--out", required=True, help="output mp4")
    ap.add_argument("--log", help="per-frame decision JSON (default OUT.inner_mouth.json)")
    ap.add_argument("--evidence", help="directory for before/after crops, contact sheets and the sbs mp4")
    ap.add_argument("--expect", help="frames that must be flagged (e.g. 20-23,31-38); exit 7 if any is missed")
    ap.add_argument("--force", help="extra frames to treat as flagged (logged as forced)")
    ap.add_argument("--task", help="MediaPipe face_landmarker.task (else OPENSOUL_MP_FACE_TASK, the detector default, "
                                    "./models/face_landmarker.task)")
    ap.add_argument("--face-box", help="x,y,w,h of the speaker on frame 0")
    ap.add_argument("--face-style", choices=["auto", "real", "anime"], default=None,
                    help="auto (default): MediaPipe, anime model lazy-loaded only for frames MediaPipe misses; "
                         "real: MediaPipe only; anime: anime landmarks first")
    ap.add_argument("--crf", type=int, default=12)
    ap.add_argument("--dry-run", action="store_true", help="detect and log only; write no video")
    for f in dataclasses.fields(Config):
        if f.name == "colour_gain_clip":
            continue
        t = type(f.default)
        if t is bool:
            ap.add_argument("--" + f.name.replace("_", "-"), action=argparse.BooleanOptionalAction, default=None,
                            help=f"default {'on' if f.default else 'off'}")
            continue
        ap.add_argument("--" + f.name.replace("_", "-"), type=t, default=None, help=f"default {f.default}")
    return ap


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    cfg = Config(**{f.name: getattr(a, f.name) for f in dataclasses.fields(Config)
                    if f.name != "colour_gain_clip" and getattr(a, f.name, None) is not None})
    si, ri = video_info(a.synced), video_info(a.raw)
    if abs(si["fps"] - ri["fps"]) > 1e-3:
        raise ConformError(f"fps mismatch: synced {si['fps']} vs raw {ri['fps']}")
    syn, raw = read_frames(a.synced), read_frames(a.raw)
    if len(syn) != len(raw):
        raise ConformError(f"frame count mismatch: synced {len(syn)} vs raw {len(raw)}")
    if si["nb_frames"] and si["nb_frames"] != len(syn):
        raise ConformError(f"synced container says {si['nb_frames']} frames, decoded {len(syn)}")
    rep_in = repeated_frames(syn)
    tr = LipTracker(task_path=a.task, style=a.face_style, face_box=a.face_box)
    syn_lms = tr.track(syn, cfg.lm_sigma)
    tr_raw = LipTracker(task_path=a.task, style=a.face_style, face_box=a.face_box)
    raw_lms = tr_raw.track(raw, cfg.lm_sigma)
    force = parse_frames(a.force)
    out, log = process(syn, raw, syn_lms, raw_lms, cfg, force=force)
    if cfg.lip_color_fix:
        sc = [lip_colour(f, l) if l else np.full(3, np.nan) for f, l in zip(syn, syn_lms)]
        rc_ = [lip_colour(f, l) if l else np.full(3, np.nan) for f, l in zip(raw, raw_lms)]
        jumps = [j for j in detect_lip_jumps(sc, rc_, cfg)
                 if all(syn_lms[k] for k in range(j["start"] - 1, j["end"] + 2))]
        out, lip_log = lip_colour_fix(out, syn_lms, jumps, cfg)
        log["lip_color_fix"] = {"runs": jumps, "frames": lip_log}
        log["applied"] = sorted(set(log["applied"]) | {e["i"] for e in lip_log})
    fps = si["fps"]
    for pf in log["per_frame"]:
        pf["t"] = round(pf["i"] / fps, 4)
        pf["forced"] = pf["i"] in force
        pf["synced_landmarks"] = syn_lms[pf["i"]]["source"] if syn_lms[pf["i"]] else None
        pf["raw_landmarks"] = raw_lms[pf["i"]]["source"] if raw_lms[pf["i"]] else None
    expect = parse_frames(a.expect)
    log.update(synced=str(a.synced), raw=str(a.raw), out=str(a.out), fps=fps, input_repeated_frames=rep_in,
               detector={"synced": tr.report(), "raw": tr_raw.report()},
               expect=expect, expect_missed=[i for i in expect if i not in log["fixed"]],
               extra_flagged=[i for i in log["fixed"] if expect and i not in expect], **parent_sidecar(a.synced))
    log.update(out_frames=None, out_sha256=None)
    log_path = Path(a.log or (str(a.out) + ".inner_mouth.json"))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    rc = 0
    if not a.dry_run:
        if rep_in:
            raise ConformError(f"synced input already has repeated frames at {rep_in}")
        yuv = read_yuv(a.synced)
        if len(yuv) != len(syn):
            raise ConformError(f"yuv decode gave {len(yuv)} frames, rgb decode {len(syn)}")
        touched = set(log["applied"])
        yuv = [apply_delta_yuv(yuv[i], syn[i], out[i]) if i in touched else yuv[i] for i in range(len(syn))]
        write_video(yuv, int(round(fps)), a.synced, a.out, crf=a.crf)
        log["conform"] = verify(a.out, a.synced, len(syn), fps)
        if a.evidence:
            stem = Path(a.out).stem
            log["evidence"] = {"contact_sheets": write_evidence(a.evidence, stem, syn, out, raw, syn_lms, log)}
            sbs = Path(a.evidence) / f"{stem}_sbs_L1b_L1c_raw.mp4"
            write_sbs(syn, out, raw, int(round(fps)), a.synced, sbs)
            log["evidence"]["sbs"] = str(sbs)
        # OUT.mp4 is final here (the evidence goes to its own directory); hash it now and write the sidecar last
        log.update(out_frames=log["conform"]["frames"], out_sha256=file_sha256(a.out))
    tmp = log_path.with_name(log_path.name + ".tmp")
    tmp.write_text(json.dumps(log, indent=1, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o)))
    os.replace(tmp, log_path)
    print(json.dumps({"out": str(a.out), "log": str(log_path), "frames": len(syn), "detected": log["detected"],
                      "fixed": log["fixed"], "applied": log["applied"], "expect_missed": log["expect_missed"],
                      "extra_flagged": log["extra_flagged"]}))
    if log["expect_missed"]:
        print(f"ERROR: expected frames not flagged: {log['expect_missed']}", file=sys.stderr)
        rc = 7
    return rc


if __name__ == "__main__":
    try:
        code = main()
    except ConformError as e:
        print(f"CONFORM ERROR: {e}", file=sys.stderr)
        code = ConformError.code
    sys.stdout.flush()
    sys.stderr.flush()
    # MediaPipe's FaceLandmarker can hang or raise in __del__ at interpreter shutdown; everything is written by now
    os._exit(code)
