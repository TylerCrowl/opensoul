"""OS-074: opening a story (Shorts, a link, a hand-off) must also select it in the Story list."""
import re
from pathlib import Path

JS = (Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "storyboard.js").read_text(encoding="utf-8")


def test_open_project_selects_it_in_the_story_list():
    body = JS[JS.index("async function openProject(id)"):]
    body = body[: body.index("\n  }\n")]
    assert re.search(r'\$\("sbProject"\)\.value = sb\.project\.id', body)


def test_shorts_opens_the_shorts_story():
    q = JS[JS.index("async function quickShot()"):]
    q = q[: q.index("\n  }\n")]
    assert "openProject(q.id)" in q
