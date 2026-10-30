"""CPU unit tests for runners/ls_face_detector.py (the MediaPipe/anime replacement for LatentSync's InsightFace
detector). No mediapipe, torch or model files needed: the detectors are replaced by synthetic faces."""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

RUN = Path(__file__).resolve().parents[1] / "custom_nodes" / "opensoul_nodes" / "runners"


@pytest.fixture(scope="module")
def fd():
    spec = importlib.util.spec_from_file_location("ls_face_detector_under_test", RUN / "ls_face_detector.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def mp_face(fd, x, y, w, h):
    """Synthetic 478-point MediaPipe face filling the box (x, y, w, h)."""
    rel = np.full((478, 2), 0.5)
    rel[fd.MP_BROW_A] = np.c_[np.linspace(0.20, 0.40, 10), np.full(10, 0.30)]
    rel[fd.MP_BROW_B] = np.c_[np.linspace(0.60, 0.80, 10), np.full(10, 0.30)]
    rel[fd.MP_NOSE] = [0.5, 0.55]
    rel[fd.MP_HALF] = [0.5, 0.45]
    t = np.linspace(np.pi, 0, len(fd.MP_JAW))
    rel[fd.MP_JAW] = np.c_[0.5 + 0.5 * np.cos(t), 0.55 + 0.45 * np.sin(t)]
    a = np.linspace(0, 2 * np.pi, len(fd.MP_MOUTH), endpoint=False)
    rel[fd.MP_MOUTH] = np.c_[0.5 + 0.12 * np.cos(a), 0.75 + 0.04 * np.sin(a)]
    rel[10] = [0.5, 0.0]
    return rel * [w, h] + [x, y]


def anime_kp(x, y, w, h, mouth_y=0.78):
    rel = np.zeros((28, 2))
    rel[0:5] = np.c_[np.linspace(0.1, 0.9, 5), [0.6, 0.85, 1.0, 0.85, 0.6]]
    rel[5:8] = np.c_[[0.2, 0.3, 0.4], [0.3, 0.27, 0.3]]
    rel[8:11] = np.c_[[0.6, 0.7, 0.8], [0.3, 0.27, 0.3]]
    rel[11:23] = np.c_[np.r_[np.linspace(0.22, 0.42, 6), np.linspace(0.58, 0.78, 6)], np.full(12, 0.45)]
    rel[23] = [0.5, 0.62]
    rel[24:28] = np.c_[[0.42, 0.5, 0.58, 0.5], [mouth_y, mouth_y - 0.02, mouth_y, mouth_y + 0.02]]
    return rel * [w, h] + [x, y]


def make_detector(fd, faces_per_frame, anime_per_frame=None, face_box=None, style="real", hold=2):
    d = object.__new__(fd.FaceDetector)
    d.style, d.hold = style, hold
    d.target = fd.parse_face_box(",".join(map(str, face_box))) if face_box else None
    d._last = d._last_ext = None
    d._miss = 0
    d.last_source = None
    d.rec = fd.Record(style, d.target)
    d._anime = object() if anime_per_frame is not None else None
    seq = iter(faces_per_frame)
    aseq = iter(anime_per_frame or [])
    cur = {}

    def mp_points(rgb, off=(0, 0)):
        if rgb.shape == FRAME.shape:  # full frame (a crop retry is smaller)
            cur["f"] = next(seq)
            return [mp_face(fd, *b) for b in cur["f"]]
        return []  # crop retry finds nothing

    def anime_preds(frame):
        bs = next(aseq)
        return [{"bbox": np.array([x, y, x + w, y + h, 0.9]), "keypoints": anime_kp(x, y, w, h, my)} for x, y, w, h, my in bs]

    d._mp_points = mp_points
    d._anime_preds = anime_preds
    return d


FRAME = np.zeros((720, 1280, 3), np.uint8)


def test_build_lmk106_keeps_affine_point_means(fd):
    bl = np.array([[10, 20], [12, 18], [14, 17], [16, 18], [18, 20]], float)
    br = bl + [40, 0]
    nose = np.array([[30, 40], [32, 41], [28, 41], [30, 43]], float)
    half = np.array([[30, 30], [30, 34]], float)
    jaw = np.c_[np.linspace(0, 60, 21), np.full(21, 70)]
    mouth = np.c_[np.linspace(20, 40, 20), np.full(20, 55)]
    l = fd.build_lmk106(bl, br, nose, half, jaw, mouth, [30, 40])
    assert l.shape == (106, 2)
    # the three points LatentSync's ImageProcessor.affine_transform reads (rounded to int pixels)
    assert np.allclose(l[[43, 48, 49, 51, 50]].mean(0), bl.mean(0), atol=1)
    assert np.allclose(l[101:106].mean(0), br.mean(0), atol=1)
    assert np.allclose(l[[74, 77, 83, 86]].mean(0), nose.mean(0), atol=1)
    # 74 is shared with the half-face pair: the half point must still be right
    assert np.allclose(np.mean([l[73], l[74]], 0), half.mean(0), atol=1)


def test_from_mediapipe_orders_brows_and_box_is_sane(fd):
    pts = mp_face(fd, 100, 50, 200, 260)
    l = fd.from_mediapipe(pts)
    assert l[[43, 48, 49, 51, 50]].mean(0)[0] < l[101:106].mean(0)[0]   # image-left brow first
    x1, y1, x2, y2 = fd.ls_box(l, 1280, 720)
    assert 80 <= x1 < 160 and 240 < x2 <= 320 and y2 > 250 and y1 < y2


def test_from_anime_nose_k_and_mouth(fd):
    kp = anime_kp(0, 0, 100, 100)
    l0, l1 = fd.from_anime(kp, k=0.0), fd.from_anime(kp, k=1.0)
    mid = (kp[5:8].mean(0) + kp[8:11].mean(0)) / 2
    assert np.allclose(l0[74], mid, atol=1) and np.allclose(l1[74], kp[23], atol=1)
    assert np.allclose(l1[52:72].mean(0), kp[24:28].mean(0), atol=1.5)


def test_parse_face_box(fd):
    assert fd.parse_face_box("10,20,30,40") == (10, 20, 40, 60)
    assert fd.parse_face_box(None) is None
    with pytest.raises(ValueError):
        fd.parse_face_box("1,2,0,5")


def test_single_face_needs_no_box_and_reports(fd):
    d = make_detector(fd, [[(100, 100, 200, 260)]] * 3)
    for _ in range(3):
        box, lmk = d(FRAME)
        assert box is not None and lmk.shape == (106, 2)
    r = d.report()
    assert r["frames"] == 3 and r["face_found_ratio"] == 1.0 and r["held_frames"] == 0
    assert r["detector_counts"] == {"mediapipe": 3, "anime_fallback": 0, "held": 0, "none": 0}
    assert r["face_px_median"] == pytest.approx(260, abs=1) and r["multi_face_frames"] == 0


def test_two_faces_without_box_is_ambiguous(fd):
    d = make_detector(fd, [[(100, 100, 200, 260), (700, 120, 180, 240)]])
    with pytest.raises(fd.AmbiguousFace) as e:
        d(FRAME)
    assert "ambiguous_face" in str(e.value) and e.value.code == "ambiguous_face"


def test_tiny_background_face_is_not_ambiguous(fd):
    d = make_detector(fd, [[(100, 100, 200, 260), (900, 100, 40, 50)]])
    box, _ = d(FRAME)
    assert box is not None and box[0] < 300


def test_face_box_picks_by_iou_then_tracks(fd):
    a, b = (100, 100, 200, 260), (700, 120, 180, 240)
    frames = [[a, b], [b, a], [(110, 104, 200, 260), (690, 120, 180, 240)]]
    d = make_detector(fd, frames, face_box=(690, 110, 200, 250))
    xs = []
    for _ in frames:
        box, _ = d(FRAME)
        xs.append(box[0])
    assert all(x > 600 for x in xs)          # stayed on the right-hand face, whatever the list order
    assert d.report()["multi_face_frames"] == 3


def test_face_box_without_overlap_uses_nearest_centre(fd):
    d = make_detector(fd, [[(100, 100, 200, 260), (700, 120, 180, 240)]], face_box=(1000, 600, 20, 20))
    box, _ = d(FRAME)
    assert box[0] > 600


def test_hold_then_miss(fd):
    d = make_detector(fd, [[(100, 100, 200, 260)], [], [], []], hold=2)
    assert d(FRAME)[0] is not None
    assert d(FRAME)[0] is not None and d.last_source == "hold"
    assert d(FRAME)[0] is not None
    assert d(FRAME) == (None, None) and d.last_source == "miss"
    c = d.report()["detector_counts"]
    assert c == {"mediapipe": 1, "anime_fallback": 0, "held": 2, "none": 1}


def test_track_lost_when_only_far_face_left(fd):
    d = make_detector(fd, [[(100, 100, 200, 260)], [(900, 100, 200, 260)]], hold=0)
    d(FRAME)
    assert d(FRAME) == (None, None)  # never jumps to another person mid-clip


def test_auto_prefers_anime_when_mediapipe_mouth_is_off(fd):
    # same face from both models, but the anime model puts the mouth much higher than FaceMesh
    d = make_detector(fd, [[(100, 100, 200, 260)]], anime_per_frame=[[(100, 100, 200, 260, 0.62)]], style="auto")
    d(FRAME)
    assert d.last_source == "anime_override"
    assert d.report()["detector_counts"]["anime_fallback"] == 1


def test_auto_keeps_mediapipe_when_they_agree(fd):
    d = make_detector(fd, [[(100, 100, 200, 260)]], anime_per_frame=[[(100, 100, 200, 260, 0.75)]], style="auto")
    d(FRAME)
    assert d.last_source == "mediapipe"


def test_anime_fallback_when_mediapipe_misses(fd):
    d = make_detector(fd, [[]], anime_per_frame=[[(300, 100, 200, 220, 0.78)]], style="auto")
    box, _ = d(FRAME)
    assert box is not None and d.last_source == "anime"


def test_registry_holds_records_not_detectors(fd):
    d = make_detector(fd, [[(100, 100, 200, 260)]])
    d(FRAME)
    assert isinstance(d.rec, fd.Record) and d.rec.report()["frames"] == 1
    assert all(isinstance(r, fd.Record) for r in fd.INSTANCES)
