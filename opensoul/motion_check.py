"""Automatic camera-motion direction check (dense optical flow).

Estimates the dominant camera move of a clip with OpenCV Farneback optical flow on small
grey frames, so the shot pipeline can catch takes that move the wrong way (a "zoom out"
that pushes in, a "jib down" that is a plain push-in, an "orbit" that barely drifts) and
re-seed them. CPU only; deps: opencv-python-headless (Apache-2.0) + numpy (BSD).

Per frame pair the flow field is fitted with a zoom + translation + roll model
(u = tx + s*x - r*y, v = ty + r*x + s*y, coordinates centred and scaled by half the short
side, robust re-weighting). Summed over the clip that gives:

* ``zoom``  = sum of s ~ log of the scale change. > 0: image expands = camera pushes in /
  zooms in; < 0: pulls out / zooms out.
* ``pan_x`` / ``pan_y`` = summed global translation (image content motion, y points down).
* ``par_x`` / ``par_y`` / ``par_y_side`` = motion parallax: residual flow of the background
  bands (left/right edges; top band; side bands for vertical) minus the subject box in the
  centre. Vertical travel is only counted when the top and side bands agree (``par_y_agreed``). Parallax gives the direction the
  camera *travelled* regardless of any tilt/pan used to keep the subject framed:
  background moving UP relative to the subject = camera rising (jib/crane up); background
  moving DOWN relative to the subject (the foreground/subject rises in frame) = camera
  descending (jib/crane down). Background moving right relative to the subject = camera
  travelling right (truck/orbit right).

Labels: ``static``, ``zoom_in``, ``zoom_out``, ``truck_left``, ``truck_right``,
``orbit_left``, ``orbit_right`` (lateral parallax with the subject held in frame, larger
sweep), ``crane_up``, ``crane_down``, ``pan_left``/``pan_right``/``tilt_up``/``tilt_down``
(uniform translation without parallax: a rotation of the camera; named after the camera
move, so content moving left = pan right).

Limits (honest): monocular flow cannot separate a pure tilt from a pedestal move without
parallax; cuts, morphs and lighting changes (outfit switch, day-to-night) are not camera
moves; a dolly zoom keeps the subject size and is not a single global zoom. Presets whose
look is not a single camera move declare ``expect_motion: "any"``.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

LABELS = (
    "static", "zoom_in", "zoom_out", "truck_left", "truck_right", "orbit_left", "orbit_right",
    "crane_up", "crane_down", "pan_left", "pan_right", "tilt_up", "tilt_down",
)

# Tuned on the 20 pt1/pt1b LTX takes (see docs/evidence/motion_check.md) + synthetic clips.
THRESHOLDS = {
    "static_motion": 0.20,  # summed mean |flow| over the clip (normalised units) below this = static
    "min_component": 0.12,  # dominant component must exceed this, else static
    "orbit_sweep": 0.60,    # lateral parallax above this with the subject held in frame = orbit
    "subject_hold": 0.5,    # |subject shift| / |background sweep| below this = subject held in frame
    "min_confidence": 0.2,  # a mismatch below this confidence is "uncertain" and passes (no re-seed)
}


@dataclass
class MotionResult:
    label: str
    confidence: float
    numbers: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _read_frames(path: str | Path, width: int = 160, step: int = 2, max_frames: int = 400) -> list[np.ndarray]:
    import cv2

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError(f"cannot open video: {path}")
    out: list[np.ndarray] = []
    i = 0
    while len(out) < max_frames:
        ok, f = cap.read()
        if not ok:
            break
        if i % step == 0:
            h, w = f.shape[:2]
            s = width / w
            g = cv2.cvtColor(cv2.resize(f, (width, max(8, int(round(h * s)))), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
            out.append(g)
        i += 1
    cap.release()
    return out


def _fit_pair(flow: np.ndarray) -> dict:
    h, w = flow.shape[:2]
    sc = min(h, w) / 2.0
    ys, xs = np.mgrid[0:h, 0:w]
    x = ((xs - (w - 1) / 2) / sc).ravel()
    y = ((ys - (h - 1) / 2) / sc).ravel()
    u = flow[..., 0].ravel() / sc
    v = flow[..., 1].ravel() / sc
    n = x.size
    # Unknowns [tx, ty, s, r]; rows: u = tx + s x - r y ; v = ty + r x + s y
    A = np.zeros((2 * n, 4))
    A[:n, 0] = 1
    A[:n, 2] = x
    A[:n, 3] = -y
    A[n:, 1] = 1
    A[n:, 2] = y
    A[n:, 3] = x
    b = np.concatenate([u, v])
    wts = np.ones(n)
    p = np.zeros(4)
    for _ in range(3):
        W = np.sqrt(np.concatenate([wts, wts]))
        p = np.linalg.lstsq(A * W[:, None], b * W, rcond=None)[0]
        r = b - A @ p
        rr = np.hypot(r[:n], r[n:])
        c = 3 * np.median(rr) + 1e-6
        wts = 1.0 / np.maximum(1.0, rr / c)
    res = (b - A @ p)
    ru = res[:n].reshape(h, w)
    rv = res[n:].reshape(h, w)
    cx = slice(int(w * 0.3), int(w * 0.7))
    cy = slice(int(h * 0.25), int(h * 0.75))
    sub_u = float(np.median(ru[cy, cx]))
    sub_v = float(np.median(rv[cy, cx]))
    bw = max(1, int(w * 0.15))
    bh = max(1, int(h * 0.15))
    bg_u = float(np.median(np.concatenate([ru[:, :bw].ravel(), ru[:, -bw:].ravel()])))
    bg_v = float(np.median(rv[:bh].ravel()))  # top band: the bottom band is usually the subject's body
    mid = slice(int(h * 0.25), int(h * 0.75))
    side_v = float(np.median(np.concatenate([rv[mid, :bw].ravel(), rv[mid, -bw:].ravel()])))
    U = flow[..., 0] / sc
    return {
        "tx": float(p[0]), "ty": float(p[1]), "s": float(p[2]), "r": float(p[3]),
        "par_x": bg_u - sub_u, "par_y": bg_v - sub_v, "par_y_side": side_v - sub_v,
        "sub_x": float(np.median(U[cy, cx])),
        "mag": float(np.mean(np.hypot(u, v))),
    }


def analyze(path: str | Path, *, width: int = 160, step: int = 2) -> dict:
    """Clip-level motion numbers (summed over frame pairs, normalised units)."""
    import cv2

    frames = _read_frames(path, width=width, step=step)
    if len(frames) < 2:
        raise ValueError(f"need at least 2 frames: {path}")
    rows = []
    for a, b in zip(frames, frames[1:]):
        fl = cv2.calcOpticalFlowFarneback(a, b, None, 0.5, 3, 15, 3, 5, 1.2, 0)
        rows.append(_fit_pair(fl))
    tot = {k: float(np.sum([r[k] for r in rows])) for k in rows[0]}
    s = np.array([r["s"] for r in rows])
    big = np.abs(s) > 1e-3
    zoom_consistency = float(np.mean(np.sign(s[big]) == np.sign(tot["s"]))) if big.any() else 0.0
    return {
        "pairs": len(rows),
        "motion": round(tot["mag"], 4),
        "zoom": round(tot["s"], 4),
        "pan_x": round(tot["tx"], 4),
        "pan_y": round(tot["ty"], 4),
        "roll": round(tot["r"], 4),
        "par_x": round(tot["par_x"], 4),
        "par_y": round(tot["par_y"], 4),
        "par_y_side": round(tot["par_y_side"], 4),
        "sub_x": round(tot["sub_x"], 4),
        "zoom_consistency": round(zoom_consistency, 3),
    }


def classify(n: dict, thresholds: dict | None = None) -> MotionResult:
    t = {**THRESHOLDS, **(thresholds or {})}
    if n["motion"] < t["static_motion"]:
        conf = 1.0 - n["motion"] / t["static_motion"] * 0.5
        return MotionResult("static", round(conf, 3), n)
    zoom = n["zoom"]
    par_x = n["par_x"]
    # Vertical travel needs the top band AND the side bands to move the same way relative to the
    # subject. A push-in also gives the top band a downward residual (the far background expands
    # less than the near subject) but leaves the side bands' vertical flow near zero/opposite, so a
    # push-in is not mistaken for a crane down (it was on the raw top-band number alone).
    pt, ps = n["par_y"], n.get("par_y_side", n["par_y"])
    par_y = math.copysign(min(abs(pt), abs(ps)), pt) if pt * ps > 0 else 0.0
    n = {**n, "par_y_agreed": round(par_y, 4)}
    pan_x, pan_y = n["pan_x"], n["pan_y"]
    comps = {
        "zoom": abs(zoom),
        "lateral": abs(par_x),
        "vertical": abs(par_y),
        # Uniform translation counts as a pan/tilt (camera rotation) only where parallax does not
        # explain it (a truck/crane also translates the frame), and at half weight because a zoom
        # about an off-centre point (the face) also shows up as a translation.
        "pan": max(0.0, abs(pan_x) - 2 * abs(par_x)) * 0.5,
        "tilt": max(0.0, abs(pan_y) - 2 * abs(par_y)) * 0.5,
    }
    order = sorted(comps, key=comps.get, reverse=True)
    dom, second = order[0], order[1]
    dv, sv = comps[dom], comps[second]
    if dv < t["min_component"]:
        return MotionResult("static", round(1.0 - dv / t["min_component"] * 0.5, 3), n)
    if dom == "zoom":
        label = "zoom_in" if zoom > 0 else "zoom_out"
    elif dom == "lateral":
        right = par_x > 0  # background moves right relative to subject = camera travels right
        held = abs(n["sub_x"]) < t["subject_hold"] * abs(par_x)
        kind = "orbit" if (held and abs(par_x) >= t["orbit_sweep"]) else "truck"
        label = f"{kind}_{'right' if right else 'left'}"
    elif dom == "vertical":
        label = "crane_up" if par_y < 0 else "crane_down"
    elif dom == "pan":
        label = "pan_right" if pan_x < 0 else "pan_left"
    else:
        label = "tilt_down" if pan_y < 0 else "tilt_up"
    conf = (dv - sv) / (dv + 1e-9) * min(1.0, dv / (2 * t["min_component"]))
    return MotionResult(label, round(float(max(0.0, min(1.0, conf))), 3), n)


def detect(path: str | Path, thresholds: dict | None = None) -> MotionResult:
    return classify(analyze(path), thresholds)


def expected_labels(expect: str | list | None) -> list[str] | None:
    """Normalise a preset's ``expect_motion`` (label, list of labels, "any"/None) to a list or None."""
    if expect is None or expect == "any":
        return None
    if isinstance(expect, str):
        expect = [expect]
    alias = {"orbit": ["orbit_left", "orbit_right"], "truck": ["truck_left", "truck_right"]}
    out: list[str] = []
    for e in expect:
        out.extend(alias.get(e, [e]))
    unknown = [e for e in out if e not in LABELS]
    if unknown:
        raise ValueError(f"unknown motion label(s): {unknown}")
    return out


def check(path: str | Path, expect: str | list | None, thresholds: dict | None = None) -> dict:
    """Run detection and compare with the preset's expected motion. ``ok`` is True when nothing is expected."""
    t = {**THRESHOLDS, **(thresholds or {})}
    res = detect(path, t)
    want = expected_labels(expect)
    match = True if want is None else res.label in want
    # A low-confidence read (two components nearly tied) is "uncertain": not a mismatch, so no
    # GPU time is spent re-seeding a take the checker cannot actually call.
    uncertain = (not match) and res.confidence < t["min_confidence"]
    return {"ok": match or uncertain, "uncertain": uncertain, "expected": want, **res.to_dict()}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Estimate the dominant camera move of a clip.")
    ap.add_argument("videos", nargs="+")
    ap.add_argument("--expect", default=None, help="expected label (comma list) to compare against")
    a = ap.parse_args(argv)
    bad = 0
    for v in a.videos:
        exp = a.expect.split(",") if a.expect else None
        r = check(v, exp)
        bad += 0 if r["ok"] else 1
        print(json.dumps({"video": v, **r}))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
