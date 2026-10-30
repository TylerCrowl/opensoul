"""Script split: every spoken line is its own shot with the right speaker (was: KAI + MIO lines merged into one
shot named "Come", "Kai says" holding both lines); sounds become Orpheus tags; dialogue shots get real names."""
import pytest

from opensoul.script_split import split_script


def _rows(text, cast=None):
    return [(s["beat"], s["speaker"], s["line"], s["characters"]) for s in split_script(text, cast)["shots"]]


def test_name_colon_lines_on_consecutive_lines():
    assert _rows("KAI: Come on, come on.\nMIO: (sighs) Another night.") == [
        ("Kai – Come on", "Kai", "Come on, come on.", ["Kai"]),
        ("Mio – Another night", "Mio", "<sigh> Another night.", ["Mio"]),
    ]  # each turn casts its own speaker (was: every speaker of the scene on every row)


def test_a_turn_also_casts_people_named_in_the_action():
    rows = _rows("INT. BUS STOP - NIGHT\nRain. Kai waits.\nKAI\nCome on, come on.\nMIO\n(sighs)\nAnother night.")
    assert [(who, cast) for _, who, _, cast in rows] == [("Kai", ["Kai"]), ("Mio", ["Mio", "Kai"])]
    rows = _rows("INT. BUS STOP - NIGHT\nKai and Mio wait in the rain.\nKAI: Come on.\nMIO: Another night.")
    assert [cast for *_, cast in rows] == [["Kai", "Mio"], ["Mio", "Kai"]]


def test_screenplay_format_with_parentheticals():
    rows = _rows("INT. BUS STOP - NIGHT\nRain. Kai waits.\nKAI\nCome on, come on.\nMIO\n(sighs)\nAnother night.\n"
                 "KAI\n(quietly)\nYeah. Same.")
    assert [(b.split(" – ")[0], who, line) for b, who, line, _ in rows] == [
        ("Bus Stop", "Kai", "Come on, come on."), ("Bus Stop", "Mio", "<sigh> Another night."),
        ("Bus Stop", "Kai", "Yeah. Same.")]  # "(quietly)" is an acting note: dropped, never read aloud
    assert len({b for b, *_ in rows}) == 3  # names stay unique


def test_same_speaker_keeps_one_line_and_single_line_shots_stay_whole():
    assert _rows("LUMI: Whole milk.\nLUMI: (laughs) Obviously.") == [
        ("Lumi – Whole milk", "Lumi", "Whole milk. <laugh> Obviously.", ["Lumi"])]
    r = split_script("Lumi wipes the counter.\n\nLumi: Real coffee.")["shots"]
    assert [s["speaker"] for s in r] == ["", "Lumi"] and r[1]["beat"] == "Lumi – Real coffee"


@pytest.mark.parametrize("line", ["<scream> No!", "No! <whisper>"])
def test_unknown_tags_never_reach_the_story(line):
    s = split_script(f"REN: {line}")["shots"][0]
    assert "<" not in s["line"] and s["line"] == "No!"


def test_each_split_shot_saves_with_its_speaker(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    monkeypatch.setattr(server, "LIBRARY", tmp_path / "library")
    c = TestClient(server.app)
    rows = c.post("/api/storyboard/script/split", json={"text": "KAI: Come on, come on.\nMIO: (sighs) Another night."}).json()["shots"]
    p = c.post("/api/storyboard/projects", json={"title": "Bus", "shots": rows}).json()
    assert [(s["speaker"], s["line"]) for s in p["shots"]] == [("Kai", "Come on, come on."), ("Mio", "<sigh> Another night.")]
