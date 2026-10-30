"""P0-03: one app-wide Host / Origin guard (app/local_guard.py). A web page that rebinds its own DNS name to
127.0.0.1 must not read character pictures or voice clips, and must not make stories."""
import json

import pytest
from fastapi.testclient import TestClient

from app import local_guard as G

PORT = 7860
BASE = f"http://127.0.0.1:{PORT}"


@pytest.fixture
def data(tmp_path, monkeypatch):
    """A throwaway data folder with one 'private' file the attacker wants."""
    import app.server as srv

    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    monkeypatch.setattr(srv, "DATA", tmp_path)
    (tmp_path / "character_voices.json").write_text(json.dumps({"Ada": "tara"}))
    return tmp_path


@pytest.fixture
def local(data):
    from app.server import app

    return TestClient(app, base_url=BASE)


EVIL = [{"Host": "evil.example"}, {"Host": f"evil.example:{PORT}"}, {"Host": f"127.0.0.1.evil.example:{PORT}"},
        {"Host": "127.0.0.1:9999"}, {"Host": ""}]


def test_production_names_are_loopback_only(monkeypatch):
    monkeypatch.delenv("OPENSOUL_ALLOWED_HOSTS", raising=False)
    assert G.allowed_names() == {"127.0.0.1", "localhost", "[::1]"}
    assert not G.host_ok("testserver", 80)
    for h in ("127.0.0.1:7860", "localhost:7860", "[::1]:7860"):
        assert G.host_ok(h, 7860)
    assert not G.host_ok("127.0.0.1:7861", 7860)


def test_allow_list_from_config(monkeypatch):
    monkeypatch.setenv("OPENSOUL_ALLOWED_HOSTS", "studio-laptop.local, Example.lan")
    assert G.host_ok("studio-laptop.local:7860", 7860) and G.host_ok("example.lan:7860", 7860)
    assert not G.host_ok("evil.example:7860", 7860)


@pytest.mark.parametrize("headers", EVIL)
def test_foreign_host_cannot_read_data(local, data, headers):
    for path in (f"/api/file?path={data}/character_voices.json", "/api/launcher/status", "/api/bootstrap",
                 "/api/storyboard/projects", "/api/storyboard/cast", "/"):
        r = local.get(path, headers=headers)
        assert r.status_code == 403, (path, headers, r.status_code)
        assert "Ada" not in r.text


@pytest.mark.parametrize("headers", EVIL)
def test_foreign_host_cannot_make_a_story(local, headers):
    before = local.get("/api/storyboard/projects").json()
    r = local.post("/api/storyboard/projects", json={"title": "rebind-demo"}, headers=headers)
    assert r.status_code == 403
    assert local.get("/api/storyboard/projects").json() == before


@pytest.mark.parametrize("origin", ["http://evil.example", f"http://evil.example:{PORT}", "null",
                                    f"https://127.0.0.1:{PORT}", "http://127.0.0.1:9999", f"http://localhost:{PORT}"])
def test_foreign_origin_cannot_change_anything(local, origin):
    before = local.get("/api/storyboard/projects").json()
    r = local.post("/api/storyboard/projects", json={"title": "csrf-demo"}, headers={"Origin": origin})
    assert r.status_code == 403
    r = local.post("/api/storyboard/projects", json={"title": "csrf-demo"}, headers={"Referer": origin + "/x"})
    assert r.status_code == 403
    assert local.get("/api/storyboard/projects").json() == before


def test_text_plain_body_is_refused(local):
    """text/plain is the classic way to post JSON cross-site without a CORS preflight."""
    for ctype in ("text/plain", "text/plain;charset=UTF-8", "application/xml"):
        r = local.post("/api/storyboard/projects", content='{"title": "x"}', headers={"Content-Type": ctype})
        assert r.status_code == 415


def test_cross_site_form_is_refused(local):
    """A cross-site HTML form sends urlencoded or multipart bodies, and the browser adds its Origin."""
    for origin in ("http://evil.example", "null"):
        r = local.post("/api/master", data={"name": "x"}, headers={"Origin": origin})
        assert r.status_code == 403
        r = local.post("/api/master", files={"photo": ("a.png", b"x")}, headers={"Origin": origin})
        assert r.status_code == 403


def test_own_page_still_works(local, data):
    assert local.get("/").status_code == 200
    assert local.get("/api/launcher/status").json()["app"] == "opensoul"
    r = local.post("/api/storyboard/projects", json={"title": "Mine"}, headers={"Origin": BASE, "Referer": BASE + "/"})
    assert r.status_code == 200, r.text
    assert local.get(f"/api/file?path={data}/character_voices.json").status_code == 200
    # the desktop window (WKWebView / WebView2) and a browser on "localhost" send their own same origin
    other = TestClient(local.app, base_url=f"http://localhost:{PORT}")
    assert other.post("/api/storyboard/projects", json={"title": "Mine 2"},
                      headers={"Origin": f"http://localhost:{PORT}"}).status_code == 200


def test_upload_from_own_page_is_allowed(local):
    """File uploads are multipart, not JSON: allowed from our own origin."""
    r = local.post("/api/storyboard/projects", files={"x": ("a.txt", b"hi")}, headers={"Origin": BASE})
    assert r.status_code != 415 and r.status_code != 403


def test_api_docs_are_off_by_default(local):
    """P2-07: /docs and /redoc load from public CDNs, so they stay off unless OPENSOUL_DEV=1."""
    import app.server as srv

    assert srv.app.docs_url is None and srv.app.redoc_url is None and srv.app.openapi_url is None
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert local.get(path).status_code == 404


def test_unknown_page_is_html_for_a_browser(local):
    """P2-06."""
    r = local.get("/does-not-exist", headers={"Accept": "text/html,application/xhtml+xml"})
    assert r.status_code == 404 and "Back to OpenSoul" in r.text and r.headers["content-type"].startswith("text/html")
    r = local.get("/api/nope", headers={"Accept": "text/html"})
    assert r.status_code == 404 and r.json()["detail"] == "Not Found"


@pytest.mark.parametrize("value,lan,want", [(None, None, "127.0.0.1"), ("0.0.0.0", None, "127.0.0.1"),
                                            ("0.0.0.0", "1", "0.0.0.0"), ("::1", None, "::1")])
def test_lan_listen_needs_opt_in(monkeypatch, value, lan, want):
    """P2-15: OPENSOUL_HOST=0.0.0.0 would share the unauthenticated API with the whole network."""
    import app.server as srv

    for k, v in (("OPENSOUL_HOST", value), ("OPENSOUL_ALLOW_LAN", lan)):
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    assert srv.serve_host() == want
