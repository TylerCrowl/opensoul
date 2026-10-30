"""OS-024: spoken lines and a song together (Export > Add the song; Music export > Keep the spoken lines)."""
import shutil
import subprocess

import pytest

from tests.test_music_api import _client, _song

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")


def _talk_clip(path, secs=2.0, freq=440):
    """A short clip with a loud tone as its own audio (stands in for a spoken line)."""
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c=gray:s=320x180:r=24:d={secs}",
                    "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={secs}", "-shortest", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)], check=True)
    return path


def _streams(path):
    return sorted(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0",
                                  str(path)], capture_output=True, text=True).stdout.split())


def _dur(path):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                 str(path)], capture_output=True, text=True).stdout)


def test_add_song_bed_keeps_length_and_picture(tmp_path):
    from opensoul import media

    v = _talk_clip(tmp_path / "v.mp4", 2.0)
    song = tmp_path / "song.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=6",
                    str(song)], check=True)
    out = media.add_song_bed(v, song, tmp_path / "out.mp4")
    assert _streams(out) == ["audio", "video"] and abs(_dur(out) - _dur(v)) < 0.1


def _setup(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    d = _song(c)
    sid = d["song_id"]
    h = c.post(f"/api/music/songs/{sid}/handoff", json={"character": "Kestrel"}).json()
    pid = h["project_id"]
    quiet = next(s for s in h["shots"] if not s["lipsync"])
    import app.storyboard_api as A

    st = A._store()
    clip = _talk_clip(tmp_path / "talk.mp4", 2.0)

    def fn(p):
        p.shot(quiet["id"]).line = "We are late again."
    st._edit(pid, fn)
    v = st.add_version(pid, quiet["id"], kind="render", status="ready", file=str(clip), label="Final")
    st.set_keeper(pid, quiet["id"], v.id)
    return c, sid, pid


def test_music_export_keeps_spoken_lines(monkeypatch, tmp_path):
    c, sid, pid = _setup(monkeypatch, tmp_path)
    e = c.post(f"/api/music/songs/{sid}/export", json={"project_id": pid, "keep_lines": True})
    assert e.status_code == 200, e.text
    assert "Kept the spoken lines of 1 shot" in e.json()["note"]
    import app.server as server

    out = server.file_of_url(e.json()["output_url"])
    assert _streams(out) == ["audio", "video"]
    off = c.post(f"/api/music/songs/{sid}/export", json={"project_id": pid}).json()
    assert "spoken lines" not in off["note"]


def test_story_export_adds_the_song(monkeypatch, tmp_path):
    c, sid, pid = _setup(monkeypatch, tmp_path)
    songs = c.get(f"/api/storyboard/projects/{pid}/songs").json()["songs"]
    assert songs[0]["song_id"] == sid and songs[0]["for_this_story"]
    r = c.post(f"/api/storyboard/projects/{pid}/export", json={"song": sid, "song_level": 0.4})
    assert r.status_code == 200, r.text
    j = r.json()
    assert "plays under the story" in j["note"] and j["plan"]["song"]["id"] == sid
    assert j["output_path"].endswith("_with_song.mp4") and _streams(j["output_path"]) == ["audio", "video"]
    assert c.post(f"/api/storyboard/projects/{pid}/export", json={"song": "0123456789"}).status_code == 404
    plain = c.post(f"/api/storyboard/projects/{pid}/export").json()
    assert "song" not in plain["plan"]


def test_music_export_vertical_cut(monkeypatch, tmp_path):  # OS-040
    c, sid, pid = _setup(monkeypatch, tmp_path)
    e = c.post(f"/api/music/songs/{sid}/export", json={"project_id": pid, "vertical": True})
    assert e.status_code == 200, e.text
    d = e.json()
    assert d["aspect"] == "9:16" and "_vertical" in d["output_url"]
    import app.server as server

    out = server.file_of_url(d["output_url"])
    wh = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                         "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout.strip()
    assert wh == "720,1280"
