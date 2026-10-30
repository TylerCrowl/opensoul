"""OpenSoul MCP server: six thin tools over the app's HTTP routes (mocked backend, no GPU, no network)."""
from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("mcp.server.mcpserver")
from opensoul import mcp_server as M  # noqa: E402

PROJECT = {"id": "diner", "shots": [{"id": "s1", "versions": [
    {"id": "v1", "status": "ready", "label": "Draft", "file": "projects/diner/shots/s1/v1.mp4",
     "video_url": "/api/file?path=v1.mp4", "poster_url": "/api/file?path=v1.jpg"},
    {"id": "v2", "status": "running", "label": "Final"}]}]}


class FakeBackend(M.Backend):
    def __init__(self):
        super().__init__("http://127.0.0.1:8765")
        self.calls = []

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path.endswith("/speak"):
            return {"audio_url": "/api/file?path=a.wav", "voice": "tara", "seconds": 1.2}
        if method == "GET" and path == "/api/storyboard/projects":
            return {"projects": [{"id": "diner"}]}
        if method == "GET":
            return PROJECT
        return {"ok": True}


def _call(app, name, args=None):
    r = asyncio.run(app.call_tool(name, args or {}))
    blocks = getattr(r, "content", None) or (r[0] if isinstance(r, tuple) else r)
    sc = getattr(r, "structuredContent", None) or getattr(r, "structured_content", None)
    if sc is not None:
        return sc.get("result", sc) if isinstance(sc, dict) and set(sc) == {"result"} else sc
    return json.loads(blocks[0].text)


def test_the_six_tools_are_listed():
    app = M.build(FakeBackend())
    names = {t.name for t in asyncio.run(app.list_tools())}
    assert names == set(M.TOOLS)


def test_tools_wrap_the_app_routes():
    be = FakeBackend()
    app = M.build(be)
    assert _call(app, "list_projects") == {"projects": [{"id": "diner"}]}
    _call(app, "generate_still", {"project_id": "diner", "shot_id": "s1", "seed": 3})
    _call(app, "generate_shot", {"project_id": "diner", "shot_id": "s1", "quality": "final"})
    r = _call(app, "tts_line", {"project_id": "diner", "shot_id": "s1"})
    assert r["audio_url"] == "http://127.0.0.1:8765/api/file?path=a.wav"
    paths = [(m, p) for m, p, _ in be.calls]
    assert ("POST", "/api/storyboard/projects/diner/shots/s1/frame") in paths
    assert ("POST", "/api/storyboard/projects/diner/shots/s1/regenerate") in paths
    assert ("POST", "/api/storyboard/projects/diner/shots/s1/speak") in paths
    assert be.calls[2][2] == {"quality": "final", "seed": None, "edit": ""}


def test_job_status_and_get_output():
    app = M.build(FakeBackend())
    assert _call(app, "job_status", {"project_id": "diner", "shot_id": "s1"})["status"] == "running"
    out = _call(app, "get_output", {"project_id": "diner", "shot_id": "s1", "take_id": "v1"})
    assert out["path"] == "projects/diner/shots/s1/v1.mp4"
    assert out["video_url"] == "http://127.0.0.1:8765/api/file?path=v1.mp4"


def test_not_ready_output_is_an_error():
    from mcp.server.mcpserver.exceptions import ToolError

    app = M.build(FakeBackend())
    with pytest.raises(ToolError, match="isn't ready yet"):
        asyncio.run(app.call_tool("get_output", {"project_id": "diner", "shot_id": "s1"}))


def test_http_binds_loopback_unless_lan_is_explicit():
    assert M.check_host("127.0.0.1", lan=False) == "127.0.0.1"
    for host in ("0.0.0.0", "198.51.100.20", "::"):  # 198.51.100.x: documentation range (RFC 5737)
        with pytest.raises(SystemExit):
            M.check_host(host, lan=False)
    assert M.check_host("198.51.100.20", lan=True) == "198.51.100.20"


def test_backend_url_ids_are_quoted():
    be = FakeBackend()
    asyncio.run(M.build(be).call_tool("generate_shot", {"project_id": "a/b", "shot_id": "s 1"}))
    assert be.calls[-1][1] == "/api/storyboard/projects/a%2Fb/shots/s%201/regenerate"
