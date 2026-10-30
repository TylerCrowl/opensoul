"""Models screen front end (app/web/static/models.js): served, its own tab right before Characters (with a small link
from Settings), never approves, and shows the user's CLI approve command. Light string checks, the repo's pattern for page tests (see test_hardware_advisory.py)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "web" / "static"


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import server

    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    monkeypatch.setattr(server, "DATA", tmp_path)
    yield TestClient(server.app)


# ---------------------------------------------------------------- front-end smoke

def test_models_page_is_served_and_wired(client):
    html = client.get("/").text
    assert re.search(r'/static/models\.js\?v=\w+"', html) and re.search(r'/static/models\.css\?v=\w+"', html)
    assert 'id="modelsView"' in html
    assert client.get("/static/models.js").status_code == 200


def test_models_js_never_approves_and_shows_the_cli_command():
    js = (STATIC / "models.js").read_text(encoding="utf-8")
    for bit in ("/api/hardware/models", "/api/setup/plan", "approve_command", "navigator.clipboard", "Agents can't approve",
                'id="mdCommercial"', 'id="mdSim"', "Plan install / swap", "fit", "license_acks_needed", "disk_fits"):
        assert bit in js, bit
    assert "/api/setup/apply" not in js and "/api/setup/slot" not in js
    assert not re.search(r"approval_token|fetch\([^)]*approve", js)
    hw = (STATIC / "hardware.js").read_text(encoding="utf-8")
    assert "hwModelsOpen" in hw or "hwModelsOpen" in js


# ---------------------------------------------------------------- Models as its own tab

def _tab_bar(html: str) -> str:
    start = html.index('id="ufTabs"')
    return html[start:html.index("</nav>", start)]


def _tab_buttons(nav: str) -> list[str]:
    """The tab bar's buttons in DOM order (= keyboard Tab order: none of them sets tabindex)."""
    out = []
    for m in re.finditer(r"<button\b([^>]*)>(.*?)</button>", nav, re.DOTALL):
        attrs, label = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
        assert "tabindex" not in attrs
        tab = re.search(r'data-tab="(\w+)"', attrs)
        bid = re.search(r'id="(\w+)"', attrs)
        out.append(tab.group(1) if tab else (bid.group(1) if bid else label))
    return out


def test_top_bar_is_six_steps_and_tools_sit_apart(client):
    """Music placement: a clean six-step timeline; Music videos and Shorts apart after a thin divider (no label); Models in Settings."""
    for html in ((ROOT / "app" / "web" / "index.html").read_text(encoding="utf-8"), client.get("/").text):
        order = _tab_buttons(_tab_bar(html))
        assert order == ["characters", "stages", "shots", "render", "review", "export"], order
        assert 'id="ufModelsBtn"' not in html
        start = html.index('id="ufTools"')
        tools = html[start:html.index("</nav>", start)]
        assert 'id="ufMusicBtn"' in tools and 'id="toQuickShot"' in tools and 'aria-label="Music videos and Shorts"' in html
        assert ">Music videos</button>" in tools and ">Shorts</a>" in tools
        assert "uf-tools-label" not in html and ">Tools<" not in html and "Quick shot<" not in html
        assert html.index('id="ufTools"') > html.index('id="ufTabs"')


def test_models_tab_active_state_deep_links_and_settings_link():
    js = (STATIC / "models.js").read_text(encoding="utf-8")
    # active look: the same .active + aria-current the step tabs use, and the step tabs lose theirs while Models is open
    assert 'btn.setAttribute("aria-current", "page");  // Models is part of Settings' in js
    assert 'b.classList.remove("active"); b.removeAttribute("aria-current")' in js
    # old addresses land on the tab: ?models=1 (with or without settings=1) and ?tab=models
    assert 'qs.get("models") === "1" || qs.get("tab") === "models"' in js
    assert 'url.searchParams.set("models", "1"); url.searchParams.delete("settings")' in js
    uni = (STATIC / "unified.js").read_text(encoding="utf-8")
    assert 'params.get("tab") === "models"' in uni and 'u.searchParams.set("models", "1")' in uni
    # Settings -> Models, and "Settings ›  Models" at the top of the page goes back
    assert 'id="hwModelsOpen"' in js and 'id="mdToSettings"' in js
    hw = (STATIC / "hardware.js").read_text(encoding="utf-8")
    assert "window.OpenSoulModels.close()" in hw  # opening Settings leaves the Models tab
    css = (STATIC / "models.css").read_text(encoding="utf-8")
    assert "body.models-on #storyboardView" in css and "body.models-on #musicView" in css
    assert ".uf-tabs button.active" in (STATIC / "storyboard.css").read_text(encoding="utf-8")  # the shared active-tab style


def test_shorts_and_music_videos_terms_are_used_everywhere():
    """Owner rename (Oct 27): Quick shot -> Shorts, Music -> Music videos, no "Tools" label; a thin divider stays."""
    welcome = (ROOT / "app" / "web" / "welcome.html").read_text(encoding="utf-8")
    assert "<b>Music videos</b>" in welcome and "<b>Shorts</b>" in welcome and "<b>Tools</b>" not in welcome
    music = (STATIC / "music.js").read_text(encoding="utf-8")
    assert '<h1 id="muH">Music videos</h1>' in music
    sbjs = (STATIC / "storyboard.js").read_text(encoding="utf-8")
    assert "Make a song in Music videos (top bar)." in sbjs and "(Tools)" not in sbjs
    html = (ROOT / "app" / "web" / "index.html").read_text(encoding="utf-8")
    assert "Make a song in Music videos." in html and "Make a short</button>" in html
    css = (STATIC / "storyboard.css").read_text(encoding="utf-8")
    assert "border-left: 1px solid var(--border)" in css[css.index(".uf-tools {"):]
    style = (ROOT / "docs" / "STYLE.md").read_text(encoding="utf-8")
    assert "| **Shorts** |" in style and "| **Music videos** |" in style
    for doc in ("README.md", "docs/MUSIC.md", "docs/DESKTOP.md"):
        text = (ROOT / doc).read_text(encoding="utf-8")
        assert "Quick shot**" not in text and "Music tab" not in text, doc
