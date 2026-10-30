"""Orpheus TTS as the default voice engine: tags, voices, plan wiring, per-character voices, API, node, docs."""
import importlib.util
import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opensoul import character_voices as cv
from opensoul import orpheus as orp
from opensoul.presets import build_shot_plan, load_presets

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- tags
@pytest.mark.parametrize("raw,want", [
    ("<sigh> No.", "<sigh> No."),
    ("(sighs) No.", "<sigh> No."),
    ("Coffee! [laughs] We need coffee!", "Coffee! <laugh> We need coffee!"),
    ("*gasp* Oh wow.", "<gasp> Oh wow."),
    ("Hm. <Chuckles> fine", "Hm. <chuckle> fine"),
    ("(clears throat) Ahem.", "<cough> Ahem."),
])
def test_normalize_tags(raw, want):
    assert orp.normalize_tags(raw) == want


def test_stage_directions_are_not_sounds():
    assert orp.normalize_tags("(quietly) Coffee. [beat] Yes.") == "(quietly) Coffee. [beat] Yes."


def test_unknown_angle_tag_is_refused():
    with pytest.raises(orp.TagError) as e:
        orp.normalize_tags("No. <sneer> Never.")
    assert "<sneer>" in str(e.value) and "<sigh>" in str(e.value)


def test_strip_tags_and_tags_in():
    line = "Whole milk. Sixty-five degrees. <chuckle> Anything hotter is an apology."
    assert orp.strip_tags(line) == "Whole milk. Sixty-five degrees. Anything hotter is an apology."
    assert orp.strip_tags("Coffee <laugh>!") == "Coffee!"
    assert orp.tags_in("(sighs) No. [laugh]") == ["sigh", "laugh"]


# ---------------------------------------------------------------- voices
def test_voices_preset_matches_orpheus_speakers_and_kokoro_map():
    vs = load_presets()["voices"]
    assert [v["id"] for v in vs] == list(orp.VOICE_IDS)
    # each preset's Kokoro voice maps to it; older Kokoro ids (af_sarah, am_fenrir) still map for old projects
    assert {v["kokoro"]: v["id"] for v in vs}.items() <= orp.FROM_KOKORO.items()
    assert set(orp.FROM_KOKORO.values()) == set(orp.VOICE_IDS)
    assert all(v["gender"] in {"female", "male"} for v in vs)


def test_resolve_voice():
    assert orp.resolve_voice("Tara") == "tara"
    assert orp.resolve_voice("am_michael") == "leo"
    assert orp.resolve_voice(None) == orp.DEFAULT_VOICE
    assert orp.resolve_voice("bm_lewis") == orp.DEFAULT_VOICE   # Kokoro id with no twin
    with pytest.raises(ValueError):
        orp.resolve_voice("morgan_freeman")


def test_node_voice_list_matches_module():
    spec = importlib.util.spec_from_file_location("osn", ROOT / "custom_nodes/opensoul_nodes/nodes.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert m.ORPHEUS_VOICES == list(orp.VOICE_IDS)
    req = m.OpenSoulOrpheusTTS.INPUT_TYPES()["required"]
    assert req["voice"][0] == list(orp.VOICE_IDS) and req["voice"][1]["default"] == "tara"


# ---------------------------------------------------------------- token maths
def test_audio_codes_and_snac_layers():
    frame = [orp.AUDIO_OFFSET + k * orp.CODEBOOK + (10 + k) for k in range(7)]
    gen = [orp.START_SPEECH - 4, orp.START_SPEECH] + frame + frame + [orp.AUDIO_OFFSET + 1, orp.END_SPEECH, 99]
    codes = orp.audio_codes(gen)
    assert len(codes) == 14                       # the trailing partial frame is dropped
    l1, l2, l3 = orp.snac_layers(codes)
    assert l1 == [10, 10] and l2 == [11, 14, 11, 14] and l3 == [12, 13, 15, 16, 12, 13, 15, 16]


def test_prompt_wrapping():
    assert orp.prompt_text("(sighs) No.", "leah") == "leah: <sigh> No."
    assert orp.wrap_prompt([1, 2]) == [orp.START_HUMAN, 1, 2, orp.END_TEXT, orp.END_HUMAN]


# ---------------------------------------------------------------- shot plan
def test_plan_defaults_to_orpheus_and_keeps_tags_out_of_the_video_prompt(monkeypatch):
    monkeypatch.delenv("OPENSOUL_TTS", raising=False)
    plan = build_shot_plan(camera="static", line="(sighs) No. I will not let you drink that.", voice="tara")
    voice = plan["stages"][0]
    assert voice["stage"] == "voice" and voice["backend"] == "orpheus"
    assert voice["workflow"] == "workflows/03c_tts_orpheus_api.json"
    assert voice["inputs"] == {"text": "<sigh> No. I will not let you drink that.", "voice": "tara"}
    assert "<sigh>" not in plan["prompt"] and "(sighs)" not in plan["prompt"]
    assert 'saying: "No. I will not let you drink that."' in plan["prompt"]


def test_plan_with_kokoro_gets_words_and_kokoro_voice():
    plan = build_shot_plan(camera="static", line="Coffee! <laugh> We need coffee!", voice="zac", tts_backend="kokoro")
    v = plan["stages"][0]
    assert v["workflow"] == "workflows/03_tts_api.json"
    assert v["inputs"] == {"text": "Coffee! We need coffee!", "voice": "am_puck"}


def test_plan_maps_old_kokoro_voice_ids():
    plan = build_shot_plan(camera="static", line="Hi", voice="am_michael")
    assert plan["voice"] == "leo" and plan["stages"][0]["inputs"]["voice"] == "leo"
    with pytest.raises(KeyError):
        build_shot_plan(camera="static", line="Hi", voice="nobody")


def test_plan_tag_only_line_has_no_voice():
    assert [s["stage"] for s in build_shot_plan(camera="static", line="<sigh>")["stages"]] == ["video", "era"]


def test_estimate_seconds_counts_tags():
    from opensoul.speak import estimate_seconds

    assert estimate_seconds("<sigh> one two three four five six seven eight") > estimate_seconds(
        "one two three four five six seven eight")


def test_registry_default_voice_backend_is_orpheus(monkeypatch):
    from opensoul import models_registry as mr

    monkeypatch.delenv("OPENSOUL_TTS", raising=False)
    mr.clear_registry_cache()
    row = next(r for r in mr.stage_status() if r["id"] == "voice")
    assert row["default_backend"] == "orpheus"
    orp_b = next(b for b in row["backends"] if b["id"] == "orpheus")
    assert "Llama" in orp_b["license"]


# ---------------------------------------------------------------- per-character voices
def test_character_voice_defaults_and_save(tmp_path):
    assert cv.voice_for(tmp_path, "Lumi") == "tara"
    assert cv.voice_for(tmp_path, " mio ") == "leah"
    assert cv.voice_for(tmp_path, "REN") == "zac"
    assert cv.voice_for(tmp_path, "Kai") == orp.DEFAULT_VOICE
    assert cv.set_voice(tmp_path, "Kai", "Leo") == "leo"
    assert cv.voice_for(tmp_path, "kai") == "leo"
    assert json.loads((tmp_path / cv.FILENAME).read_text()) == {"kai": "leo"}
    with pytest.raises(ValueError):
        cv.set_voice(tmp_path, "Kai", "af_heart")
    (tmp_path / cv.FILENAME).write_text("not json")
    assert cv.voice_for(tmp_path, "Kai") == orp.DEFAULT_VOICE   # a broken file never breaks a render


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    monkeypatch.setattr(server, "LIBRARY", tmp_path / "library")
    return TestClient(server.app)


def _png() -> bytes:
    from PIL import Image

    b = io.BytesIO()
    Image.new("RGB", (64, 96), (90, 120, 160)).save(b, format="PNG")
    return b.getvalue()


def test_api_voices(client):
    d = client.get("/api/voices?name=Mio").json()
    assert [v["id"] for v in d["voices"]] == list(orp.VOICE_IDS)
    assert d["tags"] == list(orp.TAGS) and d["character_voice"] == "leah"
    assert client.get("/api/voices").json()["character_voice"] is None


def test_cast_voice_picker_api(client):
    r = client.post("/api/storyboard/cast", data={"name": "Kai", "consent": "true", "kind": "reference",
                                                  "description": "a courier in a yellow rain jacket"},
                    files={"image": ("kai.png", _png(), "image/png")})
    assert r.status_code == 200, r.text
    v = r.json()["character"]["voice"]
    assert v in orp.VOICE_IDS and v != orp.DEFAULT_VOICE  # a new character never borrows Lumi's voice
    r = client.put("/api/storyboard/cast/kai/voice", json={"voice": "dan"})
    assert r.status_code == 200 and r.json() == {"name": "Kai", "voice": "dan"}
    assert client.get("/api/storyboard/cast").json()["cast"][0]["voice"] == "dan"
    assert client.put("/api/storyboard/cast/Kai/voice", json={"voice": "nobody"}).status_code == 400
    assert client.put("/api/storyboard/cast/Zed/voice", json={"voice": "tara"}).status_code == 404


def test_api_shot_refuses_unknown_tag(client):
    r = client.post("/api/shot", json={"camera": "static", "line": "No. <smirk>"})
    assert r.status_code == 400 and "<smirk>" in r.json()["detail"]


# ---------------------------------------------------------------- UI, setup, docs
def test_line_editor_has_emotion_tag_buttons():
    html = (ROOT / "app/web/index.html").read_text()
    for t in ("sigh", "laugh", "chuckle", "gasp"):
        assert f'data-tag="{t}"' in html
    js = (ROOT / "app/web/static/app.js").read_text()
    assert "#tagBar [data-tag]" in js and "/api/voices" in js
    sbjs = (ROOT / "app/web/static/storyboard.js").read_text()
    assert "data-voice-for" in sbjs and "/voice`" in sbjs


def test_setup_script_and_download_group():
    setup = (ROOT / "scripts/setup_tts_orpheus.sh").read_text()
    assert "tts-envs/orpheus" in setup and "download_models.sh\" orpheus" in setup
    dl = (ROOT / "scripts/download_models.sh").read_text()
    assert "orpheus() {" in dl and "|orpheus|" in dl
    assert "18284d3efd9831d0a8409f5f5877c84bff69009df7c3db818e904dccea6b6c55" in dl


def test_built_with_llama_attribution():
    for f in ("docs/MODEL_STACK.md", "NOTICE", "README.md", "custom_nodes/opensoul_nodes/README.md"):
        assert "Built with Llama" in (ROOT / f).read_text(), f
    stack = (ROOT / "docs/MODEL_STACK.md").read_text()
    assert "Llama 3.2 Community License" in stack and "huggingface.co/canopylabs/orpheus-3b-0.1-ft" in stack
