import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "custom_nodes/opensoul_nodes"


@pytest.fixture(scope="module")
def nodes():
    spec = importlib.util.spec_from_file_location("opensoul_nodes_nodes", PACK / "nodes.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_pack_registers_six_nodes(nodes):
    assert set(nodes.NODE_CLASS_MAPPINGS) == {"OpenSoulKokoroTTS", "OpenSoulChatterboxTTS", "OpenSoulOrpheusTTS", "OpenSoulVoxCPM2TTS",
                                              "OpenSoulLatentSync", "OpenSoulIdentityGate"}
    assert set(nodes.NODE_DISPLAY_NAME_MAPPINGS) == set(nodes.NODE_CLASS_MAPPINGS)
    allow = json.loads((ROOT / "workflows/node_allowlist.json").read_text())["opensoul_nodes"]
    assert set(allow) == set(nodes.NODE_CLASS_MAPPINGS)


def test_workflow_inputs_match_node_schema(nodes):
    """Every OpenSoul node used in a workflow sets only inputs its INPUT_TYPES declares, and all required ones."""
    for f in (ROOT / "workflows").glob("*_api.json"):
        for nid, n in json.loads(f.read_text()).items():
            cls = nodes.NODE_CLASS_MAPPINGS.get(n["class_type"])
            if not cls:
                continue
            it = cls.INPUT_TYPES()
            declared = set(it["required"]) | set(it.get("optional", {}))
            assert set(n["inputs"]) <= declared, (f.name, nid)
            assert set(it["required"]) <= set(n["inputs"]), (f.name, nid)


def test_gate_report_logic(nodes):
    r = nodes.gate_report([0.62, None, 0.30, 0.51], 0.45)
    assert r["kept"] == [0, 3] and r["passed"] and r["best_index"] == 0
    r = nodes.gate_report([None, 0.2], 0.45)
    assert not r["passed"] and r["kept"] == [] and r["best_index"] == 1


def test_wav_roundtrip(nodes, tmp_path):
    torch = pytest.importorskip("torch")
    sr = 24000
    wave = torch.sin(torch.linspace(0, 200, sr)).reshape(1, 1, -1) * 0.5
    p = nodes.audio_to_wav({"waveform": wave, "sample_rate": sr}, tmp_path / "a.wav")
    back = nodes.wav_to_audio(p)
    assert back["sample_rate"] == sr and back["waveform"].shape == (1, 1, sr)
    assert float((back["waveform"] - wave).abs().max()) < 1e-3


def test_runners_exist():
    for r in ("orpheus_tts.py", "kokoro_tts.py", "chatterbox_tts.py", "latentsync_run.py", "idsim_json.py"):
        assert (PACK / "runners" / r).is_file()


def _img(seed, n=1, h=64, w=48):
    rng = np.random.default_rng(seed)
    return rng.random((n, h, w, 3), dtype=np.float32)


def test_gate_defaults_to_apache_patch_backend(nodes):
    it = nodes.OpenSoulIdentityGate.INPUT_TYPES()
    assert "backend" not in it["required"]
    choices, opts = it["optional"]["backend"]
    assert choices[0] == "patch" and opts["default"] == "patch" and "arcface" in choices
    import inspect
    assert inspect.signature(nodes.OpenSoulIdentityGate.run).parameters["backend"].default == "patch"


def test_patch_gate_runs_without_insightface(nodes, monkeypatch):
    """Default path must never shell out to the InsightFace runner."""
    def boom(*a, **k):
        raise AssertionError("ArcFace runner called on the default path")
    monkeypatch.setattr(nodes, "_run", boom)
    anchor = _img(1)
    cands = np.concatenate([anchor, _img(2)])
    out = nodes.OpenSoulIdentityGate().run(anchor, cands, -1.0, False)
    rep = json.loads(out["result"][3])
    assert rep["backend"] == "patch" and rep["threshold"] == nodes.GATE_THRESHOLDS["patch"]
    assert rep["scores"][0] == pytest.approx(1.0, abs=1e-4)
    assert 0 in rep["kept"] and rep["passed"]


def test_patch_embedding_matches_app_scorer(nodes):
    from PIL import Image
    from opensoul.consistency import patch_embedding
    rgb = (_img(3)[0] * 255).astype(np.uint8)
    a = nodes.patch_embedding_array(rgb)
    b = patch_embedding(Image.fromarray(rgb))
    assert float(np.dot(a, b)) == pytest.approx(1.0, abs=1e-5)


def test_arcface_backend_is_opt_in(nodes, monkeypatch):
    calls = []
    monkeypatch.setattr(nodes.OpenSoulIdentityGate, "_arcface_scores",
                        staticmethod(lambda a, c: calls.append(1) or [0.5, 0.1]))
    cands = _img(5, n=2)
    out = nodes.OpenSoulIdentityGate().run(_img(4), cands, -1.0, False, backend="arcface")
    rep = json.loads(out["result"][3])
    assert calls and rep["backend"] == "arcface" and rep["threshold"] == 0.45 and rep["kept"] == [0]


def test_unknown_backend_rejected(nodes):
    with pytest.raises(ValueError):
        nodes.OpenSoulIdentityGate().run(_img(1), _img(1), -1.0, False, backend="nope")


def test_default_workflow_uses_patch_backend():
    w = json.loads((ROOT / "workflows/06_identity_gate_api.json").read_text())
    assert w["3"]["inputs"]["backend"] == "patch"
    w2 = json.loads((ROOT / "workflows/06b_identity_gate_arcface_api.json").read_text())
    assert w2["3"]["inputs"]["backend"] == "arcface"


def test_download_script_dry_run_has_no_arcface_by_default():
    import subprocess
    out = subprocess.run(["bash", str(ROOT / "scripts/download_models.sh"), "--dry-run"], capture_output=True,
                         text=True, check=True, env={"HOME": "/tmp", "PATH": "/usr/bin:/bin"}).stdout
    assert "qwen_image_edit_2511" in out and "ltx-2.5" in out and "LatentSync-1.6" in out
    assert "buffalo" not in out.lower() and "arcface" not in out.lower()
