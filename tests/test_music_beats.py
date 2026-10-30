"""Beat, bar and section detection on synthetic click tracks made in the test (original audio, no recordings)."""
import wave

import numpy as np
import pytest

from opensoul.music import beats as B


def _check(bpm, lead, tol_bpm=0.02, tol_s=0.035):
    y = B.click_track(bpm=bpm, bars=24, lead_in_s=lead, sections=[(8, "a"), (8, "b"), (8, "a")])
    bm = B.analyze_samples(y)
    expect = [lead + k * 60.0 / bpm for k in range(96)]
    assert abs(bm.tempo_bpm - bpm) / bpm < tol_bpm, bm.tempo_bpm
    assert len(bm.beats) >= 94
    assert max(min(abs(b - e) for e in expect) for b in bm.beats) < tol_s
    return bm


@pytest.mark.parametrize("bpm,lead", [(90, 0.37), (120, 0.5), (140, 1.0)])
def test_tempo_and_beats_on_a_click_track(bpm, lead):
    _check(bpm, lead)


def test_bar_one_is_the_accented_click_and_sections_follow_the_sound():
    bm = _check(120, 0.5)
    assert abs(bm.bars[0] - 0.5) < 0.035 and abs(bm.bars[1] - 2.5) < 0.035
    assert [(s.label, s.start_bar, s.end_bar) for s in bm.sections] == [("A", 0, 8), ("B", 8, 16), ("A", 16, 24)]
    loud = {s.label: s.energy for s in bm.sections}
    assert loud["B"] > loud["A"]


def test_wav_files_any_width_rate_and_channels(tmp_path):
    y = B.click_track(bpm=100, bars=8, lead_in_s=0.4)
    p = B.write_wav(tmp_path / "mono.wav", y)
    assert abs(B.analyze(p).tempo_bpm - 100) < 2
    # 44.1 kHz stereo 16-bit
    up = np.interp(np.arange(int(len(y) * 2)) / 2, np.arange(len(y)), y)
    st = (np.stack([up, up], axis=1) * 32767).astype("<i2")
    with wave.open(str(tmp_path / "st.wav"), "wb") as w:
        w.setnchannels(2), w.setsampwidth(2), w.setframerate(44100), w.writeframes(st.tobytes())
    assert abs(B.analyze(tmp_path / "st.wav").tempo_bpm - 100) < 2


def test_active_regions_find_the_sung_parts(tmp_path):
    sr = B.SR
    y = np.zeros(sr * 6, dtype=np.float32)
    t = np.arange(sr) / sr
    y[sr: 2 * sr] = 0.3 * np.sin(2 * np.pi * 220 * t)
    y[4 * sr: 5 * sr] = 0.3 * np.sin(2 * np.pi * 330 * t)
    regs = B.active_regions(B.write_wav(tmp_path / "v.wav", y))
    assert len(regs) == 2 and abs(regs[0][0] - 1) < 0.1 and abs(regs[1][1] - 5) < 0.1


def test_beat_this_is_optional(tmp_path, monkeypatch):
    from opensoul.music import beat_this_backend as bt

    p = B.write_wav(tmp_path / "s.wav", B.click_track(bpm=120, bars=8, lead_in_s=0.5))
    monkeypatch.setattr(bt, "available", lambda: False)
    bm, used = B.analyze_with(p)
    assert used == "opensoul_onset" and abs(bm.tempo_bpm - 120) < 2
    monkeypatch.setattr(bt, "available", lambda: True)
    monkeypatch.setattr(bt, "beats_and_downbeats", lambda path, device="cpu": ([0.5 + 0.5 * k for k in range(32)],
                                                                             [0.5 + 2.0 * k for k in range(8)]))
    bm, used = B.analyze_with(p)
    assert used == "beat_this" and bm.bars[0] == 0.5 and abs(bm.tempo_bpm - 120) < 0.01 and bm.downbeat_phase == 0


def test_too_short_or_missing_audio(tmp_path):
    with pytest.raises(B.AudioError):
        B.analyze_samples(np.zeros(B.SR // 2, dtype=np.float32))
    with pytest.raises(B.AudioError):
        B.load_audio(tmp_path / "nope.wav")


def test_beatmap_round_trips_through_json():
    bm = B.analyze_samples(B.click_track(bpm=120, bars=8, lead_in_s=0.5))
    assert B.BeatMap.from_dict(bm.to_dict()) == bm


def test_beat_this_loads_only_a_local_checkpoint_with_the_pinned_sha(tmp_path, monkeypatch):
    import hashlib
    import sys
    import types

    from opensoul.music import beat_this_backend as bt

    assert bt.expected_sha256() == "8c328b45f59d8dd3dff219253ff6a8d6482be57d0133a29140e2febbf8eb8331"
    monkeypatch.setattr(bt.importlib.util, "find_spec", lambda name: object())  # pretend beat_this + torch exist
    seen = {}

    class File2Beats:
        def __init__(self, checkpoint_path, device, dbn):
            seen["ckpt"] = checkpoint_path

        def __call__(self, path):
            return [0.5 + 0.5 * k for k in range(32)], [0.5 + 2.0 * k for k in range(8)]

    inf = types.ModuleType("beat_this.inference")
    inf.File2Beats = File2Beats
    monkeypatch.setitem(sys.modules, "beat_this", types.ModuleType("beat_this"))
    monkeypatch.setitem(sys.modules, "beat_this.inference", inf)
    p = B.write_wav(tmp_path / "s.wav", B.click_track(bpm=120, bars=8, lead_in_s=0.5))

    monkeypatch.delenv(bt.ENV, raising=False)
    assert "no beat_this checkpoint" in bt.why_not_available()
    assert B.analyze_with(p)[1] == "opensoul_onset" and not seen  # never asks the library for 'final0'
    monkeypatch.setenv(bt.ENV, str(tmp_path / "missing.ckpt"))
    assert "missing" in bt.why_not_available()
    ck = tmp_path / "final0.ckpt"
    ck.write_bytes(b"not the real checkpoint")
    monkeypatch.setenv(bt.ENV, str(ck))
    assert "does not match" in bt.why_not_available()
    assert B.analyze_with(p)[1] == "opensoul_onset" and not seen
    with pytest.raises(RuntimeError):
        bt.beats_and_downbeats(p)
    monkeypatch.setattr(bt, "expected_sha256", lambda: hashlib.sha256(ck.read_bytes()).hexdigest())
    assert bt.available()
    bm, used = B.analyze_with(p)
    assert used == "beat_this" and seen["ckpt"] == str(ck) and abs(bm.tempo_bpm - 120) < 0.01
