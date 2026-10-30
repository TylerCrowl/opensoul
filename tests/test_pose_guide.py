import importlib.util
import pathlib

import numpy as np
import pytest

spec = importlib.util.spec_from_file_location(
    "make_pose_guide", pathlib.Path(__file__).resolve().parents[1] / "scripts" / "make_pose_guide.py")
mpg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mpg)


def test_coco_to_openpose_neck_and_order():
    kp = np.arange(34, dtype=np.float32).reshape(17, 2)
    sc = np.linspace(0.1, 0.9, 17).astype(np.float32)
    k, s = mpg.coco_body_to_openpose(kp, sc)
    assert k.shape == (18, 2) and s.shape == (18,)
    np.testing.assert_allclose(k[1], (kp[5] + kp[6]) / 2)  # neck
    assert s[1] == min(sc[5], sc[6])
    np.testing.assert_allclose(k[2], kp[6])   # right shoulder
    np.testing.assert_allclose(k[5], kp[5])   # left shoulder
    np.testing.assert_allclose(k[14], kp[2])  # right eye
    np.testing.assert_allclose(k[17], kp[3])  # left ear


def test_simcc_decode_peak_and_min_confidence():
    sx = np.zeros((1, 2, 576), np.float32)
    sy = np.zeros((1, 2, 768), np.float32)
    sx[0, 0, 100], sy[0, 0, 300] = 0.9, 0.6
    locs, vals = mpg.simcc_decode(sx, sy)
    np.testing.assert_allclose(locs[0, 0], [50, 150])
    assert vals[0, 0] == pytest.approx(0.6)
    assert (locs[0, 1] == -1).all()  # no peak -> invalid


def test_draw_pose_draws_only_confident_points():
    pytest.importorskip("cv2")
    canvas = np.zeros((256, 256, 3), np.uint8)
    k = np.full((18, 2), 128, np.float32)
    s = np.zeros(18, np.float32)
    mpg.draw_pose(canvas, k, s)
    assert canvas.sum() == 0
    s[0] = 1.0
    mpg.draw_pose(canvas, k, s)
    assert canvas.sum() > 0
