"""The share caption (with #OpenSoul) is only shown for the user to paste. It is never written into the
exported media's metadata (no ffmpeg -metadata, no PNG text chunk, no EXIF) on any export or share path."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
WRITERS = re.compile(r"""["']-metadata(:s:[av]:?\d*)?["']|PngInfo|add_itxt|add_text\(|exif\s*=|piexif|mutagen""")


def _srv():
    import app.server as server

    return server


def test_no_code_path_writes_metadata_into_exports():
    hits = [f"{p.relative_to(ROOT)}:{i}" for d in ("app", "opensoul", "custom_nodes/opensoul_nodes")
            for p in sorted((ROOT / d).rglob("*.py")) for i, line in enumerate(p.read_text().splitlines(), 1)
            if WRITERS.search(line)]
    assert hits == [], hits


def test_shared_mp4_carries_no_caption_or_hashtag(monkeypatch, tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    d = TestClient(server.app).post("/api/share", json={"title": "Orbit", "name": "Pixel",
                                                        "video_url": "/assets/example_character/pixel_reference.png"}).json()
    assert "#OpenSoul" in d["caption"] and d["mp4_url"], d
    mp4 = _srv().file_of_url(d["mp4_url"])
    raw = mp4.read_bytes()
    for s in (b"Made with OpenSoul", d["caption"].encode()):
        assert s not in raw
    if shutil.which("ffprobe"):
        tags = json.loads(subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams",
                                          str(mp4)], capture_output=True, text=True).stdout or "{}")
        assert "Higgsfield" not in json.dumps(tags)
