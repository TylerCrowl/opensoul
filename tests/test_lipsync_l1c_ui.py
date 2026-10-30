"""L1c cost hint where render-time estimates live: the shot's dialogue record carries latentsync_est_s
(ceil(frames / 16) x 35.3 s) and the take details show it. No GPU."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dialogue_record_and_take_details_show_the_mouth_pass_estimate():
    import app.storyboard_api as A
    from opensoul import lipsync as L

    src = Path(A.__file__).read_text()
    assert '"latentsync_est_s": (l1c or {}).get("cost_est_s")' in src and '"recipe": (l1c or {}).get("recipe")' in src
    js = (ROOT / "app/web/static/storyboard.js").read_text()
    assert "d.latentsync_est_s" in js and "Mouth pass (LatentSync): about" in js
    assert "only if the take fails a check" in js
    assert L.latentsync_cost_s(45) == 105.9


def test_dialogue_plan_for_a_rebuilt_speaker_has_the_estimate(monkeypatch):
    import app.storyboard_api as A
    from opensoul import lipsync as L
    from opensoul import storyboard as sb

    monkeypatch.delenv(L.BEST_OF_ENV, raising=False)
    monkeypatch.setattr(L, "scorer_enabled", lambda: True)  # best-of needs the scorer (OS-057)
    monkeypatch.delenv(L.RECIPE_ENV, raising=False)
    monkeypatch.setattr(A, "_speaker_pack", lambda who: {"rebuilt": True})
    monkeypatch.setattr(A, "_shot_voice", lambda s: ("F", "shot"))
    monkeypatch.setattr(L, "latentsync_installed", lambda: True)
    s = sb.Shot(id="s1", beat="b", characters=["Lumi", "Ren"], line="Have a good night.", speaker="Lumi",
                face_box=[100, 100, 200, 300])  # two faces: LatentSync needs the speaker's box
    d = A._dialogue(s, prompt="p", quality="final", seed=1, size=(704, 1280), position=1)
    assert d["recipe"] == "L1c" and d["stage2_default_on"] is True
    lip = next(x for x in d["stages"] if x.get("only_if") == L.ONLY_IF_L1C_STAGE2)
    assert d["latentsync_est_s"] == lip["cost_est_s"] == L.latentsync_cost_s(lip["frames_est"])
    assert "eyes on Ren." in d["stages"][1]["inputs"][L.N_PROMPT]["text"]


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_cam_lock(monkeypatch):
    # These cover the Stage 2 defaults (rebuilt / voice F / a failing base). Since the review ruling, a
    # camera-locked (AddGuide) take keeps Stage 2 off unless 'Mouth refine' is ticked (tests/test_mouth_refine.py),
    # so they run on the takes the defaults still apply to: camera lock off.
    monkeypatch.setenv("OPENSOUL_A2V_CAMLOCK", "off")
