"""LatentSync wiring: the shot's face_box reaches the runner as --face-box; runner exit 3 -> ambiguous_face,
exit 4 -> no_face (the LTX take is kept with a note). The runner itself is not touched or run."""
import importlib.util
import json
from pathlib import Path

import pytest

from opensoul import lipsync as L
from opensoul import speak

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def nodes():
    spec = importlib.util.spec_from_file_location("opensoul_nodes_nodes_ls", ROOT / "custom_nodes/opensoul_nodes/nodes.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_node_builds_face_box_arg_and_maps_exit_codes(nodes):
    cmd = nodes.latentsync_cmd("py", "/ls", "in.mp4", "in.wav", "out.mp4", 20, 1.5, 7, " 300, 200.4,180,220 ")
    assert cmd[cmd.index("--face-box") + 1] == "300,200,180,220"
    assert "--face-box" not in nodes.latentsync_cmd("py", "/ls", "a", "b", "c", 20, 1.5, 7, "")
    with pytest.raises(ValueError):
        nodes.parse_face_box("1,2,0,4")
    assert L.error_code(str(nodes.latentsync_error(3, "two faces"))) == "ambiguous_face"
    assert L.error_code(str(nodes.latentsync_error(4, "face on 31% of frames"))) == "no_face"
    assert L.error_code(str(nodes.latentsync_error(1, "CUDA OOM"))) is None
    it = nodes.OpenSoulLatentSync.INPUT_TYPES()
    assert "face_box" in it["optional"]
    assert json.loads((ROOT / "workflows/05_lipsync_api.json").read_text())["3"]["inputs"]["face_box"] == ""


def test_latentsync_backend_sends_the_face_box_to_the_workflow(monkeypatch, tmp_path):
    seen = {}

    def fake_sdk(wf, inputs, node, dest, what):  # the OpenSoul runner always reports its detector (fail-closed check)
        seen.update(wf=wf, inputs=inputs)
        (dest.parent / "node3_report.txt").write_text(json.dumps({"frames": 9, "detector_counts": {"mediapipe": 9}}))
        return dest

    monkeypatch.setattr(speak, "_run_sdk", fake_sdk)
    be = speak.LatentSyncLipSync(dry_run=False)
    L.run_latentsync_stage(be, tmp_path / "v.mp4", tmp_path / "a.wav", tmp_path / "o.mp4",
                           {"face_box": [300, 200, 180, 220], "speaker": "Ren"})
    assert seen["inputs"]["3"] == {"face_box": "300,200,180,220"}
    be2 = speak.LatentSyncLipSync(dry_run=False)
    L.run_latentsync_stage(be2, tmp_path / "v.mp4", tmp_path / "a.wav", tmp_path / "o.mp4", {})
    assert "3" not in seen["inputs"]


class _Fails:
    name = "latentsync"
    face_box = None

    def __init__(self, msg):
        self.msg = msg

    def sync(self, video, audio, dest):
        raise RuntimeError(self.msg)


def test_no_face_keeps_the_ltx_take_with_a_note(tmp_path):
    v = tmp_path / "ltx.mp4"
    out, note = L.run_latentsync_stage(_Fails("[lipsync:no_face] exit 4"), v, tmp_path / "a.wav", tmp_path / "o.mp4",
                                       {"speaker": "Ren"})
    assert out == v and "Ren's face" in note and "LTX audio+video" in note


def test_ambiguous_face_and_crashes_raise(tmp_path):
    with pytest.raises(L.LipSyncError) as e:
        L.run_latentsync_stage(_Fails("[lipsync:ambiguous_face] exit 3"), tmp_path / "v", tmp_path / "a", tmp_path / "o", {})
    assert e.value.code == "ambiguous_face" and "Several faces" in str(e.value)
    with pytest.raises(RuntimeError, match="CUDA"):
        L.run_latentsync_stage(_Fails("CUDA out of memory"), tmp_path / "v", tmp_path / "a", tmp_path / "o", {})


def test_run_shot_no_face_finishes_as_the_ltx_take(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    from opensoul import media

    if not media.ffmpeg_bin():
        pytest.skip("no ffmpeg")
    from PIL import Image

    from opensoul.shot import run_shot

    Image.new("RGB", (64, 64), "gray").save(tmp_path / "s.png")
    st, _, mode = L.dialogue_stages(line="Go now.", voice="tara", quality="final", backend="latentsync", prompt="p",
                                    speaker="Ren", seed=1, latentsync_installed=True, face_box=(300, 200, 180, 220))
    assert mode == "ltx_a2v+latentsync"

    class Tts:
        name = "fake"

        def synthesize(self, text, voice, dest):
            return L.placeholder_voice(dest, 1.0)

    res = run_shot({"stages": st}, tmp_path / "s.png", tmp_path / "o", tts=Tts(), lipsync=_Fails("[lipsync:no_face] 4"))
    assert res.video.name == "a2v_preview.mp4" and any("couldn't find Ren's face" in n for n in res.notes)
    assert res.steps[-1] == {"stage": "lipsync", "backend": "latentsync", "error": "no_face", "file": str(res.video)}


def test_node_hands_back_the_sidecar_as_text(nodes, tmp_path):
    out = tmp_path / "latentsync.mp4"
    assert nodes.sidecar_text(out) == ""
    Path(str(out) + ".lipsync.json").write_text(json.dumps({"face_found_ratio": 0.93, "frames": 121}))
    assert json.loads(nodes.sidecar_text(out)) == {"face_found_ratio": 0.93, "frames": 121}
    assert nodes.OpenSoulLatentSync.OUTPUT_NODE is True


def test_app_stores_the_sidecar_next_to_the_take_and_reads_stats(monkeypatch, tmp_path):
    take = tmp_path / "v3"
    take.mkdir()

    def fake_sdk(wf, inputs, node, dest, what):  # what comfy_client does with the node's text output + SaveVideo
        (dest.parent / "node3_report.txt").write_text(json.dumps({
            "face_found_ratio": 0.97, "held_frames": 3, "frames": 121, "face_px_median": 212, "face_px_min": 180,
            "detector_counts": {"mediapipe": 118, "anime_fallback": 0, "held": 3, "none": 0}, "backend": "latentsync"}))
        saved = dest.parent / "opensoul_lipsync_00001_.mp4"
        saved.write_bytes(b"mp4")
        return saved

    monkeypatch.setattr(speak, "_run_sdk", fake_sdk)
    out = speak.LatentSyncLipSync(dry_run=False).sync(take / "in.mp4", take / "a.wav", take / "lipsync.mp4")
    side = Path(str(out) + ".lipsync.json")
    assert side.is_file() and not (take / "node3_report.txt").exists()
    stats = L.read_sidecar(out)
    assert stats["face_found_ratio"] == 0.97 and stats["detector_counts"]["mediapipe"] == 118

    from types import SimpleNamespace as NS

    from app.storyboard_api import _lipsync_stats

    res = NS(steps=[{"stage": "voice", "file": "v.wav"}, {"stage": "video", "file": "a.mp4"},
                    {"stage": "lipsync", "backend": "latentsync", "file": str(out)}])
    assert _lipsync_stats(res)["face_px_median"] == 212


def test_bad_or_missing_report_leaves_no_sidecar(tmp_path):
    v = tmp_path / "o.mp4"
    assert speak.store_sidecar(tmp_path / "none.txt", v) is None
    (tmp_path / "r.txt").write_text("not json")
    assert speak.store_sidecar(tmp_path / "r.txt", v) is None and not Path(str(v) + ".lipsync.json").exists()
