"""media.mux makes a clip exactly as long as its audio (O18: a 2.4 s voice on a 2 s clip came out 44 s)."""
import pytest

from opensoul import lipsync as L
from opensoul import media
from opensoul.speak import get_lipsync

pytestmark = pytest.mark.skipif(not media.ffmpeg_bin(), reason="no ffmpeg")


@pytest.fixture()
def clip(tmp_path):
    from PIL import Image

    Image.new("RGB", (64, 64), "gray").save(tmp_path / "s.png")
    return media.still_to_clip(tmp_path / "s.png", tmp_path / "c.mp4", seconds=2.0, width=64, height=64)


@pytest.mark.parametrize("secs", [0.8, 2.0, 2.4, 5.3])
def test_mux_length_follows_the_audio(tmp_path, clip, secs):
    wav = L.placeholder_voice(tmp_path / f"v{secs}.wav", secs)
    out = media.mux(clip, wav, tmp_path / f"o{secs}.mp4")
    assert media.duration(out) == pytest.approx(secs, abs=0.12)


def test_speak_dry_lipsync_backends_use_the_fixed_mux(monkeypatch, tmp_path, clip):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    wav = L.placeholder_voice(tmp_path / "v.wav", 2.4)
    for name in ("latentsync", "ltx_av"):
        out = get_lipsync(name, dry_run=True).sync(clip, wav, tmp_path / f"{name}.mp4")
        assert media.duration(out) == pytest.approx(2.4, abs=0.12), name
