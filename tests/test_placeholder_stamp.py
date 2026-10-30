"""Dry-run placeholder takes: everything baked in sits in the bottom band (the app's own take label and Keeper
pill sit on top and used to cover a baked "PREVIEW · vN" badge), long captions wrap instead of running off the
frame, and a new take never starts from an already stamped preview still."""
import numpy as np
from PIL import Image

from app import storyboard_api as api
from opensoul import storyboard as sb

LONG = ("Sip and freeze: she takes one slow sip, then freezes mid-sip as the door bell rings and the whole cafe "
        "goes quiet behind her while the rain keeps going outside")


def _plain(tmp_path, size):
    p = tmp_path / "base.png"
    Image.new("RGB", size, (200, 200, 200)).save(p)
    return p


def test_top_of_the_frame_is_left_clear(tmp_path):
    for size in ((704, 1280), (1280, 704)):
        out = api._stamp(_plain(tmp_path, size), tmp_path / "s.jpg", "Lumi", 3, LONG, size)
        a = np.asarray(Image.open(out).convert("L")).astype(int)
        top = a[: size[1] // 3]
        assert abs(top - 200).max() < 40, size  # nothing baked where the take label / Keeper pill go


def test_long_caption_wraps_inside_the_frame(tmp_path):
    size = (704, 1280)
    out = api._stamp(_plain(tmp_path, size), tmp_path / "s.jpg", "Lumi", 3, LONG, size)
    a = np.asarray(Image.open(out).convert("L"))
    band = a[int(size[1] * 0.6):]
    bright = band > 235  # white text on the dark band
    cols = np.nonzero(bright.any(axis=0))[0]
    assert cols.size and cols.max() < size[0] - 20  # text stops before the right edge (wrapped, not cut off)
    rows = np.nonzero(bright.any(axis=1))[0]
    assert rows.size and (rows.max() - rows.min()) > 120  # several lines, not one clipped line


def test_new_take_does_not_start_from_a_stamped_preview(tmp_path, monkeypatch):
    poster = tmp_path / "poster.jpg"
    Image.new("RGB", (64, 64), "red").save(poster)
    v = sb.Version(id="v1", take=1, take_id="s1-v1", file=str(poster), poster=str(poster), kind="preview", placeholder=True)
    shot = sb.Shot(id="s1", beat="Counter", versions=[v])
    proj = sb.Project(id="p", title="t", character="Nobody", shots=[shot])
    monkeypatch.setattr(api._srv(), "_character_look", lambda *a, **k: {"still": None, "sheet": None, "source": None})
    assert api._base_still(proj, shot, None) is None
