"""Orpheus back-compat: the picker now recommends Chatterbox, but the app's voice engine did not change. Projects and
packs that use Orpheus voices (Lumi tara, Mio leah, Ren zac, Pixel jess) must render exactly as before."""
from __future__ import annotations

import yaml
from pathlib import Path

from opensoul import character_voices as CV
from opensoul import lipsync as L
from opensoul import orpheus, presets, speak

ROOT = Path(__file__).resolve().parents[1]
CAST = {"Lumi": "tara", "Mio": "leah", "Ren": "zac", "Pixel": "jess"}


def test_the_default_engine_is_still_orpheus_everywhere(monkeypatch):
    monkeypatch.delenv("OPENSOUL_TTS", raising=False)
    assert speak.DEFAULT_TTS == presets.DEFAULT_TTS == "orpheus"
    reg = yaml.safe_load((ROOT / "presets/models.yaml").read_text())
    assert next(s for s in reg["stages"] if s["id"] == "voice")["default_backend"] == "orpheus"
    assert isinstance(speak.get_tts(dry_run=True), speak.OrpheusTTS)
    assert presets.TTS_WORKFLOWS["orpheus"] == "workflows/03c_tts_orpheus_api.json"


def test_example_cast_keeps_its_orpheus_voices(tmp_path):
    for name, voice in CAST.items():
        assert CV.voice_for(tmp_path, name) == voice  # a fresh data folder: the built-in picks
        assert orpheus.check_voice(voice) == voice
    CV.set_voice(tmp_path, "Lumi", "tara")  # a saved pick round-trips unchanged
    assert CV.voice_for(tmp_path, "lumi") == "tara"


def test_story_dialogue_still_uses_orpheus_with_emotion_tags():
    for name, voice in CAST.items():
        for quality in ("draft", "final"):
            stages, _notes, _mode = L.dialogue_stages(
                line="<sigh> Whole milk.", voice=voice, quality=quality, backend="ltx_av", prompt="a barista",
                speaker=name, seed=7)
            v = stages[0]
            assert v["stage"] == "voice" and v["backend"] == "orpheus" and v["inputs"]["voice"] == voice
            assert "<sigh>" in v["inputs"]["text"]  # Orpheus keeps the tags; other engines would drop them


def test_quick_shot_plan_still_uses_orpheus(monkeypatch):
    monkeypatch.delenv("OPENSOUL_TTS", raising=False)
    for voice in CAST.values():
        plan = presets.build_shot_plan(line="<chuckle> Obviously.", voice=voice, quality="final")
        v = next(s for s in plan["stages"] if s["stage"] == "voice")
        assert v["backend"] == "orpheus" and v["inputs"]["voice"] == voice
        assert v["workflow"] == "workflows/03c_tts_orpheus_api.json" and "<chuckle>" in v["inputs"]["text"]


def test_chatterbox_stays_an_explicit_choice(monkeypatch):
    # Chatterbox is wired as an engine (workflow 03b) but only when asked for; nothing switches to it silently.
    monkeypatch.setenv("OPENSOUL_TTS", "chatterbox")
    assert isinstance(speak.get_tts(dry_run=True), speak.ChatterboxTTS)
    assert (ROOT / "workflows/03b_tts_chatterbox_api.json").is_file()
    assert (ROOT / "custom_nodes/opensoul_nodes/runners/chatterbox_tts.py").is_file()
