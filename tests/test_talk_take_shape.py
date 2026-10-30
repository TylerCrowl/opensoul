"""Talking takes (anime trailer issues): short silence around the line (OS-056), the take as long as the planned
length with a closed-mouth hold (OS-059), mouth words in the change are not used (OS-060), a new video wins over a
still keeper (OS-058), and best-of is off without a scorer (OS-057)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from opensoul import lipsync as L
from opensoul import media
from opensoul import voice_shape as V

ROOT = Path(__file__).resolve().parents[1]
needs_ffmpeg = pytest.mark.skipif(not media.ffmpeg_bin(), reason="no ffmpeg")


def _tts_like(path: Path, lead=0.41, words=(1.2, 0.3, 0.8), tail=0.63) -> Path:
    """A Kokoro-like clip: silence, word, pause, word, silence."""
    sr = V.SR
    parts = [np.zeros(int(lead * sr), np.float32)]
    for i, d in enumerate(words):
        n = int(d * sr)
        parts.append((0.3 * np.sin(2 * np.pi * 220 * np.arange(n) / sr)).astype(np.float32) if i % 2 == 0
                     else np.zeros(n, np.float32))
    parts.append(np.zeros(int(tail * sr), np.float32))
    return V.write_mono(path, np.concatenate(parts))


@needs_ffmpeg
def test_lead_and_tail_silence_are_trimmed_and_the_pause_is_found(tmp_path):
    src = _tts_like(tmp_path / "v.wav")
    out = V.shape_voice(src, tmp_path / "p.wav")
    assert out["speech_start"] == pytest.approx(V.LEAD_S, abs=0.02)
    assert out["speech_end"] == pytest.approx(V.LEAD_S + 2.3, abs=0.03)
    assert out["cut_lead_s"] == pytest.approx(0.31, abs=0.02) and out["cut_tail_s"] == pytest.approx(0.48, abs=0.03)
    assert out["pauses"] and out["pauses"][0][1] - out["pauses"][0][0] == pytest.approx(0.3, abs=0.03)
    # auto length: the line and a short hold, 8k+1 frames
    assert (out["frames"] - 1) % 8 == 0 and out["seconds"] < 3.1
    assert media.duration(tmp_path / "p.wav") == pytest.approx(out["frames"] / 24, abs=0.02)


@needs_ffmpeg
def test_the_take_is_as_long_as_the_planned_length(tmp_path):
    src = _tts_like(tmp_path / "v.wav", words=(1.5,))
    out = V.shape_voice(src, tmp_path / "p.wav", target_s=5)
    assert out["frames"] == 121 and media.duration(tmp_path / "p.wav") == pytest.approx(121 / 24, abs=0.02)
    short = V.shape_voice(src, tmp_path / "q.wav", target_s=1)  # never shorter than the line
    assert short["seconds"] >= short["speech_end"] + 0.3
    keep = V.shape_voice(src, tmp_path / "r.wav", min_frames=145)  # a camera stack's minimum stays
    assert keep["frames"] == 145


def test_hold_guide_after_the_line_and_the_graph_wiring():
    stage = L.a2v_stage(prompt="p", audio_s=2.0, seed=1, target_s=5, shape=True)
    assert stage["shape_voice"] and stage["target_s"] == 5 and stage["frames"] == 121
    fit = L.fit_a2v_to_voice({**stage, "cam_lock": True},
                             {"file": "/x.wav", "frames": 121, "speech_start": 0.1, "speech_end": 1.6, "pauses": []})
    assert fit["inputs"][L.N_VIDEO_LATENT]["length"] == 121 and fit["inputs"][L.N_AUDIO_LATENT]["frames_number"] == 121
    assert fit["hold_guide"]["frame_idx"] == int(np.ceil((1.6 + L.HOLD_AFTER_S) * 24))
    assert L.hold_frame(1.6, 49) is None  # less than 0.5 s of silence after the line: no hold guide
    g = json.loads((ROOT / L.A2V_WORKFLOW).read_text())
    g = L.apply_hold_guide(L.apply_cam_lock(g), 45)
    hold = g["96"]
    assert hold["class_type"] == "LTXVAddGuide" and hold["inputs"]["frame_idx"] == 45
    assert hold["inputs"]["latent"] == ["93", 2] and hold["inputs"]["image"] == ["3", 0]
    assert g["33"]["inputs"]["video_latent"] == ["96", 2]
    assert g["34"]["inputs"]["positive"] == ["96", 0] and g["94"]["inputs"]["negative"] == ["96", 1]


def test_talk_prompt_asks_for_closed_still_lips_in_silence():
    out = L.speaker_prompt("Close-up.", "Aldric", "Every war is a game.", "he")
    assert out.endswith("Before the first word, in each pause and after the last word, his lips are closed and still.")
    assert L.silent_mouth(out, "he").count(L.SILENT_MOUTH_MARK) == 1


def test_mouth_words_in_the_change_are_not_used_on_a_talking_shot():
    from app.storyboard_api import _dropped_note, _talk_edit
    from opensoul import storyboard as sb

    s = sb.Shot(id="s1", beat="b", characters=["Bastian"], line="Come home, Aldric. Please.")
    edit = ("Serious, pleading face, no smile. His lips press fully shut on the m of home and the p of please, "
            "and stay shut after the last word.")
    used, left = _talk_edit(s, edit)
    assert used == "Serious, pleading face, no smile." and left and "lips press" in left[0]
    assert "voice moves the mouth" in _dropped_note(s, edit)
    silent = sb.Shot(id="s2", beat="b", characters=["Bastian"])
    assert _talk_edit(silent, "lips shut")[0] == "lips shut"  # no line: the change is used as typed


def test_best_of_is_off_and_said_so_without_a_scorer():
    st, notes, _ = L.dialogue_stages(line="Hello there.", voice="tara", quality="final", backend="ltx_av",
                                     prompt="p", speaker="Lumi", seed=1, best_of=3, scorer_ready=False)
    assert "best_of" not in st[1] and any(n.startswith("Best of 3 is off") for n in notes)
    st, notes, _ = L.dialogue_stages(line="Hello there.", voice="tara", quality="final", backend="ltx_av",
                                     prompt="p", speaker="Lumi", seed=1, best_of=3, scorer_ready=True)
    assert st[1]["best_of"] == 3


def test_planned_length_is_saved_and_checked(tmp_path):
    from opensoul import storyboard as sb

    st = sb.Store(tmp_path)
    p = st.create_project("Len")
    s = st.add_shot(p.id, "Talk", characters=["Rhea"], line="We take back the sky.", seconds=5)
    assert s.seconds == 5.0
    assert st.update_shot(p.id, s.id, seconds=0).seconds == 0.0
    with pytest.raises(sb.StoryError):
        st.update_shot(p.id, s.id, seconds=40)


def test_a_new_video_take_becomes_the_keeper_over_a_still(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    monkeypatch.setenv("OPENSOUL_SHEET_SYNC", "1")
    from fastapi.testclient import TestClient
    from PIL import Image

    import app.server as server
    from app import storyboard_api as A
    from opensoul import storyboard as sb

    monkeypatch.setattr(server, "DATA", tmp_path)
    monkeypatch.setattr(server, "LIBRARY", tmp_path / "library")
    st = sb.Store(tmp_path / "projects")
    monkeypatch.setattr(A, "_store", lambda: st)
    p = st.create_project("Keeper test")
    s = st.add_shot(p.id, "Close-up", prompt="Aldric in the war room.", characters=[])
    pic = tmp_path / "f.png"
    Image.new("RGB", (64, 36), (90, 90, 90)).save(pic)
    for _ in range(2):  # v1 (the keeper, a bad frame) and v2 (a better frame)
        st.add_version(p.id, s.id, take=st.reserve_take(p.id, s.id), file=sb.rel_path(pic), poster=sb.rel_path(pic),
                       prompt="Start frame", kind="frame", label="Start frame")
    shot = st.load(p.id).shots[0]
    assert shot.keeper == "v1"
    c = TestClient(server.app)
    r = c.post(f"/api/storyboard/projects/{p.id}/shots/{s.id}/regenerate", json={"quality": "final", "from_version": "v2"})
    assert r.status_code == 200, r.text
    shot = r.json()["shots"][0]
    assert shot["keeper"] == shot["versions"][-1]["id"] != "v1"  # OS-058
    r = c.post(f"/api/storyboard/projects/{p.id}/shots/{s.id}/regenerate", json={"quality": "final", "from_version": "v2"})
    shot = r.json()["shots"][0]
    assert shot["keeper"] == "v3"  # a video keeper stays
