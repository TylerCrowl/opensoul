"""Polish: the Pixel demo picture has no caption box or footnote (they showed as a stray white rectangle on the card)."""
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / "assets" / "demo_samples" / "pixel_pack" / "refs" / "ref_00.png"


def test_caption_box_and_footnote_are_gone():
    im = Image.open(REF).convert("RGB")
    bg = im.getpixel((8, 8))
    for box in ((36, 36, 425, 105), (40, 705, 600, 745)):
        region = im.crop(box)
        assert region.getcolors(1) and region.getcolors(1)[0][1] == bg, box  # one flat colour = the background


def test_the_robot_is_still_there():
    im = Image.open(REF).convert("RGB")
    assert im.getpixel((512, 400)) != im.getpixel((8, 8))  # body
    assert im.size == (1024, 768)
