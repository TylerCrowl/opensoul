"""MCP setup tools: list_hardware, recommend_models, plan_install, apply_install, set_slot, health_check. They wrap
/api/setup/* (app/setup_routes.py). The end-to-end tests route the MCP backend into the app in-process (TestClient):
no GPU, no network, preview mode, temp data folder. There is no approve tool."""
from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("mcp.server.mcpserver")
from fastapi.testclient import TestClient  # noqa: E402

from opensoul import mcp_server as M  # noqa: E402
from opensoul import setup_engine as SE  # noqa: E402


class AppBackend(M.Backend):
    """Sends the MCP server's requests straight into the FastAPI app (no sockets)."""

    def __init__(self, client):
        super().__init__("http://127.0.0.1:8765")
        self.c, self.calls = client, []

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        r = self.c.request(method, path, json=body)
        if r.status_code >= 400:
            raise M.BackendError(f"OpenSoul said {r.status_code}: {r.json().get('detail')}")
        return r.json()


def _call(app, name, args=None):
    r = asyncio.run(app.call_tool(name, args or {}))
    sc = getattr(r, "structuredContent", None) or getattr(r, "structured_content", None)
    if sc is not None:
        return sc.get("result", sc) if isinstance(sc, dict) and set(sc) == {"result"} else sc
    blocks = getattr(r, "content", None) or (r[0] if isinstance(r, tuple) else r)
    return json.loads(blocks[0].text)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    from app import hardware_routes as routes
    from app import server

    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    monkeypatch.setenv("OPENSOUL_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("COMFY_DIR", str(tmp_path / "home" / "ComfyUI"))
    monkeypatch.delenv("OPENSOUL_MACHINES", raising=False)
    monkeypatch.setattr(server, "DATA", tmp_path / "data")
    routes._cache.clear()
    be = AppBackend(TestClient(server.app))
    yield M.build(be), be, tmp_path / "data"
    routes._cache.clear()


def test_setup_tools_are_listed_and_there_is_no_approve_tool():
    names = {t.name for t in asyncio.run(M.build(M.Backend()).list_tools())}
    assert set(M.SETUP_TOOLS) <= names and set(M.JOB_TOOLS) <= names and names == set(M.TOOLS)
    assert not any("approve" in n for n in names)


def test_list_hardware_and_recommend_models(setup):
    app, be, _ = setup
    hw = _call(app, "list_hardware", {"simulate": "mac64"})
    assert hw["auto_tier"] == "fallback" and hw["advisory_tier"] == "apple_64gb"
    rec = _call(app, "recommend_models", {"simulate": "spark", "commercial": "open_only"})
    assert rec["recommendation"]["tier"] == "spark_x1" and len(rec["slots"]) == 7
    assert all(o["commercial_use"] == "yes" for s in rec["slots"] for o in s["options"])
    assert be.calls[0][1] == "/api/setup/hardware?simulate=mac64"


def test_plan_then_user_approves_then_apply_in_preview_mode(setup):
    app, _, data = setup
    plan = _call(app, "plan_install", {"models": ["kokoro"]})
    assert plan["ok"] and plan["dry_run"] and plan["items"][0]["commands"]
    from mcp.server.mcpserver.exceptions import ToolError

    with pytest.raises(ToolError, match="no unused approval"):
        asyncio.run(app.call_tool("apply_install", {"plan_id": plan["plan_id"], "approval_token": "guess", "approve": True}))
    tok = SE.approve(plan["plan_id"], data_dir=data)["approval_token"]  # the user's step, outside the MCP server
    with pytest.raises(ToolError, match="approve flag"):
        asyncio.run(app.call_tool("apply_install", {"plan_id": plan["plan_id"], "approval_token": tok}))
    out = _call(app, "apply_install", {"plan_id": plan["plan_id"], "approval_token": tok, "approve": True})
    assert out["executed"] is False and out["dry_run"] is True and out["would_run"]


def test_plan_refuses_blocked_and_not_in_app_models(setup):
    app, _, _ = setup
    plan = _call(app, "plan_install", {"models": ["flux2_dev", "seedvr2_3b"]})
    assert not plan["ok"] and len(plan["errors"]) == 2


def test_set_slot_plans_then_records_with_the_users_token(setup):
    app, _, data = setup
    plan = _call(app, "set_slot", {"slot": "voice", "model": "kokoro"})
    assert plan["slot_changes"] == [{"slot": "voice", "from": "voxcpm2", "to": "kokoro"}]
    assert SE.active_slots(data) == {}
    tok = SE.approve(plan["plan_id"], data_dir=data)["approval_token"]
    out = _call(app, "set_slot", {"slot": "voice", "model": "kokoro", "approval_token": tok, "plan_id": plan["plan_id"]})
    assert out["slots"] == {"voice": "kokoro"}
    rec = _call(app, "recommend_models", {"simulate": "spark"})
    voice = next(s for s in rec["slots"] if s["id"] == "voice")
    assert voice["active"] == "kokoro" and voice["default"] == "voxcpm2"  # the default itself never changes


def test_health_check(setup):
    app, _, _ = setup
    h = _call(app, "health_check")
    assert h["problems"]["model_manifest"] == [] and h["dry_run"] is True and "missing" in h


def test_no_approve_route_in_the_api(setup):
    _, be, _ = setup
    assert be.c.post("/api/setup/approve", json={"plan_id": "0" * 16}).status_code in (404, 405)
