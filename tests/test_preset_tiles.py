"""Preset tiles: every committed thumbnail is a small 9:16 loop; orbit tiles stay on the UI's animated placeholder."""
import glob
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from release_assets import TILE_CLIP, requires_demo_asset

ROOT = Path(__file__).resolve().parents[1]


def _presets():
    return [json.loads(Path(f).read_text()) for f in sorted(glob.glob(str(ROOT / "presets" / "*" / "*.json")))
            if Path(f).parent.name in ("camera", "effects")]


@requires_demo_asset(TILE_CLIP)
def test_tiles_exist_except_orbits():
    have = {p["id"]: (ROOT / p["thumbnail"].removeprefix("/")).is_file() for p in _presets()}
    assert not have["orbit"] and not have["orbit_freeze"]
    assert all(v for k, v in have.items() if k not in ("orbit", "orbit_freeze")), have


@pytest.mark.skipif(not shutil.which("ffprobe"), reason="ffprobe not installed")
def test_tiles_are_small_muted_9x16_loops():
    for p in _presets():
        f = ROOT / p["thumbnail"].removeprefix("/")
        if not f.is_file():
            continue
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height", "-of", "json", str(f)],
                             capture_output=True, text=True).stdout
        streams = json.loads(out)["streams"]
        assert [s["codec_type"] for s in streams] == ["video"], f
        assert (streams[0]["width"], streams[0]["height"]) == (360, 630), f
        assert f.stat().st_size < 600_000, f
