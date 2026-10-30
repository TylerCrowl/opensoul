"""Ear-tip trim: long sideways spikes against the background get shorter; faces and plain images are untouched."""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from opensoul.character_sheet import wants_subtle_ears
from opensoul.ear_trim import trim_array, trim_view

SKIN = (150, 180, 225)  # BGR
HAIR = (150, 150, 150)
BG = (225, 225, 225)


def _head(spike_len=120):
    im = np.full((1024, 1024, 3), BG, np.uint8)
    cv2.ellipse(im, (512, 330), (150, 190), 0, 0, 360, HAIR, -1)       # hair
    cv2.ellipse(im, (512, 380), (95, 120), 0, 0, 360, SKIN, -1)        # face
    for side in (-1, 1):                                                # ear spikes pointing out sideways
        x0 = 512 + side * 150
        pts = np.array([[x0, 300], [x0, 340], [x0 + side * spike_len, 290]], np.int32)
        cv2.fillPoly(im, [pts], SKIN)
    return im


def _span(im):
    r, b = im[..., 2].astype(int), im[..., 0].astype(int)
    skin = (r - b > 40)
    skin[:, 362:662] = False  # ignore the face and hair column
    xs = np.nonzero(skin.any(0))[0]
    return 0 if not len(xs) else int(xs.max() - xs.min())


def test_front_spikes_get_shorter_and_face_stays():
    im = _head()
    out, mask, ears = trim_array(im, "close_front")
    assert len(ears) == 2 and mask.any()
    assert _span(out) < _span(im) - 120
    face = (slice(330, 430), slice(470, 555))
    assert np.abs(out[face].astype(int) - im[face].astype(int)).max() == 0


def test_plain_image_is_untouched(tmp_path):
    p = tmp_path / "v.png"
    cv2.imwrite(str(p), np.full((600, 400, 3), BG, np.uint8))
    r = trim_view(p, "full_front", out=tmp_path / "o.png")
    assert not r.changed and r.ears == []


def test_wants_subtle_ears():
    assert wants_subtle_ears("long silver hair, short subtle pointed elf ears that sit close to the head")
    assert not wants_subtle_ears("a young elf barista with pointed ears")
    assert not wants_subtle_ears("long pointed elf ears")
