"""CPU-only consistency scoring tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageEnhance

from demo_character import DEMO_PACK, DEMO_SHEET
from opensoul.consistency import (
    cosine_similarity,
    filter_candidates,
    patch_embedding,
    score_consistency,
    sheet_tiles,
)
from release_assets import LUMI_REFS, requires_demo_asset

ROOT = Path(__file__).resolve().parents[1]
PIXEL = ROOT / "assets" / "example_character" / "pixel_reference.png"
DEMO_SHEET_IMG = DEMO_SHEET  # the demo character's sheet picture (tests/demo_character.py)


def _solid(color, size=(224, 224)) -> Image.Image:
    return Image.new("RGB", size, color)


def test_same_image_near_one():
    emb = patch_embedding(PIXEL)
    assert emb.shape[0] > 0
    assert abs(cosine_similarity(emb, emb) - 1.0) < 1e-5


def test_identical_files_pass():
    r = score_consistency(PIXEL, [PIXEL], threshold=0.99, mode="mean")
    assert r.passed
    assert r.score >= 0.99


def test_unrelated_colors_reject():
    blue = _solid((20, 80, 200))
    red = _solid((220, 30, 30))
    r = score_consistency(red, [blue], threshold=0.78, mode="mean")
    assert not r.passed


def test_near_duplicate_accepts():
    im = Image.open(PIXEL).convert("RGB")
    arr = np.asarray(im).astype(np.float32)
    rng = np.random.RandomState(0)
    noisy = np.clip(arr + rng.randn(*arr.shape) * 3.0, 0, 255).astype(np.uint8)
    bright = np.clip(arr * 1.08, 0, 255).astype(np.uint8)
    r_noise = score_consistency(Image.fromarray(noisy), [PIXEL], threshold=0.90, mode="mean")
    r_bright = score_consistency(Image.fromarray(bright), [PIXEL], threshold=0.90, mode="mean")
    assert r_noise.passed, r_noise.detail
    assert r_bright.passed, r_bright.detail


def test_demo_character_vs_pixel_rejects_mean():
    if not DEMO_SHEET_IMG.is_file():
        pytest.skip("demo sheet missing")
    r = score_consistency(PIXEL, [DEMO_SHEET_IMG], threshold=0.78, mode="mean")
    assert not r.passed, r.detail


@requires_demo_asset(*LUMI_REFS)
def test_sheet_max_dual_gate_rejects_wrong_character():
    if not DEMO_PACK.is_dir():
        pytest.skip("demo pack missing")
    from opensoul.character_pack import CharacterPack

    pack = CharacterPack.load(DEMO_PACK)
    r = score_consistency(PIXEL, pack.ref_images, mode="sheet_max")
    assert not r.passed, r.detail
    assert r.mean_score is not None
    assert r.mean_score < 0.75 or r.score < 0.70


def test_sheet_tiles_nonempty():
    tiles = sheet_tiles(PIXEL, rows=2, cols=2)
    assert len(tiles) >= 5  # full + 4


def test_filter_candidates():
    good = PIXEL
    bad = _solid((10, 10, 10))
    kept = filter_candidates([good, bad], [PIXEL], threshold=0.78, mode="mean")
    assert len(kept) == 1


def test_mean_of_two_refs():
    im = Image.open(PIXEL).convert("RGB")
    draw = ImageDraw.Draw(im)
    draw.rectangle([10, 10, 40, 40], fill=(255, 0, 0))
    r = score_consistency(PIXEL, [PIXEL, im], threshold=0.70, mode="mean")
    assert r.score > 0.70


@requires_demo_asset(*LUMI_REFS)
def test_demo_pack_self_passes():
    if not DEMO_PACK.is_dir():
        pytest.skip("demo pack missing")
    from opensoul.character_pack import CharacterPack

    pack = CharacterPack.load(DEMO_PACK)
    r = score_consistency(pack.ref_images[0], pack.ref_images, mode="mean", threshold=0.78)
    assert r.passed, r.detail
