"""The fresh-state footer reason in the character master step names the button to tap."""
from pathlib import Path

APP_JS = Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "app.js"


def test_fresh_state_reason_names_make_4_options():
    js = APP_JS.read_text(encoding="utf-8")
    assert '"Do step 1 first: click Make 4 options to make a master."' in js
    assert "Step 1 first: generate a master from your description." not in js
