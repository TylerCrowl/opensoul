"""Shots cards: every camera shows as a chip (Static too), and a cast placeholder picture shows the initial."""
from pathlib import Path

JS = (Path(__file__).resolve().parents[1] / "app/web/static/storyboard.js").read_text()


def test_static_camera_is_a_chip_like_the_others():
    body = JS[JS.index("function movesChipsHTML"):JS.index("const camOptions")]
    assert '=== "static") return ""' not in body and "sb-move-chip" in body


def test_placeholder_cast_picture_shows_the_initial_not_a_blank_circle():
    face = JS[JS.index("function face("):JS.index("function castHTML")]
    assert "card_placeholder" in face and "initial(c.name)" in face
    assert "hasPic(c) ?" in JS and JS.count("c.picture_url ? `<img") == 0
