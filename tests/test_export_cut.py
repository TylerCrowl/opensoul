"""OS-061: Export cuts each shot to its planned Length, from its Start in the keeper; the Export tab shows the cut."""
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opensoul import storyboard as sb
from opensoul.media import duration, ffmpeg_bin

ROOT = Path(__file__).resolve().parents[1]
needs_ffmpeg = pytest.mark.skipif(ffmpeg_bin() is None, reason="needs ffmpeg")


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    return TestClient(server.app)


def _clip(dest: Path, secs: float) -> Path:
    subprocess.run([ffmpeg_bin(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=s=320x180:r=24:d={secs}",
                    "-f", "lavfi", "-i", f"sine=f=440:d={secs}", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(dest)], check=True)
    return dest


def _still(dest: Path) -> Path:
    from PIL import Image

    Image.new("RGB", (320, 180), "#335").save(dest)
    return dest


def test_plan_items_carry_length_and_start(tmp_path):
    st = sb.Store(tmp_path / "projects")
    p = st.create_project("Cut", "")
    a = st.add_shot(p.id, "A", characters=[])
    st.add_version(p.id, a.id, file="a.mp4")
    st.update_shot(p.id, a.id, seconds=4, trim_start=1.5)
    it = sb.export_plan(st.load(p.id))["items"][0]
    assert it["seconds"] == 4.0 and it["trim_start"] == 1.5 and it["talking"] is False


def test_cut_seconds_rules():
    assert sb.cut_seconds({"seconds": 4, "source_kind": "video"}, 7.04) == 4
    assert sb.cut_seconds({"seconds": 0, "source_kind": "video", "trim_start": 1}, 7.0) == 6.0
    assert sb.cut_seconds({"seconds": 0, "source_kind": "still"}) == 3.0
    assert sb.cut_seconds({"seconds": 5, "source_kind": "still"}) == 5


def test_trim_start_is_checked(tmp_path):
    st = sb.Store(tmp_path / "projects")
    p = st.create_project("Cut2", "")
    a = st.add_shot(p.id, "A", characters=[])
    with pytest.raises(sb.StoryError):
        st.update_shot(p.id, a.id, trim_start=-1)
    with pytest.raises(sb.StoryError):
        st.update_shot(p.id, a.id, trim_start="soon")
    assert st.update_shot(p.id, a.id, trim_start="2.25").trim_start == 2.2


@needs_ffmpeg
def test_render_export_cuts_to_length_from_the_start(tmp_path):
    long_clip = _clip(tmp_path / "long.mp4", 7.0)
    short_clip = _clip(tmp_path / "short.mp4", 2.0)
    still = _still(tmp_path / "card.png")
    plan = {"title": "T", "aspect": "16:9", "items": [
        {"index": 1, "beat": "a", "source": str(long_clip), "source_kind": "video", "seconds": 3.0, "trim_start": 2.0},
        {"index": 2, "beat": "b", "source": str(short_clip), "source_kind": "video", "seconds": 4.0},  # holds the end
        {"index": 3, "beat": "c", "source": str(still), "source_kind": "still", "seconds": 5.0},
        {"index": 4, "beat": "d", "source": str(long_clip), "source_kind": "video", "seconds": 0},  # whole take
    ]}
    out = sb.render_export(plan, tmp_path / "work")
    cuts = [it["cut_seconds"] for it in plan["items"]]
    assert abs(cuts[0] - 3.0) < 0.15 and abs(cuts[1] - 4.0) < 0.15 and abs(cuts[2] - 5.0) < 0.15
    assert abs(cuts[3] - 7.0) < 0.2
    assert abs(duration(out) - 19.0) < 0.5


@needs_ffmpeg
def test_export_api_reports_the_cut_and_project_json_has_take_length(client, tmp_path):
    p = client.post("/api/storyboard/projects", json={"title": "Cut API"}).json()
    pid = p["id"]
    p = client.post(f"/api/storyboard/projects/{pid}/shots", json={"beat": "One", "characters": []}).json()
    sid = p["shots"][0]["id"]
    clip = _clip(tmp_path / "take.mp4", 6.0)
    st = sb.Store(tmp_path / "projects")
    st.add_version(pid, sid, file=str(clip), poster=None)
    st.set_keeper(pid, sid, "v1")
    r = client.patch(f"/api/storyboard/projects/{pid}/shots/{sid}", json={"seconds": 2.5, "trim_start": 1})
    assert r.status_code == 200, r.text
    k = r.json()["shots"][0]["versions"][0]
    assert abs(k["take_seconds"] - 6.0) < 0.2
    j = client.post(f"/api/storyboard/projects/{pid}/export").json()
    assert abs(j["plan"]["cut_total"] - 2.5) < 0.2
    assert "The cut is" in j["note"]


def test_export_tab_has_start_and_length_fields():
    js = (ROOT / "app/web/static/storyboard.js").read_text()
    assert "data-trim=" in js and "data-len=" in js and "Length of the cut" in js
    assert 'id="sbExportTotal"' in (ROOT / "app/web/index.html").read_text()


# ---------------------------------------------------------------- OS-065: no keeper = black of the shot's Length
def test_fill_gaps_turns_a_missing_keeper_into_black(tmp_path):
    st = sb.Store(tmp_path / "projects")
    p = st.create_project("Gaps", "")
    a = st.add_shot(p.id, "A", characters=[])
    b = st.add_shot(p.id, "End card", characters=[], seconds=4)
    c = st.add_shot(p.id, "C", characters=[])
    st.add_version(p.id, a.id, file="a.mp4")
    plan = sb.fill_gaps(sb.export_plan(st.load(p.id)))
    assert [it["source_kind"] for it in plan["items"]] == ["video", "black", "black"]
    assert [it["seconds"] for it in plan["items"][1:]] == [4.0, 3.0]
    assert plan["skipped"] == [] and [x["beat"] for x in plan["filled"]] == ["End card", "C"]
    assert b.id and c.id


@needs_ffmpeg
def test_export_api_fills_gaps_by_default_and_can_skip(client, tmp_path):
    p = client.post("/api/storyboard/projects", json={"title": "Gap API"}).json()
    pid = p["id"]
    for beat in ("One", "Coming soon"):
        p = client.post(f"/api/storyboard/projects/{pid}/shots", json={"beat": beat, "characters": [], "seconds": 2}).json()
    s1 = p["shots"][0]["id"]
    st = sb.Store(tmp_path / "projects")
    st.add_version(pid, s1, file=str(_clip(tmp_path / "t.mp4", 2.0)))
    st.set_keeper(pid, s1, "v1")
    j = client.post(f"/api/storyboard/projects/{pid}/export", json={}).json()
    assert [it["source_kind"] for it in j["plan"]["items"]] == ["video", "black"]
    assert abs(j["plan"]["cut_total"] - 4.0) < 0.3 and "black" in j["note"]
    j = client.post(f"/api/storyboard/projects/{pid}/export", json={"fill_gaps": False}).json()
    assert len(j["plan"]["items"]) == 1 and j["plan"]["skipped"][0]["beat"] == "Coming soon"


def test_export_tab_has_the_black_fill_switch():
    assert 'id="sbFillGaps"' in (ROOT / "app/web/index.html").read_text()
    assert "fill_gaps: fillOn()" in (ROOT / "app/web/static/storyboard.js").read_text()


# ---------------------------------------------------------------- OS-072: room tone under talking takes
def _silent_tail_clip(dest: Path) -> Path:
    """1 s of tone then 3 s of digital silence (a talking take: the line, then nothing)."""
    subprocess.run([ffmpeg_bin(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=s=320x180:r=24:d=4",
                    "-f", "lavfi", "-i", "sine=f=300:d=1", "-af", "apad=whole_dur=4", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", "4", str(dest)], check=True)
    return dest


def _tail_db(seg: Path) -> float:
    r = subprocess.run([ffmpeg_bin(), "-hide_banner", "-ss", "2", "-i", str(seg), "-af", "volumedetect", "-f", "null", "-"],
                       capture_output=True, text=True)
    import re

    m = re.search(r"mean_volume:\s*(-?[\d.]+|-inf) dB", r.stderr)
    return float(m[1]) if m and m[1] != "-inf" else -200.0


@needs_ffmpeg
def test_talking_take_gets_room_tone_in_its_silence(tmp_path):
    clip = _silent_tail_clip(tmp_path / "talk.mp4")
    plan = {"title": "Tone", "aspect": "16:9", "items": [
        {"index": 1, "beat": "talk", "source": str(clip), "source_kind": "video", "seconds": 4.0, "talking": True},
        {"index": 2, "beat": "quiet", "source": str(clip), "source_kind": "video", "seconds": 4.0, "talking": False}]}
    sb.render_export(plan, tmp_path / "w")
    talk, quiet = (Path(it["segment"]) for it in plan["items"])
    assert -60 < _tail_db(talk) < -30   # air, not digital silence and not hiss
    assert _tail_db(quiet) < -80        # a picture-only take keeps its own sound (here: none)
    assert abs(duration(talk) - 4.0) < 0.15
