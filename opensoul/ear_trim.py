"""Shorten long sideways elf-ear tips in character-sheet views (local, no model, a few hundred ms per view).

Why: image-edit models keep drawing long horizontal ear spikes on a plain studio background, whatever the prompt
says (Lumi v3 to v3.2, Oct 2026). This finds the ear tips and trims them to a short point close to the head.

- Front, back and three-quarter views: skin-coloured patches in the head band that sit against the plain background
  are ear spikes. Keep the inner ``keep`` part (next to the head) and inpaint the rest from the background.
- Profile close-ups (``close_side``): the ear lies over the hair, behind the face. Keep the part near the lowest
  point (where the ear joins the head) and refill the rest along the hair strands.
Always look at the result: it is tuned for one adult character on a plain light background.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


SUBTLE_EARS_RE = re.compile(r"\b(short|subtle|small|modest)\b[^.;]{0,40}\b(elf|elven|pointed)\b[^.;]{0,20}\bears?\b", re.I)
# What worked in scenes (Lumi d2, 6 of 6 frames): describe the hair covering the ears, not the ears themselves.
HIDDEN_EARS_PHRASE = "The hair covers most of the ears; only a small, short pointed ear tip peeks out, close to the head."


def wants_subtle_ears(text: str) -> bool:
    """True when a description asks for short/subtle pointed ears (e.g. Lumi's prompt lock)."""
    return bool(SUBTLE_EARS_RE.search(text or ""))


@dataclass
class TrimResult:
    view: str
    ears: list[dict] = field(default_factory=list)  # bbox + area of each trimmed ear
    removed_px: int = 0

    @property
    def changed(self) -> bool:
        return self.removed_px > 0


def _skin(im: np.ndarray, rb: int) -> np.ndarray:
    r, b = im[..., 2].astype(int), im[..., 0].astype(int)
    v = im.max(axis=2).astype(int)
    return ((r - b > rb) & (v > 90)).astype(np.uint8)


def _against_bg(im, keep, ymax, rb, min_area):
    import cv2

    h, w = im.shape[:2]
    hsv = cv2.cvtColor(im, cv2.COLOR_BGR2HSV).astype(int)
    bg = ((hsv[..., 1] < 30) & (hsv[..., 2] > 150)).astype(np.uint8)
    skin = cv2.morphologyEx(_skin(im, rb), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(skin, 8)
    bgd = cv2.dilate(bg, np.ones((7, 7), np.uint8))
    rm = np.zeros((h, w), np.uint8)
    ears = []
    for i in range(1, n):
        x, y, bw, bh, a = (int(t) for t in st[i])
        if a < min_area or a > 0.02 * h * w or y > ymax * h:
            continue
        comp = lab == i
        touch = float((bgd[comp] > 0).mean())
        if touch < 0.25:  # an ear spike sits against the plain background; faces and hands don't
            continue
        xs = np.where(comp.any(0))[0]
        span = xs.max() - xs.min() + 1
        # The thin apex drops out of the opened mask, so the cut also takes any skin-tinted pixel just past it.
        loose = np.zeros_like(comp)
        y0, y1 = max(0, y - 6), min(h, y + bh + 6)
        loose[y0:y1, max(0, x - 14):min(w, x + bw + 14)] = True
        loose &= (im[..., 2].astype(int) - im[..., 0].astype(int) > rb) | comp
        if x + bw / 2 < w / 2:  # left ear points left: keep its right (inner) part
            m = loose & (np.arange(w)[None, :] < xs.max() - int(keep * span))
        else:
            m = loose & (np.arange(w)[None, :] > xs.min() + int(keep * span))
        rm |= m.astype(np.uint8)
        ears.append({"bbox": [x, y, bw, bh], "area": a, "bg_touch": round(touch, 2)})
    rm = cv2.dilate(rm, np.ones((5, 5), np.uint8))
    return cv2.inpaint(im, rm, 7, cv2.INPAINT_TELEA), rm, ears


def _strand_fill(im, mask):
    """Refill masked pixels from the nearest clean pixels above and below (hair strands run mostly vertically)."""
    import cv2

    src = im.astype(np.float32)
    out = src.copy()
    h = mask.shape[0]
    for x in np.nonzero(mask.any(0))[0]:
        col = mask[:, x]
        for y in np.nonzero(col)[0]:
            a = y
            while a > 0 and col[a]:
                a -= 1
            b = y
            while b < h - 1 and col[b]:
                b += 1
            t = (y - a) / max(b - a, 1)
            out[y, x] = (1 - t) * src[a, x] + t * src[b, x]
    m3 = mask[..., None]
    out = cv2.GaussianBlur(out, (1, 5), 0) * m3 + out * (~m3)
    return out.astype(np.uint8)


def _profile(im, keep, ymax):
    import cv2

    h, w = im.shape[:2]
    hsv = cv2.cvtColor(im, cv2.COLOR_BGR2HSV).astype(int)
    hh, ss, vv = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    skin = (((hh <= 22) | (hh >= 170)) & (ss > 55) & (vv > 90)).astype(np.uint8)
    skin = cv2.morphologyEx(skin, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, lab, st, cen = cv2.connectedComponentsWithStats(skin, 8)
    if n < 2:
        return im, np.zeros((h, w), np.uint8), []
    # The face is the biggest skin patch in the head band (the neck, hands and a beige cardigan sit lower).
    top = [i for i in range(1, n) if st[i][1] < ymax * h]
    if not top:
        return im, np.zeros((h, w), np.uint8), []
    face = max(top, key=lambda i: st[i][4])
    fx = cen[face][0]
    hair = (ss < 30) & (vv > 60) & (vv < 200)  # grey/silver hair, darker than the light background
    hair[int(ymax * h):] = False
    hx = float(np.nonzero(hair)[1].mean()) if hair.any() else w / 2
    left_facing = fx < hx  # the ear sits behind the face, on the hair side
    rm = np.zeros((h, w), bool)
    ears = []
    for i in range(1, n):
        x, y, bw, bh, a = (int(t) for t in st[i])
        if i == face or a < 150 or y > ymax * h or a > 0.01 * h * w:
            continue
        if (left_facing and cen[i][0] < fx + 0.08 * w) or (not left_facing and cen[i][0] > fx - 0.08 * w):
            continue
        ys, xs = np.nonzero(lab == i)
        bx, by = xs[np.argmax(ys)], ys.max()  # lowest point = where the ear joins the head
        d = np.hypot(xs - bx, ys - by)
        far = d > keep * d.max()
        rm[ys[far], xs[far]] = True
        ears.append({"bbox": [x, y, bw, bh], "area": a})
    rm = cv2.dilate(rm.astype(np.uint8), np.ones((5, 5), np.uint8))
    rm = cv2.dilate(rm, np.ones((7, 7), np.uint8)) > 0
    return _strand_fill(im, rm), rm.astype(np.uint8), ears


def trim_array(im: np.ndarray, view: str) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    """BGR image in, (trimmed image, removed-pixel mask, ears) out. ``view`` is a sheet view id."""
    if view == "close_side":
        return _profile(im, keep=0.58, ymax=0.45)
    if view.startswith("full"):
        return _against_bg(im, keep=0.3 if view == "full_back" else 0.35, ymax=0.2, rb=12, min_area=25)
    return _against_bg(im, keep=0.35, ymax=0.6, rb=12, min_area=80)


def trim_view(path: str | Path, view: str, out: str | Path | None = None, debug: str | Path | None = None) -> TrimResult:
    """Trim the ear tips of one sheet view. Writes ``out`` (default: overwrite ``path``)."""
    import cv2

    im = cv2.imread(str(path))
    if im is None:
        raise FileNotFoundError(path)
    res, mask, ears = trim_array(im, view)
    cv2.imwrite(str(out or path), res)
    if debug:
        d = im.copy()
        d[mask > 0] = (255, 0, 255)
        cv2.imwrite(str(debug), d)
    return TrimResult(view=view, ears=ears, removed_px=int((mask > 0).sum()))
