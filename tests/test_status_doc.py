"""docs/STATUS.md: the honest "what works today" page. Only the Spark row is verified; every other hardware row says
estimate / planned / not supported, and the README links the page."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs/STATUS.md"


def _hw_rows():
    text = DOC.read_text(encoding="utf-8")
    table = text.split("## Hardware and models", 1)[1].split("Mac notes", 1)[0]
    return [ln for ln in table.splitlines() if ln.startswith("|") and not ln.startswith("|---") and "Machine" not in ln]


def test_readme_links_the_status_page():
    assert "docs/STATUS.md" in (ROOT / "README.md").read_text(encoding="utf-8")


def test_only_the_spark_row_is_verified():
    rows = _hw_rows()
    assert len(rows) >= 8
    verified = [r for r in rows if "**Verified**" in r]
    assert len(verified) == 1 and verified[0].startswith("| DGX Spark, 128 GB")
    for r in rows:
        if r not in verified:
            low = r.lower()
            assert any(w in low for w in ("estimate", "planned", "not supported", "render elsewhere")), r


def test_mac_caveats_and_music_tab_are_honest():
    text = DOC.read_text(encoding="utf-8")
    assert "15804" in text and "MLX" in text and "Not supported by the app yet" in text
    assert "never been run from the app" in text and "gpu_validated: false" in text
