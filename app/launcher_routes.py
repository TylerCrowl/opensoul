"""Launcher API and the first-run welcome page. Mounted by app/server.py.

GET  /welcome                     first-run setup: what this computer is, Preview or Connect a studio
GET  /help/desktop                docs/DESKTOP.md as plain text (the welcome page's "read how it works" link)
GET  /api/launcher/status         {"app": "opensoul", mode, studio_url, launched, ...} (the launcher's health check)
POST /api/launcher/test   {url, api_url?}   GET <url>/system_stats + checks the comfy-api-proxy answers (changes nothing);
                          says what it found (ComfyUI version, GPU, memory) or why not, and warns about public addresses
POST /api/launcher/config {mode, studio_url, studio_api_url?}   saves the choice (launcher.json) and applies it right away,
                          no restart; the reply carries the same public-address warning (a warning, not a block)
POST /api/launcher/quit           stops the server (only when started by the launcher)

The POST routes only accept JSON from this computer's own page. The app-wide guard (app/local_guard.py) checks Host
and Origin on every route, so another website open in the same browser can't point the app at a different studio.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel

from opensoul import launcher as L

router = APIRouter(tags=["launcher"])
WEB = Path(__file__).resolve().parent / "web"
def local_only(request: Request) -> None:
    """The app-wide guard (app/local_guard.py) already checked Host and Origin; these routes also need JSON."""
    from app.local_guard import ORIGIN_MSG, host_ok, same_origin

    host = request.headers.get("host", "")
    origin = request.headers.get("origin")
    port = request.scope.get("server", (None, None))[1] if request.scope.get("server") else None
    if not host_ok(host, port) or (origin is not None and not same_origin(origin, host)):
        raise HTTPException(403, ORIGIN_MSG)
    if "application/json" not in (request.headers.get("content-type") or ""):
        raise HTTPException(415, "Send JSON.")


def _launched() -> bool:
    return os.environ.get("OPENSOUL_LAUNCHED") == "1"


def _state() -> dict:
    cfg = L.load_config()
    dry = os.environ.get("OPENSOUL_DRY_RUN", "1").strip().lower() in {"1", "true", "yes", ""}
    return {"app": "opensoul", "launched": _launched(), "mode": "preview" if dry else "studio",
            "saved_mode": cfg["mode"], "studio_url": cfg["studio_url"], "studio_api_url": cfg["studio_api_url"],
            "first_run_done": cfg["first_run_done"], "pid": os.getpid()}


@router.get("/welcome", include_in_schema=False)
def welcome():
    html = (WEB / "welcome.html").read_text(encoding="utf-8")
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


@router.get("/help/desktop", include_in_schema=False)
def help_desktop():
    doc = WEB.parent.parent / "docs" / "DESKTOP.md"
    try:
        text = doc.read_text(encoding="utf-8")
    except OSError:
        raise HTTPException(404, "The desktop guide isn't in this copy of OpenSoul.") from None
    return PlainTextResponse(text, headers={"Cache-Control": "no-cache"})


@router.get("/api/launcher/status")
def status():
    return _state()


class TestBody(BaseModel):
    url: str
    api_url: str = ""


@router.post("/api/launcher/test")
def test(body: TestBody, request: Request):
    local_only(request)
    return L.probe_studio(body.url, api_url=body.api_url)


class ConfigBody(BaseModel):
    mode: str
    studio_url: str = ""
    studio_api_url: str = ""


@router.post("/api/launcher/config")
def config(body: ConfigBody, request: Request):
    local_only(request)
    try:
        cfg = L.save_config({"mode": body.mode, "studio_url": body.studio_url,
                             "studio_api_url": body.studio_api_url, "first_run_done": True})
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    L.apply_env(cfg)
    warning = None
    if cfg["mode"] == "studio":
        for u in (cfg["studio_url"], L.api_url_for(cfg["studio_url"], cfg["studio_api_url"])):
            warning = warning or L.check_address(u)["warning"]
    return {**_state(), "warning": warning}


@router.post("/api/launcher/quit")
def quit_app(request: Request):
    local_only(request)
    if not _launched():
        raise HTTPException(409, "The OpenSoul app did not start this server. Stop it where you started it.")
    import signal

    threading.Timer(0.5, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()
    return {"ok": True, "message": "OpenSoul is closing. You can close this tab."}
