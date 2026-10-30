"""Script import for the anime trailer (OS-050..053): first names and titles match library characters, cards and
names inside lines are not cast, the line is not copied into What happens, the speaker is saved and carried."""
from opensoul import storyboard as sb
from opensoul.script_split import split_script

LIB = ["Aldric Vane", "Rhea Solenne", "Octavia Dravenmoor", "Bastian Kade"]
SCRIPT = """## The strategist
Close-up on Aldric, half his face in shadow. [camera: static]
ALDRIC: Every war is a game. I wrote this one.

## Orders from the throne
Medium shot on a dark command deck: Bastian salutes a tall blue hologram of Octavia.
REGENT OCTAVIA: Bring him back, Commander.

## Everywhere
Medium close-up on Rhea in a mecha cockpit.
RHEA: Aldric, they're everywhere!

## Title card
Title card: IRON GAMBIT over a dark chessboard.

## Coming soon
End card: black screen, COMING SOON.
"""


def _shots(cast=LIB):
    return split_script(SCRIPT, cast)["shots"]


def test_first_names_and_titles_match_the_library():  # OS-050
    r = _shots()
    assert (r[0]["characters"], r[0]["speaker"]) == (["Aldric Vane"], "Aldric Vane")
    assert r[1]["speaker"] == "Octavia Dravenmoor"
    assert set(r[1]["characters"]) == {"Bastian Kade", "Octavia Dravenmoor"}


def test_cards_and_names_in_lines_are_not_cast():  # OS-051
    r = _shots()
    assert r[2]["characters"] == ["Rhea Solenne"]  # "Aldric, they're everywhere!" does not cast Aldric
    assert r[3]["characters"] == [] and r[4]["characters"] == []
    r = _shots(cast=[])
    assert r[3]["characters"] == [] and r[4]["characters"] == []


def test_the_line_is_not_copied_into_what_happens():  # OS-052
    r = _shots()
    assert r[0]["line"] == "Every war is a game. I wrote this one."
    assert "says" not in r[0]["prompt"] and "game" not in r[0]["prompt"]


def test_quoted_speech_is_not_drawn():  # OS-052 (old stories still have it in What happens)
    from app.storyboard_api import _no_speech

    assert _no_speech("Close-up on Aldric. Aldric says: “Every war is a game.”") == "Close-up on Aldric."
    assert _no_speech("Title card: “IRON GAMBIT” over a board.") == "Title card: “IRON GAMBIT” over a board."


def test_speaker_is_saved_and_carried_to_the_renamed_chip(tmp_path):  # OS-053
    st = sb.Store(tmp_path)
    p = st.create_project("Trailer")
    p = st.add_shots(p.id, [{"beat": "Talk", "characters": ["Rhea"], "line": "We take back the sky."},
                            {"beat": "Two", "characters": ["Rhea", "Aldric"], "speaker": "Rhea", "line": "Go."}])
    one, two = p.shots
    assert one.speaker == "Rhea"  # one person in the cast: the line is theirs, and that is saved
    assert st.update_shot(p.id, one.id, characters=["Rhea Solenne"]).speaker == "Rhea Solenne"
    assert st.update_shot(p.id, two.id, characters=["Rhea Solenne", "Aldric"]).speaker == "Rhea Solenne"
    assert st.update_shot(p.id, two.id, characters=["Aldric"]).speaker == ""  # the speaker left: nobody is guessed
