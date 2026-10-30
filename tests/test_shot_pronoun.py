"""/api/shot hands the character's pack to build_shot_plan, so a talking shot asks for articulation in their own
pronoun (pack 'pronoun', opensoul/presets.py), not 'they' for everyone."""
import json

import pytest
from fastapi.testclient import TestClient

from opensoul import lipsync as L


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    return TestClient(server.app), server, tmp_path


def _pack(tmp_path, name, pronoun):
    d = tmp_path / "packs" / name
    (d / "refs").mkdir(parents=True)
    (d / "pack.json").write_text(json.dumps({"name": name, "prompt_lock": "a courier in a teal raincoat", "pronoun": pronoun,
                                             "ref_images": [], "meta": {}}))
    return d


def test_talking_shot_uses_the_pack_pronoun(client, monkeypatch):
    c, server, tmp = client
    seen = {}
    real = server.build_shot_plan

    def spy(**kw):
        seen.update(kw)
        return real(**kw)

    monkeypatch.setattr(server, "build_shot_plan", spy)
    d = _pack(tmp, "Kai", "he")
    c.post("/api/shot", json={"name": "Kai", "pack_dir": str(d), "camera": "static", "line": "Morning, everyone."})
    assert seen["pack_dir"] == str(d)
    plan = real(**seen)
    assert L.articulation("he") in plan["prompt"] and L.articulation("they") not in plan["prompt"]


def test_main_demo_without_pack_dir_uses_its_own_pack(client, monkeypatch):
    c, server, _ = client
    seen = {}
    monkeypatch.setattr(server, "build_shot_plan", lambda **kw: seen.update(kw) or (_ for _ in ()).throw(KeyError("x")))
    c.post("/api/shot", json={"name": server.DEMO_NAME, "pack_dir": "", "camera": "static", "line": "Hi."})
    assert seen["pack_dir"] == str(server.DEMO_PACK)
