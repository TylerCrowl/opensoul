"""App ↔ lip-sync adapter (opensoul/lipsync.py): frame maths, the 04b graph patch, stage plans, face check, sidecar.
Dry-run / plan tests only: nothing here touches a GPU, LatentSync or ComfyUI."""
import json
import math
from pathlib import Path

import pytest

from opensoul import lipsync as L

ROOT = Path(__file__).resolve().parents[1]
A2V = json.loads((ROOT / L.A2V_WORKFLOW).read_text())


@pytest.mark.parametrize("secs", [0.2, 1.0, 1.04, 2.5, 3.3, 7.77, 12.0])
def test_a2v_frames_is_8k_plus_1_and_covers_the_audio(secs):
    f = L.a2v_frames(secs)
    k = (f - 1) // 8
    assert f == 8 * k + 1 and k >= 1
    assert k == max(1, math.ceil((secs * 24 - 1) / 8))
    assert f / 24 >= secs - 1 / 24  # never shorter than the voice (to the frame)
    assert L.padded_seconds(secs) == f / 24


def test_workflow_node_ids_the_patch_relies_on():
    want = {L.N_IMAGE: "LoadImage", L.N_PROMPT: "CLIPTextEncode", L.N_VIDEO_LATENT: "EmptyLTXVLatentVideo",
            L.N_AUDIO_LATENT: "LTXVEmptyLatentAudio", L.N_AUDIO: "LoadAudio", L.N_OUT: "SaveVideo",
            L.FROZEN_AUDIO_NODE: "SetLatentNoiseMask", L.N_NOISE_1: "RandomNoise", L.N_NOISE_2: "RandomNoise"}
    assert {k: A2V[k]["class_type"] for k in want} == want
    assert all(A2V[n]["class_type"] == "LTXVConcatAVLatent" for n in L.AV_CONCAT_NODES)


def test_patched_graph_feeds_frozen_audio_into_base_and_refine_and_sets_both_lengths():
    st = L.a2v_stage(prompt="Lumi speaks.", audio_s=3.3, seed=9)
    g = L.patch_graph(A2V, st["inputs"])
    assert L.frozen_audio_feeds(g) == {"33": True, "42": True}
    f = L.a2v_frames(3.3)
    assert g["30"]["inputs"]["length"] == f and g["32"]["inputs"]["frames_number"] == f
    assert g["35"]["inputs"]["noise_seed"] == 9 and g["43"]["inputs"]["noise_seed"] == 9
    assert g["62"]["inputs"]["value"] == 0.0  # the mask keeps the voice latent frozen
    assert st["audio_from"] == "voice" and st["pad_audio_to_s"] == round(f / 24, 4)
    broken = json.loads(json.dumps(g))
    broken["42"]["inputs"]["audio_latent"] = ["39", 1]  # refine pass on generated audio: must be caught
    assert L.frozen_audio_feeds(broken) == {"33": True, "42": False}


def test_draft_is_tts_only():
    st, notes, mode = L.dialogue_stages(line="Hi <sigh> there.", voice="leo", quality="draft", backend="ltx_av",
                                        prompt="p", speaker="Bram", seed=1)
    assert mode == "tts_only" and [s["stage"] for s in st] == ["voice", "video", "mux"]
    assert "<sigh>" in st[0]["inputs"]["text"] and st[0]["inputs"]["voice"] == "leo"
    assert st[1]["workflow"] != L.A2V_WORKFLOW


def test_final_ltx_av_is_one_joint_pass_with_the_speaker_in_the_prompt():
    st, notes, mode = L.dialogue_stages(line="Whole milk. <chuckle>", voice="tara", quality="final", backend="ltx_av",
                                        prompt="At the counter.", speaker="Lumi", seed=3)
    assert mode == "ltx_a2v" and [s["stage"] for s in st] == ["voice", "video"]
    v = st[1]
    assert v["workflow"] == L.A2V_WORKFLOW and v["lipsync"] == "ltx_av"
    assert "Lumi is the one speaking" in v["inputs"]["20"]["text"] and "<chuckle>" not in v["inputs"]["20"]["text"]


def test_final_latentsync_stacks_on_a2v_only_when_installed():
    kw = dict(line="Go.", voice="tara", quality="final", backend="latentsync", prompt="p", speaker="Ren", seed=1)
    st, notes, mode = L.dialogue_stages(**kw, latentsync_installed=False)
    assert mode == "ltx_a2v" and any("isn't installed" in n for n in notes)
    st, notes, mode = L.dialogue_stages(**kw, latentsync_installed=True, face_box=(300, 200, 180, 220))
    assert mode == "ltx_a2v+latentsync" and st[-1]["stage"] == "lipsync" and st[-1]["face_box"] == [300, 200, 180, 220]


def test_face_size_thresholds_are_provisional_warn_and_block():
    assert L.face_check(None, "latentsync")["level"] == "unknown"
    assert L.face_check((0, 0, 200, 200), "latentsync")["level"] == "ok"
    assert L.FACE_WARN_PX == 128 and L.FACE_BLOCK_PX == 96
    assert L.face_check((0, 0, 120, 150), "latentsync")["level"] == "ok"   # 150 px: fine since the 128 px warn
    assert L.face_check((0, 0, 120, 127), "latentsync")["level"] == "warn"
    assert L.face_check((0, 0, 120, 96), "latentsync")["level"] == "warn"  # the block is strictly below 96
    assert L.face_check((0, 0, 80, 90), "latentsync")["level"] == "block"
    assert L.face_check((0, 0, 80, 90), "ltx_av")["level"] == "warn"  # only latentsync is blocked
    st, notes, mode = L.dialogue_stages(line="Go.", voice="tara", quality="final", backend="latentsync", prompt="p",
                                        speaker="Ren", seed=1, latentsync_installed=True, face_box=(0, 0, 60, 80))
    assert mode == "ltx_a2v" and any("too small" in n for n in notes)


def test_bad_tag_and_bad_backend_are_refused():
    from opensoul.orpheus import TagError

    with pytest.raises(TagError):
        L.dialogue_stages(line="hi <scream>", voice="tara", quality="final", backend="ltx_av", prompt="", speaker="", seed=1)
    with pytest.raises(ValueError):
        L.check_backend("wav2lip")


def test_sidecar_keys_and_missing_sidecar(tmp_path):
    out = tmp_path / "take.mp4"
    assert L.read_sidecar(out) is None
    Path(str(out) + ".lipsync.json").write_text(json.dumps({"face_found_ratio": 0.97, "held_frames": 3, "frames": 121,
        "detector_counts": {"mediapipe": 110, "anime_fallback": 8, "held": 3, "none": 0}, "face_px_median": 212,
        "extra": "ignored"}))
    s = L.read_sidecar(out)
    assert set(s) == set(L.SIDECAR_KEYS) and s["face_found_ratio"] == 0.97 and "extra" not in s and s["seed"] is None


def test_placeholder_voice_is_audible_and_padding_never_stretches(tmp_path):
    from opensoul import media

    if not media.ffmpeg_bin():
        pytest.skip("no ffmpeg")
    w = L.placeholder_voice(tmp_path / "v.wav", 1.3)
    assert abs(media.duration(w) - 1.3) < 0.06
    p = L.pad_audio(w, tmp_path / "p.wav", L.padded_seconds(1.3))
    assert abs(media.duration(p) - L.padded_seconds(1.3)) < 0.06


def test_post_lipsync_dry_run_muxes_and_ltx_av_is_not_a_post_step(tmp_path):
    from opensoul import media

    if not media.ffmpeg_bin():
        pytest.skip("no ffmpeg")
    from PIL import Image

    Image.new("RGB", (64, 64), "gray").save(tmp_path / "s.png")
    clip = media.still_to_clip(tmp_path / "s.png", tmp_path / "c.mp4", seconds=1.0, width=64, height=64)
    wav = L.placeholder_voice(tmp_path / "v.wav", 1.0)
    r = L.lipsync(L.LipSyncRequest(audio=wav, dest=tmp_path / "o.mp4", backend="latentsync", video=clip), dry_run=True)
    assert r.placeholder and r.video.is_file()
    with pytest.raises(ValueError):
        L.lipsync(L.LipSyncRequest(audio=wav, dest=tmp_path / "x.mp4", backend="ltx_av"), dry_run=True)
    with pytest.raises(L.LipSyncError) as e:
        L.lipsync(L.LipSyncRequest(audio=wav, dest=tmp_path / "y.mp4", backend="latentsync", video=clip,
                                   face_box=(0, 0, 50, 50)), dry_run=True)
    assert e.value.code == "face_too_small"


def test_latentsync_without_a_face_box_and_two_people_is_ambiguous():
    st, notes, mode = L.dialogue_stages(line="Go.", voice="tara", quality="final", backend="latentsync", prompt="p",
                                        speaker="Ren", seed=1, latentsync_installed=True, faces=2)
    assert mode == "ltx_a2v" and any("Several faces" in n for n in notes)
