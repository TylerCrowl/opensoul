"""Storyboard shot sheet: the dialogue controls (static checks on storyboard.js; the screenshots cover the look)."""
import re
from pathlib import Path

JS = (Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "storyboard.js").read_text()


def _fn(name: str) -> str:
    m = re.search(r"function " + name + r"\(.*?\n  }\n", JS, re.S)
    assert m, name
    return m.group(0)


def test_only_the_allowed_orpheus_tags_are_offered():
    from opensoul.orpheus import TAGS

    m = re.search(r"const TAGS = \[(.*?)\];", JS)
    assert tuple(re.findall(r'"(\w+)"', m.group(1))) == TAGS


def test_dialogue_section_is_always_in_the_sheet_and_wired():
    html = _fn("dialogueHTML")
    for bit in ('id="sbLine"', 'id="sbSpeaker"', 'id="sbLineVoice"', 'id="sbSpeak"', 'id="sbLipsync"', 'id="sbLipsyncBackend"',
                'id="sbLipHint"', "lipHint(s)"):
        assert bit in html, bit
    hint = _fn("lipHint")  # OS-043: the hint says what Draft and Final do with the mouth, for this shot
    assert "Draft: voice only, no lip-sync. Final: LTX audio+video moves the mouth to the voice." in hint
    assert "${dialogueHTML(s)}" in _fn("renderSheet") and "wireDialogue(" in _fn("renderSheet")
    assert '["ltx_av", "LTX audio+video (joint)"]' in JS  # the default backend is listed first


def test_tags_insert_at_the_cursor_and_speak_posts_the_unsaved_line():
    w = _fn("wireDialogue")
    assert "selectionStart" in w and "setSelectionRange" in w
    assert "`${base}/speak`" in w and "line: ta.value" in w
    for field in ("line:", "speaker:", "voice:", "lipsync:", "lipsync_backend:"):
        assert "save({ " + field in w, field


def test_script_rows_keep_the_line_and_speaker():
    assert 'line: line || "", speaker: speaker || ""' in JS
    assert 'class="sb-srow-line"' in JS


def test_take_details_show_lipsync_stats_when_there_are_any():
    d = _fn("dialogueDetails")
    assert "lipsync_stats" in d and "face_found_ratio" in d and "none yet" in d


def test_dialogue_controls_sit_in_two_clean_rows():
    html = _fn("dialogueHTML")
    grid = html[html.index('class="sb-dia-grid"'):]
    grid = grid[:grid.index("</div>")]
    for bit in ('id="sbSpeaker"', 'id="sbLipsync"'):
        assert bit in grid, bit
    # P2-10 (audit Oct 25): engine names stay off the main path; the lip-sync engine picker is under "Advanced".
    # D4 (Oct 18): the per-shot voice override is folded under "Advanced"; the character's voice is the default.
    adv = html[html.index('<details class="sb-adv"'):]
    assert 'id="sbLineVoice"' in adv[:adv.index("</details>")] and 'id="sbLineVoice"' not in grid
    assert 'id="sbLipsyncBackend"' in adv[:adv.index("</details>")] and 'id="sbLipsyncBackend"' not in grid
    assert "LTX" not in html[:html.index('<details class="sb-adv"')]
    assert 'id="sbSpeak"' not in grid  # Speak sits with the tag chips, not between the labels
    css = (Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "storyboard.css").read_text()
    rule = css[css.index(".sb-dia-grid {"):]
    assert "grid-template-columns: max-content minmax(0, 1fr) max-content minmax(0, 1fr)" in rule
    assert ".sb-dia-grid label {" in css and "white-space: nowrap" in css[css.index(".sb-dia-grid label {"):][:200]


def test_tag_chip_insert_is_undoable():
    w = _fn("wireDialogue")
    assert 'execCommand("insertText", false, ins)' in w  # browser undo stack (Ctrl+Z) covers the insert
    assert 'setRangeText(ins, a, z, "end")' in w        # fallback where execCommand is gone
    assert "ta.value = pre + ins + post" not in w        # a direct value write wipes the undo history


def test_switching_takes_keeps_the_previous_still_until_the_new_one_loads():
    st = _fn("stageHTML")
    assert "sb.lastStill" in st and "background-image" in st and "sb-media" in st
    w = _fn("wireStageHold")
    assert "loadeddata" in w and '"load"' in w and "setTimeout(show" in w and "sb.lastStill = v.poster_url" in w
    assert "wireStageHold(" in _fn("renderSheet")
    css = (Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "storyboard.css").read_text()
    assert ".sb-stage .sb-media.loading { opacity: 0; }" in css
