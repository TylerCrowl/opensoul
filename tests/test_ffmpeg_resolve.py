"""ffmpeg resolution: env override, PATH, imageio-ffmpeg fallback, and duration() without ffprobe."""
import shutil
import subprocess

import pytest

from opensoul import media


@pytest.fixture(autouse=True)
def _clear_cache():
    media.ffmpeg_bin.cache_clear()
    yield
    media.ffmpeg_bin.cache_clear()


def test_env_override_wins(monkeypatch, tmp_path):
    fake = tmp_path / "myffmpeg"
    fake.write_text("#!/bin/sh\n")
    monkeypatch.setenv("OPENSOUL_FFMPEG", str(fake))
    assert media.ffmpeg_bin() == str(fake)
    assert media._resolve(["ffmpeg", "-y"]) == [str(fake), "-y"]


def test_missing_everything_raises_clear_error(monkeypatch):
    monkeypatch.delenv("OPENSOUL_FFMPEG", raising=False)
    monkeypatch.setattr(media.shutil, "which", lambda name: None)
    import builtins

    real_import = builtins.__import__

    def no_imageio(name, *a, **k):
        if name == "imageio_ffmpeg":
            raise ImportError(name)
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_imageio)
    assert media.ffmpeg_bin() is None
    with pytest.raises(media.MediaError, match="imageio-ffmpeg"):
        media._resolve(["ffmpeg", "-y"])


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_duration_without_ffprobe(monkeypatch, tmp_path):
    clip = tmp_path / "c.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=s=64x64:d=1.5:r=24",
                    "-c:v", "libx264", str(clip)], check=True)
    real_which = shutil.which
    monkeypatch.setattr(media.shutil, "which", lambda n: None if n == "ffprobe" else real_which(n))
    assert media.duration(clip) == pytest.approx(1.5, abs=0.1)
