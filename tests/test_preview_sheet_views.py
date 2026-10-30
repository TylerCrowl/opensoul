"""Preview (dry-run) sheet cells: side views are not mirrored (a reference with text read backwards), and back
views are a silhouette, not a plain grey box."""
import numpy as np
from PIL import Image, ImageDraw

from opensoul.character_sheet import load_preset, placeholder_view

P = load_preset()
G = P["grid"]
CELL = (int(G["cell_width"]), int(G["cell_height"]))
BG = G["background"]
VIEWS = {v["id"]: v for v in P["views"]}


def _dark(im):
    return np.asarray(im.convert("L")) < 120


def test_side_view_is_not_mirrored(tmp_path):
    ref = Image.new("RGB", (600, 1000), BG)
    ImageDraw.Draw(ref).rectangle((60, 300, 260, 700), fill="#202020")  # subject on the left
    ref.save(tmp_path / "r.png")
    for vid in ("full_side", "close_side"):
        d = _dark(placeholder_view(tmp_path / "r.png", VIEWS[vid], CELL, BG))
        xs = np.nonzero(d)[1]
        assert xs.size and xs.mean() < CELL[0] / 2, vid  # still on the left: no mirror


def test_back_view_of_a_flat_card_is_a_figure(tmp_path):
    card = Image.new("RGB", (720, 1280), BG)
    ImageDraw.Draw(card).text((100, 600), "Name card", fill="#333")
    card.save(tmp_path / "card.png")
    for vid in ("full_back", "close_back"):
        d = _dark(placeholder_view(tmp_path / "card.png", VIEWS[vid], CELL, BG))
        assert 0.05 < d.mean() < 0.6, (vid, d.mean())  # a silhouette, not empty and not a solid box
        rows = d.any(axis=1)
        assert rows.mean() < 0.95


def test_back_view_follows_the_subject_outline(tmp_path):
    ref = Image.new("RGB", (600, 1000), BG)
    ImageDraw.Draw(ref).ellipse((200, 80, 400, 300), fill="#C8A080")       # head
    ImageDraw.Draw(ref).rectangle((150, 300, 450, 950), fill="#203060")    # body
    ref.save(tmp_path / "r.png")
    cell = placeholder_view(tmp_path / "r.png", VIEWS["full_back"], CELL, BG)
    d = _dark(cell)
    a = np.asarray(cell.convert("RGB"))
    cy, cx = CELL[1] // 2, CELL[0] // 2
    assert tuple(a[cy, cx]) == (0x5A, 0x5A, 0x5A)  # flat silhouette fill, no photo detail (the body was blue)
    assert 0.1 < d.mean() < 0.7


def _card_box(cell):
    """Bounding box of everything that isn't the sheet background (the card)."""
    a = np.asarray(cell.convert("RGB")).astype(int)
    bg = np.array(Image.new("RGB", (1, 1), BG).getpixel((0, 0)))
    m = np.abs(a - bg).max(axis=2) > 6
    m[: CELL[1] // 9] = False  # the PREVIEW stamp above the card
    ys, xs = np.nonzero(m)
    return xs.min(), ys.min(), xs.max(), ys.max()


def test_name_card_panels_line_up_and_the_back_has_no_bar(tmp_path):
    """QA round 2 (P_01): uneven panel widths, a back panel with no card, a dark bar under the feet."""
    from app.server import _name_card

    ref = _name_card("Wren Tally", tmp_path / "card.png")
    cells = {v: placeholder_view(ref, VIEWS[v], CELL, BG) for v in ("full_front", "full_side", "full_back")}
    boxes = {v: _card_box(c) for v, c in cells.items()}
    assert len({b[2] - b[0] for b in boxes.values()}) == 1, boxes  # same card width in all three
    x0, y0, x1, y1 = boxes["full_back"]
    d = _dark(cells["full_back"])
    figure_rows = np.flatnonzero(d.any(axis=1))
    # The figure ends well above the name line; nothing dark in the card's bottom fifth.
    assert figure_rows.size and figure_rows.max() < y1 - (y1 - y0) // 5
