"""D3: a take note that already says it kept LTX audio+video does not suggest LTX lip-sync again."""
def test_d3_note_does_not_suggest_ltx_when_already_kept():
    from app.storyboard_api import _tidy_note

    small = "Kai's face is too small for LatentSync (60px; needs 96px). Use LTX lip-sync or a closer shot. Kept LTX audio+video only."
    assert _tidy_note(small) == ("Kai's face is too small for LatentSync (60px; needs 96px). "
                                 "Kept LTX audio+video only (or move to a closer shot).")
    none = "Couldn't find Kai's face in this take. Try a closer shot or LTX lip-sync. Kept LTX audio+video only."
    assert "LTX lip-sync" not in _tidy_note(none) and _tidy_note(none).endswith("(or move to a closer shot).")
    plain = "Kai's face is too small for LatentSync (60px; needs 96px). Use LTX lip-sync or a closer shot."
    assert _tidy_note(plain) == plain  # before a render it is still the right advice
