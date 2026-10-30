"""Pipeline dry-run tests (no ComfyUI required)."""

from __future__ import annotations

import os
from pathlib import Path

from opensoul.pipeline import build_character_pack, generate_stills, generate_talking_video

ROOT = Path(__file__).resolve().parents[1]
PIXEL = ROOT / "assets" / "example_character" / "pixel_reference.png"


def test_build_and_stills_dry_run(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    pack_dir = tmp_path / "pack"
    build_character_pack("Pixel", [PIXEL], "cute robot", pack_dir, seed=1)
    assert (pack_dir / "pack.json").is_file()
    kept = generate_stills(
        pack_dir,
        "in a sunny field",
        n=1,
        out_dir=tmp_path / "stills",
        threshold=0.85,
    )
    assert len(kept) == 1
    assert kept[0][1].passed


def test_video_dry_run(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    out = generate_talking_video(tmp_path, PIXEL, "Hello", out_dir=tmp_path / "vid")
    assert out.is_file()
    assert "DRY RUN" in out.read_text(encoding="utf-8")
