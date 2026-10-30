"""The live (non-dry-run) pipeline must call comfy_client.run_workflow_file with valid node inputs."""
import json
from pathlib import Path

import pytest

from opensoul import comfy_client, speak

ROOT = Path(__file__).resolve().parents[1]


def test_apply_inputs_rejects_typos():
    g = json.loads((ROOT / "workflows/02_consistent_stills_api.json").read_text())
    comfy_client.apply_inputs(g, {"6": {"prompt": "x"}, "3": {"seed": 1}})
    with pytest.raises(KeyError):
        comfy_client.apply_inputs(g, {"6": {"text": "x"}})
    with pytest.raises(KeyError):
        comfy_client.apply_inputs(g, {"999": {"seed": 1}})


def test_default_base_url_is_local_proxy(monkeypatch):
    monkeypatch.delenv("COMFY_BASE_URL", raising=False)
    assert comfy_client.base_url() == "http://127.0.0.1:8189"


@pytest.fixture
def captured(monkeypatch, tmp_path):
    calls = []

    def fake(workflow_path, *, inputs=None, output_node_id="9", out_dir="outputs", metadata=None):
        comfy_client.apply_inputs(comfy_client.load_graph(workflow_path), inputs or {})
        calls.append((Path(workflow_path).name, inputs, output_node_id))
        out = Path(out_dir) / "out.bin"
        out.write_bytes(b"x")
        if Path(workflow_path).name == "05_lipsync_api.json":  # the runner's detector stats (speak fails closed without)
            (Path(out_dir) / "node3_report.txt").write_text(json.dumps({"frames": 1, "detector_counts": {"mediapipe": 1}}))
        return [out]

    monkeypatch.setattr(comfy_client, "run_workflow_file", fake)
    return calls


def test_live_tts_and_lipsync_route_through_sdk(captured, tmp_path):
    speak.get_tts(dry_run=False, name="kokoro").synthesize("Hi there <sigh>", "am_michael", tmp_path / "a.wav")
    speak.get_tts(dry_run=False, name="chatterbox").synthesize("Hi", "x", tmp_path / "b.wav")
    speak.get_lipsync("latentsync", dry_run=False).sync(tmp_path / "v.mp4", tmp_path / "a.wav", tmp_path / "o.mp4")
    assert [c[0] for c in captured] == ["03_tts_api.json", "03b_tts_chatterbox_api.json", "05_lipsync_api.json"]
    assert captured[0][1] == {"1": {"text": "Hi there", "voice": "am_michael"}}  # Kokoro gets the words, not the tag


def test_default_tts_is_orpheus_and_keeps_tags(captured, tmp_path, monkeypatch):
    monkeypatch.delenv("OPENSOUL_TTS", raising=False)
    tts = speak.get_tts(dry_run=False)
    assert tts.name == "orpheus"
    tts.synthesize("(sighs) No. Anything hotter is an apology. [chuckle]", "tara", tmp_path / "a.wav")
    wf, inputs, node = captured[0]
    assert wf == "03c_tts_orpheus_api.json" and node == "2"
    assert inputs["1"]["text"] == "<sigh> No. Anything hotter is an apology. <chuckle>"
    assert inputs["1"]["voice"] == "tara"


def test_default_lipsync_is_ltx_av(monkeypatch):
    monkeypatch.delenv("OPENSOUL_LIPSYNC", raising=False)
    assert speak.get_lipsync(dry_run=True).name == "ltx_av"


def test_long_prompt_is_not_treated_as_a_file(tmp_path):
    """Regression (Oct 17): a >255-char prompt passed to Path.is_file() raised ENAMETOOLONG."""
    from opensoul.comfy_client import _is_existing_file

    f = tmp_path / "a.png"
    f.write_bytes(b"x")
    assert _is_existing_file(str(f))
    assert not _is_existing_file("word " * 200)
    assert not _is_existing_file(42)
