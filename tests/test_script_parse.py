from pathlib import Path
from opensoul.script_parse import parse_script_markdown

ROOT = Path(__file__).resolve().parents[1]


def test_demo_script_spoken_plain():
    import app.server as server

    f = sorted(p for p in server.SCRIPTS.glob("*.md") if p.stem != "README")[0]
    p = parse_script_markdown(f.read_text(encoding="utf-8"), f.stem)
    assert p.spoken and p.title
    assert "##" not in p.spoken
    assert "**" not in p.spoken
    assert len(p.shots) >= 4
    assert p.tip
