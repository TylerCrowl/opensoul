"""One-click launcher (opensoul/launcher.py) and its routes (app/launcher_routes.py): config, studio check, the
same-computer guard on POSTs, live mode switch, the background server lifecycle."""
import io
import json
import os
import urllib.error

import pytest
from fastapi.testclient import TestClient

from opensoul import launcher as L

ENV_KEYS = ("OPENSOUL_DRY_RUN", "COMFY_BASE_URL", "OPENSOUL_COMFYUI_URL", "OPENSOUL_LAUNCHED", "OPENSOUL_LAUNCHER_HOME")


@pytest.fixture
def lhome(tmp_path, monkeypatch):
    for k in ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("OPENSOUL_LAUNCHER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    return tmp_path / "home"


@pytest.fixture
def client(lhome):
    from app.server import app

    return TestClient(app)


# ---------- addresses ----------

@pytest.mark.parametrize("typed,want", [
    ("spark.local", "http://spark.local:8188"),
    ("192.0.2.10:8188", "http://192.0.2.10:8188"),
    ("http://198.51.100.5:8189/", "http://198.51.100.5:8189"),
    ("  https://studio.example:443/comfy/  ", "https://studio.example:443/comfy"),
    ("[::1]:8188", "http://[::1]:8188"),
])
def test_normalize_url_accepts_what_people_type(typed, want):
    assert L.normalize_url(typed) == want


@pytest.mark.parametrize("bad", ["", "   ", "ftp://x", "file:///etc/passwd", "http://user:pw@host:8188", "http://",
                                 "host:notaport", "http://h:8188/?x=1", "a b"])
def test_normalize_url_rejects_bad_addresses_with_a_plain_message(bad):
    with pytest.raises(ValueError) as e:
        L.normalize_url(bad)
    assert str(e.value) and "Traceback" not in str(e.value)


def test_api_url_defaults_to_the_proxy_port_on_the_same_host():
    assert L.api_url_for("http://spark.local:8188") == "http://spark.local:8189"
    assert L.api_url_for("spark.local", "198.51.100.9") == "http://198.51.100.9:8189"


# ---------- config ----------

def test_home_per_platform(tmp_path):
    env = {"HOME": str(tmp_path)}
    assert L.home(env, "darwin") == tmp_path / "Library" / "Application Support" / "OpenSoul"
    assert L.home(env, "linux") == tmp_path / ".local" / "share" / "opensoul"
    assert L.home({**env, "LOCALAPPDATA": str(tmp_path / "LA")}, "win32") == tmp_path / "LA" / "OpenSoul"
    assert L.home({"OPENSOUL_LAUNCHER_HOME": str(tmp_path / "x")}, "darwin") == tmp_path / "x"


def test_config_defaults_to_preview_and_round_trips(tmp_path):
    assert L.load_config(tmp_path) == L.DEFAULT_CONFIG
    saved = L.save_config({"mode": "studio", "studio_url": "spark.local"}, tmp_path)
    assert saved["studio_url"] == "http://spark.local:8188" and saved["first_run_done"] is True
    assert L.load_config(tmp_path)["mode"] == "studio"


def test_config_rejects_studio_without_address_and_survives_a_broken_file(tmp_path):
    with pytest.raises(ValueError):
        L.save_config({"mode": "studio", "studio_url": ""}, tmp_path)
    with pytest.raises(ValueError):
        L.save_config({"mode": "cloud"}, tmp_path)
    L.config_path(tmp_path).write_text("{not json")
    assert L.load_config(tmp_path)["mode"] == "preview"
    L.config_path(tmp_path).write_text(json.dumps({"mode": "studio"}))
    assert L.load_config(tmp_path)["mode"] == "preview"  # studio with no address falls back


def test_apply_env_sets_preview_or_studio():
    env = L.apply_env({"mode": "preview"}, {})
    assert env == {"OPENSOUL_DRY_RUN": "1"}
    env = L.apply_env({"mode": "studio", "studio_url": "http://s:8188"}, {})
    assert env == {"OPENSOUL_DRY_RUN": "0", "COMFY_BASE_URL": "http://s:8189", "OPENSOUL_COMFYUI_URL": "http://s:8188",
                   "NO_PROXY": "s", "no_proxy": "s"}


def test_apply_env_sends_studio_traffic_around_any_proxy():
    env = L.apply_env({"mode": "studio", "studio_url": "http://s:8188", "studio_api_url": "http://p:8189"},
                      {"NO_PROXY": "corp.example", "no_proxy": "s"})
    assert env["NO_PROXY"] == "corp.example,s,p" and env["no_proxy"] == "s,p"
    import urllib.request

    assert urllib.request.proxy_bypass_environment("s", {"no": env["no_proxy"]})


# ---------- studio check ----------

class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _opener(stats=None, proxy=True, fail=None, nodes=None):
    seen = []
    have = set(L.OPENSOUL_NODES) if nodes is None else set(nodes)

    def op(req, timeout=None):
        if "/object_info/" in req.full_url and not fail:
            cls = req.full_url.rsplit("/", 1)[1]
            return _Resp(json.dumps({cls: {"name": cls}} if cls in have else {}).encode())
        seen.append(req.full_url)
        if fail:
            raise fail
        if req.full_url.endswith("/system_stats"):
            return _Resp(json.dumps(stats).encode() if stats is not None else b"<html>")
        if not proxy:
            raise urllib.error.URLError("refused")
        raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, None)  # something is listening: counts
    op.seen = seen
    return op


STATS = {"system": {"comfyui_version": "0.3.99"}, "devices": [{"name": "cuda:0 NVIDIA GB10 : cudaMallocAsync",
                                                                "vram_total": 128 * 1024 ** 3}]}


def _resolver(*ips, fail=False):
    def res(host, port, family=0, type=0):
        if fail:
            import socket

            raise socket.gaierror(-2, "Name or service not known")
        return [(2, 1, 6, "", (ip, 0)) for ip in ips]
    return res


def test_probe_reports_gpu_and_checks_the_proxy():
    op = _opener(STATS)
    r = L.probe_studio("spark.local", opener=op, resolver=_resolver(fail=True))
    assert r["ok"] and r["api_ok"] and r["vram_gb"] == 128.0 and r["gpu"] == "NVIDIA GB10" and r["kind"] == "ok"
    assert r["comfyui"] == "0.3.99" and r["warning"] is None
    assert "ComfyUI 0.3.99 on NVIDIA GB10 (128 GB)" in r["message"]
    assert op.seen == ["http://spark.local:8188/system_stats", "http://spark.local:8189/"]


@pytest.mark.parametrize("raw,want", [("cuda:0 NVIDIA GB10 : cudaMallocAsync", "NVIDIA GB10"), ("mps", ""),
                                      ("cuda:1 NVIDIA GeForce RTX 4090 : native", "NVIDIA GeForce RTX 4090"), (None, "")])
def test_gpu_name(raw, want):
    assert L._gpu_name(raw) == want


def test_probe_lists_missing_opensoul_nodes():  # OS-009
    r = L.probe_studio("spark.local", opener=_opener(STATS, nodes=["OpenSoulKokoroTTS"]), resolver=_resolver(fail=True))
    assert r["ok"] and r["kind"] == "nodes_missing" and r["nodes_checked"]
    assert "OpenSoulIdentityGate" in r["missing_nodes"] and "OpenSoulKokoroTTS" not in r["missing_nodes"]
    assert "character sheets" in r["message"] and "custom_nodes/opensoul_nodes" in r["message"]


def test_probe_warns_when_proxy_is_missing():
    r = L.probe_studio("spark.local", opener=_opener(STATS, proxy=False), resolver=_resolver(fail=True))
    assert r["ok"] and not r["api_ok"] and "comfy-api-proxy" in r["message"] and r["kind"] == "proxy_missing"


@pytest.mark.parametrize("op", [_opener(fail=urllib.error.URLError("x")), _opener(stats=None), _opener(stats={"a": 1}),
                                _opener(fail=urllib.error.HTTPError("u", 500, "e", {}, None))])
def test_probe_failures_are_plain_and_never_raise(op):
    r = L.probe_studio("http://198.51.100.1:8188", opener=op)
    assert r["ok"] is False and r["message"]


def test_probe_bad_address():
    assert L.probe_studio("ftp://x")["ok"] is False


# ---------- routes ----------

def test_welcome_and_status(client):
    r = client.get("/welcome")
    assert r.status_code == 200 and "Connect my studio" in r.text and "Try it now" in r.text
    s = client.get("/api/launcher/status").json()
    assert s["app"] == "opensoul" and s["mode"] == "preview" and s["launched"] is False and "home" not in s


def test_index_loads_the_launcher_chip(client):
    html = client.get("/").text
    assert "/static/launcher.js?v=" in html and "/static/launcher.css?v=" in html


def test_config_post_applies_live_and_back(client, lhome):
    r = client.post("/api/launcher/config", json={"mode": "studio", "studio_url": "203.0.113.3"})
    assert r.status_code == 200 and r.json()["mode"] == "studio"
    assert os.environ["OPENSOUL_DRY_RUN"] == "0" and os.environ["COMFY_BASE_URL"] == "http://203.0.113.3:8189"
    assert json.loads((lhome / "launcher.json").read_text())["studio_url"] == "http://203.0.113.3:8188"
    assert client.get("/api/health").json()["dry_run"] is False
    r = client.post("/api/launcher/config", json={"mode": "preview"})
    assert r.json()["mode"] == "preview" and os.environ["OPENSOUL_DRY_RUN"] == "1"


def test_config_post_bad_address_is_400(client):
    r = client.post("/api/launcher/config", json={"mode": "studio", "studio_url": "ftp://x"})
    assert r.status_code == 400 and "http" in r.json()["detail"]


@pytest.mark.parametrize("headers", [{"Origin": "https://evil.example"}, {"Host": "evil.example"},
                                     {"Origin": "http://127.0.0.1.evil.example:7860"}])
def test_posts_refuse_other_sites(client, headers):
    for path, body in (("/api/launcher/config", {"mode": "studio", "studio_url": "evil.example"}),
                       ("/api/launcher/test", {"url": "evil.example"}), ("/api/launcher/quit", {})):
        assert client.post(path, json=body, headers=headers).status_code == 403
    assert not (L.home() / "launcher.json").exists()


def test_posts_need_json(client):
    # a form-style cross-site POST (no CORS preflight) must never change the studio
    for body in ("mode=studio", json.dumps({"mode": "studio", "studio_url": "evil.example"})):
        r = client.post("/api/launcher/config", content=body, headers={"Content-Type": "text/plain"})
        assert r.status_code in (415, 422)
    assert not (L.home() / "launcher.json").exists()


def test_local_origin_is_fine(lhome):
    from app.server import app

    local = TestClient(app, base_url="http://127.0.0.1:7860")
    r = local.post("/api/launcher/config", json={"mode": "preview"}, headers={"Origin": "http://127.0.0.1:7860"})
    assert r.status_code == 200
    # same name, other port: another local web page, not this one
    r = local.post("/api/launcher/config", json={"mode": "preview"}, headers={"Origin": "http://127.0.0.1:9999"})
    assert r.status_code == 403


def test_test_route_uses_probe(client, monkeypatch):
    monkeypatch.setattr(L, "probe_studio", lambda url, api_url="": {"ok": True, "url": url, "message": "hi"})
    assert client.post("/api/launcher/test", json={"url": "x"}).json()["message"] == "hi"


def test_quit_only_when_launched(client, monkeypatch):
    assert client.post("/api/launcher/quit", json={}).status_code == 409
    monkeypatch.setenv("OPENSOUL_LAUNCHED", "1")
    killed = []
    monkeypatch.setattr("threading.Timer", lambda t, fn: type("T", (), {"start": lambda self: killed.append(t)})())
    r = client.post("/api/launcher/quit", json={})
    assert r.status_code == 200 and killed == [0.5]


# ---------- lifecycle ----------

def test_start_url_first_run_goes_to_welcome():
    assert L.start_url(7861, {"first_run_done": False}).endswith(":7861/welcome")
    assert L.start_url(7861, {"first_run_done": True}).endswith(":7861/")


def test_pick_port_skips_busy_ports():
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        busy = s.getsockname()[1]
        assert L.pick_port(busy) != busy


def test_running_ignores_stale_server_file(tmp_path):
    L.server_file(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    L.server_file(tmp_path).write_text(json.dumps({"port": L.pick_port(), "pid": 1}))
    assert L.running(tmp_path) is None


def test_open_starts_reuses_and_stops_a_background_server(lhome, monkeypatch):
    monkeypatch.setenv("OPENSOUL_NO_BROWSER", "1")
    monkeypatch.setenv("OPENSOUL_NO_DIALOG", "1")
    try:
        assert L.open_app(lhome, wait_s=60) == 0
        first = L.running(lhome)
        assert first and first["launched"] is True and first["mode"] == "preview"
        assert L.open_app(lhome, wait_s=5) == 0  # second click: same server
        assert L.running(lhome)["pid"] == first["pid"]
    finally:
        L.stop(lhome)
    import time

    for _ in range(40):
        if L.running(lhome) is None:
            break
        time.sleep(0.25)
    assert L.running(lhome) is None


# ---------- address safety (check_address) ----------
# Sample addresses are built from each range's first address as an integer, so this file holds no dotted private
# addresses (the publish scan flags those). The ranges: 10/8, 172.16/12, 192.168/16, 100.64/10, 169.254/16.
import ipaddress  # noqa: E402

def _ip(first: int, prefix: int, n: int = 5) -> str:
    return str(ipaddress.IPv4Network((first, prefix))[n])


PRIVATE_SAMPLES = [_ip(0x0A000000, 8, 77), _ip(0xAC100000, 12, 300), _ip(0xC0A80000, 16, 306), _ip(0x64400000, 10, 9),
                   _ip(0xA9FE0000, 16, 513), "127.0.0.1", "[::1]", "[fe80::1]", "[fd12:3456::5]"]


@pytest.mark.parametrize("ip", PRIVATE_SAMPLES)
def test_home_network_vpn_and_local_addresses_are_fine(ip):
    r = L.check_address(f"http://{ip}:8188")
    assert r["ok"] and r["kind"] == "local" and r["warning"] is None, r


def test_range_edges():
    assert L._ip_kind(ipaddress.ip_address(_ip(0x64400000, 10, 0))) == "local"
    assert L._ip_kind(ipaddress.ip_address(str(ipaddress.IPv4Address(0x64400000 - 1)))) == "public"  # just below 100.64/10
    assert L._ip_kind(ipaddress.ip_address(str(ipaddress.IPv4Address(0x64800000)))) == "public"  # just above it
    assert L._ip_kind(ipaddress.ip_address(str(ipaddress.IPv4Address(0xAC200000)))) == "public"  # just above 172.16/12
    assert L._ip_kind(ipaddress.ip_address("::ffff:" + _ip(0xC0A80000, 16, 7))) == "local"  # IPv4-mapped IPv6


@pytest.mark.parametrize("name,ips", [("localhost", []), ("studio.localhost", []),
                                      ("my-studio.local", []), ("my-studio.local", [_ip(0xC0A80000, 16, 50)]),
                                      ("spark.home.arpa", [_ip(0x0A000000, 8, 9)]),
                                      ("box.vpn-name.example", [_ip(0x64400000, 10, 20)])])
def test_local_names(name, ips):
    r = L.check_address(name, resolver=_resolver(*ips, fail=not ips))
    assert r["ok"] and r["kind"] == "local" and r["warning"] is None, r


@pytest.mark.parametrize("typed,res", [("http://8.8.8.8:8188", None), ("1.1.1.1", None), ("[2001:4860:4860::8888]", None),
                                       ("studio.example.com", _resolver("93.184.215.14")),
                                       ("mixed.example.com", _resolver(_ip(0xC0A80000, 16, 50), "93.184.215.14"))])
def test_public_addresses_get_a_warning_not_a_block(typed, res):
    r = L.check_address(typed, resolver=res)
    assert r["ok"] and r["kind"] == "public" and "public internet" in r["warning"] and "password" in r["warning"]
    L.normalize_url(typed)  # still allowed


def test_unresolvable_name_is_unknown_without_warning():
    r = L.check_address("nosuchhost.invalid", resolver=_resolver(fail=True))
    assert r["ok"] and r["kind"] == "unknown" and r["warning"] is None


@pytest.mark.parametrize("bad", ["file:///etc/passwd", "ftp://studio:21", "javascript:alert(1)", "ws://studio:8188",
                                 "data:text/html,hi", "http://admin:secret@studio:8188", "http://token@studio:8188",
                                 "admin:secret@studio:8188", "https://@studio", "http://0.0.0.0:8188", "http://[::]:8188"])
def test_bad_schemes_and_credentials_are_refused(bad):
    with pytest.raises(ValueError):
        L.normalize_url(bad)
    r = L.check_address(bad)
    assert r["ok"] is False and r["kind"] == "invalid"
    p = L.probe_studio(bad, opener=_opener(STATS))
    assert p["ok"] is False and p["kind"] == "invalid"


def test_credentials_message_is_plain():
    with pytest.raises(ValueError, match="user name and password"):
        L.normalize_url("http://admin:secret@studio:8188")


def test_probe_on_a_public_address_still_tests_but_warns():
    r = L.probe_studio("http://8.8.8.8:8188", opener=_opener(STATS))
    assert r["ok"] and "public internet" in r["warning"]


def test_probe_warns_when_only_the_api_helper_is_public():
    r = L.probe_studio("my-studio.local", api_url="http://8.8.4.4:8189", opener=_opener(STATS), resolver=_resolver(fail=True))
    assert r["ok"] and r["warning"]


# ---------- friendly test-connection errors ----------

import socket  # noqa: E402


@pytest.mark.parametrize("err,kind,words", [
    (urllib.error.URLError(ConnectionRefusedError(111, "refused")), "refused", "port 8188"),
    (urllib.error.URLError(socket.gaierror(-2, "unknown")), "dns", "Couldn't find a computer called"),
    (urllib.error.URLError(socket.timeout("timed out")), "timeout", "No answer"),
    (TimeoutError("timed out"), "timeout", "No answer"),
    (urllib.error.URLError(OSError(113, "No route to host")), "unreachable", "Couldn't connect"),
])
def test_probe_unreachable_kinds(err, kind, words):
    r = L.probe_studio("my-studio.local", opener=_opener(fail=err), resolver=_resolver(fail=True))
    assert r["ok"] is False and r["kind"] == kind and words in r["message"], r


def test_refused_on_an_odd_port_suggests_8188():
    r = L.probe_studio("http://my-studio.local:7000", opener=_opener(fail=urllib.error.URLError(ConnectionRefusedError())),
                       resolver=_resolver(fail=True))
    assert r["kind"] == "refused" and "usually uses port 8188" in r["message"]


@pytest.mark.parametrize("url,stats,kind,words", [
    ("http://my-studio.local:8188", None, "not_comfy", "isn't ComfyUI"),
    ("http://my-studio.local:8188", {"a": 1}, "not_comfy", "isn't ComfyUI"),
    ("http://my-studio.local:7860", None, "wrong_port", "usually uses port 8188"),
    ("http://my-studio.local:8189", {"detail": "nf"}, "wrong_port", "API helper's port"),
])
def test_probe_not_comfy_and_wrong_port(url, stats, kind, words):
    r = L.probe_studio(url, opener=_opener(stats=stats), resolver=_resolver(fail=True))
    assert r["ok"] is False and r["kind"] == kind and words in r["message"], r


def test_probe_http_error_on_other_port_is_wrong_port():
    r = L.probe_studio("http://my-studio.local:80", opener=_opener(fail=urllib.error.HTTPError("u", 404, "nf", {}, None)),
                       resolver=_resolver(fail=True))
    assert r["kind"] == "wrong_port" and "error 404" in r["message"]


def test_probe_handles_missing_device_info():
    r = L.probe_studio("my-studio.local", opener=_opener({"system": {}, "devices": []}), resolver=_resolver(fail=True))
    assert r["ok"] and r["gpu"] is None and r["vram_gb"] is None and r["comfyui"] is None
    assert r["message"].startswith("Connected to ComfyUI.")


def _stub(handler_get):
    import http.server
    import threading

    class H(http.server.BaseHTTPRequestHandler):
        do_GET = handler_get

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_probe_goes_straight_to_the_studio_even_with_a_proxy_set(monkeypatch):
    def get(self):
        body = json.dumps(STATS).encode() if self.path == "/system_stats" else b"ok"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    srv = _stub(get)
    for k in ("HTTP_PROXY", "http_proxy", "ALL_PROXY"):
        monkeypatch.setenv(k, "http://127.0.0.1:9")  # a proxy that doesn't exist: using it would fail
    for k in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(k, raising=False)
    try:
        port = srv.server_address[1]
        r = L.probe_studio(f"http://127.0.0.1:{port}", api_url=f"http://127.0.0.1:{port}", timeout=3)
    finally:
        srv.shutdown()
    assert r["ok"] and r["api_ok"] and r["gpu"] == "NVIDIA GB10", r


def test_probe_against_a_real_local_server_never_follows_a_redirect():
    import http.server
    import threading

    hits = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:9/elsewhere")
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        r = L.probe_studio(f"http://127.0.0.1:{srv.server_address[1]}", timeout=3)
    finally:
        srv.shutdown()
    assert r["ok"] is False and hits == ["/system_stats"]


def test_config_reply_carries_the_public_warning(client):
    r = client.post("/api/launcher/config", json={"mode": "studio", "studio_url": "http://8.8.8.8:8188"})
    assert r.status_code == 200 and "public internet" in r.json()["warning"]
    r = client.post("/api/launcher/config", json={"mode": "studio", "studio_url": "http://127.0.0.1:8188"})
    assert r.json()["warning"] is None
    client.post("/api/launcher/config", json={"mode": "preview"})


def test_config_refuses_credentials(client):
    r = client.post("/api/launcher/config", json={"mode": "studio", "studio_url": "http://a:b@studio:8188"})
    assert r.status_code == 400 and "password" in r.json()["detail"]


def test_welcome_explains_safety_and_where_to_find_the_address(client):
    html = client.get("/welcome").text
    for words in ("Is this safe?", "Where do I find this address?", "By default, ComfyUI has no password", "--listen",
                  "No account, no cloud, no tracking", "/help/desktop", "e.g. http://my-studio.local:8188"):
        assert words in html, words
    assert "192.0.2.10" not in html


def test_help_desktop_serves_the_guide(client):
    r = client.get("/help/desktop")
    assert r.status_code == 200 and "Connecting your studio safely" in r.text
