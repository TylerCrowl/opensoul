"""Voice engines per story + per-character reference clips (docs/VOICE_ENGINE_PROPOSAL.md). Older stories and packs
stay on Orpheus; new stories take presets/voice_engine.json tts_default_new (VoxCPM2; rollback
OPENSOUL_TTS_DEFAULT=orpheus). A VoxCPM2 line whose speaker has no usable clip is spoken with Orpheus, with a note."""
from __future__ import annotations

import io
import json
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opensoul import lipsync as L
from opensoul import speak
from opensoul import storyboard as sb
from opensoul import voice_engine as VE

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("OPENSOUL_TTS", raising=False)
    monkeypatch.delenv("OPENSOUL_TTS_DEFAULT", raising=False)


def _wav(secs: float, sr: int = 16000) -> bytes:
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(b"\0\0" * int(secs * sr))
    return b.getvalue()


def _pack(tmp_path, **voice) -> tuple[Path, dict]:
    d = tmp_path / "packs" / "Lumi"
    (d / "voice").mkdir(parents=True)
    (d / "voice" / "ref.wav").write_bytes(_wav(6))
    v = {"ref_clip": "voice/ref.wav", "ref_text": "hi", "ref_made_with": "voice-design model", "consent": True, **voice}
    return d, {"voice": v}


def test_new_stories_default_comes_from_the_preset_and_is_voxcpm2(monkeypatch, tmp_path):
    assert json.loads((ROOT / "presets/voice_engine.json").read_text())["tts_default_new"] == "voxcpm2"
    assert VE.default_for_new() == "voxcpm2"
    assert sb.Store(tmp_path / "data").create_project("Fresh").tts_engine == "voxcpm2"
    monkeypatch.setenv("OPENSOUL_TTS_DEFAULT", "orpheus")  # rollback for new stories
    assert VE.default_for_new() == "orpheus"
    assert sb.Store(tmp_path / "data").create_project("Rolled back").tts_engine == "orpheus"


def test_flipping_the_preset_or_env_changes_only_new_stories(monkeypatch, tmp_path):
    p = tmp_path / "voice_engine.json"
    p.write_text(json.dumps({"tts_default_new": "voxcpm2"}))
    monkeypatch.setattr(VE, "PRESET", p)
    assert VE.default_for_new() == "voxcpm2"
    assert sb.Store(tmp_path / "data").create_project("New one").tts_engine == "voxcpm2"
    monkeypatch.setenv("OPENSOUL_TTS_DEFAULT", "chatterbox")
    assert VE.default_for_new() == "chatterbox"
    # An older story file (no tts_engine) still loads as Orpheus whatever the new-story default is.
    old = sb.Project.from_dict({"id": "x", "title": "Old", "character": "Lumi"})
    assert old.tts_engine is None and VE.engine_for(old.tts_engine, {}) == "orpheus"


def test_engine_order_force_then_pack_pin_then_story(monkeypatch):
    assert VE.engine_for(None, None) == "orpheus"
    assert VE.engine_for("voxcpm2", {}) == "voxcpm2"
    assert VE.engine_for("voxcpm2", {"voice": {"engine": "chatterbox"}}) == "chatterbox"
    monkeypatch.setenv("OPENSOUL_TTS", "orpheus")  # rollback switch
    assert VE.engine_for("voxcpm2", {"voice": {"engine": "chatterbox"}}) == "orpheus"
    with pytest.raises(ValueError):
        VE.check("nope")


def test_reference_clip_needs_consent_provenance_and_the_same_file(tmp_path):
    d, pack = _pack(tmp_path)
    r = VE.ref_for("voxcpm2", pack, d)
    assert r["clip"].endswith("voice/ref.wav") and r["text"] == "hi" and len(r["sha256"]) == 64
    assert VE.ref_for("orpheus", pack, d) is None and VE.ref_for("voxcpm2", {}, d) is None
    for bad in ({"consent": False}, {"ref_made_with": ""}, {"ref_sha256": "0" * 64}, {"ref_clip": "voice/none.wav"},
                {"ref_clip": "../../outside.wav"}):
        with pytest.raises(VE.VoiceRefError):
            VE.ref_for("chatterbox", {"voice": {**pack["voice"], **bad}}, d)


def test_voxcpm_gets_the_plain_words():
    assert VE.voxcpm_text("<sigh> Fine. <laugh> Okay.") == "Fine. Okay."
    assert VE.voxcpm_text("Plain words.") == "Plain words."
    assert VE.engine_text("orpheus", "<sigh> Fine.") == "<sigh> Fine."
    assert VE.engine_text("chatterbox", "<sigh> Fine.") == "Fine."
    assert VE.engine_voice("kokoro", "tara") == "af_heart" and VE.engine_voice("voxcpm2", "tara") == "tara"


def test_dialogue_stage_carries_engine_and_clip(tmp_path):
    d, pack = _pack(tmp_path)
    ref = VE.ref_for("voxcpm2", pack, d)
    stages, _, _ = L.dialogue_stages(line="<sigh> Whole milk.", voice="tara", quality="final", backend="ltx_av",
                                     prompt="a barista", speaker="Lumi", seed=7, tts_backend="voxcpm2", ref=ref)
    v = stages[0]
    assert v["backend"] == "voxcpm2" and v["inputs"]["text"] == "Whole milk."
    assert v["inputs"]["ref"]["clip"] == ref["clip"]
    stages, _, _ = L.dialogue_stages(line="<sigh> Whole milk.", voice="tara", quality="draft", backend="ltx_av",
                                     prompt="a barista", speaker="Lumi", seed=7)
    assert stages[0]["backend"] == "orpheus" and "ref" not in stages[0]["inputs"]


def test_voxcpm2_backend_preview_and_live_routing(monkeypatch, tmp_path):
    tts = speak.get_tts(dry_run=True, name="voxcpm2")
    assert isinstance(tts, speak.VoxCPM2TTS) and "voxcpm2" in speak.TTS_BACKENDS
    out = tts.synthesize("<sigh> Hello there.", "tara", tmp_path / "a.wav")
    assert Path(out).read_bytes()[:4] == b"RIFF"
    calls = []
    monkeypatch.setattr(speak, "_run_sdk", lambda wf, inputs, node, dest, what: calls.append((wf, inputs)) or dest)
    speak.VoxCPM2TTS(dry_run=False).synthesize("<sigh> Hi.", "tara", tmp_path / "b.wav")
    speak.VoxCPM2TTS(dry_run=False).synthesize("Hi.", "tara", tmp_path / "c.wav", ref={"clip": "/x/ref.wav", "text": "t"})
    speak.ChatterboxTTS(dry_run=False).synthesize("<sigh> Hi.", "tara", tmp_path / "d.wav", ref={"clip": "/x/ref.wav"})
    assert calls[0] == ("03d_tts_voxcpm2_api.json", {"1": {"text": "Hi.", "seed": 0}})
    assert calls[1][0] == "03d_tts_voxcpm2_ref_api.json" and calls[1][1]["3"] == {"audio": "/x/ref.wav"}
    assert calls[2] == ("03b_tts_chatterbox_ref_api.json", {"1": {"text": "Hi."}, "3": {"audio": "/x/ref.wav"}})
    for wf in ("03d_tts_voxcpm2_api", "03d_tts_voxcpm2_ref_api", "03b_tts_chatterbox_ref_api"):
        g = json.loads((ROOT / f"workflows/{wf}.json").read_text())
        assert g["2"]["class_type"] == "SaveAudio" and (ROOT / f"workflows/{wf}.meta.json").is_file()
        if "ref" in wf:
            assert g["3"]["class_type"] == "LoadAudio" and g["1"]["inputs"]["voice_reference"] == ["3", 0]
    assert (ROOT / "custom_nodes/opensoul_nodes/runners/voxcpm2_tts.py").is_file()


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    monkeypatch.setattr(server, "LIBRARY", tmp_path / "library")
    return TestClient(server.app)


def test_api_story_engine_and_voice_clip(monkeypatch, tmp_path):
    import app.storyboard_api as api

    c = _client(monkeypatch, tmp_path)
    p = c.post("/api/storyboard/projects", json={"title": "Diner", "shots": [
        {"beat": "Counter", "characters": ["Lumi"], "line": "<sigh> Whole milk.", "speaker": "Lumi"}]}).json()
    assert p["tts_engine"] == "voxcpm2" and p["voice_engine"] == "voxcpm2"  # new stories: VoxCPM2
    pid, sid = p["id"], p["shots"][0]["id"]
    r = c.post(f"/api/storyboard/projects/{pid}/shots/{sid}/speak", json={})  # fresh install: no clip yet
    assert r.status_code == 200 and r.json()["voice_engine"] == "orpheus" and "Orpheus" in r.json()["voice_note"]
    assert c.patch(f"/api/storyboard/projects/{pid}", json={"tts_engine": "nope"}).status_code == 400
    assert c.patch(f"/api/storyboard/projects/{pid}", json={"tts_engine": "voxcpm2"}).json()["voice_engine"] == "voxcpm2"
    d = tmp_path / "packs" / "Lumi"
    d.mkdir(parents=True)
    (d / "pack.json").write_text(json.dumps({"name": "Lumi"}))
    monkeypatch.setattr(api, "_resolve_pack", lambda name, packs=None: {"name": "Lumi", "pack_dir": str(d)})
    url = "/api/storyboard/cast/Lumi/voice-clip"
    files = {"clip": ("ref.wav", _wav(6), "audio/wav")}
    assert c.put(url, files=files, data={"made_with": "voice-design model"}).status_code == 400  # no consent
    assert c.put(url, files=files, data={"consent": "true"}).status_code == 400  # no provenance
    short = {"clip": ("ref.wav", _wav(2), "audio/wav")}
    assert c.put(url, files=short, data={"consent": "true", "made_with": "x"}).status_code == 400
    r = c.put(url, files=files, data={"consent": "true", "made_with": "voice-design model", "ref_text": "hi"})
    assert r.status_code == 200, r.text
    v = json.loads((d / "pack.json").read_text())["voice"]
    assert v["consent"] and v["ref_clip"] == "voice/ref.wav" and v["orpheus_voice"] == "tara" and len(v["ref_sha256"]) == 64
    r = c.post(f"/api/storyboard/projects/{pid}/shots/{sid}/speak", json={}).json()
    assert r["voice_engine"] == "voxcpm2" and r["placeholder"] and r["voice_note"] == ""
    v["consent"] = False  # consent withdrawn: the line falls back to Orpheus and says so, the clip is never used
    (d / "pack.json").write_text(json.dumps({"voice": v}))
    r = c.post(f"/api/storyboard/projects/{pid}/shots/{sid}/speak", json={})
    assert r.status_code == 200 and r.json()["voice_engine"] == "orpheus" and "consent" in r.json()["voice_note"]
    c.patch(f"/api/storyboard/projects/{pid}", json={"tts_engine": "chatterbox"})  # Chatterbox: still a plain 400
    assert c.post(f"/api/storyboard/projects/{pid}/shots/{sid}/speak", json={}).status_code == 400


def test_voxcpm2_without_a_usable_clip_falls_back_to_orpheus_with_a_note(tmp_path, monkeypatch):
    # No clip saved (a fresh install's demo packs have none): Orpheus, and the note says why.
    e, ref, note = VE.resolve("voxcpm2", {}, None, who="Mio")
    assert (e, ref) == ("orpheus", None) and note.startswith("Mio is spoken with Orpheus") and "consent" in note
    e, ref, note = VE.resolve("voxcpm2", {"voice": {"ref_clip": "voice/x.wav"}}, tmp_path, who="Ren")  # no consent
    assert (e, ref) == ("orpheus", None) and "consent" in note
    d, pack = _pack(tmp_path)
    e, ref, note = VE.resolve("voxcpm2", pack, d, who="Lumi")  # usable clip: VoxCPM2, no note
    assert e == "voxcpm2" and ref["clip"].endswith("voice/ref.wav") and note == ""
    (d / "voice" / "ref.wav").write_bytes(_wav(7))  # changed since saved: fallback, not a failed take
    e, ref, note = VE.resolve("voxcpm2", {"voice": {**pack["voice"], "ref_sha256": "0" * 64}}, d, who="Lumi")
    assert e == "orpheus" and "changed" in note
    # Older stories (no engine saved) and Orpheus stories: unchanged, no note.
    assert VE.resolve(None, {}, None) == ("orpheus", None, "")
    assert VE.resolve("orpheus", pack, d) == ("orpheus", None, "")
    # Chatterbox keeps its old behaviour: no clip = its shared voice; an unusable clip stops the take.
    assert VE.resolve("chatterbox", {}, None) == ("chatterbox", None, "")
    with pytest.raises(VE.VoiceRefError):
        VE.resolve("chatterbox", {"voice": {"ref_clip": "voice/x.wav"}}, tmp_path)
    monkeypatch.setenv("OPENSOUL_TTS", "orpheus")  # the every-line rollback still wins
    assert VE.resolve("voxcpm2", pack, d)[0] == "orpheus"
