"""The Mac app's own window (opensoul/desktop_window.py), its browser fallback and quit, and the one-time
"Move to Applications?" offer (opensoul/mac_move.py). No GUI here: pywebview and the dialogs are faked."""
import json
import types

import pytest

from opensoul import desktop_window as W
from opensoul import launcher as L
from opensoul import mac_move as M


@pytest.mark.parametrize("env,platform,want", [
    ({"OPENSOUL_APP": "mac"}, "darwin", True),
    ({}, "darwin", False),                                   # a developer's `python -m opensoul.launcher` on a Mac
    ({"OPENSOUL_APP": "mac", "OPENSOUL_WINDOW": "0"}, "darwin", False),
    ({"OPENSOUL_APP": "mac"}, "linux", False),
    ({}, "linux", False), ({}, "win32", False),
    ({"OPENSOUL_WINDOW": "1"}, "linux", True),
])
def test_window_is_the_mac_app_default_only(env, platform, want):
    assert W.wanted(env, platform) is want


def _fake_webview(fail_on=None):
    calls = {"created": [], "started": [], "destroyed": 0}

    class Win:
        def destroy(self):
            calls["destroyed"] += 1

    def create_window(title, url, **kw):
        if fail_on == "create":
            raise RuntimeError("no GUI")
        calls["created"].append((title, url, kw))
        return Win()

    def start(**kw):
        if fail_on == "start":
            raise RuntimeError("no backend")
        calls["started"].append(kw)

    mod = types.SimpleNamespace(create_window=create_window, start=start,
                                settings={"ALLOW_DOWNLOADS": False, "OPEN_EXTERNAL_LINKS_IN_BROWSER": False})
    return mod, calls


def test_run_opens_one_window_on_the_local_server(tmp_path):
    mod, calls = _fake_webview()
    assert W.run("http://127.0.0.1:7861/welcome", alive=lambda: True, storage=tmp_path / "w", webview_module=mod)
    (title, url, kw), = calls["created"]
    assert title == "OpenSoul" and url == "http://127.0.0.1:7861/welcome" and kw["min_size"] == W.MIN_SIZE
    assert calls["started"] == [{"private_mode": False, "storage_path": str(tmp_path / "w")}]
    assert mod.settings == {"ALLOW_DOWNLOADS": True, "OPEN_EXTERNAL_LINKS_IN_BROWSER": True}


@pytest.mark.parametrize("fail_on", ["create", "start"])
def test_run_reports_failure_so_the_browser_takes_over(fail_on):
    mod, _ = _fake_webview(fail_on)
    assert W.run("http://127.0.0.1:7861/", alive=lambda: True, webview_module=mod) is False


def test_run_without_pywebview_is_false(monkeypatch):
    import builtins

    real = builtins.__import__
    monkeypatch.setattr(builtins, "__import__", lambda n, *a, **k: (_ for _ in ()).throw(ImportError(n)) if n == "webview" else real(n, *a, **k))
    assert W.run("http://127.0.0.1:7861/", alive=lambda: True) is False


def test_watcher_closes_the_window_when_the_server_quits():
    mod, calls = _fake_webview()
    beats = iter([True, False, False, False])
    win = mod.create_window("OpenSoul", "u")
    W._watch(win, alive=lambda: next(beats), every=0, misses=3)
    assert calls["destroyed"] == 1


def _launcher_env(lhome, monkeypatch, app):
    monkeypatch.setenv("OPENSOUL_LAUNCHER_HOME", str(lhome))
    monkeypatch.delenv("OPENSOUL_NO_BROWSER", raising=False)
    monkeypatch.delenv("OPENSOUL_WINDOW", raising=False)
    if app:
        monkeypatch.setenv("OPENSOUL_APP", "mac")
    else:
        monkeypatch.delenv("OPENSOUL_APP", raising=False)
    monkeypatch.setattr(L, "running", lambda h=None: {"port": 7861, "app": "opensoul"})
    opened, stopped = [], []
    import webbrowser

    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url))
    monkeypatch.setattr(L, "stop", lambda h=None: stopped.append(h) or 0)
    return opened, stopped


def test_mac_app_uses_the_window_and_quits_the_server_when_it_closes(tmp_path, monkeypatch):
    opened, stopped = _launcher_env(tmp_path, monkeypatch, app=True)
    monkeypatch.setattr("sys.platform", "darwin")
    seen = []
    monkeypatch.setattr(W, "run", lambda url, **kw: seen.append(url) or True)
    assert L.open_app(tmp_path) == 0
    assert seen == ["http://127.0.0.1:7861/welcome"] and opened == [] and stopped == [tmp_path]


def test_mac_app_falls_back_to_the_browser(tmp_path, monkeypatch):
    opened, stopped = _launcher_env(tmp_path, monkeypatch, app=True)
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr(W, "run", lambda url, **kw: False)
    assert L.open_app(tmp_path) == 0
    assert opened == ["http://127.0.0.1:7861/welcome"] and stopped == []


def test_linux_and_windows_keep_the_browser(tmp_path, monkeypatch):
    opened, _ = _launcher_env(tmp_path, monkeypatch, app=False)
    monkeypatch.setattr(W, "run", lambda url, **kw: pytest.fail("no window off the Mac app"))
    for plat in ("linux", "win32"):
        monkeypatch.setattr("sys.platform", plat)
        assert L.open_app(tmp_path) == 0
    assert len(opened) == 2


# ---------- Move to Applications? ----------

def _app(where):
    app = where / "OpenSoul.app"
    (app / "Contents").mkdir(parents=True)
    (app / "Contents" / "Info.plist").write_text("x")
    return app


@pytest.fixture
def mac_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "Downloads").mkdir(parents=True)
    monkeypatch.delenv("OPENSOUL_LAUNCHER_HOME", raising=False)
    return home


def test_move_offer_moves_only_after_a_yes(mac_home, tmp_path):
    app = _app(mac_home / "Downloads")
    sysapps = tmp_path / "Applications"
    sysapps.mkdir()
    opened = []
    rc = M.offer(app, mac_home, asker=lambda: True, opener=opened.append, system_apps=sysapps)
    assert rc == M.MOVED and (sysapps / "OpenSoul.app" / "Contents" / "Info.plist").is_file() and not app.exists()
    assert opened == [sysapps / "OpenSoul.app"]


def test_not_now_moves_nothing_and_is_asked_only_once(mac_home, tmp_path):
    app = _app(mac_home / "Downloads")
    asked = []
    assert M.offer(app, mac_home, asker=lambda: asked.append(1) or False, system_apps=tmp_path / "none") == 0
    assert app.is_dir() and not (mac_home / "Applications" / "OpenSoul.app").exists()
    assert M.offer(app, mac_home, asker=lambda: asked.append(1) or True, system_apps=tmp_path / "none") == 0
    assert asked == [1] and app.is_dir()
    state = json.loads((mac_home / "Library" / "Application Support" / "OpenSoul" / "move_prompt.json").read_text())
    assert state["asked"] == [str(app)]


def test_no_offer_outside_downloads_or_when_already_installed(mac_home, tmp_path):
    never = lambda: pytest.fail("must not ask")  # noqa: E731
    elsewhere = _app(tmp_path / "Desktop")
    assert M.offer(elsewhere, mac_home, asker=never, system_apps=tmp_path / "none") == 0
    sysapps = tmp_path / "Applications"
    _app(sysapps)
    app = _app(mac_home / "Downloads")
    assert M.offer(app, mac_home, asker=never, system_apps=sysapps) == 0 and app.is_dir()


def test_personal_applications_when_the_system_folder_is_not_writable(mac_home, tmp_path):
    app = _app(mac_home / "Downloads")
    rc = M.offer(app, mac_home, asker=lambda: True, opener=lambda p: None, system_apps=tmp_path / "missing")
    assert rc == M.MOVED and (mac_home / "Applications" / "OpenSoul.app").is_dir()


def test_failed_move_says_so_and_carries_on(mac_home, tmp_path, monkeypatch):
    app = _app(mac_home / "Downloads")
    told = []
    monkeypatch.setattr(M.os, "rename", lambda a, b: (_ for _ in ()).throw(OSError(18, "cross-device")))
    rc = M.offer(app, mac_home, asker=lambda: True, teller=told.append, system_apps=tmp_path / "x")
    assert rc == 0 and app.is_dir() and told and "drag it there" in told[0]


def test_ask_needs_the_move_button():
    yes = types.SimpleNamespace(returncode=0, stdout="button returned:Move to Applications\n")
    no = types.SimpleNamespace(returncode=1, stdout="")
    seen = []
    assert M.ask(run=lambda cmd, **k: seen.append(cmd) or yes) is True
    assert M.ask(run=lambda cmd, **k: no) is False
    assert seen[0][0] == "/usr/bin/osascript" and "Not Now" in seen[0][2]


def test_main_is_a_no_op_off_the_mac(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    assert M.main(["/whatever/OpenSoul.app"]) == 0
