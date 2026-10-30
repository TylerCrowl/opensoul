#!/usr/bin/env python3
"""Make an OpenPose-style pose guide video outside ComfyUI (no custom nodes, no Comfy restart).

Used by the experimental "Openjutsu" re-perform path: a driver clip (CC0, public domain or
synthetic, never a real private person) is turned into a black-background skeleton video that
feeds the LTX-2.5 Union Control IC-LoRA as its guide.

Models: DWPose wholebody + YOLOX-L person detector, ONNX, Apache-2.0 (huggingface.co/yzd-v/DWPose).
Fetch with: ./scripts/download_models.sh pose

Usage:
  python scripts/make_pose_guide.py driver.mp4 guide.mp4 [--models DIR] [--width W --height H] [--max-frames N]
Writes guide.mp4 plus guide.json (per-frame detection and keypoint confidence, for gating).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

import numpy as np

# ---------------------------------------------------------------- pure helpers (unit tested)

# OpenPose-18 body from COCO-17 (index 1 = neck = mean of the shoulders).
COCO_TO_OP = [0, None, 6, 8, 10, 5, 7, 9, 12, 14, 16, 11, 13, 15, 2, 1, 4, 3]
LIMBS = [(1, 2), (1, 5), (2, 3), (3, 4), (5, 6), (6, 7), (1, 8), (8, 9), (9, 10), (1, 11), (11, 12),
         (12, 13), (1, 0), (0, 14), (14, 16), (0, 15), (15, 17)]
COLORS = [(255, 0, 0), (255, 85, 0), (255, 170, 0), (255, 255, 0), (170, 255, 0), (85, 255, 0), (0, 255, 0),
          (0, 255, 85), (0, 255, 170), (0, 255, 255), (0, 170, 255), (0, 85, 255), (0, 0, 255), (85, 0, 255),
          (170, 0, 255), (255, 0, 255), (255, 0, 170), (255, 0, 85)]
HAND_EDGES = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (0, 9), (9, 10), (10, 11),
              (11, 12), (0, 13), (13, 14), (14, 15), (15, 16), (0, 17), (17, 18), (18, 19), (19, 20)]
THR = 0.3


def coco_body_to_openpose(kp: np.ndarray, sc: np.ndarray):
    """kp (>=17,2), sc (>=17,) COCO order -> (18,2), (18,) OpenPose order with a synthesized neck."""
    out_k = np.zeros((18, 2), np.float32)
    out_s = np.zeros(18, np.float32)
    for op, c in enumerate(COCO_TO_OP):
        if c is None:
            out_k[op] = (kp[5] + kp[6]) / 2
            out_s[op] = min(sc[5], sc[6])
        else:
            out_k[op], out_s[op] = kp[c], sc[c]
    return out_k, out_s


def simcc_decode(simcc_x: np.ndarray, simcc_y: np.ndarray, split: float = 2.0):
    """(N,K,Wx), (N,K,Wy) -> locs (N,K,2) in input pixels, vals (N,K) = min of the two peaks."""
    x = simcc_x.argmax(-1)
    y = simcc_y.argmax(-1)
    vals = np.minimum(simcc_x.max(-1), simcc_y.max(-1))
    locs = np.stack([x, y], -1).astype(np.float32) / split
    locs[vals <= 0] = -1
    return locs, vals


def draw_pose(canvas: np.ndarray, body_k, body_s, lh=None, rh=None, face=None):
    import cv2
    H, W = canvas.shape[:2]
    stick = max(2, int(round(4 * min(H, W) / 512)))
    for i, (a, b) in enumerate(LIMBS):
        if body_s[a] < THR or body_s[b] < THR:
            continue
        (x1, y1), (x2, y2) = body_k[a], body_k[b]
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        length = math.hypot(x1 - x2, y1 - y2)
        ang = math.degrees(math.atan2(y1 - y2, x1 - x2))
        poly = cv2.ellipse2Poly((int(mx), int(my)), (int(length / 2), stick), int(ang), 0, 360, 1)
        cv2.fillConvexPoly(canvas, poly, tuple(int(c * 0.6) for c in COLORS[i]))
    for i in range(18):
        if body_s[i] >= THR:
            cv2.circle(canvas, tuple(int(v) for v in body_k[i]), stick, COLORS[i], -1)
    for hand in (lh, rh):
        if hand is None:
            continue
        hk, hs = hand
        for e, (a, b) in enumerate(HAND_EDGES):
            if hs[a] >= THR and hs[b] >= THR:
                import colorsys
                col = tuple(int(c * 255) for c in colorsys.hsv_to_rgb(e / len(HAND_EDGES), 1.0, 1.0))
                cv2.line(canvas, tuple(int(v) for v in hk[a]), tuple(int(v) for v in hk[b]), col, max(1, stick // 2))
        for i in range(21):
            if hs[i] >= THR:
                cv2.circle(canvas, tuple(int(v) for v in hk[i]), max(1, stick // 2), (0, 0, 255), -1)
    if face is not None:
        fk, fs = face
        for i in range(len(fk)):
            if fs[i] >= THR:
                cv2.circle(canvas, tuple(int(v) for v in fk[i]), max(1, stick // 2), (255, 255, 255), -1)
    return canvas


# ---------------------------------------------------------------- ONNX models

class Detector:
    def __init__(self, path, providers):
        import onnxruntime as ort
        self.s = ort.InferenceSession(path, providers=providers)

    def __call__(self, img_bgr):
        import cv2
        h, w = img_bgr.shape[:2]
        r = min(640 / h, 640 / w)
        pad = np.full((640, 640, 3), 114, np.uint8)
        pad[: int(h * r), : int(w * r)] = cv2.resize(img_bgr, (int(w * r), int(h * r)))
        out = self.s.run(None, {self.s.get_inputs()[0].name: pad.transpose(2, 0, 1)[None].astype(np.float32)})[0][0]
        grids, strides = [], []
        for st in (8, 16, 32):
            g = 640 // st
            yv, xv = np.meshgrid(np.arange(g), np.arange(g), indexing="ij")
            grids.append(np.stack([xv, yv], -1).reshape(-1, 2))
            strides.append(np.full((g * g, 1), st))
        grids, strides = np.concatenate(grids), np.concatenate(strides)
        out[:, :2] = (out[:, :2] + grids) * strides
        out[:, 2:4] = np.exp(out[:, 2:4]) * strides
        score = out[:, 4] * out[:, 5]  # objectness x person class
        keep = score > 0.3
        if not keep.any():
            return np.zeros((0, 4)), np.zeros(0)
        b, sc = out[keep, :4], score[keep]
        xyxy = np.stack([b[:, 0] - b[:, 2] / 2, b[:, 1] - b[:, 3] / 2, b[:, 0] + b[:, 2] / 2, b[:, 1] + b[:, 3] / 2], 1) / r
        idx = cv2.dnn.NMSBoxes([[float(x1), float(y1), float(x2 - x1), float(y2 - y1)] for x1, y1, x2, y2 in xyxy], sc.tolist(), 0.3, 0.45)
        idx = np.array(idx).reshape(-1)
        return xyxy[idx], sc[idx]


class Pose:
    W, H = 288, 384
    MEAN = np.array([123.675, 116.28, 103.53], np.float32)
    STD = np.array([58.395, 57.12, 57.375], np.float32)

    def __init__(self, path, providers):
        import onnxruntime as ort
        self.s = ort.InferenceSession(path, providers=providers)

    def __call__(self, img_bgr, box):
        import cv2
        x1, y1, x2, y2 = box
        c = np.array([(x1 + x2) / 2, (y1 + y2) / 2], np.float32)
        bw, bh = (x2 - x1) * 1.25, (y2 - y1) * 1.25
        ar = self.W / self.H
        if bw > bh * ar:
            bh = bw / ar
        else:
            bw = bh * ar
        src = np.float32([[c[0] - bw / 2, c[1] - bh / 2], [c[0] + bw / 2, c[1] - bh / 2], [c[0] - bw / 2, c[1] + bh / 2]])
        dst = np.float32([[0, 0], [self.W, 0], [0, self.H]])
        M = cv2.getAffineTransform(src, dst)
        crop = cv2.warpAffine(img_bgr, M, (self.W, self.H), flags=cv2.INTER_LINEAR)
        x = ((crop[..., ::-1].astype(np.float32) - self.MEAN) / self.STD).transpose(2, 0, 1)[None]
        sx, sy = self.s.run(None, {self.s.get_inputs()[0].name: x})
        locs, vals = simcc_decode(sx, sy)
        k = locs[0] / np.array([self.W, self.H], np.float32) * np.array([bw, bh], np.float32) + c - np.array([bw, bh]) / 2
        return k, vals[0]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("driver")
    ap.add_argument("out")
    ap.add_argument("--models", default=os.path.expanduser("~/OpenSoul/models/dwpose"))
    ap.add_argument("--width", type=int)
    ap.add_argument("--height", type=int)
    ap.add_argument("--max-frames", type=int, default=0)
    ap.add_argument("--no-face", action="store_true", help="omit face dots (lets the target face stay on-model)")
    a = ap.parse_args(argv)
    import cv2
    import onnxruntime as ort
    prov = [p for p in ("CUDAExecutionProvider", "CPUExecutionProvider") if p in ort.get_available_providers()]
    det = Detector(os.path.join(a.models, "yolox_l.onnx"), prov)
    pose = Pose(os.path.join(a.models, "dw-ll_ucoco_384.onnx"), prov)
    cap = cv2.VideoCapture(a.driver)
    fps = cap.get(cv2.CAP_PROP_FPS) or 24
    W = a.width or int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = a.height or int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    vw = cv2.VideoWriter(a.out, cv2.VideoWriter_fourcc(*"mp4v"), fps, (W, H))
    stats, n = [], 0
    while True:
        ok, fr = cap.read()
        if not ok or (a.max_frames and n >= a.max_frames):
            break
        if fr.shape[1] != W or fr.shape[0] != H:
            fr = cv2.resize(fr, (W, H))
        canvas = np.zeros_like(fr)
        boxes, bs = det(fr)
        rec = {"frame": n, "people": int(len(boxes))}
        if len(boxes):
            i = int(np.argmax((boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])))  # largest person only
            k, s = pose(fr, boxes[i])
            bk, bsc = coco_body_to_openpose(k, s)
            face = None if a.no_face else (k[23:91], s[23:91])
            draw_pose(canvas, bk, bsc, (k[91:112], s[91:112]), (k[112:133], s[112:133]), face)
            rec.update(body=float(np.mean(bsc >= THR)), hands=float(np.mean(s[91:133] >= THR)), face=float(np.mean(s[23:91] >= THR)))
        stats.append(rec)
        vw.write(canvas[..., ::-1].copy())  # drawn in RGB, written BGR
        n += 1
    vw.release()
    with open(os.path.splitext(a.out)[0] + ".json", "w") as f:
        json.dump({"driver": os.path.basename(a.driver), "fps": fps, "size": [W, H], "frames": stats}, f)
    found = sum(1 for r in stats if r["people"])
    print(f"wrote {a.out}: {n} frames, person found in {found}")
    return 0 if found else 1


if __name__ == "__main__":
    sys.exit(main())
