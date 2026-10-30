"""OS-062: a picture-only Final renders the shot's Length plus a short handle (8k+1 frames), not always 7.04 s."""
from app import storyboard_api as A
from opensoul import storyboard as sb
from opensoul.presets import build_shot_plan


def _shot(seconds):
    return sb.Shot(id="s1", beat="Waves", prompt="Waves on rocks.", characters=[], seconds=seconds)


def _video(plan):
    return next(x for x in plan["stages"] if x["stage"] == "video")


def test_final_uses_the_length_plus_a_handle():
    plan = A._length_plan(build_shot_plan(camera="static", character_prompt="x", seed=1), _shot(4), "final")
    v = _video(plan)
    frames = v["inputs"]["30"]["length"]
    assert (frames - 1) % 8 == 0 and 4.5 <= frames / 24 < 4.9
    assert v["inputs"]["32"]["frames_number"] == frames and v["params"]["frames"] == frames
    assert any("for a 4 s shot" in n for n in plan["notes"])


def test_no_length_or_a_draft_keeps_the_default():
    base = build_shot_plan(camera="static", character_prompt="x", seed=1)
    before = _video(base)["inputs"].get("30", {}).get("length")
    assert A._length_plan(base, _shot(0), "final") is base
    d = build_shot_plan(camera="static", character_prompt="x", seed=1, quality="draft")
    assert A._length_plan(d, _shot(4), "draft") is d
    assert _video(base)["inputs"].get("30", {}).get("length") == before


def test_a_long_length_is_capped_and_said():
    plan = A._length_plan(build_shot_plan(camera="static", character_prompt="x", seed=1), _shot(15), "final")
    assert _video(plan)["inputs"]["30"]["length"] / 24 <= A.SILENT_MAX_S + 0.4
    assert any("at most" in n for n in plan["notes"])
