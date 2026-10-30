"""CLI smoke tests."""

from __future__ import annotations

import json
from pathlib import Path

from opensoul.cli import main

ROOT = Path(__file__).resolve().parents[1]
PIXEL = ROOT / "assets" / "example_character" / "pixel_reference.png"


def test_cli_score_pass(capsys):
    code = main(["score", str(PIXEL), "--ref", str(PIXEL), "--mode", "mean", "--threshold", "0.9"])
    assert code == 0
    assert "PASS" in capsys.readouterr().out


def test_cli_score_json(capsys):
    code = main(["score", str(PIXEL), "--ref", str(PIXEL), "--mode", "mean", "--json"])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["passed"] is True
    assert data["score"] >= 0.99


def test_cli_info(capsys):
    assert main(["info"]) == 0
    assert "version" in capsys.readouterr().out


def test_cli_pack_init(tmp_path, capsys):
    out = tmp_path / "pack"
    assert main([
        "pack-init",
        "--name", "Pixel",
        "--ref", str(PIXEL),
        "--out", str(out),
        "--prompt-lock", "cute robot",
    ]) == 0
    assert (out / "pack.json").is_file()
