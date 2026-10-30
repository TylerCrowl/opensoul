"""The demo characters' origin wording follows one switch (presets/character_origin.json): 'rebuild' or 'disclose'."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

from opensoul import character_origin as co

ROOT = Path(__file__).resolve().parents[1]
FILES = sorted(f for f in set(co.MARKED) | {f for f, _, _ in co.FIELDS} | {co.CONFIG} if (ROOT / f).is_file())


def _copy(tmp_path):
    for rel in FILES:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, tmp_path / rel)
    return tmp_path


def test_default_is_rebuild_and_the_repo_is_in_sync():
    assert co.mode() == "rebuild" and co.stale() == []
    assert set(co.config()["texts"]) == {k for ks in co.MARKED.values() for k in ks} | {k for _, _, k in co.FIELDS}


def test_disclose_mode_drops_every_rebuild_line_and_says_closed_generator(tmp_path):
    root = _copy(tmp_path)
    changed = co.switch("disclose", root)
    assert set(changed) == set(FILES) and co.mode(root) == "disclose" and co.stale(root) == []
    for rel in FILES:
        if rel == co.CONFIG:
            continue
        s = (root / rel).read_text()
        assert "being rebuilt" not in s and "text-only rebuild" not in s, rel
        assert "closed" in s, rel
    lumi = json.loads((root / "assets/lumi/character.json").read_text())
    assert "was made from a concept image by a closed (non-open) image generator" in lumi["origin"]
    demo = json.loads((root / "presets/demo_images.json").read_text())
    assert demo["first_run_still"]["caption"].endswith("made from concept images by a closed (non-open) image generator.")
    assert demo["cast"]["lumi"]["note"] == "Look from closed-generator concept art"


def test_rebuild_mode_round_trips_to_the_same_bytes(tmp_path):
    root = _copy(tmp_path)
    before = {rel: (root / rel).read_bytes() for rel in FILES}
    co.switch("disclose", root)
    co.switch("rebuild", root)
    assert {rel: (root / rel).read_bytes() for rel in FILES} == before
    for rel, path, key in co.FIELDS:  # rebuild text in every field
        d = json.loads((root / rel).read_text())
        for k in path:
            d = d[k]
        assert d == co.config(root)["texts"][key]["rebuild"]


def test_the_switch_script_checks_and_rejects_bad_modes():
    r = subprocess.run([sys.executable, "scripts/set_character_origin.py", "--check"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0 and "mode rebuild: in sync" in r.stdout
    r = subprocess.run([sys.executable, "scripts/set_character_origin.py", "maybe"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode != 0
