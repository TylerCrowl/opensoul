"""Unify step 6: the six-tab shell behind ?ui=unified reuses Create's editor and the Storyboard; classic is untouched."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "app" / "web"


def test_six_tabs_in_order_and_the_script_is_loaded_last():
    html = (WEB / "index.html").read_text()
    nav = html[html.index('id="ufTabs"'):html.index("</nav>", html.index('id="ufTabs"'))]
    assert [t for t in ("characters", "stages", "shots", "render", "review", "export") if f'data-tab="{t}"' in nav] == \
        ["characters", "stages", "shots", "render", "review", "export"]
    assert nav.index('data-tab="characters"') < nav.index('data-tab="stages"') < nav.index('data-tab="export"')
    assert html.index("/static/storyboard.js") < html.index("/static/unified.js")
    assert 'id="ufTabs" aria-label="Make a story in six steps" hidden' in html  # classic page: no tabs


def test_shell_only_turns_on_with_the_flag_and_reuses_the_existing_pieces():
    js = (WEB / "static" / "unified.js").read_text()
    assert 'if (mode === "classic") return;' in js  # unified is the default; classic stays reachable (D2)
    for bit in ("OpenSoulStoryboard", "OpenSoulCreate", "pickCharacter", "loadDemo", "newCharacter", "/api/cast", "first_run"):
        assert bit in js, bit
    sb = (WEB / "static" / "storyboard.js").read_text()
    assert 'new CustomEvent("os:project"' in sb and "openCharacter: (name)" in sb and "openNew: () => openNew()" in sb
    assert "window.OpenSoulCreate = {" in (WEB / "static" / "app.js").read_text()


def test_first_run_card_has_three_ways_in():
    html = (WEB / "index.html").read_text()
    for b in ('id="ufTryDemo"', 'id="ufQuick"', 'id="ufScript"', 'id="ufExRow"'):
        assert b in html, b
