"""Every model the app can run (presets/models.yaml backends, presets/text_master.json files, confirmed
presets/music_models.json entries, the lip-sync face trackers) is named in the
credits card ROWS (scripts/make_credits_card.py) and in the in-app Credits dialog. A new backend fails here until
it has a credits row. The Z-Image encoder and VAE licences were confirmed by Contest Submission (licenses.md §2.2e)."""
import ast
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
# backend id -> the name its credits row uses
FAMILY = {
    "qwen_edit_bf16": "Qwen-Image-Edit-2511", "qwen_edit_fp8mixed": "Qwen-Image-Edit-2511", "qwen07t": "Qwen-Image-Edit-2511",
    "zimage": "Z-Image-Turbo", "orpheus": "Orpheus", "kokoro": "Kokoro-82M", "chatterbox": "Chatterbox", "voxcpm2": "VoxCPM2",
    "ltx25_int8": "LTX-2.5", "ltx25_bf16": "LTX-2.5", "ltx_av": "LTX-2.5", "latentsync": "LatentSync 1.6",
    "patch": "OpenSoul", "arcface": "InsightFace", "union_control_iclora": "IC-LoRA Union Control", "dwpose": "DWPose",
}
IN_APP = {"Qwen-Image-Edit-2511", "Z-Image-Turbo", "LTX-2.5", "Orpheus", "Kokoro-82M", "Chatterbox", "VoxCPM2", "LatentSync 1.6"}


def _rows():
    tree = ast.parse((ROOT / "scripts/make_credits_card.py").read_text())
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "ROWS" for t in n.targets):
            return ast.literal_eval(n.value)
    raise AssertionError("ROWS not found")


def test_every_backend_has_a_credits_row():
    rows = " | ".join(r[0] for r in _rows())
    html = (ROOT / "app/web/index.html").read_text()
    for st in yaml.safe_load((ROOT / "presets/models.yaml").read_text())["stages"]:
        for b in st["backends"]:
            assert b["id"] in FAMILY, f"new backend {b['id']}: add a credits row and map it here"
            fam = FAMILY[b["id"]]
            assert fam in rows, (b["id"], fam)
            if fam in IN_APP:
                assert fam in html, fam


def test_text_master_files_are_credited_and_unconfirmed_licenses_say_so():
    cfg = json.loads((ROOT / "presets/text_master.json").read_text())
    rows = _rows()
    names = " | ".join(r[0] for r in rows)
    html = (ROOT / "app/web/index.html").read_text()
    assert cfg["model"]["name"] in names and cfg["model"]["name"] in html
    for key in ("clip", "vae"):
        stem = cfg["files"][key].removesuffix(".safetensors")
        row = next(r for r in rows if f"({stem})" in r[0])
        assert row[2] == "Apache-2.0", row
        assert f"({stem})" in html
    assert ("FLUX.1 autoencoder (ae) — Black Forest Labs", "master image decoder", "Apache-2.0") in rows
    assert "FLUX.1 autoencoder (ae) — Black Forest Labs, Apache-2.0" in html
    for f in ("scripts/make_credits_card.py", "app/web/index.html", "README.md", "docs/MODEL_STACK.md"):
        assert "pending confirmation" not in (ROOT / f).read_text(), f
    assert next(r for r in rows if "Z-Image-Turbo" in r[0])[2] == "Apache-2.0"


MUSIC = {"opensoul_onset": "OpenSoul", "preview_tone": "OpenSoul", "preview_stem": "OpenSoul", "beat_this": "beat_this",
         "ace_step": "ACE-Step 1.5", "ace_step_extract": "ACE-Step 1.5", "heartmula": "HeartMuLa-oss-3B"}
LICENSE = {"ACE-Step 1.5": "MIT", "beat_this": "MIT", "HeartMuLa-oss-3B": "Apache-2.0"}


def test_confirmed_music_models_are_credited_with_their_license():
    p = ROOT / "presets/music_models.json"
    if not p.is_file():
        return
    rows = _rows()
    html = (ROOT / "app/web/index.html").read_text()
    for m in json.loads(p.read_text())["models"]:
        if m.get("status") != "confirmed":
            continue  # not offered in the app (e.g. Demucs, licence unconfirmed)
        assert m["id"] in MUSIC, f"new music model {m['id']}: add a credits row and map it here"
        fam = MUSIC[m["id"]]
        row = next((r for r in rows if fam in r[0]), None)
        assert row, (m["id"], fam)
        if fam in LICENSE:
            assert m["license"] == LICENSE[fam] and row[2].startswith(LICENSE[fam]), (m["id"], row)
            assert fam in html
    small = next(r for r in rows if "ACE-Step Qwen3 0.6B text encoder" in r[0])
    big = next(r for r in rows if "ACE-Step 4B text encoder" in r[0])
    assert small[2] == "Apache-2.0" and big[2] == "MIT / Apache-2.0 (Qwen3 base)"
    assert "Qwen3 0.6B text encoder · Apache-2.0" in html and "4B text encoder · MIT / Apache-2.0 (Qwen3 base)" in html


def test_lip_sync_face_trackers_are_credited():
    rows = {r[0]: r[2] for r in _rows()}
    assert rows["MediaPipe face landmarker"] == "Apache-2.0" and rows["hysts anime-face-detector"] == "MIT"
    html = (ROOT / "app/web/index.html").read_text()
    assert "MediaPipe face landmarker</a> · Apache-2.0" in html and "hysts anime-face-detector</a> · MIT" in html


def test_ltx_and_union_control_have_their_own_licenses_and_every_model_is_in_the_app():
    rows = {r[0]: r[2] for r in _rows()}
    assert rows["LTX-2.5"] == "LTX-2.x Community" and rows["LTX-2.3 IC-LoRA Union Control"] == "LTX-2 Community"
    assert not any("+ Union Control" in n for n in rows)
    html = (ROOT / "app/web/index.html").read_text()
    for name in ("Qwen3-VL-8B-Instruct", "DWPose", "YOLOX-L", "LTX-2.3 IC-LoRA Union Control", "Whisper tiny", "InsightFace ArcFace"):
        assert name in html, name
    assert "LTX-2.3 IC-LoRA Union Control</a> · pose-guided re-perform · LTX-2 Community License" in html


def test_credits_card_has_no_soundtrack_row_by_default():
    src = (ROOT / "scripts/make_credits_card.py").read_text()
    assert "Kevin MacLeod" not in src and "Long Trail" not in src and 'ap.add_argument("--music", default=""' in src
