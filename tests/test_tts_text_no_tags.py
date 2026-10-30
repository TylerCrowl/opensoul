"""No tag or style text ever reaches a TTS engine's text input as words to speak.

VoxCPM2 read '(amused, a small chuckle)' aloud when the speaker's clip and its transcript were used as the prompt, so
VoxCPM2, Chatterbox and Kokoro get the plain words only. Orpheus keeps its inline <tags> (it performs them, it does not
say them) but never gets a (style) or [stage] note either."""
import pytest

from opensoul import speak as S
from opensoul import voice_engine as VE

LINES = [
    "<chuckle> That's not how nights work.",
    "(amused, a small chuckle)That's not how nights work.",
    "(amused, a small chuckle) <chuckle> Ren... it's a can.",
    "[whispering] <sigh> Fine. <laugh> Okay.",
    "Have a good night. (beat) See you sometime later.",
    "It's a good can.",
]
STYLE_WORDS = ("amused", "chuckle", "whisper", "sigh", "laugh", "beat", "(", ")", "[", "]", "<", ">")


def _no_tag_text(said: str):
    low = said.lower()
    assert not any(w in low for w in STYLE_WORDS), said
    assert said == said.strip() and "  " not in said


@pytest.mark.parametrize("line", LINES)
@pytest.mark.parametrize("engine", ["voxcpm2", "chatterbox", "kokoro"])
def test_engine_text_is_words_only(engine, line):
    _no_tag_text(VE.engine_text(engine, line))


@pytest.mark.parametrize("line", LINES)
def test_orpheus_keeps_inline_tags_but_never_style_notes(line):
    said = VE.engine_text("orpheus", line)
    assert "(" not in said and "[" not in said and "amused" not in said and "whisper" not in said
    for tag in ("<chuckle>", "<sigh>", "<laugh>"):
        assert (tag in said) == (tag in line)


def test_examples():
    assert VE.spoken_words("(amused, a small chuckle)That's not how nights work.") == "That's not how nights work."
    assert VE.spoken_words("(amused) <chuckle> Ren... it's a can.") == "Ren... it's a can."
    assert VE.engine_text("orpheus", "<sigh> Fine.") == "<sigh> Fine."
    assert VE.engine_text("orpheus", "(tired) <sigh> Fine.") == "<sigh> Fine."
    assert VE.spoken_words("Plain words.") == "Plain words."


@pytest.mark.parametrize("line", LINES)
@pytest.mark.parametrize("cls,node", [(S.VoxCPM2TTS, "1"), (S.ChatterboxTTS, "1"), (S.KokoroTTS, "1")])
@pytest.mark.parametrize("with_ref", [False, True])
def test_what_the_engine_node_receives(monkeypatch, tmp_path, line, cls, node, with_ref):
    sent = {}

    def fake(workflow, inputs, output_node, dest, what):
        sent.update(inputs)
        return dest

    monkeypatch.setattr(S, "_run_sdk", fake)
    ref = {"clip": str(tmp_path / "ref.wav"), "text": "We'll be back! Sometime."} if with_ref else None
    tts = cls(dry_run=False)
    if cls is S.KokoroTTS:
        tts.synthesize(line, "af_heart", tmp_path / "o.wav")
    else:
        tts.synthesize(line, "mio", tmp_path / "o.wav", ref=ref)
    _no_tag_text(sent[node]["text"])


def test_runner_strips_style_notes_too():
    from pathlib import Path
    import re

    src = (Path(__file__).resolve().parents[1] / "custom_nodes/opensoul_nodes/runners/voxcpm2_tts.py").read_text()
    pat = re.search(r'text = re\.sub\(r"(.+?)", " ", a\.text\)', src).group(1)
    out = re.sub(pat, " ", "(amused, a small chuckle)<chuckle> That's not how nights work. [beat]")
    assert re.sub(r"\s+([,.!?;:])", r"\1", re.sub(r"\s+", " ", out)).strip() == "That's not how nights work."
    assert '"text": text' in src and '"text": a.text' not in src
