"""Motion-direction check on synthetic clips (numpy layers -> mp4) + the shot pipeline re-seed loop."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from opensoul import motion_check as mc  # noqa: E402
from opensoul.presets import build_shot_plan, load_presets  # noqa: E402

W, H, N = 180, 320, 25


def _texture(h: int, w: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = rng.random((h // 4, w // 4)).astype(np.float32)
    t = cv2.resize(t, (w, h), interpolation=cv2.INTER_CUBIC)
    t = cv2.GaussianBlur(t, (0, 0), 1.5)
    t = (t - t.min()) / (t.max() - t.min() + 1e-6)
    return (t * 220 + 20).astype(np.uint8)


BG = None
FG = None


def _layers():
    global BG, FG
    if BG is None:
        BG = _texture(H * 3, W * 3, 1)
        FG = _texture(H, W, 2)
    return BG, FG


def _frame(bg_shift=(0.0, 0.0), fg_shift=(0.0, 0.0), scale=1.0) -> np.ndarray:
    """Background (far) + a centred 'subject' block (near), each shifted; whole frame scaled about the centre."""
    bg, fg = _layers()
    M = np.float32([[1, 0, -W + bg_shift[0]], [0, 1, -H + bg_shift[1]]])
    img = cv2.warpAffine(bg, M, (W, H), borderMode=cv2.BORDER_REFLECT)
    mask = np.zeros((H, W), np.uint8)
    cv2.ellipse(mask, (W // 2, H // 2), (W // 5, H // 4), 0, 0, 360, 255, -1)
    Mf = np.float32([[1, 0, fg_shift[0]], [0, 1, fg_shift[1]]])
    fgw = cv2.warpAffine(fg, Mf, (W, H), borderMode=cv2.BORDER_REFLECT)
    mw = cv2.warpAffine(mask, Mf, (W, H))
    img = np.where(mw > 127, fgw, img)
    if scale != 1.0:
        Z = cv2.getRotationMatrix2D((W / 2, H / 2), 0, scale)
        img = cv2.warpAffine(img, Z, (W, H), borderMode=cv2.BORDER_REFLECT)
    return img


def make_clip(path: Path, kind: str) -> Path:
    frames = []
    for i in range(N):
        t = i / (N - 1)
        if kind == "zoom_in":
            f = _frame(scale=1.0 + 0.5 * t)
        elif kind == "zoom_out":
            f = _frame(scale=1.5 - 0.5 * t)
        elif kind == "truck_right":  # camera travels right: near subject slides left fast, far background slow
            f = _frame(bg_shift=(-30 * t, 0), fg_shift=(-60 * t, 0))
        elif kind == "truck_left":
            f = _frame(bg_shift=(30 * t, 0), fg_shift=(60 * t, 0))
        elif kind == "orbit_right":  # subject held centre, background sweeps right (camera circles to its right)
            f = _frame(bg_shift=(110 * t, 0))
        elif kind == "orbit_left":
            f = _frame(bg_shift=(-110 * t, 0))
        elif kind == "crane_up":  # subject held, background moves UP (camera rises, tilts down)
            f = _frame(bg_shift=(0, -80 * t))
        elif kind == "crane_down":  # untilted descent: near subject rises in frame faster than the background
            f = _frame(bg_shift=(0, -20 * t), fg_shift=(0, -70 * t))
        elif kind == "pan_right":  # camera rotates right: everything slides left together
            f = _frame(bg_shift=(-70 * t, 0), fg_shift=(-70 * t, 0))
        elif kind == "static":
            f = _frame()
            f = np.clip(f.astype(np.int16) + np.random.default_rng(i).integers(-3, 4, f.shape), 0, 255).astype(np.uint8)
        else:
            raise ValueError(kind)
        frames.append(f)
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 24, (W, H), isColor=False)
    if not vw.isOpened():
        pytest.skip("OpenCV cannot write mp4 here")
    for f in frames:
        vw.write(f)
    vw.release()
    return path


KINDS = ["zoom_in", "zoom_out", "truck_left", "truck_right", "orbit_left", "orbit_right",
         "crane_up", "crane_down", "pan_right", "static"]


@pytest.mark.parametrize("kind", KINDS)
def test_synthetic_moves_are_labelled(tmp_path, kind):
    r = mc.detect(make_clip(tmp_path / f"{kind}.mp4", kind))
    assert r.label == kind, (kind, r.label, r.numbers)
    assert 0.0 <= r.confidence <= 1.0


def test_reversed_zoom_in_reads_zoom_out(tmp_path):
    from opensoul import media

    src = make_clip(tmp_path / "zin.mp4", "zoom_in")
    if not media.ffmpeg_bin():
        pytest.skip("ffmpeg not installed")
    rev = media.reverse_video(src, tmp_path / "zin_rev.mp4")
    assert mc.detect(src).label == "zoom_in"
    assert mc.detect(rev).label == "zoom_out"


def test_check_and_expected_labels(tmp_path):
    clip = make_clip(tmp_path / "zi.mp4", "zoom_in")
    assert mc.check(clip, "zoom_in")["ok"]
    assert not mc.check(clip, "zoom_out")["ok"]
    assert mc.check(clip, "any")["ok"] and mc.check(clip, None)["ok"]
    assert mc.expected_labels("orbit") == ["orbit_left", "orbit_right"]
    with pytest.raises(ValueError):
        mc.expected_labels("spin")


def test_every_preset_declares_a_valid_expect_motion():
    p = load_presets()
    for it in p["camera"] + p["effects"]:
        assert "expect_motion" in it, it["id"]
        mc.expected_labels(it["expect_motion"])  # raises on unknown labels
    by = {it["id"]: it for it in p["camera"] + p["effects"]}
    assert by["earth_zoom_out"]["expect_motion"] == "zoom_out" and by["earth_zoom_out"]["reverse"] is True
    assert by["jib_down"]["expect_motion"] == "crane_down"


def test_reverse_preset_plan_uses_render_prompt_and_drops_camera():
    plan = build_shot_plan(effect="earth_zoom_out", camera="dolly_in", era="iphone_ugc")
    v = next(s for s in plan["stages"] if s["stage"] == "video")
    assert v["reverse"] is True and v["expect_motion"] == "zoom_out"
    assert "zoom-in" in plan["prompt"].lower() and "Smooth motorized dolly" not in plan["prompt"]
    assert any("reverse" in n for n in plan.get("notes", []))
    plain = build_shot_plan(camera="dolly_in")
    pv = next(s for s in plain["stages"] if s["stage"] == "video")
    assert pv["reverse"] is False and pv["expect_motion"] == "zoom_in"


class _FakeVideo:
    """Renders a synthetic clip per call: the first `wrong` takes move the wrong way."""

    def __init__(self, good: str, bad: str, wrong: int):
        self.good, self.bad, self.wrong, self.seeds = good, bad, wrong, []

    def render(self, stage, image, dest):
        self.seeds.append(stage["inputs"]["35"]["noise_seed"])
        kind = self.bad if len(self.seeds) <= self.wrong else self.good
        return make_clip(Path(dest).with_name(f"take{len(self.seeds)}.mp4"), kind)


def _plan(camera="dolly_in"):
    plan = build_shot_plan(camera=camera, era="iphone_ugc", seed=101)
    plan["stages"] = [s for s in plan["stages"] if s["stage"] == "video"]  # no era post for speed
    return plan


def test_shot_reseeds_on_wrong_direction(tmp_path):
    from opensoul.shot import run_shot

    vb = _FakeVideo(good="zoom_in", bad="zoom_out", wrong=1)
    res = run_shot(_plan(), tmp_path / "still.png", tmp_path / "out", video_backend=vb, motion_check=True, max_reseeds=2)
    assert len(vb.seeds) == 2 and vb.seeds[0] != vb.seeds[1]
    assert "fixed automatically: camera direction" in res.notes
    mc_steps = [s for s in res.steps if s["stage"] == "motion_check"]
    assert [s["ok"] for s in mc_steps] == [False, True]


def test_default_is_one_render_and_a_plain_note(tmp_path, monkeypatch):  # OS-017
    from opensoul.shot import run_shot

    monkeypatch.delenv("OPENSOUL_MOTION_RESEEDS", raising=False)
    vb = _FakeVideo(good="zoom_in", bad="zoom_out", wrong=99)
    res = run_shot(_plan(), tmp_path / "still.png", tmp_path / "out", video_backend=vb, motion_check=True)
    assert len(vb.seeds) == 1
    assert any("Keep this take" in n and "Regenerate" in n for n in res.notes)


def test_shot_gives_up_after_max_reseeds(tmp_path):
    from opensoul.shot import run_shot

    vb = _FakeVideo(good="zoom_in", bad="zoom_out", wrong=99)
    res = run_shot(_plan(), tmp_path / "still.png", tmp_path / "out", video_backend=vb, motion_check=True, max_reseeds=2)
    assert len(vb.seeds) == 3
    assert not any("fixed automatically" in n for n in res.notes)
    assert any("camera direction" in n and "still" in n for n in res.notes)


def test_shot_no_retry_when_direction_ok(tmp_path):
    from opensoul.shot import run_shot

    vb = _FakeVideo(good="zoom_in", bad="zoom_out", wrong=0)
    res = run_shot(_plan(), tmp_path / "still.png", tmp_path / "out", video_backend=vb, motion_check=True)
    assert len(vb.seeds) == 1 and res.notes == []


def test_shot_reverse_stage_reverses_then_checks(tmp_path):
    from opensoul.shot import run_shot

    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    plan = build_shot_plan(effect="earth_zoom_out", era="iphone_ugc", seed=7)
    plan["stages"] = [s for s in plan["stages"] if s["stage"] == "video"]
    vb = _FakeVideo(good="zoom_in", bad="zoom_out", wrong=0)  # the render pushes IN; reversed it must read zoom_out
    res = run_shot(plan, tmp_path / "still.png", tmp_path / "out", video_backend=vb, motion_check=True)
    assert len(vb.seeds) == 1
    chk = [s for s in res.steps if s["stage"] == "motion_check"][0]
    assert chk["ok"] and chk["label"] == "zoom_out"
    assert any(s["stage"] == "reverse" for s in res.steps)
    assert json.dumps(res.steps)  # serialisable for the API
