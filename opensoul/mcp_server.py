"""OpenSoul MCP server: lets an agent (Grok Bot, Hermes Agent, any MCP client) drive a running OpenSoul app, and set it
up (hardware, model recommendations, dry-run install plans; installs and slot swaps only with the user's approval).

Every tool is a thin wrapper over the app's own HTTP routes (no generation logic here), so it behaves exactly like
the Storyboard UI: preview mode stays preview mode, renders queue the same way. Docs: docs/MCP.md.

    python -m opensoul.mcp_server                      # stdio (default)
    python -m opensoul.mcp_server --http               # streamable HTTP on 127.0.0.1:8770/mcp
    python -m opensoul.mcp_server --http --lan --host 198.51.100.20   # LAN only when asked for explicitly

The app it talks to: OPENSOUL_URL (default http://127.0.0.1:8765). SDK: the official MCP Python SDK
(``mcp`` 2.3.0, MIT license)."""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_URL = "http://127.0.0.1:8765"
DEFAULT_PORT = 8770
SB = "/api/storyboard"
SETUP = "/api/setup"
JOB_TOOLS = ("list_projects", "generate_still", "generate_shot", "tts_line", "job_status", "get_output")
# Setup tools (docs/SETUP.md): read-only except apply_install / set_slot, which need the user's approval token.
SETUP_TOOLS = ("list_hardware", "recommend_models", "plan_install", "apply_install", "set_slot", "health_check")
TOOLS = JOB_TOOLS + SETUP_TOOLS


class BackendError(RuntimeError):
    pass


class Backend:
    """The running app's HTTP API (stdlib only)."""

    def __init__(self, base_url: str | None = None, timeout: float = 120.0):
        self.base = (base_url or os.environ.get("OPENSOUL_URL") or DEFAULT_URL).rstrip("/")
        self.timeout = timeout

    def request(self, method: str, path: str, body: dict | None = None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"} if data else {})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read() or b"{}").get("detail")
            except ValueError:
                detail = None
            raise BackendError(f"OpenSoul said {e.code}: {detail or e.reason}") from None
        except urllib.error.URLError as e:
            raise BackendError(f"OpenSoul isn't reachable at {self.base} ({e.reason}). Start the app first.") from None

    def url(self, rel: str | None) -> str | None:
        return None if not rel else rel if rel.startswith("http") else self.base + rel


def _q(s: str) -> str:
    return urllib.parse.quote(str(s), safe="")


def _shot(project: dict, shot_id: str) -> dict:
    s = next((x for x in project.get("shots", []) if x.get("id") == shot_id), None)
    if s is None:
        raise BackendError(f"No shot {shot_id!r} in project {project.get('id')!r}.")
    return s


def _take(shot: dict, take_id: str | None) -> dict:
    vs = shot.get("versions") or []
    v = next((x for x in vs if x.get("id") == take_id), None) if take_id else (vs[-1] if vs else None)
    if v is None:
        raise BackendError(f"Shot {shot.get('id')!r} has no take {take_id!r}." if take_id else
                           f"Shot {shot.get('id')!r} has no takes yet.")
    return v


def _query(**kw: Any) -> str:
    q = {k: v for k, v in kw.items() if v not in (None, "")}
    return ("?" + urllib.parse.urlencode(q)) if q else ""


def build(backend: Backend | None = None):
    """The MCPServer with the job tools and the setup tools, bound to ``backend`` (tests pass a mock)."""
    import functools

    from mcp.server.mcpserver import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError

    be = backend or Backend()

    def plain_errors(fn):  # the app's plain message reaches the agent (a crash would hide it)
        @functools.wraps(fn)
        def wrap(*a, **kw):
            try:
                return fn(*a, **kw)
            except BackendError as e:
                raise ToolError(str(e)) from None
        return wrap

    app = MCPServer(name="opensoul", instructions=(
        "OpenSoul makes character videos on the user's own GPU. Find a project and shot with list_projects, make a "
        "start frame (generate_still) or a take (generate_shot), hear a line in the character's voice (tts_line), "
        "poll job_status, then get_output for the file. Setup: list_hardware and recommend_models are read-only; "
        "plan_install is a dry run that returns a plan_id. Only the user can approve a plan (they run "
        "`python -m opensoul.setup_engine approve <plan_id>` and give you the token); never guess or make a token. "
        "apply_install and set_slot change things only with that token and approve=true."))

    @app.tool()
    @plain_errors
    def list_projects() -> dict:
        """Stories (projects) in the app: id, title, lead character, shot count."""
        return be.request("GET", f"{SB}/projects")

    @app.tool()
    @plain_errors
    def generate_still(project_id: str, shot_id: str, edit: str = "", seed: int | None = None) -> dict:
        """Make a new start-frame still for a shot (its cast composed into its scene). Returns the updated shot."""
        return be.request("POST", f"{SB}/projects/{_q(project_id)}/shots/{_q(shot_id)}/frame",
                          {"edit": edit, "seed": seed})

    @app.tool()
    @plain_errors
    def generate_shot(project_id: str, shot_id: str, quality: str = "draft", seed: int | None = None,
                      edit: str = "") -> dict:
        """Render a NEW take of a shot (quality 'draft' or 'final'; earlier takes are kept). Poll job_status."""
        return be.request("POST", f"{SB}/projects/{_q(project_id)}/shots/{_q(shot_id)}/regenerate",
                          {"quality": quality, "seed": seed, "edit": edit})

    @app.tool()
    @plain_errors
    def tts_line(project_id: str, shot_id: str, line: str | None = None, voice: str | None = None) -> dict:
        """Hear a shot's spoken line in the speaking character's own voice (or ``voice``). Returns the audio URL."""
        r = be.request("POST", f"{SB}/projects/{_q(project_id)}/shots/{_q(shot_id)}/speak",
                       {"line": line, "voice": voice})
        return {**r, "audio_url": be.url(r.get("audio_url"))}

    @app.tool()
    @plain_errors
    def job_status(project_id: str, shot_id: str, take_id: str | None = None) -> dict:
        """Status of a take (default: the shot's newest): queued, running, ready or error."""
        v = _take(_shot(be.request("GET", f"{SB}/projects/{_q(project_id)}"), shot_id), take_id)
        return {k: v.get(k) for k in ("id", "status", "label", "error", "progress", "created") if k in v}

    @app.tool()
    @plain_errors
    def get_output(project_id: str, shot_id: str, take_id: str | None = None) -> dict:
        """The finished take's file: its path in the app's data folder and a URL to fetch it."""
        v = _take(_shot(be.request("GET", f"{SB}/projects/{_q(project_id)}"), shot_id), take_id)
        if v.get("status") != "ready":
            raise BackendError(f"Take {v.get('id')} isn't ready yet ({v.get('status')}).")
        return {"take_id": v.get("id"), "path": v.get("file"), "video_url": be.url(v.get("video_url")),
                "poster_url": be.url(v.get("poster_url")), "missing": bool(v.get("missing"))}

    # ------------------------------------------------------------ setup tools (docs/SETUP.md)

    @app.tool()
    @plain_errors
    def list_hardware(simulate: str | None = None) -> dict:
        """This computer, read locally: GPU, memory, platform, the picker's tier and any recommendation-only tier.
        Changes nothing. ``simulate`` (preview mode only) names a simulated computer."""
        return be.request("GET", f"{SETUP}/hardware{_query(simulate=simulate)}")

    @app.tool()
    @plain_errors
    def recommend_models(tier: str | None = None, commercial: str = "any", simulate: str | None = None) -> dict:
        """Recommended model per step for this computer (or ``tier``) plus every model slot with licence, memory, disk
        and source. ``commercial``: any | allowed | open_only. Changes nothing."""
        return be.request("GET", f"{SETUP}/recommend{_query(tier=tier, commercial=commercial, simulate=simulate)}")

    @app.tool()
    @plain_errors
    def plan_install(models: list[str] | None = None, slot_changes: dict[str, str] | None = None,
                     commercial: str = "any") -> dict:
        """Dry run: what installing ``models`` and/or switching ``slot_changes`` ({slot: model}) would download, the disk
        it needs, licences that need a yes, and slot changes. Downloads nothing. Show the plan to the user; they approve
        it themselves and give you a token."""
        return be.request("POST", f"{SETUP}/plan", {"models": list(models or []), "slot_changes": dict(slot_changes or {}),
                                                     "commercial": commercial})

    @app.tool()
    @plain_errors
    def apply_install(plan_id: str, approval_token: str, approve: bool = False) -> dict:
        """Run an approved plan. Needs the token the USER got from approving it and approve=true. In preview mode it only
        reports what it would run."""
        return be.request("POST", f"{SETUP}/apply", {"plan_id": plan_id, "approval_token": approval_token,
                                                      "approve": bool(approve)})

    @app.tool()
    @plain_errors
    def set_slot(slot: str, model: str, approval_token: str | None = None, plan_id: str | None = None) -> dict:
        """Swap a slot's model. Without a token it returns a plan to show the user (changes nothing); with the plan_id and
        the user's token it records the swap (installed models only). Existing stories keep their engines."""
        return be.request("POST", f"{SETUP}/slot", {"slot": slot, "model": model, "approval_token": approval_token,
                                                     "plan_id": plan_id})

    @app.tool()
    @plain_errors
    def health_check() -> dict:
        """Missing model files per stage, manifest problems, free disk and memory, active slots. Changes nothing."""
        return be.request("GET", f"{SETUP}/health")

    return app


def check_host(host: str, lan: bool) -> str:
    """Loopback unless --lan; never a wildcard address (0.0.0.0 / ::) unless --lan is given explicitly."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if host == "localhost":
            return host
        raise SystemExit(f"--host must be an IP address, got {host!r}")
    if not ip.is_loopback and not lan:
        raise SystemExit(f"Refusing to listen on {host} without --lan (the default is 127.0.0.1, this computer only).")
    return host


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m opensoul.mcp_server", description="OpenSoul MCP server")
    ap.add_argument("--http", action="store_true", help="streamable HTTP instead of stdio")
    ap.add_argument("--host", default="127.0.0.1", help="HTTP bind address (default 127.0.0.1)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--lan", action="store_true", help="allow a non-loopback --host (other machines can connect)")
    ap.add_argument("--url", default=None, help=f"the OpenSoul app (default $OPENSOUL_URL or {DEFAULT_URL})")
    a = ap.parse_args(argv)
    app = build(Backend(a.url))
    if a.http:
        app.run("streamable-http", host=check_host(a.host, a.lan), port=a.port)
    else:
        app.run("stdio")


if __name__ == "__main__":
    main()
