"""OS-039: story takes say the camera move in viewer words and ask for no camera gear in the picture."""
from opensoul import camera_words as CW
from opensoul.presets import build_shot_plan


def test_gear_words_become_viewer_words():
    for cam in ("jib_up", "jib_down", "static", "dolly_left", "fpv", "dolly_in"):
        p = build_shot_plan(camera=cam, seed=1)["prompt"]
        out = CW.viewer_words(p).lower()
        for w in ("crane", "jib", "tripod", "slider", "drone", "motorized"):
            assert w not in out, (cam, w, out)


def test_no_cast_drops_subject_framing():
    p = build_shot_plan(camera="jib_up", seed=1)["prompt"]
    assert "subject framed" in CW.viewer_words(p, has_cast=True)
    assert "subject framed" not in CW.viewer_words(p, has_cast=False)


def test_negative_adds_gear_once():
    n = CW.negative("blurry, low quality")
    assert n.startswith("blurry, low quality, ") and "tripod" in n and CW.negative(n) == n


def test_story_plan_uses_viewer_words():
    from app.storyboard_api import _style_plan

    plan = build_shot_plan(camera="jib_up", seed=3)
    out = _style_plan(plan, "", "an empty street at dawn", has_cast=False)
    vid = next(s for s in out["stages"] if s["stage"] == "video")
    assert "jib" not in vid["inputs"]["20"]["text"].lower() and "crane" not in out["prompt"].lower()
    assert "camera crane" in vid["inputs"]["21"]["text"]
