"""One-click launcher: start the OpenSoul server in the background, open the browser, remember the studio choice.

    python -m opensoul.launcher            # same as "open": reuse a running server or start one, then open the browser
    python -m opensoul.launcher serve      # run the server in the foreground (what "open" starts in the background)
    python -m opensoul.launcher stop       # stop the background server
    python -m opensoul.launcher status     # print where it is running and the saved mode

The desktop packages (packaging/, docs/DESKTOP.md) call ``open``. In the Mac app ``open`` shows OpenSoul in its own window
(opensoul/desktop_window.py, pywebview) and quits the server when that window closes; elsewhere, or if the window
can't open, it opens the browser. Everything the launcher keeps lives in one
per-user folder (``home()``): ``launcher.json`` (preview or studio, and the studio address the user typed),
``data/`` (OPENSOUL_DATA), ``logs/server.log`` and ``server.json`` (port and pid of the running server).

Rules: the server only listens on 127.0.0.1; the launcher never changes network, firewall or VPN settings, it only
stores an address the user typed and checks it with one GET to ComfyUI's ``/system_stats`` (plus one to the API
helper). Those checks go straight to that address: no proxy, no redirects to anywhere else. Saving a studio also puts
its host on NO_PROXY, so the app's render calls go straight there too. Preview mode (OPENSOUL_DRY_RUN=1) is the
default and needs no GPU.

Addresses (``check_address``): home-network, VPN and this-computer addresses are fine; an address on the public
internet is allowed but gets a plain warning (ComfyUI has no password). It is a warning, not a block, because some
real setups use addresses Python calls "global" (IPv6 home networks hand out global addresses to every device).
Non-http(s) addresses and addresses with a user name or password in them are refused.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

APP_NAME = "OpenSoul"
DEFAULT_PORT = 7860
PORT_RANGE = range(7860, 7880)
COMFY_DEFAULT_PORT = 8188
API_PROXY_PORT = 8189  # comfy-api-proxy in front of ComfyUI: what comfy-sdk talks to (opensoul/comfy_client.py)
MODES = ("preview", "studio")
DEFAULT_CONFIG: dict[str, Any] = {"mode": "preview", "studio_url": "", "studio_api_url": "", "first_run_done": False}
EXAMPLE_URL = "http://my-studio.local:8188"
# RFC 6598 shared address space, 100.64/10: carrier-grade NAT, and the range mesh VPNs give their devices. Python's
# ipaddress calls it neither private nor global, so it is listed here (from its integer form, 0x64400000).
SHARED_NET = ipaddress.IPv4Network((0x64400000, 10))


# ---------- where things live ----------

def home(env: dict | None = None, platform: str | None = None) -> Path:
    """The per-user launcher folder. OPENSOUL_LAUNCHER_HOME overrides it (tests, portable installs)."""
    env = os.environ if env is None else env
    if env.get("OPENSOUL_LAUNCHER_HOME"):
        return Path(env["OPENSOUL_LAUNCHER_HOME"]).expanduser()
    platform = platform or sys.platform
    user = Path(env.get("HOME") or Path.home())
    if platform == "darwin":
        return user / "Library" / "Application Support" / APP_NAME
    if platform.startswith("win"):
        base = env.get("LOCALAPPDATA") or str(user / "AppData" / "Local")
        return Path(base) / APP_NAME
    return Path(env.get("XDG_DATA_HOME") or user / ".local" / "share") / "opensoul"


def config_path(h: Path | None = None) -> Path:
    return (h or home()) / "launcher.json"


def server_file(h: Path | None = None) -> Path:
    return (h or home()) / "server.json"


def log_path(h: Path | None = None) -> Path:
    return (h or home()) / "logs" / "server.log"


# ---------- config ----------

def load_config(h: Path | None = None) -> dict[str, Any]:
    try:
        raw = json.loads(config_path(h).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    cfg = dict(DEFAULT_CONFIG)
    if isinstance(raw, dict):
        if raw.get("mode") in MODES:
            cfg["mode"] = raw["mode"]
        for k in ("studio_url", "studio_api_url"):
            if isinstance(raw.get(k), str):
                cfg[k] = raw[k]
        cfg["first_run_done"] = bool(raw.get("first_run_done"))
    if cfg["mode"] == "studio" and not cfg["studio_url"]:
        cfg["mode"] = "preview"  # a studio with no address can't work: fall back to preview
    return cfg


def save_config(cfg: dict[str, Any], h: Path | None = None) -> dict[str, Any]:
    """Validates and writes launcher.json atomically. Raises ValueError with a plain message on bad input."""
    mode = cfg.get("mode", "preview")
    if mode not in MODES:
        raise ValueError("Mode must be preview or studio.")
    url = cfg.get("studio_url") or ""
    if url:
        url = normalize_url(url)
    if mode == "studio" and not url:
        raise ValueError(f"Type your studio's address first, for example {EXAMPLE_URL}")
    api = cfg.get("studio_api_url") or ""
    api = normalize_url(api, default_port=API_PROXY_PORT) if api else ""
    out = {"mode": mode, "studio_url": url, "studio_api_url": api,
           "first_run_done": bool(cfg.get("first_run_done", True))}
    p = config_path(h)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, p)
    return out


def normalize_url(text: str, default_port: int = COMFY_DEFAULT_PORT) -> str:
    """Turns what a person types ("spark.local", "192.0.2.10:8188", "http://x:8189/") into a clean base URL.

    Only http/https, a host, no user:password, no query. A missing port becomes ComfyUI's 8188."""
    s = (text or "").strip()
    if not s:
        raise ValueError(f"Type your studio's address, for example {EXAMPLE_URL}")
    if len(s) > 300 or any(c.isspace() for c in s):
        raise ValueError(f"That address has spaces in it. It should look like {EXAMPLE_URL}")
    if "://" not in s:
        head = s.split("/", 1)[0].split(":", 1)[0].lower()
        rest = s.split(":", 1)[1] if ":" in s.split("/", 1)[0] else ""
        if head in ("file", "javascript", "data", "ftp", "ws", "wss", "about", "mailto") or (
                rest and not s.startswith("[") and "." not in head and head != "localhost" and not rest[:1].isdigit()):  # vbscript:x, foo:bar
            raise ValueError("The address should start with http:// or https://")
        s = "http://" + s
    u = urllib.parse.urlsplit(s)
    if u.scheme not in ("http", "https"):
        raise ValueError("The address should start with http:// or https://")
    if "@" in u.netloc or u.username or u.password:
        raise ValueError("Remove the user name and password from the address.")
    if not u.hostname:
        raise ValueError(f"That doesn't look like an address. Example: {EXAMPLE_URL}")
    try:
        port = u.port
    except ValueError:
        raise ValueError("The port (the number after ':') isn't valid.") from None
    if u.query or u.fragment:
        raise ValueError("Remove the part after '?' or '#' from the address.")
    host = u.hostname
    if host in ("0.0.0.0", "::"):
        raise ValueError("0.0.0.0 is how the studio listens, not its address. Use the studio computer's own address, "
                         "for example " + EXAMPLE_URL)
    if ":" in host:  # IPv6 literal
        host = f"[{host}]"
    port = port or default_port
    path = u.path.rstrip("/")
    return f"{u.scheme}://{host}:{port}{path}"


def _ip_kind(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    """'local' (this computer, home network, VPN, link-local), 'public' (the internet) or 'other' (reserved ranges)."""
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if ip.is_loopback or ip.is_link_local or (isinstance(ip, ipaddress.IPv4Address) and ip in SHARED_NET):
        return "local"
    if ip.is_multicast or ip.is_unspecified:
        return "other"
    if ip.is_private:  # 10/8, 172.16/12, 192.168/16, fc00::/7 (also the documentation ranges)
        return "local"
    return "public" if ip.is_global else "other"


PUBLIC_WARNING = ("This address is on the public internet, not your home network. ComfyUI has no password, so "
                  "anyone online who finds it could use your studio. Use the studio's home-network address instead, "
                  "or a private connection such as a VPN when you're away from home.")


def check_address(url: str, resolver=None) -> dict[str, Any]:
    """Where an address points, without contacting it: {ok, url, host, kind, ips, warning, message}.

    kind: 'local' | 'public' | 'unknown' (a name that didn't resolve) | 'other'. Names ending in .local are home-network
    names (mDNS); other names are looked up once with the computer's normal resolver. Never raises."""
    try:
        base = normalize_url(url)
    except ValueError as e:
        return {"ok": False, "url": url, "kind": "invalid", "ips": [], "warning": None, "message": str(e)}
    host = (urllib.parse.urlsplit(base).hostname or "").lower()
    out: dict[str, Any] = {"ok": True, "url": base, "host": host, "ips": [], "warning": None, "message": ""}
    try:
        ips = [ipaddress.ip_address(host)]
    except ValueError:
        if host == "localhost" or host.endswith(".localhost"):
            return {**out, "kind": "local"}
        resolver = resolver or socket.getaddrinfo
        try:
            infos = resolver(host, None, 0, socket.SOCK_STREAM)
            ips = []
            for info in infos:
                try:
                    a = ipaddress.ip_address(str(info[4][0]).split("%", 1)[0])
                except ValueError:
                    continue
                if a not in ips:
                    ips.append(a)
        except (OSError, UnicodeError):
            ips = []
        if not ips:
            return {**out, "kind": "local" if host.endswith(".local") else "unknown"}
    kinds = [_ip_kind(a) for a in ips]
    kind = "public" if "public" in kinds else "local" if "local" in kinds else "other"
    out.update(kind=kind, ips=[str(a) for a in ips])
    if kind == "public":
        out["warning"] = PUBLIC_WARNING
    return out


def api_url_for(studio_url: str, api_url: str = "") -> str:
    """The comfy-api-proxy address: the one saved, else the studio's host on port 8189."""
    if api_url:
        return normalize_url(api_url, default_port=API_PROXY_PORT)
    u = urllib.parse.urlsplit(normalize_url(studio_url))
    host = f"[{u.hostname}]" if ":" in (u.hostname or "") else u.hostname
    return f"{u.scheme}://{host}:{API_PROXY_PORT}"


def apply_env(cfg: dict[str, Any], env: dict | None = None) -> dict:
    """Sets the variables the app reads on every call: preview vs real renders, where ComfyUI is (stills that call it
    directly, OPENSOUL_COMFYUI_URL) and where its comfy-api-proxy is (everything through comfy-sdk, COMFY_BASE_URL)."""
    env = os.environ if env is None else env
    if cfg.get("mode") == "studio" and cfg.get("studio_url"):
        env["OPENSOUL_DRY_RUN"] = "0"
        env["COMFY_BASE_URL"] = api_url_for(cfg["studio_url"], cfg.get("studio_api_url") or "")
        env["OPENSOUL_COMFYUI_URL"] = cfg["studio_url"]
        _bypass_proxy(env, [cfg["studio_url"], env["COMFY_BASE_URL"]])
    else:
        env["OPENSOUL_DRY_RUN"] = "1"
    return env


def _bypass_proxy(env: dict, urls: list[str]) -> None:
    """Adds the studio's host(s) to NO_PROXY / no_proxy so urllib and httpx talk to it directly, never through a proxy
    configured on this computer (with these set, urllib on macOS also stops reading the system proxy settings)."""
    hosts = []
    for url in urls:
        h = urllib.parse.urlsplit(url).hostname
        if h and h not in hosts:
            hosts.append(h)
    for key in ("NO_PROXY", "no_proxy"):
        cur = [x.strip() for x in (env.get(key) or "").split(",") if x.strip()]
        env[key] = ",".join(cur + [h for h in hosts if h not in cur])


# ---------- checking a studio ----------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect would send the check somewhere the user didn't type: treat it as 'not ComfyUI'."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def _direct_open(req, timeout=None):
    """Straight to the address: no proxy from the environment or system settings, no redirects."""
    return _DIRECT.open(req, timeout=timeout)


def _answers(url: str, timeout: float, opener) -> bool:
    """True when any web server answers at url (an error page counts: something is listening)."""
    try:
        with opener(urllib.request.Request(url), timeout=timeout) as r:
            r.read(1000)
        return True
    except urllib.error.HTTPError:
        return True
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError, ValueError):
        return False


def _gpu_name(raw: Any) -> str:
    """ComfyUI's device name, e.g. "cuda:0 NVIDIA GB10 : cudaMallocAsync" -> "NVIDIA GB10"."""
    import re

    s = str(raw or "").split(" : ", 1)[0].strip()
    return re.sub(r"^(cuda|mps|xpu|cpu|privateuseone)(:\d+)?\s*", "", s, flags=re.I).strip()


def _unreachable(base: str, err: BaseException) -> dict[str, Any]:
    u = urllib.parse.urlsplit(base)
    reason = getattr(err, "reason", err)
    if isinstance(reason, socket.gaierror):
        return {"kind": "dns", "message": f"Couldn't find a computer called {u.hostname}. Check the spelling, or use "
                                          "its number address instead (it often starts with 192.168. or 10.)."}
    if isinstance(reason, (socket.timeout, TimeoutError)) or "timed out" in str(reason).lower():
        return {"kind": "timeout", "message": "No answer from that address. Check that the studio is on. Check that it "
                                              "is on the same network as this computer."}
    if isinstance(reason, ConnectionRefusedError):
        hint = (" ComfyUI usually uses port 8188." if u.port != COMFY_DEFAULT_PORT else "")
        return {"kind": "refused", "message": f"Found the computer, but nothing answered on port {u.port}. Check that "
                                              "ComfyUI runs there and accepts connections from other computers "
                                              f"(see \u201cWhere do I find this address?\u201d).{hint}"}
    return {"kind": "unreachable", "message": "Couldn't connect to that address. Check that the studio is on and runs "
                                              "ComfyUI. Check that this computer is on the same network."}


def _not_comfy(base: str, detail: str = "") -> dict[str, Any]:
    port = urllib.parse.urlsplit(base).port
    if port == API_PROXY_PORT:
        return {"kind": "wrong_port", "message": "That's the API helper's port. The studio address usually ends in "
                                                 ":8188. OpenSoul finds the helper itself."}
    if port != COMFY_DEFAULT_PORT:
        return {"kind": "wrong_port", "message": f"Something answered on port {port}{detail}, but it isn't ComfyUI. "
                                                 "ComfyUI usually uses port 8188. Put :8188 at the end of the address."}
    return {"kind": "not_comfy", "message": f"Something answered at that address{detail}, but it isn't ComfyUI."}


# OpenSoul's own ComfyUI nodes (custom_nodes/opensoul_nodes) and what needs them (OS-009). LatentSync is optional.
OPENSOUL_NODES = {
    "OpenSoulIdentityGate": "character sheets",
    "OpenSoulVoxCPM2TTS": "VoxCPM2 voices (new stories)",
    "OpenSoulKokoroTTS": "Kokoro voices",
    "OpenSoulOrpheusTTS": "Orpheus voices",
    "OpenSoulChatterboxTTS": "Chatterbox voices",
}
NODES_HINT = ("Install the OpenSoul nodes on the studio: link custom_nodes/opensoul_nodes into ComfyUI's custom_nodes "
              "folder (see the README, 'Run it on your studio'). Then restart ComfyUI and test again.")


def missing_nodes(base: str, timeout: float = 4.0, opener=None) -> list[str] | None:
    """OpenSoul node classes the studio's ComfyUI does not have (GET /object_info/<class>), or None when the studio
    did not answer that question."""
    opener = opener or _direct_open
    missing = []
    for cls in OPENSOUL_NODES:
        try:
            with opener(urllib.request.Request(f"{base}/object_info/{cls}", headers={"Accept": "application/json"}),
                        timeout=timeout) as r:
                data = json.loads(r.read(2_000_000).decode("utf-8", "replace"))
        except urllib.error.HTTPError:
            missing.append(cls)
            continue
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError, ValueError):
            return None
        if not (isinstance(data, dict) and cls in data):
            missing.append(cls)
    return missing


def probe_studio(url: str, timeout: float = 4.0, opener=None, api_url: str = "", resolver=None) -> dict[str, Any]:
    """Says where the address points (check_address), GETs ComfyUI's /system_stats, then checks that the studio's
    comfy-api-proxy answers. Straight to the address: no proxy, no redirects.

    Returns {ok, kind, url, api_url, api_ok, message, warning, address, gpu, vram_gb, comfyui}; never raises.
    kind: ok | proxy_missing | invalid | dns | timeout | refused | unreachable | wrong_port | not_comfy."""
    addr = check_address(url, resolver=resolver)
    if not addr["ok"]:
        return {"ok": False, "kind": "invalid", "url": url, "message": addr["message"], "warning": None}
    base = addr["url"]
    info = {"url": base, "warning": addr["warning"], "address": {"kind": addr["kind"], "ips": addr["ips"]}}
    opener = opener or _direct_open
    req = urllib.request.Request(base + "/system_stats", headers={"Accept": "application/json"})
    try:
        with opener(req, timeout=timeout) as r:
            body = r.read(200_000)
        data = json.loads(body.decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return {"ok": False, **info, **_not_comfy(base, f" (error {e.code})")}
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as e:
        return {"ok": False, **info, **_unreachable(base, e)}
    except ValueError:
        return {"ok": False, **info, **_not_comfy(base)}
    if not isinstance(data, dict) or not isinstance(data.get("system"), dict):
        return {"ok": False, **info, **_not_comfy(base)}
    dev = (data.get("devices") or [{}])[0] if isinstance(data.get("devices"), list) and data.get("devices") else {}
    name = _gpu_name(dev.get("name")) if isinstance(dev, dict) else ""
    vram = dev.get("vram_total") if isinstance(dev, dict) else None
    vram_gb = round(vram / 1024 ** 3, 1) if isinstance(vram, (int, float)) and vram > 0 else None
    ver = data["system"].get("comfyui_version")
    ver = str(ver) if isinstance(ver, (str, int, float)) and str(ver).strip() else None
    msg = ("Connected to ComfyUI" + (f" {ver}" if ver else "") + (f" on {name}" if name else "")
           + (f" ({vram_gb:g} GB)" if vram_gb else "") + ".")
    try:
        api = api_url_for(base, api_url)
    except ValueError:
        api = ""
    api_ok = bool(api) and _answers(api + "/", timeout, opener)
    if not api_ok:
        msg += (f" But its API helper (comfy-api-proxy) didn't answer at {api or 'that address'}; videos and voices"
                " need it running there too.")
    if api and not addr["warning"]:
        api_addr = check_address(api, resolver=resolver)
        info["warning"] = api_addr.get("warning")
    miss = missing_nodes(base, timeout, opener)
    kind = "ok" if api_ok else "proxy_missing"
    if miss:  # OS-009: Connected to ComfyUI, but the OpenSoul nodes are not there
        needs = sorted({OPENSOUL_NODES[c] for c in miss})
        msg += f" But the studio does not have the OpenSoul nodes for: {', '.join(needs)}. {NODES_HINT}"
        if "OpenSoulIdentityGate" in miss and kind == "ok":
            kind = "nodes_missing"
    return {"ok": True, "kind": kind, **info, "api_url": api, "api_ok": api_ok,
            "message": msg, "gpu": name or None, "vram_gb": vram_gb, "comfyui": ver,
            "missing_nodes": miss or [], "nodes_checked": miss is not None}


# ---------- the running server ----------

def port_free(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if not sys.platform.startswith("win"):  # like uvicorn: a port in TIME_WAIT after a Quit is still usable
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


def pick_port(preferred: int | None = None) -> int:
    for p in ([preferred] if preferred else []) + list(PORT_RANGE):
        if p and port_free(p):
            return p
    with socket.socket() as s:  # anything free
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def ping(port: int, timeout: float = 1.5) -> dict | None:
    """Our own status route; None when nothing (or something else) answers."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/launcher/status", timeout=timeout) as r:
            d = json.loads(r.read(20_000))
        return d if isinstance(d, dict) and d.get("app") == "opensoul" else None
    except (OSError, ValueError):
        return None


def running(h: Path | None = None) -> dict | None:
    try:
        info = json.loads(server_file(h).read_text(encoding="utf-8"))
        port = int(info["port"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    st = ping(port)
    return {"port": port, **st} if st else None


def start_url(port: int, cfg: dict[str, Any]) -> str:
    return f"http://127.0.0.1:{port}/" + ("" if cfg.get("first_run_done") else "welcome")


def _notify_error(msg: str) -> None:
    print(msg, file=sys.stderr)
    if sys.platform == "darwin" and os.environ.get("OPENSOUL_NO_DIALOG") != "1":
        safe = msg.replace("\\", "\\\\").replace('"', '\\"')
        subprocess.run(["osascript", "-e", f'display alert "OpenSoul" message "{safe}"'], check=False)


def open_app(h: Path | None = None, wait_s: float = 120.0, browser: bool = True) -> int:
    h = h or home()
    cfg = load_config(h)
    cur = running(h)
    if cur:
        url = start_url(cur["port"], cfg)
    else:
        port = pick_port(DEFAULT_PORT)
        log = log_path(h)
        log.parent.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, OPENSOUL_LAUNCHER_HOME=str(h))
        kw: dict[str, Any] = {}
        if sys.platform.startswith("win"):
            kw["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        else:
            kw["start_new_session"] = True
        with open(log, "ab") as fh:
            py = [sys.executable] + (["-I"] if sys.flags.isolated else [])
            proc = subprocess.Popen(py + ["-m", "opensoul.launcher", "serve", "--port", str(port)],
                                    stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env,
                                    cwd=str(Path(__file__).resolve().parents[1]), **kw)
        deadline = time.time() + wait_s
        while time.time() < deadline:
            if ping(port):
                break
            if proc.poll() is not None:
                _notify_error(f"OpenSoul couldn't start. Details are in {log}")
                return 1
            time.sleep(0.5)
        else:
            _notify_error(f"OpenSoul is taking too long to start. Details are in {log}")
            return 1
        url = start_url(port, cfg)
    print(f"OpenSoul is running: {url}")
    if browser and os.environ.get("OPENSOUL_NO_BROWSER") != "1":
        from opensoul import desktop_window as W

        if W.wanted():
            port = int(urllib.parse.urlsplit(url).port or DEFAULT_PORT)
            if W.run(url, alive=lambda: ping(port) is not None, storage=h / "window",
                     icon=os.environ.get("OPENSOUL_APP_ICON")):
                stop(h)  # the window closed (or Cmd-Q): quit OpenSoul like Quit in the corner does
                return 0
        import webbrowser

        webbrowser.open(url)
    return 0


def serve(port: int, h: Path | None = None) -> int:
    h = h or home()
    cfg = load_config(h)
    os.environ["OPENSOUL_LAUNCHER_HOME"] = str(h)
    os.environ["OPENSOUL_LAUNCHED"] = "1"
    os.environ.setdefault("OPENSOUL_DATA", str(h / "data"))
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    apply_env(cfg)
    Path(os.environ["OPENSOUL_DATA"]).mkdir(parents=True, exist_ok=True)
    sf = server_file(h)
    sf.parent.mkdir(parents=True, exist_ok=True)
    sf.write_text(json.dumps({"port": port, "pid": os.getpid(), "started": time.time()}), encoding="utf-8")
    import uvicorn

    from app.server import app  # imported after the environment is set: app/server.py reads OPENSOUL_DATA at import

    try:
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
    finally:
        try:
            if json.loads(sf.read_text(encoding="utf-8")).get("pid") == os.getpid():
                sf.unlink()
        except (OSError, ValueError):
            pass
    return 0


def stop(h: Path | None = None) -> int:
    cur = running(h)
    if not cur:
        print("OpenSoul isn't running.")
        return 0
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{cur['port']}/api/launcher/quit", data=b"{}",
                                     headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=3).read()
    except OSError:
        pass
    print("OpenSoul is stopping.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="opensoul-launcher", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("open")
    sp = sub.add_parser("serve")
    sp.add_argument("--port", type=int, default=None)
    sub.add_parser("stop")
    sub.add_parser("status")
    a = ap.parse_args(argv)
    if a.cmd == "serve":
        return serve(a.port or pick_port(DEFAULT_PORT))
    if a.cmd == "stop":
        return stop()
    if a.cmd == "status":
        cur, cfg = running(), load_config()
        print(json.dumps({"home": str(home()), "running": cur, "config": cfg}, indent=2))
        return 0
    return open_app()


if __name__ == "__main__":
    sys.exit(main())
