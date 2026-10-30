"""Unify step 8: Render (a queue over regenerate / final) and Review (side-by-side takes + keeper) use the existing routes only."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "app" / "web" / "static" / "unified.js").read_text()
SB = (ROOT / "app" / "web" / "static" / "storyboard.js").read_text()


def test_queue_calls_only_the_existing_storyboard_routes():
    assert "`${base}/final`, { version_id: s.keeper }" in JS
    assert '`${base}/regenerate`, { edit: "", seed: null, from_version: null, quality: a === "Make a final" ? "final" : "draft" }' in JS
    assert '"Make a final"' in JS  # 3 camera moves: Drafts take 2 at most, so the queue goes straight to Final
    assert "/shots/${sid}/keeper`, { version_id: b.dataset.keep }" in JS
    for r in ('"/api/shot"', "/export", "fetch(\"/api/storyboard"):
        assert r not in JS, r  # no new or side routes


def test_every_shot_state_has_one_clear_next_step():
    for text in ('"Make a draft"', '"Render final"', '"Choose in Review"', '"Rendering…"', "✓ Final", "✓ Keeper", "Keep this"):
        assert text in JS, text
    assert "Preview mode: takes are samples from a real render. OpenSoul sends nothing to the GPU." in JS


def test_the_storyboard_exposes_what_the_tabs_need_and_announces_project_changes():
    assert "api, post, setProject, poll, toast, keeperOf, kindLabel };" in SB
    assert SB.count('new CustomEvent("os:project"') == 2  # on every change and when a story is opened
    assert 'document.addEventListener("os:project", () => renderQueue());' in JS
