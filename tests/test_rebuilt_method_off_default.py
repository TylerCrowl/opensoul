"""The rebuilt-character method (opensoul.lipsync.run_rebuilt_method) and its scorer (opensoul.lipsync_scorer, an
OPTIONAL EXTERNAL tool that is not part of this repo) stay OFF the default lip-sync path: nothing in the app,
the nodes or the scripts calls them, the shipped scorer config is empty, and the default flow runs without them."""
import ast
from pathlib import Path

import pytest

from opensoul import lipsync as L
from opensoul import lipsync_scorer as S

ROOT = Path(__file__).resolve().parents[1]
SCAN = [ROOT / "app", ROOT / "opensoul", ROOT / "custom_nodes" / "opensoul_nodes", ROOT / "scripts", ROOT / "tools"]


def _py_files():
    for d in SCAN:
        if d.is_dir():
            yield from (p for p in d.rglob("*.py") if "__pycache__" not in p.parts)


def test_nothing_in_the_product_calls_the_rebuilt_method_or_the_scorer():
    callers, scorer_users = [], []
    for p in _py_files():
        rel = p.relative_to(ROOT).as_posix()
        src = p.read_text(encoding="utf-8", errors="replace")
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Call):
                f = node.func
                if (f.id if isinstance(f, ast.Name) else getattr(f, "attr", "")) == "run_rebuilt_method":
                    callers.append(rel)
        if rel not in ("opensoul/lipsync.py", "opensoul/lipsync_scorer.py") and "lipsync_scorer" in src:
            scorer_users.append(rel)
    assert callers == [], f"run_rebuilt_method must stay off the default path; called from {callers}"
    assert scorer_users == [], f"the external scorer must stay optional; referenced from {scorer_users}"


def test_shipped_scorer_config_is_empty_so_the_scorer_is_off(monkeypatch):
    for k in (S.ENV_CLI, S.ENV_PY, S.ENV_TIMEOUT):
        monkeypatch.delenv(k, raising=False)
    cfg = S.load_config()
    assert cfg.cli == "" and cfg.python == "" and not S.enabled()


def test_default_flow_runs_without_the_rebuilt_method(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise AssertionError("the default lip-sync flow must not run the rebuilt method or the scorer")

    monkeypatch.setattr(L, "run_rebuilt_method", boom)
    monkeypatch.setattr(S, "score", boom)
    monkeypatch.setattr(S, "scorer", boom)
    assert L.DEFAULT_BACKEND == "ltx_av"
    for backend, installed in ((L.DEFAULT_BACKEND, False), ("latentsync", True)):
        for quality in ("draft", "final"):
            stages, _notes, _mode = L.dialogue_stages(line="Hello there.", voice="tara", quality=quality,
                                                      backend=backend, prompt="Lumi smiles", speaker="Lumi",
                                                      seed=1, latentsync_installed=installed)
            assert all("score" not in s and s.get("method") != L.REBUILT_METHOD for s in stages)
    monkeypatch.setattr(L, "mux_voice", lambda v, a, d: Path(d))
    res = L.lipsync(L.LipSyncRequest(audio=tmp_path / "a.wav", dest=tmp_path / "o.mp4", backend="latentsync",
                                     video=tmp_path / "v.mp4", speaker="Lumi"), dry_run=True)
    assert res.placeholder


def test_scorer_files_are_documented_as_external_with_no_internal_paths():
    shipped = [ROOT / "opensoul" / "lipsync_scorer.py", ROOT / "presets" / "lipsync_scorer.json",
               ROOT / "opensoul" / "lipsync.py", ROOT / "docs" / "LIPSYNC_SCORER.md"]
    for p in shipped:
        assert "review/" not in p.read_text(encoding="utf-8"), p
    doc = (ROOT / "docs" / "LIPSYNC_SCORER.md").read_text(encoding="utf-8")
    assert "not part of this repository" in doc and "sfd_face.pth" in doc and "MIT" in doc
    assert "never be" in doc and "redistributed" in doc and "never downloaded by default" in doc
    assert "OPTIONAL EXTERNAL" in (ROOT / "opensoul" / "lipsync_scorer.py").read_text(encoding="utf-8")
