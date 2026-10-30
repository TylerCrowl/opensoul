"""Automatic character-consistency scoring (CPU-runnable).

Primary path: lightweight patch embedding (no model download).
Sheet-aware scoring tiles multi-panel refs and takes max cosine, then
**dual-gates** with mean-ref similarity so a lucky tile cannot accept a
wrong character.

Optional CLIP backend: ``opensoul[clip]``.
InsightFace is NOT the default (non-commercial model packs).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
from PIL import Image

Array = np.ndarray

DEFAULT_THRESHOLD = 0.78
DEFAULT_SHEET_THRESHOLD = 0.70
DEFAULT_MEAN_GATE = 0.75  # secondary gate when mode=sheet_max


@dataclass(frozen=True)
class ConsistencyResult:
    score: float
    passed: bool
    threshold: float
    backend: str
    detail: str = ""
    best_ref_index: int = 0
    mode: str = "mean"
    mean_score: float | None = None

    def to_dict(self) -> dict:
        return {
            "score": float(self.score),
            "passed": bool(self.passed),
            "threshold": float(self.threshold),
            "backend": self.backend,
            "detail": self.detail,
            "best_ref_index": int(self.best_ref_index),
            "mode": self.mode,
            "mean_score": None if self.mean_score is None else float(self.mean_score),
        }


def _as_pil(image: str | Path | Image.Image) -> Image.Image:
    if isinstance(image, Image.Image):
        return image.convert("RGB")
    return Image.open(image).convert("RGB")


def _load_rgb(path: str | Path | Image.Image, size: int = 224) -> Image.Image:
    return _as_pil(path).resize((size, size), Image.Resampling.BICUBIC)


def patch_embedding(image: str | Path | Image.Image, grid: int = 8) -> Array:
    """Mean-centered patch colors + luma/gradient histograms."""
    im = _load_rgb(image)
    arr = np.asarray(im, dtype=np.float32) / 255.0
    arr_n = arr - arr.mean(axis=(0, 1), keepdims=True)
    h, w, _ = arr.shape
    gh, gw = h // grid, w // grid
    patches: list[Array] = []
    for i in range(grid):
        for j in range(grid):
            tile = arr_n[i * gh : (i + 1) * gh, j * gw : (j + 1) * gw]
            patches.append(tile.mean(axis=(0, 1)))
    color = np.concatenate(patches)

    luma = 0.2126 * arr_n[..., 0] + 0.7152 * arr_n[..., 1] + 0.0722 * arr_n[..., 2]
    hist, _ = np.histogram(luma, bins=32, range=(-0.5, 0.5), density=True)

    gy = np.abs(np.diff(luma, axis=0, prepend=luma[:1]))
    gx = np.abs(np.diff(luma, axis=1, prepend=luma[:, :1]))
    gmag = np.sqrt(gx * gx + gy * gy)
    ghist, _ = np.histogram(gmag, bins=24, range=(0.0, 1.0), density=True)

    vec = np.concatenate([color, hist.astype(np.float32) * 0.25, ghist.astype(np.float32) * 0.4])
    return _l2_normalize(vec)


def _l2_normalize(v: Array) -> Array:
    n = float(np.linalg.norm(v) + 1e-12)
    return (v / n).astype(np.float32)


def cosine_similarity(a: Array, b: Array) -> float:
    return float(np.dot(_l2_normalize(a), _l2_normalize(b)))


def sheet_tiles(
    image: str | Path | Image.Image,
    rows: int = 2,
    cols: int = 3,
    include_full: bool = True,
) -> list[Image.Image]:
    im = _as_pil(image)
    w, h = im.size
    tw, th = w // cols, h // rows
    tiles: list[Image.Image] = []
    if include_full:
        tiles.append(im)
    for r in range(rows):
        for c in range(cols):
            x0, y0 = c * tw, r * th
            x1 = w if c == cols - 1 else (c + 1) * tw
            y1 = h if r == rows - 1 else (r + 1) * th
            if x1 - x0 < 16 or y1 - y0 < 16:
                continue
            tiles.append(im.crop((x0, y0, x1, y1)))
    return tiles


def mean_reference_embedding(
    references: Sequence[str | Path | Image.Image],
    backend: str = "patch",
) -> Array:
    if not references:
        raise ValueError("at least one reference image is required")
    embs = [_embed_one(r, backend) for r in references]
    return _l2_normalize(np.mean(np.stack(embs, axis=0), axis=0))


def _embed_one(image: str | Path | Image.Image, backend: str) -> Array:
    if backend == "patch":
        return patch_embedding(image)
    if backend == "clip":
        return _clip_embedding(image)
    raise ValueError(f"unknown backend: {backend!r} (expected 'patch' or 'clip')")


_CLIP_MODEL = None
_CLIP_PROCESSOR = None


def _clip_embedding(image: str | Path | Image.Image) -> Array:
    global _CLIP_MODEL, _CLIP_PROCESSOR
    try:
        import torch
        from transformers import CLIPModel, CLIPProcessor
    except ImportError as e:  # pragma: no cover
        raise ImportError(
            "CLIP backend requires: pip install 'opensoul[clip]' (transformers + torch)"
        ) from e

    if _CLIP_MODEL is None:
        name = "openai/clip-vit-base-patch32"
        _CLIP_PROCESSOR = CLIPProcessor.from_pretrained(name)
        _CLIP_MODEL = CLIPModel.from_pretrained(name)
        _CLIP_MODEL.eval()

    im = _as_pil(image)
    inputs = _CLIP_PROCESSOR(images=im, return_tensors="pt")
    with torch.no_grad():
        feats = _CLIP_MODEL.get_image_features(**inputs)
    return _l2_normalize(feats[0].cpu().numpy().astype(np.float32))


def score_consistency(
    candidate: str | Path | Image.Image,
    references: Sequence[str | Path | Image.Image],
    *,
    threshold: float | None = None,
    backend: str = "patch",
    mode: str = "sheet_max",
    sheet_rows: int = 2,
    sheet_cols: int = 3,
    mean_gate: float | None = None,
) -> ConsistencyResult:
    """Score candidate vs references.

    ``sheet_max``: max cosine vs tiles; also requires mean-ref cosine >= mean_gate
    so a single lucky tile cannot accept a wrong subject.
    """
    if not references:
        raise ValueError("at least one reference image is required")
    if mode not in {"mean", "sheet_max"}:
        raise ValueError(f"unknown mode: {mode!r}")

    if threshold is None:
        threshold = DEFAULT_SHEET_THRESHOLD if mode == "sheet_max" else DEFAULT_THRESHOLD
    if mean_gate is None:
        mean_gate = DEFAULT_MEAN_GATE

    cand = _embed_one(candidate, backend)
    mean_ref = mean_reference_embedding(references, backend=backend)
    mean_score = cosine_similarity(mean_ref, cand)

    if mode == "mean":
        score = mean_score
        best_i = 0
        passed = score >= threshold
    else:
        best = -1.0
        best_i = 0
        idx = 0
        for ref_img in references:
            for tile in sheet_tiles(ref_img, rows=sheet_rows, cols=sheet_cols):
                s = cosine_similarity(_embed_one(tile, backend), cand)
                if s > best:
                    best, best_i = s, idx
                idx += 1
        score = best
        passed = score >= threshold and mean_score >= mean_gate

    detail = (
        f"cosine={score:.4f} mean={mean_score:.4f} thr={threshold:.4f} "
        f"mean_gate={mean_gate:.4f} mode={mode} ({'accept' if passed else 'reject'})"
    )
    return ConsistencyResult(
        score=score,
        passed=passed,
        threshold=float(threshold),
        backend=backend,
        detail=detail,
        best_ref_index=best_i,
        mode=mode,
        mean_score=mean_score,
    )


def filter_candidates(
    candidates: Iterable[str | Path | Image.Image],
    references: Sequence[str | Path | Image.Image],
    *,
    threshold: float | None = None,
    backend: str = "patch",
    mode: str = "sheet_max",
) -> list[tuple[str | Path | Image.Image, ConsistencyResult]]:
    kept: list[tuple[str | Path | Image.Image, ConsistencyResult]] = []
    for c in candidates:
        r = score_consistency(c, references, threshold=threshold, backend=backend, mode=mode)
        if r.passed:
            kept.append((c, r))
    return kept


def recommend_threshold(backend: str = "patch", mode: str = "sheet_max") -> float:
    if backend == "clip":
        return 0.72
    return DEFAULT_SHEET_THRESHOLD if mode == "sheet_max" else DEFAULT_THRESHOLD
