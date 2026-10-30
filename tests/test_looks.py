"""OS-006 / OS-007 / OS-010 / OS-012 / OS-018 / OS-038: a drawn look reaches every prompt, and nothing fights it."""
from __future__ import annotations

from opensoul import looks as LK
from opensoul import stage_sheet, text_master as tm
from opensoul.presets import NEGATIVE_BASE, NEGATIVE_ANTI_GHOST


def test_photo_is_unchanged():
    t = "Photorealistic three-quarter-length reference photo of a woman."
    assert LK.prompt(t, "") == t and LK.prompt(t, "photo") == t
    assert LK.negative("cartoon, anime", "") == "cartoon, anime"


def test_anime_swaps_style_and_negative():
    p = LK.prompt("Photorealistic three-quarter-length reference photo of a farmer. Plain grey.", "anime")
    assert "Photorealistic" not in p and "anime" in p.lower()
    n = LK.negative(NEGATIVE_BASE + ", " + NEGATIVE_ANTI_GHOST, "anime")
    low = n.lower()
    for bad in ("cartoon", "video game", "pc game"):
        assert bad not in low
    assert "photorealistic" in low and "childish" in low  # adults stay adults


def test_eye_words_dropped_when_asked():
    n = LK.negative("ugly, squinting, closed eyes, frowning", "photo", "She gives a quick wink.")
    assert "squinting" not in n and "closed eyes" not in n and "frowning" in n


def test_look_words_leave_the_subject_slot():
    f = {"look": "anime style, 2D cel-shaded anime illustration, a cheerful adult woman with red hair",
         "outfit": "denim overalls", "age": "26-35", "style": ""}
    parts = tm.master_parts(f)
    assert parts["look"] == "anime"
    assert parts["description"].startswith("a cheerful adult woman wearing denim overalls")
    assert "anime style wearing" not in parts["description"]
    assert tm.look_of("a man", "toon3d") == "toon3d" and tm.look_of("a man", "") == "photo"


def test_stage_angle_keeps_the_users_set():
    p = stage_sheet.angle_prompt("medium", "a sunny farm at sunrise", look="")
    assert "register" not in p and "night rain" not in p and "neon" not in p
    assert "same light, weather and time of day" in p and "closer" in p


def test_sheet_preset_for_anime():
    from opensoul.character_sheet import load_preset

    p = LK.sheet_preset(load_preset(), "anime")
    assert "Photorealistic" not in p["style"] and "cartoon" not in p["negative"].lower()


def test_style_plan_drops_era_and_fixes_negative():
    from app.storyboard_api import _style_plan
    from opensoul.presets import build_shot_plan

    plan = build_shot_plan(camera="static", character_prompt="Momo waves.", seed=1)
    assert any(x["stage"] == "era" for x in plan["stages"])
    out = _style_plan(plan, "anime", "Momo waves and winks.")
    assert not any(x["stage"] == "era" for x in out["stages"])
    vid = next(x for x in out["stages"] if x["stage"] == "video")
    assert "smartphone" not in vid["inputs"]["20"]["text"].lower()
    assert vid["inputs"]["20"]["text"].startswith("2D cel-shaded anime")
    assert "cartoon" not in vid["inputs"]["21"]["text"] and "closed eyes" not in vid["inputs"]["21"]["text"]


def test_project_look_patch(tmp_path, monkeypatch):
    from opensoul import storyboard as sb

    st = sb.Store(tmp_path)
    p = st.create_project("Anime trailer")
    assert p.look == ""
    assert st.update_project(p.id, look="anime").look == "anime"
    import pytest

    with pytest.raises(sb.StoryError):
        st.update_project(p.id, look="vaporwave")
