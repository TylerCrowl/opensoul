"""One app-wide guard: OpenSoul answers only its own page on this computer.

Why: the server has no login. A web page on another site could use DNS rebinding (its own name pointed at
127.0.0.1) to read character pictures and voice clips, or to make stories. The browser then sends that site's
name in the Host header, so a Host allow-list stops it.

Rules (every HTTP and WebSocket request):
1. Host must be 127.0.0.1, localhost or [::1] (plus any names in OPENSOUL_ALLOWED_HOSTS, comma separated),
   and its port must be the port this server listens on.
2. State-changing requests (POST, PUT, PATCH, DELETE): Origin (else Referer), when sent, must be this same
   origin. A request with a body must be JSON or a file upload (multipart/form-data), so a plain cross-site
   form can't post text.

Refusals are 403 (wrong host or origin) or 415 (wrong body type), with a short JSON reason.
"""
from __future__ import annotations

import json
import os
from urllib.parse import urlsplit

LOCAL_NAMES = ("127.0.0.1", "localhost", "[::1]")
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
BODY_TYPES = ("application/json", "multipart/form-data", "application/x-www-form-urlencoded")
HOST_MSG = "OpenSoul only answers its own page on this computer (http://127.0.0.1)."
ORIGIN_MSG = "Only OpenSoul's own page on this computer can change this."
TYPE_MSG = "Send JSON."


def allowed_names() -> set[str]:
    """The local names, plus OPENSOUL_ALLOWED_HOSTS (for example a test client or a LAN name you chose)."""
    extra = {h.strip().lower() for h in os.environ.get("OPENSOUL_ALLOWED_HOSTS", "").split(",") if h.strip()}
    return set(LOCAL_NAMES) | extra


def split_host(value: str, default_port: int | None = 80) -> tuple[str, int | None]:
    """'Example:8080' -> ('example', 8080); '[::1]:7860' -> ('[::1]', 7860); bad input -> ('', None)."""
    v = (value or "").strip().lower()
    if not v or any(c in v for c in "/@ \t"):
        return "", None
    if v.startswith("["):
        name, _, rest = v.partition("]")
        name += "]"
        port_s = rest[1:] if rest.startswith(":") else ""
        if rest and not rest.startswith(":"):
            return "", None
    else:
        name, _, port_s = v.partition(":")
    if port_s:
        if not port_s.isdigit():
            return "", None
        return name, int(port_s)
    return name, default_port


def host_ok(host: str, server_port: int | None) -> bool:
    name, port = split_host(host)
    if not name or name not in allowed_names():
        return False
    return server_port is None or port == server_port


def same_origin(origin: str, host: str) -> bool:
    """True when ``origin`` (an Origin or Referer value) is http://<the request's own Host>."""
    try:
        u = urlsplit(origin.strip())
    except ValueError:
        return False
    if u.scheme != "http" or not u.netloc or u.username or u.password:
        return False
    o_name, o_port = split_host(u.netloc)
    h_name, h_port = split_host(host)
    return bool(o_name) and o_name == h_name and o_port == h_port and o_name in allowed_names()


def check(method: str, headers: dict[str, str], server_port: int | None) -> tuple[int, str] | None:
    """None when the request may go on, else (status, reason). ``headers`` keys are lower case."""
    host = headers.get("host", "")
    if not host_ok(host, server_port):
        return 403, HOST_MSG
    if method.upper() not in UNSAFE:
        return None
    origin = headers.get("origin")
    if origin is not None:
        if not same_origin(origin, host):
            return 403, ORIGIN_MSG
    elif headers.get("referer") and not same_origin(headers["referer"], host):
        return 403, ORIGIN_MSG
    has_body = headers.get("content-length", "0").strip() not in ("", "0") or "transfer-encoding" in headers
    ctype = headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if has_body and ctype not in BODY_TYPES:
        return 415, TYPE_MSG
    return None


class LocalOnlyMiddleware:
    """Pure ASGI middleware (it never buffers bodies, so file streaming is unchanged)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}
        server = scope.get("server")
        port = server[1] if server and len(server) > 1 and server[1] else None
        bad = check(scope.get("method", "GET"), headers, port)
        if bad is None:
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            return await send({"type": "websocket.close", "code": 1008})
        status, reason = bad
        body = json.dumps({"detail": reason}).encode()
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
                                (b"cache-control", b"no-store")]})
        await send({"type": "http.response.body", "body": body})
