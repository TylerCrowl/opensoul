"""Voices on the studio (anime trailer issues): engines the studio lacks are not used (OS-054), voices the studio lacks
are not offered (OS-055), new characters get a voice of their gender (OS-048), the voice sits on the character with
a sample (OS-049)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from opensoul import character_voices as CV
from opensoul import studio_info as SI
from opensoul import voice_engine as VE

ROOT = Path(__file__).resolve().parents[1]
NO_ORPHEUS = {"orpheus": False, "kokoro": True, "chatterbox": True, "voxcpm2": False}
STUDIO_KOKORO = {"am_michael", "am_adam", "am_puck", "af_heart", "af_bella", "af_nicole", "bm_lewis", "bf_emma"}


def test_new_stories_skip_an_engine_the_studio_does_not_have(monkeypatch):
    monkeypatch.delenv("OPENSOUL_TTS_DEFAULT", raising=False)
    assert VE.default_for_new(NO_ORPHEUS) == "kokoro"
    # VoxCPM2 is there but its no-clip engine (Orpheus) isn't: the clip-less fallback is Kokoro
    both = {**NO_ORPHEUS, "voxcpm2": True}
    assert VE.no_clip_fallback(both) == "kokoro" and VE.default_for_new(both) == "voxcpm2"


def test_resolve_falls_back_to_an_engine_the_studio_has(monkeypatch):
    monkeypatch.setattr(VE, "studio_engines", lambda: {**NO_ORPHEUS, "voxcpm2": True})
    engine, ref, note = VE.resolve("voxcpm2", {}, None, who="Aldric Vane")
    assert engine == "kokoro" and ref is None and "spoken with Kokoro" in note


def test_story_take_never_sends_a_missing_engine(monkeypatch):
    import app.storyboard_api as A

    monkeypatch.setattr(VE, "studio_engines", lambda: NO_ORPHEUS)
    monkeypatch.setattr(A, "_speaker_pack", lambda who: {})
    engine, _, note = A._voice_engine("Aldric Vane", "orpheus")
    assert engine == "kokoro" and "Orpheus isn't on your studio" in note
    monkeypatch.setattr(VE, "studio_engines", lambda: {e: False for e in VE.ENGINES})
    with pytest.raises(Exception) as e:
        A._voice_engine("Aldric Vane", "orpheus")
    assert "no voice engine" in str(e.value.detail)


def test_twins_dan_and_zoe_use_voices_the_studio_ships():
    rows = {r["id"]: r for r in json.loads((ROOT / "presets/voices.json").read_text())}
    assert rows["dan"]["kokoro"] == "am_adam" and rows["zoe"]["kokoro"] == "af_kore"
    assert VE.engine_voice("kokoro", "dan") == "am_adam"


def test_a_missing_kokoro_voice_is_swapped_for_one_of_the_same_gender():
    assert VE.kokoro_substitute("dan", STUDIO_KOKORO) == "dan"
    assert VE.kokoro_substitute("zoe", STUDIO_KOKORO) in {"tara", "leah", "jess", "mia"}
    assert VE.kokoro_substitute("zoe", {"am_michael"}) is None
    assert VE.kokoro_substitute("zoe", None) == "zoe"


def test_studio_lists_engines_and_voices_and_learns_missing_files(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "0")
    monkeypatch.setenv("OPENSOUL_COMFYUI_URL", "http://studio.test:8190")
    SI.clear_cache()
    info = {"OpenSoulKokoroTTS": {"input": {"required": {"voice": [["am_michael", "am_fenrir", "af_heart"], {}]}}}}

    def fake(url, timeout=SI.TIMEOUT_S, opener=None):
        node = url.rsplit("/", 1)[-1]
        return {node: info[node]} if node in info else {}
    monkeypatch.setattr(SI, "_get_json", fake)
    assert SI.tts_engines() == {"orpheus": False, "kokoro": True, "chatterbox": False, "voxcpm2": False}
    assert SI.kokoro_voices(tmp_path) == {"am_michael", "am_fenrir", "af_heart"}
    msg = "job 1 ended failed: FileNotFoundError: No such file: models/kokoro/voices/am_fenrir.pt"
    assert SI.note_missing_voice(tmp_path, msg) == "am_fenrir"
    assert SI.kokoro_voices(tmp_path) == {"am_michael", "af_heart"}
    monkeypatch.setattr(VE, "studio_engines", SI.tts_engines)
    monkeypatch.setattr(SI, "kokoro_voices", lambda data_dir=None: {"am_michael", "af_heart"})
    assert VE.available_voice_ids(tmp_path) == {"leo", "tara"}
    SI.clear_cache()


def test_gender_from_pronoun_or_look_words():
    assert CV.gender_of("she/her", "") == "female"
    assert CV.gender_of("they", "a tall lean adult man, 31 years old, close-cropped black hair") == "male"
    assert CV.gender_of("", "a young woman with long silver hair, her coat collar up") == "female"
    assert CV.gender_of("", "a robot") == ""


def test_new_characters_get_a_free_voice_of_their_gender(tmp_path):
    assert CV.ensure_voice(tmp_path, "Aldric Vane", text="an adult man, 30, strategist") in {"zac", "leo", "dan"}
    assert CV.voice_gender(CV.ensure_voice(tmp_path, "Rhea Solenne", text="a young woman, rebel pilot")) == "female"
    assert CV.voice_gender(CV.ensure_voice(tmp_path, "Octavia", pronoun="she")) == "female"
    assert CV.voice_gender(CV.ensure_voice(tmp_path, "Bastian Kade", text="a tall lean adult man")) == "male"
    picks = CV.load(tmp_path)
    assert len(set(picks.values())) == 4  # nobody shares
    assert CV.free_voice(tmp_path, "X", "male", available={"leo", "tara"}) == "leo"


def test_voice_on_the_character_card_with_a_sample(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    from fastapi.testclient import TestClient

    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    c = TestClient(server.app)
    d = c.get("/api/voices?name=Rhea").json()
    assert all(v["available"] for v in d["voices"]) and d["engines"] is None
    r = c.post("/api/voices/sample", json={"voice": "tara"})
    assert r.status_code == 200 and r.json()["placeholder"]
    assert c.post("/api/voices/sample", json={"voice": "nobody"}).status_code == 400
    html = (ROOT / "app/web/index.html").read_text()
    js = (ROOT / "app/web/static/app.js").read_text()
    assert 'id="charVoice"' in html and 'id="btnVoiceSample"' in html
    assert "/api/voices/sample" in js and "/voice`" in js
    sbjs = (ROOT / "app/web/static/storyboard.js").read_text()
    assert "Voices (for every shot)" in sbjs and "not on your studio" in sbjs
