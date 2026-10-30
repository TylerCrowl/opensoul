"""Dialogue through the takes (dry run): Speak preview, Draft = voice only, Final = LTX a2v job spec (+LatentSync)."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opensoul import lipsync as L
from opensoul import media
from opensoul import storyboard as sb

needs_ffmpeg = pytest.mark.skipif(not media.ffmpeg_bin(), reason="no ffmpeg")


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    monkeypatch.setenv("OPENSOUL_SHEET_SYNC", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    monkeypatch.setattr(server, "LIBRARY", tmp_path / "library")
    return TestClient(server.app)


def _shot(c, **kw):
    p = c.post("/api/storyboard/projects", json={"title": "Diner", "shots": [{"beat": "Counter", "characters": ["Lumi", "Bram"],
                                                                           "line": "Whole milk. <chuckle> Obviously.", "speaker": "Lumi", **kw}]}).json()
    return p["id"], p["shots"][0]["id"]


def _last(c, pid, sid):
    s = c.get(f"/api/storyboard/projects/{pid}").json()["shots"][0]
    return s, s["versions"][-1]


@needs_ffmpeg
def test_speak_preview_is_a_placeholder_wav_with_the_characters_voice(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    pid, sid = _shot(c)
    from opensoul.character_voices import set_voice

    set_voice(tmp_path, "Lumi", "leah")  # the character's own voice (what PUT /cast/{name}/voice saves)
    r = c.post(f"/api/storyboard/projects/{pid}/shots/{sid}/speak", json={}).json()
    assert r["placeholder"] and r["voice"] == "leah" and r["speaker"] == "Lumi" and r["seconds"] > 1
    f = c.get(r["audio_url"])
    assert f.status_code == 200 and f.content[:4] == b"RIFF"
    r = c.post(f"/api/storyboard/projects/{pid}/shots/{sid}/speak", json={"line": "Unsaved (sighs) try", "voice": "zac"}).json()
    assert r["voice"] == "zac" and r["line"] == "Unsaved <sigh> try"
    assert c.post(f"/api/storyboard/projects/{pid}/shots/{sid}/speak", json={"line": "<scream>"}).status_code == 400
    assert c.post(f"/api/storyboard/projects/{pid}/shots/{sid}/speak", json={"line": " "}).status_code == 400


@needs_ffmpeg
def test_draft_take_is_voice_only_with_sound(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    pid, sid = _shot(c)
    assert c.post(f"/api/storyboard/projects/{pid}/shots/{sid}/regenerate", json={"quality": "draft"}).status_code == 200
    s, v = _last(c, pid, sid)
    d = v["settings"]["dialogue"]
    assert d["mode"] == "tts_only" and "voice only" in v["label"]
    assert [x["stage"] for x in v["settings"]["job"]["stages"]] == ["voice", "video", "mux"]
    import subprocess

    probe = subprocess.run([media.ffmpeg_bin(), "-i", str(sb.abs_path(v["file"]))], capture_output=True, text=True).stderr
    assert "Audio:" in probe


@needs_ffmpeg
def test_final_take_is_ltx_a2v_spec_routed_to_04b_with_the_voice(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    pid, sid = _shot(c)
    c.post(f"/api/storyboard/projects/{pid}/shots/{sid}/regenerate", json={"quality": "final", "seed": 77})
    s, v = _last(c, pid, sid)
    d, job = v["settings"]["dialogue"], v["settings"]["job"]
    assert d["mode"] == "ltx_a2v" and d["backend"] == "ltx_av" and "LTX audio+video" in v["label"]
    vid = job["stages"][1]
    assert vid["workflow"] == L.A2V_WORKFLOW and vid["audio_from"] == "voice"
    g = L.patch_graph(json.loads((Path(__file__).resolve().parents[1] / L.A2V_WORKFLOW).read_text()), vid["inputs"])
    assert L.frozen_audio_feeds(g) == {"33": True, "42": True}
    assert g["30"]["inputs"]["length"] == g["32"]["inputs"]["frames_number"] == vid["frames"]
    assert g["35"]["inputs"]["noise_seed"] == 77 and "Lumi is the one speaking" in g["20"]["inputs"]["text"]
    assert media.duration(sb.abs_path(v["file"])) == pytest.approx(vid["frames"] / 24, abs=0.15)


@needs_ffmpeg
def test_final_latentsync_option_and_lipsync_off(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    pid, sid = _shot(c, lipsync_backend="latentsync", face_box=[300, 200, 180, 220])
    monkeypatch.setattr(L, "latentsync_installed", lambda: True)
    c.post(f"/api/storyboard/projects/{pid}/shots/{sid}/regenerate", json={"quality": "final"})
    s, v = _last(c, pid, sid)
    assert v["settings"]["dialogue"]["mode"] == "ltx_a2v+latentsync"
    assert v["settings"]["job"]["stages"][-1] == {"stage": "lipsync", "backend": "latentsync", "workflow": L.LATENTSYNC_WORKFLOW,
                                                  "speaker": "Lumi", "face_box": [300, 200, 180, 220]}
    c.post(f"/api/storyboard/projects/{pid}/shots/{sid}/regenerate", json={"quality": "final", "lipsync": False})
    s, v = _last(c, pid, sid)
    assert v["settings"]["dialogue"]["mode"] == "tts_only" and "off for this shot" in v["note"]
    assert s["lipsync"] is True  # a per-take override doesn't change the shot


def test_live_plan_swaps_in_the_dialogue_stages(monkeypatch, tmp_path):
    """Studio mode builds the a2v plan (checked without running it: run_shot is stubbed)."""
    c = _client(monkeypatch, tmp_path)
    pid, sid = _shot(c)
    import app.server as server
    import opensoul.shot as shot_mod

    seen = {}
    monkeypatch.setattr(server, "_dry", lambda: False)
    monkeypatch.setattr(server, "_start", lambda fn: None)
    from PIL import Image

    Image.new("RGB", (64, 64)).save(tmp_path / "base.png")
    import app.storyboard_api as api

    monkeypatch.setattr(api, "_base_still", lambda *a, **k: tmp_path / "base.png")
    monkeypatch.setattr(shot_mod, "run_shot", lambda plan, *a, **k: seen.setdefault("plan", plan))
    r = c.post(f"/api/storyboard/projects/{pid}/shots/{sid}/regenerate", json={"quality": "final"})
    assert r.status_code == 200, r.text
    s, v = _last(c, pid, sid)
    assert v["status"] == "rendering" and "LTX audio+video" in v["label"]
    assert [x["stage"] for x in v["settings"]["job"]["stages"]] == ["voice", "video"]


@needs_ffmpeg
def test_run_shot_dry_a2v_pads_the_voice_and_mux_stage(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    from PIL import Image

    from opensoul.shot import run_shot

    Image.new("RGB", (64, 64), "gray").save(tmp_path / "s.png")
    st, _, _ = L.dialogue_stages(line="Hello there friend.", voice="tara", quality="final", backend="ltx_av",
                                 prompt="p", speaker="Ren", seed=1)

    class Tts:
        name = "fake"

        def synthesize(self, text, voice, dest):
            return L.placeholder_voice(dest, 1.1)

    res = run_shot({"stages": st}, tmp_path / "s.png", tmp_path / "o", tts=Tts())
    shaped = next(x for x in res.steps if x["stage"] == "voice_shape")  # OS-056/059: sized to the real voice
    assert media.duration(tmp_path / "o" / "voice_padded.wav") == pytest.approx(shaped["frames"] / 24, abs=0.05)
    assert shaped["speech_end"] == pytest.approx(1.1, abs=0.03) and (shaped["frames"] - 1) % 8 == 0
    st2, _, _ = L.dialogue_stages(line="Hi.", voice="tara", quality="draft", backend="ltx_av", prompt="p", speaker="", seed=1,
                                  i2v_stage={"stage": "video", "workflow": "workflows/04_i2v_ltx_api.json", "params": {"duration_s": 2}})
    res = run_shot({"stages": st2}, tmp_path / "s.png", tmp_path / "o2", tts=Tts())
    assert res.video.name == "with_voice.mp4"


@needs_ffmpeg
def test_latentsync_fallback_reason_is_on_the_take(monkeypatch, tmp_path):
    """LatentSync picked but skipped (face too small / not installed): the take carries the reason for the label."""
    c = _client(monkeypatch, tmp_path)
    pid, sid = _shot(c, lipsync_backend="latentsync", face_box=[300, 260, 70, 84])
    monkeypatch.setattr(L, "latentsync_installed", lambda: True)
    c.post(f"/api/storyboard/projects/{pid}/shots/{sid}/regenerate", json={"quality": "final"})
    s, v = _last(c, pid, sid)
    assert "too small" in v["settings"]["dialogue"]["fallback"]
    monkeypatch.setattr(L, "latentsync_installed", lambda: False)
    c.patch(f"/api/storyboard/projects/{pid}/shots/{sid}", json={"face_box": [300, 200, 180, 220]})
    c.post(f"/api/storyboard/projects/{pid}/shots/{sid}/regenerate", json={"quality": "final"})
    s, v = _last(c, pid, sid)
    assert "isn't installed" in v["settings"]["dialogue"]["fallback"]
    c.patch(f"/api/storyboard/projects/{pid}/shots/{sid}", json={"lipsync_backend": "ltx_av"})
    c.post(f"/api/storyboard/projects/{pid}/shots/{sid}/regenerate", json={"quality": "final"})
    s, v = _last(c, pid, sid)
    assert v["settings"]["dialogue"]["fallback"] == ""  # LTX chosen: nothing fell back


def test_take_label_shows_the_fallback_inline():
    js = (Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "storyboard.js").read_text()
    body = js[js.index("function renderSheet()"):]
    body = body[:body.index("$(\"sbSheetBody\").innerHTML")]
    assert "dialogue || {}).fallback" in body and 'class="sb-fallback"' in body and "LatentSync not used:" in body
