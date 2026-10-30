"""Light and dark theme: every colour lives in theme.css as a token, both themes define the same tokens, the
choice persists, and the token pairs the UI puts together pass WCAG AA (4.5:1 text, 3:1 large text and UI parts).

The contrast part doubles as the contrast script: `python tests/test_theme_tokens.py` prints the table."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "web" / "static"
THEME = (STATIC / "theme.css").read_text(encoding="utf-8")
STYLE_FILES = ["app.css", "storyboard.css", "music.css", "hardware.css", "models.css", "launcher.css"]
SCRIPT_FILES = ["app.js", "storyboard.js", "music.js", "hardware.js", "models.js", "theme.js", "tiles.js", "unified.js"]


def _block(start: str) -> str:
    i = THEME.index(start)
    j = THEME.index("{", i) + 1
    depth, k = 1, j
    while depth:
        depth += {"{": 1, "}": -1}.get(THEME[k], 0)
        k += 1
    return THEME[j:k - 1]


def _tokens(block: str) -> dict:
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"(--[a-z0-9-]+)\s*:\s*([^;]+);", block)}


LIGHT = _tokens(_block(":root {"))
DARK = _tokens(_block(':root[data-theme="dark"] {'))
SYSTEM_DARK = _tokens(_block(':root:not([data-theme="light"]) {'))
THEMES = {"light": LIGHT, "dark": DARK}

# (foreground, background, minimum ratio, what it is)
PAIRS = [
    ("--text", "--bg", 4.5, "body text on the page"),
    ("--text", "--surface", 4.5, "text on cards"),
    ("--text", "--control", 4.5, "button text on grey buttons"),
    ("--text", "--field-bg", 4.5, "typed text in fields"),
    ("--text-2", "--surface", 4.5, "strong secondary text"),
    ("--text-secondary", "--surface", 4.5, "secondary text on cards"),
    ("--text-secondary", "--bg", 4.5, "secondary text on the page"),
    ("--text-secondary", "--wash", 4.5, "secondary text on washes"),
    ("--text-tertiary", "--surface", 4.5, "hints on cards"),
    ("--text-tertiary", "--bg", 4.5, "hints on the page"),
    ("--text-tertiary", "--wash", 4.5, "hints on washes"),
    ("--accent-text", "--surface", 4.5, "links on cards"),
    ("--accent-text", "--bg", 4.5, "links on the page"),
    ("--accent-text", "--accent-wash", 4.5, "selected chip text"),
    ("--on-accent", "--accent", 4.5, "primary button text"),
    ("--on-accent", "--accent-hover", 4.5, "primary button text, hovered"),
    ("--ok-text", "--ok-bg", 4.5, "tested badge"),
    ("--warn-text", "--warn-bg", 4.5, "untested / preview badge"),
    ("--restricted-text", "--restricted-bg", 4.5, "use-restricted licence badge"),
    ("--restricted-text", "--surface", 4.5, "use-restricted explanation line"),
    ("--planned-text", "--planned-bg", 4.5, "planned badge"),
    ("--planned-text", "--surface", 4.5, "planned reason line"),
    ("--danger-text", "--surface", 4.5, "error text"),
    ("--text-secondary", "--neutral-bg", 4.5, "neutral badge"),
    ("--text-tertiary", "--control", 4.5, "hints on grey controls"),
    ("--inverse-text", "--inverse-bg", 4.5, "toast text"),
    ("--inverse-link", "--inverse-bg", 4.5, "toast link"),
    ("--on-media", "--media-bg", 4.5, "captions on video"),
    ("--focus-ring", "--bg", 3.0, "focus ring on the page"),
    ("--focus-ring", "--surface", 3.0, "focus ring on cards"),
    ("--accent", "--surface", 3.0, "accent controls (checkbox, progress)"),
    ("--danger", "--surface", 3.0, "error icons and outlines"),
]
# Decorative only (empty-state glyphs, separators): exempt from text contrast, but must still be visible.
DECORATIVE = [("--text-faint", "--surface", 1.5), ("--line-strong", "--surface", 1.3)]


def _rgb(value: str):
    m = re.fullmatch(r"#([0-9a-fA-F]{6})", value)
    assert m, f"not a #rrggbb colour: {value}"
    return tuple(int(m.group(1)[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _lum(rgb) -> float:
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_lum(_rgb(a)), _lum(_rgb(b))), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_both_themes_define_the_same_colour_tokens():
    light_colours = {k for k, v in LIGHT.items() if not k.startswith(("--radius", "--pill", "--font"))}
    assert light_colours - set(DARK) <= {"--shadow"}, sorted(light_colours - set(DARK))  # --shadow reuses the channels
    assert set(DARK) <= set(LIGHT)
    for name in ("--bg", "--surface", "--text", "--text-secondary", "--accent", "--accent-text", "--focus-ring",
                 "--ok-bg", "--ok-text", "--warn-bg", "--warn-text", "--danger-text", "--line-strong",
                 "--restricted-bg", "--restricted-text", "--planned-bg", "--planned-text"):
        assert name in LIGHT and name in DARK, name
        assert LIGHT[name] != DARK[name] or name in ("--accent",), name


def test_system_dark_matches_chosen_dark():
    # "System default" with a dark OS must look exactly like choosing Dark.
    assert SYSTEM_DARK == DARK
    assert "@media (prefers-color-scheme: dark)" in THEME
    assert re.search(r":root\s*\{\s*color-scheme:\s*light", THEME)
    assert "color-scheme: dark" in _block(':root[data-theme="dark"] {')


def test_page_background_is_opaque():
    for name, t in THEMES.items():
        assert re.fullmatch(r"#[0-9a-fA-F]{6}", t["--bg"]), name
        assert re.fullmatch(r"#[0-9a-fA-F]{6}", t["--surface"]), name


def test_token_pairs_pass_wcag_aa():
    failures = []
    for theme, t in THEMES.items():
        for fg, bg, need, what in PAIRS:
            r = contrast(t[fg], t[bg])
            if r < need:
                failures.append(f"{theme}: {what} {fg} on {bg} = {r:.2f} < {need}")
        for fg, bg, need in DECORATIVE:
            r = contrast(t[fg], t[bg])
            if r < need:
                failures.append(f"{theme}: decorative {fg} on {bg} = {r:.2f} < {need}")
    assert not failures, "\n".join(failures)


_ALLOWED = [
    re.compile(r"mask-image:"),  # masks use #000 as alpha, not as a colour you see
]
_RAW = re.compile(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgb|hsl)a?\(\s*\d|\b(?:white|black|red|green|blue|gray|grey|silver)\b(?!-)")


def _strip_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def test_no_raw_colours_outside_the_token_file():
    hits = []
    for name in STYLE_FILES:
        for n, line in enumerate(_strip_comments((STATIC / name).read_text(encoding="utf-8")).splitlines(), 1):
            line = re.sub(r"white-space\s*:\s*[a-z-]+", "", line)
            if _RAW.search(line) and not any(a.search(line) for a in _ALLOWED):
                hits.append(f"{name}:{n}: {line.strip()[:120]}")
    for name in SCRIPT_FILES:
        text = re.sub(r"//[^\n]*", "", _strip_comments((STATIC / name).read_text(encoding="utf-8")))
        for n, line in enumerate(text.splitlines(), 1):
            if re.search(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b(?![\w-])|\brgba?\(\s*\d", line):
                hits.append(f"{name}:{n}: {line.strip()[:120]}")
    html = (ROOT / "app" / "web" / "index.html").read_text(encoding="utf-8")
    for n, line in enumerate(html.splitlines(), 1):
        if re.search(r"style=\"[^\"]*(#[0-9a-fA-F]{3,6}\b|rgba?\()", line):
            hits.append(f"index.html:{n}: {line.strip()[:120]}")
    assert not hits, "raw colours outside theme.css:\n" + "\n".join(hits)


def test_every_token_used_is_defined():
    used = set()
    for name in STYLE_FILES:
        used |= set(re.findall(r"var\((--[a-z0-9-]+)", (STATIC / name).read_text(encoding="utf-8")))
    local = set()
    for name in STYLE_FILES:
        local |= set(re.findall(r"(--[a-z0-9-]+)\s*:", (STATIC / name).read_text(encoding="utf-8")))
    missing = sorted(u for u in used if u not in LIGHT and u not in local)
    assert not missing, missing


def test_theme_loads_before_paint_and_choice_persists():
    html = (ROOT / "app" / "web" / "index.html").read_text(encoding="utf-8")
    head = html[: html.index("</head>")]
    assert '<meta name="color-scheme" content="light dark"' in head
    # the inline script sets data-theme from localStorage before any stylesheet paints
    inline = head.index('localStorage.getItem("opensoul.theme")')
    assert inline < head.index("theme.css") < head.index("app.css")
    assert 'setAttribute("data-theme"' in head
    js = (STATIC / "theme.js").read_text(encoding="utf-8")
    assert '"opensoul.theme"' in js and "localStorage.setItem" in js and "localStorage.removeItem" in js
    for label in ("System default", "Light", "Dark"):
        assert label in js
    assert "prefers-color-scheme: dark" in js  # follows the OS live while on System default
    assert 'addEventListener("storage"' in js  # other open tabs follow the change
    assert "theme.js" in html and "theme.css" in html


def test_theme_assets_are_cache_busted():
    import app.server as server

    assert "theme.css" in server.UI_ASSETS and "theme.js" in server.UI_ASSETS  # hashed and given ?v= (one shared list)


def test_reduced_motion_and_focus_ring():
    assert "prefers-reduced-motion: reduce" in THEME
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    assert ":focus-visible" in css and "var(--focus-ring)" in css


if __name__ == "__main__":
    for theme, t in THEMES.items():
        print(f"\n{theme}")
        for fg, bg, need, what in PAIRS:
            r = contrast(t[fg], t[bg])
            print(f"  {'ok ' if r >= need else 'LOW'} {r:5.2f} (≥{need}) {what}: {fg} {t[fg]} on {bg} {t[bg]}")


def test_badge_tiers_have_distinct_colours():
    # tested (green), untested (yellow), planned (violet), use-restricted (amber): four different looks per theme
    for theme, t in THEMES.items():
        pairs = {(t[f"--{k}-bg"], t[f"--{k}-text"]) for k in ("ok", "warn", "planned", "restricted")}
        assert len(pairs) == 4, theme
