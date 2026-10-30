"""Every voice / lip-sync engine in presets/models.yaml must be one the code can actually run.

Otherwise the Advanced picker could offer an engine that /api/shot accepts and speak.py then rejects.
See docs/SWAP_A_MODEL.md (step 6).
"""
from opensoul import models_registry as mr
from opensoul import speak


def _ids(stage_id: str) -> set[str]:
    mr.clear_registry_cache()
    stage = next(s for s in mr.load_registry()["stages"] if s["id"] == stage_id)
    return {b["id"] for b in stage["backends"]}


def test_voice_backends_have_code():
    assert _ids("voice") <= set(speak.TTS_BACKENDS)


def test_lipsync_backends_have_code():
    assert _ids("lipsync") <= set(speak.BACKENDS)


def test_swap_guide_exists():
    from pathlib import Path
    doc = Path(__file__).resolve().parents[1] / "docs" / "SWAP_A_MODEL.md"
    text = doc.read_text()
    for ref in ("presets/models.yaml", "scripts/check_workflows.py", "node_allowlist.json", "opensoul/speak.py"):
        assert ref in text
