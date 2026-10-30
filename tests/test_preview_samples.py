"""P0-01: Preview mode ("Try it now") shows real sample pictures and clips, never only gray cards, and its export
is a real short sample video. The samples are ours, documented and small."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opensoul import preview_samples as P

ROOT = Path(__file__).resolve().parents[1]
FF = shutil.which("ffmpeg")


def test_every_sample_file_exists_and_is_documented():
    cfg = P.load()
    assert len(P.clips(cfg)) == len(cfg["clips"]) >= 3
    prov = (ROOT / "assets/demo_preview/PROVENANCE.md").read_text(encoding="utf-8")
    for f in (ROOT / "assets/demo_preview").iterdir():
        if f.suffix in (".mp4", ".jpg"):
            assert f"`{f.name}`" in prov, f.name
    for s in cfg["stills"]:
        assert (ROOT / s).is_file(), s
    for word in ("text only", "no closed", "adult", "AI-generated"):
        assert word.lower() in prov.lower(), word


def test_the_sample_pack_stays_small():
    total = sum(f.stat().st_size for d in ("assets/demo_preview", "assets/juno_pell") for f in (ROOT / d).iterdir())
    assert total < 4_000_000, total
    for c in P.clips():
        assert c["video_path"].stat().st_size < 600_000


def test_samples_are_not_from_the_closed_generator_lineage():
    from opensoul.export_guard import blocked

    for c in P.clips():
        assert not blocked(c["video"]) and not blocked(c["poster"])
    assert "demo_audited" not in json.dumps(P.load())


@pytest.fixture
def client(monkeypatch, tmp_path):
    import app.server as server

    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    monkeypatch.setattr(server, "DATA", tmp_path)
    return TestClient(server.app)


def test_start_card_shows_sample_clips(client):
    fr = client.get("/api/bootstrap").json()["first_run"]
    assert fr["mode"] == "samples" and len(fr["items"]) == 3
    for it in fr["items"]:
        assert it["video_url"].startswith("/assets/demo_preview/") and it["label"] == "Preview sample from a real render"
        assert client.get(it["video_url"]).status_code == 200


def _mean_and_spread(jpg: Path) -> tuple[float, float]:
    from PIL import Image, ImageStat

    st = ImageStat.Stat(Image.open(jpg).convert("L"))
    return st.mean[0], st.stddev[0]


@pytest.mark.skipif(not FF, reason="needs ffmpeg")
def test_preview_takes_are_samples_and_the_export_is_a_real_video(client, tmp_path):
    p = client.post("/api/storyboard/projects", json={"title": "Sample run"}).json()
    for beat in ("One", "Two", "Three"):
        p = client.post(f"/api/storyboard/projects/{p['id']}/shots", json={"beat": beat, "prompt": "x"}).json()
    files = []
    for s in p["shots"]:
        r = client.post(f"/api/storyboard/projects/{p['id']}/shots/{s['id']}/regenerate", json={})
        assert r.status_code == 200, r.text
        sh = next(x for x in r.json()["shots"] if x["id"] == s["id"])
        v = sh["versions"][-1]
        assert v["label"].startswith("Preview sample from a real render") and v["placeholder"] and v["kind"] == "preview"
        assert "sample clip" in v["note"] and v["settings"]["sample"]["video"].startswith("assets/demo_preview/")
        files.append(v["file"])
        assert client.post(f"/api/storyboard/projects/{p['id']}/shots/{s['id']}/keeper", json={"version_id": v["id"]}).status_code == 200
    assert len(set(files)) == 3  # three shots, three different samples
    r = client.post(f"/api/storyboard/projects/{p['id']}/export")
    assert r.status_code == 200, r.text
    out = Path(r.json()["output_path"])
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=width,height",
                            "-of", "json", str(out)], capture_output=True, text=True)
    info = json.loads(probe.stdout)
    assert float(info["format"]["duration"]) > 6
    assert any(st.get("width") == 1280 and st.get("height") == 720 for st in info["streams"])
    frame = tmp_path / "f.jpg"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "1.5", "-i", str(out), "-frames:v", "1", str(frame)], check=True)
    mean, spread = _mean_and_spread(frame)
    assert spread > 25, (mean, spread)  # real picture content; the old gray card had almost none


def test_without_samples_the_stand_in_card_still_works(client, monkeypatch):
    monkeypatch.setattr(P, "make_take", lambda *a, **k: None)
    p = client.post("/api/storyboard/projects", json={"title": "No samples"}).json()
    p = client.post(f"/api/storyboard/projects/{p['id']}/shots", json={"beat": "One", "prompt": "x"}).json()
    sid = p["shots"][0]["id"]
    v = client.post(f"/api/storyboard/projects/{p['id']}/shots/{sid}/regenerate", json={}).json()["shots"][0]["versions"][-1]
    assert "stand-in" in v["label"] and v["placeholder"]
