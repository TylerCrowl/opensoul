"""LTX a2v camera lock (native LTXVAddGuide last-frame pin) and the camera-creep gate.

Graph: after stage-1 LTXVImgToVideoInplace, native ComfyUI ``LTXVAddGuide`` (NOT KJNodes) pins the last frame to
the same start-frame preprocess (node 3), frame_idx=-1, strength=1.0; ConcatAV and DualCFG take the guide conds;
after SeparateAV, ``LTXVCropGuides`` runs before the upsampler and stage-2 DualCFG uses the cropped conds. Stage-1
i2v strength stays 0.85; cfg stays 1.0/1.0. Wiring mirrors ``notes/v7g/batch3.py`` and the last-guide a2v workflow.
Default ON; ``OPENSOUL_A2V_CAMLOCK=off`` restores the old graph (no guide).

Gate: SIFT on the background, partial affine vs frame 0; REJECT when max |s-1| > 0.5% OR max centre translation
> 1 px. Used after a2v (re-seed / never LatentSync on a fail) and again after LatentSync (re-pick the base like a
grin in the output; never re-run LatentSync with other settings).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CAMLOCK_ENV = "OPENSOUL_A2V_CAMLOCK"  # on (default) | off
N_ADD_GUIDE, N_CROP_GUIDES, N_GUIDER_2 = "93", "94", "95"
N_PREPROCESS, N_COND, N_I2V_1 = "3", "22", "31"
N_CONCAT_1, N_GUIDER_1, N_SEPARATE_1, N_UPSAMPLE = "33", "34", "39", "40"
N_VAE, N_MODEL, N_SAMPLER_2 = "12", "10", "46"
# Gate thresholds: scale drift ≤ 0.5%, translation ≤ 1 px.
SCALE_DRIFT_MAX_PCT = 0.5
TRANS_MAX_PX = 1.0
SIFT_FEATURES = 3000
RATIO_TEST = 0.7
RANSAC_PX = 1.5


def cam_lock_enabled(env: dict | None = None) -> bool:
    """Camera lock on the a2v graph (and the cam gate) is the default. ``OPENSOUL_A2V_CAMLOCK=off`` restores the old
    recipe (no AddGuide / CropGuides, no cam gate)."""
    import os

    v = ((os.environ if env is None else env).get(CAMLOCK_ENV) or "on").strip().lower()
    return v not in ("0", "off", "false", "no")


def is_cam_locked(graph: dict) -> bool:
    return (graph.get(N_ADD_GUIDE) or {}).get("class_type") == "LTXVAddGuide"


def apply_cam_lock(graph: dict) -> dict:
    """Return a copy of the 04b a2v graph with native LTXVAddGuide + LTXVCropGuides wired in (idempotent).

    AddGuide.image is the SAME start-frame preprocess as frame 0 (node 3); frame_idx=-1, strength=1.0. DualCFG 34
    gets the guide conds; after SeparateAV, CropGuides feeds the upsampler and a second DualCFG (95) runs stage 2.
    """
    g = json.loads(json.dumps(graph))
    if is_cam_locked(g):
        return g
    for need in (N_PREPROCESS, N_COND, N_I2V_1, N_CONCAT_1, N_GUIDER_1, N_SEPARATE_1, N_UPSAMPLE, N_SAMPLER_2, N_VAE):
        if need not in g:
            raise KeyError(f"a2v cam lock needs node {need} in the workflow")
    g[N_ADD_GUIDE] = {
        "class_type": "LTXVAddGuide",
        "inputs": {
            "positive": [N_COND, 0],
            "negative": [N_COND, 1],
            "vae": [N_VAE, 0],
            "latent": [N_I2V_1, 0],
            "image": [N_PREPROCESS, 0],  # same preprocess as f0
            "frame_idx": -1,
            "strength": 1.0,
        },
    }
    g[N_CONCAT_1]["inputs"]["video_latent"] = [N_ADD_GUIDE, 2]
    g[N_GUIDER_1]["inputs"]["positive"] = [N_ADD_GUIDE, 0]
    g[N_GUIDER_1]["inputs"]["negative"] = [N_ADD_GUIDE, 1]
    g[N_CROP_GUIDES] = {
        "class_type": "LTXVCropGuides",
        "inputs": {
            "positive": [N_ADD_GUIDE, 0],
            "negative": [N_ADD_GUIDE, 1],
            "latent": [N_SEPARATE_1, 0],
        },
    }
    g[N_UPSAMPLE]["inputs"]["samples"] = [N_CROP_GUIDES, 2]
    g[N_GUIDER_2] = json.loads(json.dumps(g[N_GUIDER_1]))
    g[N_GUIDER_2]["inputs"]["positive"] = [N_CROP_GUIDES, 0]
    g[N_GUIDER_2]["inputs"]["negative"] = [N_CROP_GUIDES, 1]
    g[N_GUIDER_2]["inputs"]["video_cfg"] = 1.0
    g[N_GUIDER_2]["inputs"]["audio_cfg"] = 1.0
    # Keep the model link from the stage-1 guider (with_loras may have rewritten it).
    g[N_GUIDER_2]["inputs"]["model"] = list(g[N_GUIDER_1]["inputs"]["model"])
    g[N_SAMPLER_2]["inputs"]["guider"] = [N_GUIDER_2, 0]
    return g


N_HOLD_GUIDE = "96"
HOLD_STRENGTH = 0.8   # OS-056: the closed-mouth hold after the line (the end pin stays 1.0)


def apply_hold_guide(graph: dict, frame_idx: int, strength: float = HOLD_STRENGTH) -> dict:
    """OS-056/OS-059: a second native LTXVAddGuide with the start picture (mouth closed) at ``frame_idx``, the first
    silent frame after the line. With the last-frame pin, the silent end of a talking take holds a closed, still
    mouth. Needs a camera-locked graph (:func:`apply_cam_lock`); LTXVCropGuides removes both guides."""
    g = json.loads(json.dumps(graph))
    if not is_cam_locked(g):
        raise KeyError("the hold guide needs the camera-locked a2v graph")
    if N_HOLD_GUIDE in g:
        g[N_HOLD_GUIDE]["inputs"].update({"frame_idx": int(frame_idx), "strength": float(strength)})
        return g
    g[N_HOLD_GUIDE] = {
        "class_type": "LTXVAddGuide",
        "inputs": {
            "positive": [N_ADD_GUIDE, 0],
            "negative": [N_ADD_GUIDE, 1],
            "vae": [N_VAE, 0],
            "latent": [N_ADD_GUIDE, 2],
            "image": [N_PREPROCESS, 0],
            "frame_idx": int(frame_idx),
            "strength": float(strength),
        },
    }
    g[N_CONCAT_1]["inputs"]["video_latent"] = [N_HOLD_GUIDE, 2]
    for n in (N_GUIDER_1, N_CROP_GUIDES):
        g[n]["inputs"]["positive"] = [N_HOLD_GUIDE, 0]
        g[n]["inputs"]["negative"] = [N_HOLD_GUIDE, 1]
    return g


def crop_guides_before_upsampler(graph: dict) -> bool:
    """True when LTXVCropGuides feeds the latent upsampler (cam-lock wiring)."""
    if not is_cam_locked(graph):
        return False
    src = (graph.get(N_UPSAMPLE) or {}).get("inputs", {}).get("samples") or [None]
    return src[0] == N_CROP_GUIDES and (graph.get(N_CROP_GUIDES) or {}).get("class_type") == "LTXVCropGuides"


def add_guide_ok(graph: dict) -> bool:
    """True when AddGuide uses frame_idx -1, strength 1.0 and the same preprocess image as f0."""
    n = graph.get(N_ADD_GUIDE) or {}
    if n.get("class_type") != "LTXVAddGuide":
        return False
    inp = n.get("inputs") or {}
    return (inp.get("frame_idx") == -1 and float(inp.get("strength", 0)) == 1.0
            and list(inp.get("image") or []) == [N_PREPROCESS, 0]
            and (graph.get(N_I2V_1) or {}).get("inputs", {}).get("image") == [N_PREPROCESS, 0])


def cam_thresholds(cfg_cam: dict | None = None) -> tuple[float, float]:
    c = cfg_cam or {}
    return float(c.get("scale_drift_max_pct", SCALE_DRIFT_MAX_PCT)), float(c.get("trans_max_px", TRANS_MAX_PX))


def cam_verdict_of(scale_drift_max_pct: float, trans_max_px: float, cfg_cam: dict | None = None) -> str:
    smax, tmax = cam_thresholds(cfg_cam)
    return "FAIL" if scale_drift_max_pct > smax or trans_max_px > tmax else "PASS"


def _subject_mask(shape: tuple[int, int], face_box=None):
    """Background-only mask: zero out the subject so SIFT locks onto the set, not the face.

    With a face_box (x, y, w, h) the box is expanded toward a torso column; without one, the centre 40% of width
    (full height) is masked — portrait a2v is typically 704×1280, so a fixed 1280×704 column would be wrong."""
    import numpy as np

    h, w = shape
    m = np.full((h, w), 255, np.uint8)
    if face_box and len(face_box) >= 4:
        x, y, fw, fh = [float(v) for v in face_box[:4]]
        # Expand sideways and down so hair / shoulders stay out of the background match.
        pad_x, pad_y0, pad_y1 = fw * 0.6, fh * 0.4, fh * 2.2
        x0, x1 = max(0, int(x - pad_x)), min(w, int(x + fw + pad_x))
        y0, y1 = max(0, int(y - pad_y0)), min(h, int(y + pad_y1))
        m[y0:y1, x0:x1] = 0
    else:
        x0, x1 = int(0.30 * w), int(0.70 * w)
        m[:, x0:x1] = 0
    return m


def score_cam(video, *, face_box=None, cfg_cam: dict | None = None) -> dict[str, Any]:
    """Camera-creep score for one take (SIFT + partial affine vs frame 0, any frame size).

    Returns ``scale_drift_max_pct``, ``trans_max_px``, ``cam_verdict`` ('PASS'|'FAIL'|'ERROR'), plus last-frame
    scale/translation and frame count. Never raises: an unreadable clip or a match failure is ``ERROR`` (callers that
    gate on cam treat ERROR like FAIL when the lock is on).
    """
    import cv2
    import numpy as np

    path = Path(video)
    try:
        cap = cv2.VideoCapture(str(path))
        frames = []
        while True:
            ok, f = cap.read()
            if not ok:
                break
            frames.append(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY))
        cap.release()
        if len(frames) < 2:
            return {"video": str(path), "n": len(frames), "cam_verdict": "ERROR",
                    "error": "need at least 2 frames", "scale_drift_max_pct": None, "trans_max_px": None}
        f0 = frames[0]
        h, w = f0.shape
        mask = _subject_mask((h, w), face_box)
        sift = cv2.SIFT_create(SIFT_FEATURES)
        k0, d0 = sift.detectAndCompute(f0, mask)
        if d0 is None or len(k0) < 8:
            return {"video": str(path), "n": len(frames), "cam_verdict": "ERROR",
                    "error": "not enough background SIFT features on frame 0",
                    "scale_drift_max_pct": None, "trans_max_px": None}
        bf = cv2.BFMatcher()
        cx, cy = w / 2.0, h / 2.0
        rows = []
        for i, fi in enumerate(frames):
            k1, d1 = sift.detectAndCompute(fi, mask)
            if d1 is None or len(k1) < 8:
                rows.append(dict(i=i, s=1.0, tx=0.0, ty=0.0, inl=0))
                continue
            pairs = bf.knnMatch(d0, d1, k=2)
            good = [x for x, y in pairs if x.distance < RATIO_TEST * y.distance]
            if len(good) < 6:
                rows.append(dict(i=i, s=1.0, tx=0.0, ty=0.0, inl=0))
                continue
            p0 = np.float32([k0[x.queryIdx].pt for x in good])
            p1 = np.float32([k1[x.trainIdx].pt for x in good])
            A, inl = cv2.estimateAffinePartial2D(p0, p1, ransacReprojThreshold=RANSAC_PX)
            if A is None:
                rows.append(dict(i=i, s=1.0, tx=0.0, ty=0.0, inl=0))
                continue
            s = float(np.hypot(A[0, 0], A[1, 0]))
            c = A @ np.array([cx, cy, 1.0])
            rows.append(dict(i=i, s=round(s, 4), tx=round(float(c[0] - cx), 2),
                             ty=round(float(c[1] - cy), 2), inl=int(inl.sum()) if inl is not None else 0))
        smax = max(abs(r["s"] - 1) for r in rows) * 100
        tmax = max(float(np.hypot(r["tx"], r["ty"])) for r in rows)
        last = rows[-1]
        verdict = cam_verdict_of(smax, tmax, cfg_cam)
        return {"video": str(path), "n": len(rows),
                "scale_drift_max_pct": round(smax, 2), "scale_last": last["s"],
                "trans_max_px": round(tmax, 2), "tx_last": last["tx"], "ty_last": last["ty"],
                "inl_min": min(r["inl"] for r in rows), "cam_verdict": verdict}
    except Exception as e:  # noqa: BLE001  gate must never crash the take
        return {"video": str(path), "n": 0, "cam_verdict": "ERROR", "error": str(e)[:200],
                "scale_drift_max_pct": None, "trans_max_px": None}


def cam_passes(cam: dict | None) -> bool:
    """True only on an explicit PASS (FAIL and ERROR both block the base / trigger a re-pick)."""
    return bool(cam) and cam.get("cam_verdict") == "PASS"


def cam_reject_reason(cam: dict | None, cfg_cam: dict | None = None) -> str | None:
    """Human reason when cam fails the gate, else None."""
    if cam_passes(cam):
        return None
    if not cam:
        return "camera check missing"
    smax, tmax = cam_thresholds(cfg_cam)
    if cam.get("cam_verdict") == "ERROR":
        return "camera check failed" + (f" ({cam.get('error')})" if cam.get("error") else "")
    sp = cam.get("scale_drift_max_pct")
    tp = cam.get("trans_max_px")
    return (f"camera drift (scale {sp}% > {smax:g}% or translation {tp} px > {tmax:g} px)"
            if sp is not None and tp is not None else "camera drift")
