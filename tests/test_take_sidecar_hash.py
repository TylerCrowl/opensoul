"""App-made LatentSync takes: the stored sidecar's out_sha256 / out_frames describe the FINAL take file (the node
hashed the runner's temp mp4), every later app rewrite re-hashes, and sidecar writes are atomic. Synthetic mp4s."""
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from opensoul import speak

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="needs ffmpeg")


def _mp4(path: Path, frames: int = 12, color: str = "red") -> Path:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c={color}:s=64x64:r=24",
                    "-frames:v", str(frames), "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def _wav(path: Path, seconds: float = 1.0) -> Path:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=220:sample_rate=16000",
                    "-t", str(seconds), str(path)], check=True)
    return path


def _sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _report(tmp: Path, runner_mp4: Path) -> Path:
    rep = tmp / "node3_report.txt"
    rep.write_text(json.dumps({"frames": 12, "detector_counts": {"mediapipe": 12}, "out_sha256": _sha(runner_mp4),
                               "out_frames": 13}))
    return rep


@needs_ffmpeg
def test_stored_sidecar_hashes_the_final_take_not_the_runner_temp(tmp_path):
    runner = _mp4(tmp_path / "latentsync.mp4", 13, "blue")   # the runner's temp file
    take = _mp4(tmp_path / "take_00001.mp4", 12, "red")       # what Comfy wrote: a different file
    side = speak.store_sidecar(_report(tmp_path, runner), take)
    data = json.loads(side.read_text())
    assert side == Path(str(take) + ".lipsync.json") and not (tmp_path / "node3_report.txt").exists()
    assert data["out_sha256"] == _sha(take) != data["runner_out_sha256"] == _sha(runner)
    assert data["out_frames"] == 12 and data["runner_out_frames"] == 13
    assert data["detector_counts"] == {"mediapipe": 12}
    speak.check_detector(side, take)  # still accepted


@needs_ffmpeg
def test_a_remux_after_lipsync_rehashes_and_carries_both_sidecars(tmp_path):
    from opensoul.lipsync import mux_voice

    runner = _mp4(tmp_path / "latentsync.mp4")
    synced = _mp4(tmp_path / "lipsync.mp4", 12, "green")
    speak.store_sidecar(_report(tmp_path, runner), synced)
    Path(str(synced) + ".inner_mouth.json").write_text(json.dumps({"out_sha256": "0" * 64, "out_frames": 1,
                                                                    "parent_sidecar": "x", "parent_sidecar_sha256": "y"}))
    out = mux_voice(synced, _wav(tmp_path / "v.wav"), tmp_path / "with_voice.mp4")
    written = speak.restamp_take(out, synced, "mux")
    assert [p.name for p in written] == ["with_voice.mp4.lipsync.json", "with_voice.mp4.inner_mouth.json"]
    lip = json.loads(Path(str(out) + ".lipsync.json").read_text())
    im = json.loads(Path(str(out) + ".inner_mouth.json").read_text())
    assert lip["out_sha256"] == im["out_sha256"] == _sha(out) != _sha(synced)
    assert lip["out_frames"] == im["out_frames"] == speak.count_frames(out)
    assert lip["runner_out_sha256"] == _sha(runner) and lip["rewritten_by"] == ["mux"]
    assert im["parent_sidecar"] == "with_voice.mp4.lipsync.json"
    assert im["parent_sidecar_sha256"] == _sha(Path(str(out) + ".lipsync.json"))
    # the synced take keeps its own, still true for its file
    assert json.loads(Path(str(synced) + ".lipsync.json").read_text())["out_sha256"] == _sha(synced)


@needs_ffmpeg
def test_in_place_rewrite_rehashes(tmp_path):
    take = _mp4(tmp_path / "take.mp4", 12)
    speak.store_sidecar(_report(tmp_path, take), take)
    _mp4(tmp_path / "take.mp4", 10, "white")  # rewritten in place (e.g. an audio replace)
    speak.restamp_take(take)
    d = json.loads(Path(str(take) + ".lipsync.json").read_text())
    assert d["out_sha256"] == _sha(take) and d["out_frames"] == 10 and "rewritten_by" not in d


@needs_ffmpeg
def test_era_and_mux_steps_after_lipsync_restamp(tmp_path):
    import opensoul.shot as S

    synced = _mp4(tmp_path / "lipsync.mp4", 12)
    speak.store_sidecar(_report(tmp_path, synced), synced)

    def fake_era(src, dest, era):
        return _mp4(Path(dest), 12, "yellow")

    src = Path(S.__file__).read_text()
    assert 'restamp_take(current, prev, "era")' in src and 'restamp_take(current, prev, "mux")' in src
    final = fake_era(synced, tmp_path / "final.mp4", "vhs")
    speak.restamp_take(final, synced, "era")
    d = json.loads(Path(str(final) + ".lipsync.json").read_text())
    assert d["out_sha256"] == _sha(final) and d["rewritten_by"] == ["era"]


def test_sidecar_write_is_atomic(tmp_path, monkeypatch):
    dest = tmp_path / "take.mp4.lipsync.json"
    dest.write_text('{"old": true}')
    real = os.replace

    def boom(a, b):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        speak.write_json_atomic(dest, {"new": True})
    assert json.loads(dest.read_text()) == {"old": True}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["take.mp4.lipsync.json"]  # no temp left behind
    monkeypatch.setattr(os, "replace", real)

    class Bad:
        pass

    with pytest.raises(TypeError):  # fails while serialising: still no partial file
        speak.write_json_atomic(dest, {"x": Bad()})
    assert json.loads(dest.read_text()) == {"old": True} and len(list(tmp_path.iterdir())) == 1
    speak.write_json_atomic(dest, {"new": True})
    assert json.loads(dest.read_text()) == {"new": True} and len(list(tmp_path.iterdir())) == 1


def test_missing_take_gets_no_hash_not_the_runner_one(tmp_path):
    rep = tmp_path / "node3_report.txt"
    rep.write_text(json.dumps({"detector_counts": {"mediapipe": 3}, "out_sha256": "a" * 64, "out_frames": 3}))
    d = json.loads(speak.store_sidecar(rep, tmp_path / "gone.mp4").read_text())
    assert d["out_sha256"] is None and d["out_frames"] is None and d["runner_out_sha256"] == "a" * 64


def test_unreadable_report_stores_nothing(tmp_path):
    rep = tmp_path / "node3_report.txt"
    rep.write_text("not json")
    assert speak.store_sidecar(rep, tmp_path / "take.mp4") is None
    assert not (tmp_path / "take.mp4.lipsync.json").exists()
