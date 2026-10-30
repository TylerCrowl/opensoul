import shutil
import subprocess
from pathlib import Path

import pytest

from demo_character import DEMO_POSTER
from opensoul import media
from opensoul.era import apply_era, build_filter, era_params
from opensoul.presets import build_shot_plan
from opensoul.shot import run_shot
from opensoul.speak import BACKENDS, estimate_seconds, get_lipsync, get_tts

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
ROOT = Path(__file__).resolve().parents[1]


def _poster():
    """The demo poster in the dev tree; a small synthetic still in a release archive (which leaves the demo files out)."""
    if DEMO_POSTER.is_file():
        return DEMO_POSTER
    import tempfile
    from pathlib import Path as _P

    from PIL import Image

    out = _P(tempfile.mkdtemp(prefix="opensoul_test_")) / "synthetic_still.png"
    Image.new("RGB", (270, 480), (90, 110, 140)).save(out)
    return out


POSTER = _poster()


@pytest.fixture()
def clip(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    p = tmp_path / "in.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=s=180x320:d=1:r=24",
                    "-pix_fmt", "yuv420p", str(p)], check=True)
    return p


def test_era_filters_differ_and_match_spec():
    ugc = build_filter(era_params("iphone_ugc"))
    film = build_filter(era_params("film_35mm"))
    assert "noise=alls=4" in ugc and "sin(" in ugc and "vignette" not in ugc
    assert "noise=alls=14" in film and "random(" in film and "vignette" in film and "colorbalance" in film
    with pytest.raises(KeyError):
        era_params("vhs")


@needs_ffmpeg
@pytest.mark.parametrize("era", ["iphone_ugc", "film_35mm"])
def test_apply_era_keeps_size(clip, tmp_path, era):
    out = apply_era(clip, tmp_path / f"{era}.mp4", era)
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                        "-of", "csv=p=0", str(out)], capture_output=True, text=True)
    assert r.stdout.strip() == "180,320"


def test_lipsync_registry():
    assert set(BACKENDS) == {"latentsync", "ltx_av", "infinitetalk"}
    for b in BACKENDS:
        assert get_lipsync(b, dry_run=True).name == b
    with pytest.raises(ValueError):
        get_lipsync("wav2lip")


def test_infinitetalk_live_is_marked_in_progress(tmp_path):
    with pytest.raises(NotImplementedError):
        get_lipsync("infinitetalk", dry_run=False).sync(tmp_path / "a.mp4", tmp_path / "a.wav", tmp_path / "o.mp4")


@needs_ffmpeg
def test_dry_tts_length_tracks_text(tmp_path):
    wav = get_tts(dry_run=True).synthesize("one two three four five six seven eight", "am_michael", tmp_path / "v.wav")
    assert abs(media.duration(wav) - estimate_seconds("one two three four five six seven eight")) < 0.2


def test_plan_records_lipsync_backend():
    plan = build_shot_plan(camera="static", line="Hi", lipsync_backend="ltx_av")
    vid = next(s for s in plan["stages"] if s["stage"] == "video")
    assert vid["lipsync"] == "ltx_av" and vid["workflow"] == "workflows/04b_a2v_ltx_api.json"
    plan = build_shot_plan(camera="static", line="Hi", lipsync_backend="latentsync")
    ls = next(s for s in plan["stages"] if s["stage"] == "lipsync")
    assert ls["backend"] == "latentsync" and ls["workflow"] == "workflows/05_lipsync_api.json"


@needs_ffmpeg
@pytest.mark.parametrize("backend", BACKENDS)
def test_run_shot_speak_end_to_end_dry(monkeypatch, tmp_path, backend):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    plan = build_shot_plan(camera="dolly_in", era="film_35mm", line="Morning folks", lipsync_backend=backend)
    res = run_shot(plan, POSTER, tmp_path)
    # ltx_av renders picture + mouth to the voice in the video stage (04b); the others lip-sync afterwards
    want = ["voice", "video", "era"] if backend == "ltx_av" else ["voice", "video", "lipsync", "era"]
    assert [s["stage"] for s in res.steps] == want
    assert res.video.name == "final.mp4" and res.video.is_file()
    streams = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0",
                              str(res.video)], capture_output=True, text=True).stdout.split()
    assert "audio" in streams and "video" in streams


@needs_ffmpeg
def test_run_shot_uses_injected_video_backend(monkeypatch, tmp_path, clip):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    calls = []

    class Fake:
        def render(self, stage, image, dest):
            calls.append(stage["inputs"]["20"]["text"])
            shutil.copy(clip, dest)
            return dest

    res = run_shot(build_shot_plan(effect="earth_zoom_out"), POSTER, tmp_path, video_backend=Fake())
    # Earth zoom out is a reverse preset: the render prompt is the opposite move (zoom-in), reversed in post.
    assert calls and "zoom-in from high above" in calls[0]
    assert [s["stage"] for s in res.steps] == ["video", "reverse", "era"]
    calls.clear()
    res = run_shot(build_shot_plan(camera="dolly_in"), POSTER, tmp_path / "b", video_backend=Fake())
    assert calls and "dolly push-in" in calls[0]
    assert [s["stage"] for s in res.steps] == ["video", "era"]
