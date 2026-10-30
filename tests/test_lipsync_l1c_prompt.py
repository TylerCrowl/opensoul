"""L1c talk prompt: the soft articulation sentence (eyes open), then 'Head still, no tilt, eyes on <listener>'.
The eyes go off-lens onto the listener in the scene; the camera only when the shot has no listener. Talk shots get no
blink or glance-down beat (the eyes_safe guard stays). No GPU."""
import json

import pytest

from opensoul import lipsync as L


@pytest.mark.parametrize("text", ["Lumi gives a slow blink and smiles.", "She glances down at the till, then speaks.",
                                  "Lumi waves."])
def test_talk_prompt_has_no_blink_or_glance_beats(text):
    p = L.speaker_prompt(text, "Lumi", "Hi.", "she", look_at="the counter", listener="Ren")
    low = p.lower()
    assert "blink" not in low and "glance" not in low
    assert "eyes open" in low and "Head still, no tilt, eyes on Ren." in p and p.count("Head still") == 1
    assert "the camera" not in p  # a listener in the scene: off-lens, never the camera
    cam = L.speaker_prompt("Lumi waves.", "Lumi", "Hi.", "she")
    assert "Head still, no tilt, eyes on the camera." in cam  # no listener at all
    from opensoul.presets import build_shot_plan

    talk = build_shot_plan(camera="static", quality="final", character_prompt=text, speaker="Lumi", pronoun="she")
    t = json.dumps([s.get("inputs", {}) for s in talk["stages"]]).lower()
    assert "glance" not in t and "blink" not in t and "head still, no tilt" in t


def test_storyboard_listener_is_never_the_camera_when_someone_else_is_there():
    import app.storyboard_api as A
    from opensoul import storyboard as sb

    shot = lambda *c: sb.Shot(id="s", beat="b", characters=list(c))  # noqa: E731
    assert A._listener(shot("Lumi", "Ren"), "Lumi") == "Ren"
    assert A._listener(shot("Lumi", "Ren", "Ivy"), "Lumi") == "Ren and Ivy"
    assert A._listener(shot("Lumi", "Ren", "Ivy", "Max"), "Lumi") == "Ren, Ivy and Max"
    assert A._listener(shot("Lumi"), "Lumi") == ""  # nobody else: the camera
    p = L.speaker_prompt("x", "Lumi", "Hi.", "she", listener=A._listener(shot("Lumi", "Ren", "Ivy"), "Lumi"))
    assert "eyes on Ren and Ivy." in p and "camera" not in p
