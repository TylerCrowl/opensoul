"""CPU tests for scripts/sdk_batch.py (SDK-native render runner): graph edits match batch2.py."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("sdk_batch", ROOT / "scripts/sdk_batch.py")
sdk_batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sdk_batch)


def test_a2v_frames_rule():
    assert sdk_batch.a2v_frames(3.0) == 89      # (3.6 s * 24 = 86.4) -> 88 + 1
    assert (sdk_batch.a2v_frames(1.234) - 1) % 8 == 0


def test_build_video_job_mirrors_batch2(tmp_path):
    sf = pytest.importorskip("soundfile")
    (tmp_path / "audio").mkdir()
    sf.write(str(tmp_path / "audio/v7A.wav"), np.zeros(24000 * 3, dtype="float32"), 24000)
    (tmp_path / "cB.png").write_bytes(b"png")
    wf = json.loads((ROOT / "workflows/04b_a2v_ltx_api.json").read_text())
    (tmp_path / "a2v.json").write_text(json.dumps(wf))
    job = {"type": "vid", "name": "t1", "img": "cB", "wf": "a2v.json", "audio": "v7A", "seed": 7, "prompt": "p" * 400,
           "neg": "n", "lora2": "ltx-2-19b-lora-camera-control-static.safetensors", "lora2_w": 0.5}
    g, inputs, out = sdk_batch.build_video_job(job, tmp_path, tmp_path)
    assert out == "51"
    assert inputs["30"]["length"] == inputs["32"]["frames_number"] == 89
    assert g["71"]["inputs"]["strength_model"] == 0.5 and g["34"]["inputs"]["model"] == ["71", 0]
    assert Path(inputs["60"]["audio"]).is_file() and inputs["35"]["noise_seed"] == inputs["43"]["noise_seed"] == 7
    sdk_batch.comfy_client.apply_inputs(g, inputs)  # every override names a real node input
    a, sr = sf.read(inputs["60"]["audio"])
    assert len(a) == int(89 / 24 * sr)


def test_stdlib_wav_fallback_roundtrip(tmp_path):
    io = sdk_batch._WavIO()
    io.write(str(tmp_path / "a.wav"), np.zeros(2400, dtype="float32"), 24000)
    a, sr = io.read(str(tmp_path / "a.wav"))
    assert sr == 24000 and len(a) == 2400


def test_lipsync_stage_targets_node_pack(tmp_path):
    job = {"name": "t2", "seed": 9, "lipsync": {"steps": 25}}
    g, inputs, out = sdk_batch.build_lipsync_job(job, tmp_path / "t2.mp4", tmp_path / "a.wav")
    assert out == "9" and g["3"]["class_type"] == "OpenSoulLatentSync"
    assert inputs["3"] == {"inference_steps": 25, "guidance_scale": 1.5, "seed": 9}
    assert inputs["1"]["file"].endswith("t2.mp4") and inputs["2"]["audio"].endswith("a.wav")
    sdk_batch.comfy_client.apply_inputs(g, inputs)
    _g2, in2, _ = sdk_batch.build_lipsync_job({"name": "t3", "lipsync": True}, tmp_path / "v.mp4", tmp_path / "a.wav")
    assert in2["3"]["inference_steps"] == 50 and in2["3"]["seed"] == 1247
