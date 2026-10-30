"""README and both app shells lead with the same line and the same honest qualifier (Oct 19)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEAD = "Open models. Your own computer. Your characters."
QUAL = "Preview mode runs on any computer. Real renders need a studio."


def test_readme_and_both_heroes_share_lead_and_qualifier():
    readme = (ROOT / "README.md").read_text()
    assert readme.splitlines()[2] == f"**{LEAD}**" and readme.splitlines()[4] == QUAL
    html = (ROOT / "app/web/index.html").read_text()
    assert html.count(f'<p class="hero-lead">{LEAD}</p>') == 2 and html.count(f'<p class="hero-qual">{QUAL}</p>') == 2
    # the kicker, then the H1, then the qualifier as one small line under it (never wedged above the H1)
    for h1 in ("Shorts: direct a short video starring your character", "Make a short story with your own characters"):
        i = html.index(f"<h1>{h1}</h1>")
        assert html.rindex('<p class="hero-lead">', 0, i) > html.rfind("<h1>", 0, i)
        assert html.index('<p class="hero-qual">', i) - i < 120
    assert "Built on open models; runs on your own computer" not in html
    assert "Everything runs on open models" not in html


def test_the_two_shells_are_labelled_and_linked():
    html = (ROOT / "app/web/index.html").read_text()
    assert ">Shorts: direct a short video starring your character<" in html
    assert 'class="shell-tag shell-quick">Shorts<' in html
    assert 'id="toFullStudio" href="./">Open the full studio<' in html and re.search(r'id="toQuickShot" href="\./\?quick=1">(<svg.*?</svg>)?Shorts<', html)
    assert html.count('id="charHeading"') == 1  # one New character editor, shared by both shells


def test_demo_cast_flag_only_on_the_demo_and_release_paths():
    assert "OPENSOUL_DRY_RUN=1 OPENSOUL_DEMO_CAST=1 opensoul-ui" in (ROOT / "README.md").read_text()
    assert "OPENSOUL_DEMO_CAST=1" in (ROOT / "scripts/setup_dev.sh").read_text()
    assert "OPENSOUL_DEMO_CAST" not in (ROOT / "CONTRIBUTING.md").read_text()
