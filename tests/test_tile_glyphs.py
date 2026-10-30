"""Camera and effect tiles: every preset has a preview clip or a motion glyph, and a tile is never a blank card."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TILES = (ROOT / "app/web/static/tiles.js").read_text()
CSS = (ROOT / "app/web/static/storyboard.css").read_text()
PRESETS = sorted((ROOT / "presets/camera").glob("*.json")) + sorted((ROOT / "presets/effects").glob("*.json"))


def glyph_ids() -> set[str]:
    block = TILES.split("const GLYPHS = {", 1)[1].split("};", 1)[0]
    return set(re.findall(r"^\s*(\w+):\s*'", block, re.M))


def test_every_preset_has_a_preview_or_a_glyph():
    glyphs = glyph_ids()
    assert len(glyphs) >= 16
    for f in PRESETS:
        p = json.loads(f.read_text())
        thumb = (p.get("thumbnail") or "").removeprefix("/")
        has_preview = bool(thumb) and (ROOT / thumb).is_file()
        assert has_preview or p.get("glyph") in glyphs, f"{f.name}: no preview clip and no glyph"


def test_every_preset_names_a_known_glyph_so_tiles_look_consistent():
    glyphs = glyph_ids()
    for f in PRESETS:
        g = json.loads(f.read_text()).get("glyph")
        assert g in glyphs, f"{f.name}: glyph {g!r} is not in tiles.js GLYPHS"


def test_moves_that_look_alike_get_different_glyphs():
    by_id = {json.loads(f.read_text())["id"]: json.loads(f.read_text())["glyph"] for f in PRESETS}
    for a, b in [("dolly_in", "push_in_gentle"), ("dolly_in", "crash_zoom"), ("dolly_in", "dolly_out"), ("jib_up", "jib_down"),
                 ("dolly_left", "dolly_right"), ("orbit", "orbit_freeze")]:
        assert by_id[a] != by_id[b], (a, b)


def test_no_blank_card_fallback():
    # A missing (or failed) clip gets the silhouette + big glyph card, not an empty span.
    assert 'class="os-ph" aria-hidden="true"></span>' not in TILES
    assert "function fallback(p)" in TILES and "glyph(p, true)" in TILES and "#i-subject" in TILES
    assert TILES.count("${media(p, on)}") == 2 and "onBadClip(t" in TILES
    assert ".os-ph .os-glyph.big" in CSS and ".os-glyph {" in CSS
    assert "p.tile_still" in TILES and ".os-ph.still img" in CSS  # a passed still under the glyph


def test_clash_hint_names_both_moves():
    rules = json.loads((ROOT / "presets/camera_rules.json").read_text())
    assert all(c.get("short") for c in rules["conflicts"])
    assert "clashes with ${name(b)}: ${c.short}." in TILES
