"""Inner-mouth pass (runners/ls_inner_mouth.py): void / grey-smear detection, source choice, TPS warp, a mask that
never reaches the lips, temporal smoothing, and loud conformance checks. CPU only; synthetic faces and landmarks
(no MediaPipe, no real people)."""
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

RUN = Path(__file__).resolve().parents[1] / "custom_nodes" / "opensoul_nodes" / "runners"


@pytest.fixture(scope="module")
def im():
    spec = importlib.util.spec_from_file_location("ls_inner_mouth_under_test", RUN / "ls_inner_mouth.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def smoother():
    spec = importlib.util.spec_from_file_location("ls_fd_for_inner_mouth_test", RUN / "ls_face_detector.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.smooth_landmarks


SKIN, LIP = (205, 165, 145), (165, 55, 60)
H, W = 160, 200
C = np.array([100.0, 80.0])


def ring(c, a, b, n=20):
    t = np.pi - np.arange(n) * 2 * np.pi / n
    return np.stack([c[0] + a * np.cos(t), c[1] - b * np.sin(t)], 1)


def pts478(im, open_b=10.0, c=C, a_in=30.0, a_out=40.0, b_out=None):
    p = np.tile(c, (478, 1)).astype(np.float64)
    p[im.INNER] = ring(c, a_in, open_b)
    p[im.OUTER] = ring(c, a_out, b_out or open_b + 9)
    p[152] = c + [0, 45]
    return p


def lm_of(im, pts, source="mediapipe"):
    inner, outer = im.lip_rings(pts)
    return {"pts": pts, "inner": inner, "outer": outer, "chin": (pts[17] + pts[152]) / 2, "source": source}


def draw(im, pts, interior):
    """Skin, red lips (outer ring), interior: 'void' | 'grey' | 'teeth' | 'closed'."""
    f = np.zeros((H, W, 3), np.uint8)
    f[:] = SKIN
    cv2.fillPoly(f, [np.round(pts[im.OUTER]).astype(np.int32)], LIP)
    inner = np.round(pts[im.INNER]).astype(np.int32)
    if interior == "void":
        cv2.fillPoly(f, [inner], (4, 3, 3))
    elif interior == "grey":
        cv2.fillPoly(f, [inner], (118, 124, 116))
    elif interior == "teeth":
        cv2.fillPoly(f, [inner], (115, 58, 66))  # lit tongue / mouth with a band of upper teeth
        c = pts[im.INNER].mean(0)
        top = pts[im.INNER][:, 1].min()
        cv2.rectangle(f, (int(c[0] - 22), int(top)), (int(c[0] + 22), int(top + 6)), (240, 238, 230), -1)
        for x in range(int(c[0] - 20), int(c[0] + 21), 8):  # tooth separation
            cv2.line(f, (x, int(top)), (x, int(top + 6)), (190, 185, 180), 1)
    return f


def clip(im, kinds, opens, raw_kinds=None, raw_opens=None):
    syn, raw, sl, rl = [], [], [], []
    for k, o, rk, ro in zip(kinds, opens, raw_kinds or kinds, raw_opens or opens):
        ps, pr = pts478(im, o), pts478(im, ro)
        syn.append(draw(im, ps, k)); raw.append(draw(im, pr, rk))
        sl.append(lm_of(im, ps)); rl.append(lm_of(im, pr))
    return syn, raw, sl, rl


# ------------------------------------------------------------------ geometry
def test_rings_and_openness(im):
    p = pts478(im, 10.0)
    inner, outer = im.lip_rings(p)
    assert inner.shape == outer.shape == (20, 2)
    assert np.allclose(inner[5], p[13]) and np.allclose(inner[15], p[14])
    assert np.allclose(outer[0], p[61]) and np.allclose(outer[10], p[291])
    assert im.openness(p) == pytest.approx(20 / 80)
    assert im.ring_openness(inner, outer) == pytest.approx(im.openness(p))
    assert im.poly_area(ring(C, 30, 10, 200)) == pytest.approx(np.pi * 300, rel=0.01)


def test_inner_mask_is_zero_on_and_outside_the_outline(im):
    inner = ring(C, 30, 12)
    a = im.inner_mask((H, W), inner, 3.0)
    hard = im.fill_mask((H, W), inner) > 0.5
    assert a.max() == pytest.approx(1.0)
    assert (a[~hard] == 0).all()
    assert a[int(C[1]), int(C[0])] == 1.0
    # feather rises inward: values just inside the top edge are partial
    top = int(np.ceil(C[1] - 12)) + 1
    assert 0 < a[top, int(C[0])] < 1


def test_anime_rings_are_plausible(im):
    lmk = np.tile(C, (106, 1))
    lmk[52:72] = ring(C, 40, 15)
    inner, outer = im.anime_rings(lmk)
    assert inner.shape == (20, 2)
    assert np.ptp(inner[:, 1]) < np.ptp(outer[:, 1]) and np.ptp(inner[:, 0]) < np.ptp(outer[:, 0])


# ------------------------------------------------------------------ warps
def test_tps_interpolates_controls_and_affine_is_exact(im):
    rng = np.random.default_rng(0)
    c = rng.uniform(0, 100, (25, 2))
    v = c * 1.3 + [5, -2] + rng.normal(0, 2, c.shape)
    f = im.tps_fit(c, v, reg=1e-8)
    assert np.abs(f(c) - v).max() < 1e-3
    M = np.array([[1.1, 0.2], [-0.1, 0.9]])
    g = im.affine_fit(c, c @ M + [3, 4])
    x = rng.uniform(0, 100, (10, 2))
    assert np.allclose(g(x), x @ M + [3, 4])


def test_warp_patch_maps_donor_interior_onto_target(im):
    cfg = im.Config(src_shrink=1.0)
    donor_pts = pts478(im, 8.0)
    donor = draw(im, donor_pts, "teeth")
    tgt = pts478(im, 14.0, c=C + [6, 3], a_in=34)
    ti, to = im.lip_rings(tgt)
    di, do = im.lip_rings(donor_pts)
    x1, y1 = int(ti[:, 0].min()), int(ti[:, 1].min())
    patch = im.warp_patch(donor, di, do, ti, to, (x1, y1, int(ti[:, 0].max()), int(ti[:, 1].max())), cfg)
    # the donor's bright teeth band lands in the top part of the target opening
    g = cv2.cvtColor(patch, cv2.COLOR_RGB2GRAY)
    assert g[: g.shape[0] // 3].max() > 200
    assert g.mean() < 200


# ------------------------------------------------------------------ classification
@pytest.mark.parametrize("kind,open_b,label", [("void", 10, "void"), ("grey", 10, "smear"), ("teeth", 10, "ok"),
                                               ("closed", 1.0, "closed")])
def test_classify(im, kind, open_b, label):
    cfg = im.Config()
    p = pts478(im, open_b)
    m = im.analyse([draw(im, p, kind)], [lm_of(im, p)], cfg)[0]
    assert im.classify(m, m["open"], cfg)[0] == label


def test_thresholds_are_config(im):
    p = pts478(im, 10)
    fr, lm = draw(im, p, "void"), lm_of(im, p)
    strict = im.Config(open_thr=0.5)
    m = im.analyse([fr], [lm], strict)[0]
    assert im.classify(m, m["open"], strict)[0] == "closed"
    cfg = im.Config(void_frac=1.01)
    m = im.analyse([fr], [lm], cfg)[0]
    assert im.classify(m, m["open"], cfg)[0] != "void"


def test_donor_needs_open_teeth(im):
    cfg = im.Config()
    for kind, o, ok in (("teeth", 10, True), ("void", 10, False), ("closed", 1.0, False)):
        p = pts478(im, o)
        m = im.analyse([draw(im, p, kind)], [lm_of(im, p)], cfg)[0]
        assert im.is_donor(m, m["open"], cfg) is ok
        assert im.is_donor(m, m["open"], cfg, borrow=True) is ok


def test_anime_fallback_frames_are_skipped(im):
    syn, raw, sl, rl = clip(im, ["void"] * 3, [10] * 3, ["teeth"] * 3)
    sl[1] = dict(sl[1], source="anime")
    out, log = im.process(syn, raw, sl, rl, im.Config(temporal_sigma=0))
    assert log["per_frame"][1]["label"] == "anime_fallback" and not log["per_frame"][1]["applied"]
    assert np.array_equal(out[1], syn[1])


# ------------------------------------------------------------------ temporal
def test_runs_and_expand_flags(im):
    assert im.runs([0, 1, 1, 0, 1]) == [(1, 2), (4, 4)]
    cfg = im.Config(close_gaps=1, dilate=1, dilate_open=0.03)
    det = [0, 0, 1, 0, 1, 0, 0, 0, 1, 0]
    op = [0.0, 0.05, .2, .2, .2, .05, 0, 0, .2, 0.0]
    fix = im.expand_flags(det, op, cfg)
    assert list(np.nonzero(fix)[0]) == [1, 2, 3, 4, 5, 8]  # gap at 3 closed; 1 and 5 open -> dilated; 9 closed


def test_strength_curve_full_on_fixed_and_fades(im):
    cfg = im.Config(temporal_sigma=0.8, strength=1.0)
    s = im.strength_curve([0, 0, 0, 1, 1, 0, 0, 0], cfg)
    assert s[3] == s[4] == 1.0
    assert 0 < s[2] < 1 and 0 < s[5] < 1 and s[2] > s[1]
    assert s[7] == 0
    assert (im.strength_curve([0, 1, 0], im.Config(temporal_sigma=0)) == [0, 1, 0]).all()


def test_choose_sources_same_index_hold_or_one_stable_donor(im):
    cfg = im.Config()
    fix = [0, 1, 1, 1, 0, 0, 1, 1, 1, 0, 0, 0]
    same = [0, 1, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0]
    donor = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1]
    src, why = im.choose_sources(fix, same, donor, cfg)
    assert src[1:4] == [1, 3, 3] and why[1] == "same_index" and why[2] == "hold_f3"  # tie -> later frame
    assert src[6:9] == [10, 10, 10] and why[6] == "donor_f10"  # raw closed for the whole run: one donor, never switching
    src, why = im.choose_sources([1, 1, 0], [0, 0, 0], [0, 0, 0], cfg)
    assert src[:2] == [None, None] and why[0] == "no_donor"
    src, why = im.choose_sources([0, 0, 0, 0, 1], [0] * 5, [1, 0, 0, 0, 0], im.Config(donor_max_dist=2))
    assert src[4] is None and why[4].startswith("donor_too_far")


def test_borrowed_donor_needs_centred_visible_teeth(im):
    cfg = im.Config()
    st = {"med": 0.3, "area_px": 500, "grey_frac": 0.6, "dark_frac": 0.2, "grey_cx": 0.02}
    assert im.is_donor(st, 0.2, cfg) and im.is_donor(st, 0.2, cfg, borrow=True)
    assert not im.is_donor(dict(st, grey_cx=0.2), 0.2, cfg, borrow=True)   # teeth only on one side
    assert im.is_donor(dict(st, grey_frac=0.3), 0.2, cfg) and not im.is_donor(dict(st, grey_frac=0.3), 0.2, cfg, borrow=True)
    assert not im.is_donor(st, 0.05, cfg)                                   # closed


def test_smooth_rings(im, smoother):
    lms = [lm_of(im, pts478(im, 10 + (3 if i == 2 else 0))) for i in range(5)] + [None]
    sm = im.smooth_rings(lms, 1.0, smoother)
    assert sm[-1] is None
    assert np.ptp(sm[2]["inner"][:, 1]) < np.ptp(lms[2]["inner"][:, 1])
    assert im.smooth_rings(lms, 0, smoother) is lms


# ------------------------------------------------------------------ end to end
def test_process_fixes_voids_and_never_touches_lips(im):
    kinds = ["closed", "teeth", "void", "void", "void", "teeth", "closed"]
    opens = [1, 10, 12, 12, 12, 10, 1]
    raw_k = ["closed", "teeth", "closed", "closed", "closed", "teeth", "closed"]
    raw_o = [1, 10, 1, 1, 1, 10, 1]
    syn, raw, sl, rl = clip(im, kinds, opens, raw_k, raw_o)
    cfg = im.Config(dilate=0)
    out, log = im.process(syn, raw, sl, rl, cfg)
    assert len(out) == len(syn)
    assert log["detected"] == [2, 3, 4] and log["fixed"] == [2, 3, 4]
    assert {log["per_frame"][i]["source"] for i in (2, 3, 4)} == {5}  # raw closed there: nearest raw with teeth (later on a tie)
    for i in range(len(syn)):
        hard = im.fill_mask(syn[i].shape, sl[i]["inner"]) > 0.5
        assert np.array_equal(out[i][~hard], syn[i][~hard]), f"pixels outside the inner lip changed on f{i}"
    for i in (0, 6):
        assert np.array_equal(out[i], syn[i])
    for i in (2, 3, 4):
        a = log["per_frame"][i]["after"]
        assert a["dark_frac"] < log["per_frame"][i]["synced"]["dark_frac"]
        assert a["bright_frac"] > 0.03
        assert log["per_frame"][i]["after"] and im.classify(a, a["open"], cfg)[0] == "ok"


def test_process_same_index_and_smear(im):
    syn, raw, sl, rl = clip(im, ["teeth", "grey", "grey", "teeth"], [10, 10, 10, 10], ["teeth"] * 4)
    out, log = im.process(syn, raw, sl, rl, im.Config(dilate=0, temporal_sigma=0))
    assert log["fixed"] == [1, 2]
    assert [log["per_frame"][i]["source_why"] for i in (1, 2)] == ["same_index", "same_index"]
    assert all(log["per_frame"][i]["after"]["bright_frac"] > 0.03 for i in (1, 2))
    assert np.array_equal(out[0], syn[0]) and np.array_equal(out[3], syn[3])


def test_force_frames(im):
    syn, raw, sl, rl = clip(im, ["teeth"] * 3, [10] * 3)
    out, log = im.process(syn, raw, sl, rl, im.Config(dilate=0, temporal_sigma=0), force=[1])
    assert log["fixed"] == [1]


def test_process_rejects_length_mismatch(im):
    syn, raw, sl, rl = clip(im, ["void"] * 3, [10] * 3)
    with pytest.raises(im.ConformError):
        im.process(syn, raw[:2], sl, rl[:2])


# ------------------------------------------------------------------ io / conformance (needs ffmpeg)
needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg not installed")


def _make_src(tmp, n=12, fps=24):
    frames = [np.full((64, 96, 3), 20 + 15 * i, np.uint8) for i in range(n)]
    for i, f in enumerate(frames):
        f[5:15, 5 + i:15 + i] = 255
    src = tmp / "src.mp4"
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "96x64", "-r", str(fps),
                          "-i", "-", "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=24000:duration={n / fps}",
                          "-c:v", "libx264", "-crf", "10", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(src)],
                         stdin=subprocess.PIPE)
    for f in frames:
        p.stdin.write(f.tobytes())
    p.stdin.close()
    assert p.wait() == 0
    return src, frames


@needs_ffmpeg
def test_write_and_verify_roundtrip(im, tmp_path):
    src, frames = _make_src(tmp_path)
    dec = im.read_frames(src)
    assert len(dec) == 12
    out = tmp_path / "out.mp4"
    im.write_video(dec, 24, src, out)
    r = im.verify(out, src, 12, 24.0)
    assert r["frames"] == 12 and r["repeated_frames"] == 0 and r["audio_identical_to_input"]


@needs_ffmpeg
def test_verify_fails_loudly(im, tmp_path):
    src, _ = _make_src(tmp_path)
    dec = im.read_frames(src)
    dup = tmp_path / "dup.mp4"
    im.write_video(dec[:5] + [dec[4]] + dec[6:], 24, src, dup)
    with pytest.raises(im.ConformError, match="repeated"):
        im.verify(dup, src, 12, 24.0)
    short = tmp_path / "short.mp4"
    im.write_video(dec[:11], 24, src, short)
    with pytest.raises(im.ConformError, match="frame count"):
        im.verify(short, src, 12, 24.0)
    fast = tmp_path / "fast.mp4"
    im.write_video(dec, 25, src, fast)
    with pytest.raises(im.ConformError, match="fps"):
        im.verify(fast, src, 12, 24.0)


# ------------------------------------------------------------------ cli / hygiene
def test_cli_exposes_every_threshold(im):
    ap = im.build_parser()
    a = ap.parse_args(["s.mp4", "r.mp4", "-o", "o.mp4", "--open-thr", "0.1", "--void-frac", "0.7", "--warp", "affine"])
    assert a.open_thr == 0.1 and a.void_frac == 0.7 and a.warp == "affine"
    opts = {o for act in ap._actions for o in act.option_strings}
    for f in im.dataclasses.fields(im.Config):
        if f.name != "colour_gain_clip":
            assert "--" + f.name.replace("_", "-") in opts
    assert im.parse_frames("20-23,31,33-34") == [20, 21, 22, 23, 31, 33, 34]


def test_no_insightface_and_no_gpu(im):
    src = (RUN / "ls_inner_mouth.py").read_text()
    assert "insightface" not in src.lower().replace("no insightface", "")
    assert "cuda" not in src.replace('"cpu"', "")


@needs_ffmpeg
def test_yuv_delta_keeps_untouched_pixels_exact(im, tmp_path):
    src, _ = _make_src(tmp_path)
    rgb, yuv = im.read_frames(src), im.read_yuv(src)
    assert len(rgb) == len(yuv) == 12
    # our BT.601 limited-range formula matches ffmpeg's own conversion of the same frame
    y = im.rgb_to_yuv(rgb[3])[..., 0]
    assert np.abs(y - yuv[3][0].astype(np.float32)).mean() < 1.0
    assert im.apply_delta_yuv(yuv[3], rgb[3], rgb[3].copy()) is yuv[3]
    edit = rgb[3].copy()
    edit[20:30, 40:60] = (200, 200, 200)
    Y, U, V = im.apply_delta_yuv(yuv[3], rgb[3], edit)
    keep = np.ones(Y.shape, bool)
    keep[20:30, 40:60] = False
    assert np.array_equal(Y[keep], yuv[3][0][keep])           # untouched luma is bit-identical
    assert Y[25, 50] > yuv[3][0][25, 50] + 50                  # the edit landed
    assert np.array_equal(U[:9], yuv[3][1][:9]) and np.array_equal(V[16:], yuv[3][2][16:])
    out = tmp_path / "yuv.mp4"
    im.write_video([im.apply_delta_yuv(yuv[i], rgb[i], edit if i == 3 else rgb[i]) for i in range(12)], 24, src, out)
    assert im.verify(out, src, 12, 24.0)["frames"] == 12


# ------------------------------------------------------------------ mask containment / near-closed skip
def test_inner_mask_erodes_inside_the_own_outline(im):
    inner = ring(C, 30, 12)
    hard = (im.fill_mask((H, W), inner) > 0.5).astype(np.uint8)
    d = cv2.distanceTransform(hard, cv2.DIST_L2, 5)
    a = im.inner_mask((H, W), inner, 3.0, erode_px=2.0)
    assert (a[d <= 2.5] == 0).all()  # nothing within the erode distance of the synced outline
    assert a.max() == pytest.approx(1.0)
    assert (a <= im.inner_mask((H, W), inner, 3.0)).all()


def test_near_closed_frame_is_never_touched_by_dilate_hold_fade_or_force(im):
    # f4 is barely open (openness 0.05: above dilate_open, below open_thr) right after a void run
    kinds = ["teeth", "void", "void", "void", "void", "teeth"]
    opens = [10, 12, 12, 12, 2, 10]
    syn, raw, sl, rl = clip(im, kinds, opens, ["teeth"] * 6, [10] * 6)
    assert im.openness(sl[4]["pts"]) == pytest.approx(0.05)
    for kw, force in (({"dilate": 1}, None), ({"dilate": 1, "close_gaps": 2}, None), ({"dilate": 0}, [4])):
        cfg = im.Config(temporal_sigma=0.8, **kw)
        out, log = im.process(syn, raw, sl, rl, cfg, force=force)
        assert 4 not in log["fixed"] and 4 not in log["applied"]
        assert 4 in log["skipped_below_open"]
        assert np.array_equal(out[4], syn[4]), f"near-closed frame changed ({kw}, force={force})"
        assert {1, 2, 3} <= set(log["fixed"])
        for i in (1, 2, 3):  # and on fixed frames the mask stays strictly inside the frame's own (eroded) outline
            hard = (im.fill_mask(syn[i].shape, sl[i]["inner"]) > 0.5).astype(np.uint8)
            rim = cv2.distanceTransform(hard, cv2.DIST_L2, 5) <= cfg.mask_erode + 0.5
            assert np.array_equal(out[i][rim], syn[i][rim])


# ------------------------------------------------------------------ lip colour / shape flash
def _lip_clip(im, lips, outer_b=None, n=8):
    frames, lms = [], []
    for k in range(n):
        p = pts478(im, 1.0, b_out=(outer_b or {}).get(k, 12.0), a_out=(outer_b or {}).get(("a", k), 40.0))
        f = np.zeros((H, W, 3), np.uint8)
        f[:] = SKIN
        cv2.fillPoly(f, [np.round(p[im.OUTER]).astype(np.int32)], lips.get(k, LIP))
        cv2.polylines(f, [np.round(p[im.INNER]).astype(np.int32)], True, (60, 15, 20), 1)  # dark seam
        frames.append(f)
        lms.append(lm_of(im, p))
    return frames, lms


PALE = (235, 150, 150)


def test_detect_lip_jumps_finds_short_flashes_absent_in_raw(im):
    cfg = im.Config()
    syn, sl = _lip_clip(im, {3: PALE, 4: (200, 105, 105)})
    raw, rl = _lip_clip(im, {})
    sc = [im.lip_colour(f, l) for f, l in zip(syn, sl)]
    rc = [im.lip_colour(f, l) for f, l in zip(raw, rl)]
    j = im.detect_lip_jumps(sc, rc, cfg)
    assert [(x["start"], x["end"]) for x in j] == [(3, 4)]
    assert im.detect_lip_jumps(sc, sc, cfg) == []  # the same flash in raw -> not a sync artefact
    assert im.detect_lip_jumps(rc, rc, cfg) == []  # steady lips
    drift = [np.array([60 + 3 * k, 160, 150.0]) for k in range(8)]  # a slow grade change is not a flash
    assert im.detect_lip_jumps(drift, drift[:1] * 8, cfg) == []
    long_, _ = _lip_clip(im, {k: PALE for k in range(2, 6)})  # longer than lip_max_len -> left alone
    lc = [im.lip_colour(f, l) for f, l in zip(long_, sl)]
    assert im.detect_lip_jumps(lc, rc, cfg) == []


@pytest.mark.parametrize("mode", ["blend", "colour"])
def test_lip_colour_fix_matches_neighbours_and_stays_local(im, mode):
    cfg = im.Config(lip_color_fix=True, lip_fix_mode=mode)
    # f3-4 flash pale and pucker (narrower, taller outer lips)
    syn, sl = _lip_clip(im, {3: PALE, 4: PALE}, {3: 15.0, 4: 15.0, ("a", 3): 34.0, ("a", 4): 34.0})
    raw, rl = _lip_clip(im, {})
    sc = [im.lip_colour(f, l) for f, l in zip(syn, sl)]
    rc = [im.lip_colour(f, l) for f, l in zip(raw, rl)]
    jumps = im.detect_lip_jumps(sc, rc, cfg)
    assert [(x["start"], x["end"]) for x in jumps] == [(3, 4)]
    out, log = im.lip_colour_fix(syn, sl, jumps, cfg)
    assert [e["i"] for e in log] == [3, 4] and all(e["mode"] == mode for e in log)
    ref = im.lip_colour(syn[2], sl[2])
    for i in (3, 4):
        assert np.linalg.norm(im.lip_colour(out[i], sl[i]) - ref) < 0.5 * np.linalg.norm(sc[i] - ref)
        o = np.asarray(sl[i]["outer"])
        far = np.ones((H, W), bool)
        far[int(o[:, 1].min()) - 12:int(o[:, 1].max()) + 12, int(o[:, 0].min()) - 12:int(o[:, 0].max()) + 12] = False
        assert np.array_equal(out[i][far], syn[i][far]), "lip fix leaked away from the mouth"
    for i in (0, 1, 2, 5, 6, 7):
        assert out[i] is syn[i] or np.array_equal(out[i], syn[i])
    if mode == "blend":  # the pucker is replaced by the neighbours' shape: pale pixels gone
        pale = (np.abs(out[3].astype(int) - PALE).sum(-1) < 30).sum()
        assert pale == 0


def test_lip_flags_are_cli_switches(im):
    a = im.build_parser().parse_args(["s.mp4", "r.mp4", "-o", "o.mp4", "--lip-color-fix", "--mask-erode", "1.5"])
    assert a.lip_color_fix is True and a.mask_erode == 1.5
    b = im.build_parser().parse_args(["s.mp4", "r.mp4", "-o", "o.mp4"])
    assert b.lip_color_fix is None  # not given -> the Config default (on) applies
    c = im.build_parser().parse_args(["s.mp4", "r.mp4", "-o", "o.mp4", "--no-lip-color-fix"])
    assert c.lip_color_fix is False


# ------------------------------------------------------------------ defaults = reviewer-approved L1c2
L1C2 = {  # "config" of the reviewer-approved L1c2 validation render (2026-10-19)
    "open_thr": 0.06, "min_area_px": 30, "dark_rel": 0.22, "bright_rel": 0.45, "teeth_rel": 0.85, "void_frac": 0.6,
    "void_teeth_max": 0.03, "grey_rel": 0.3, "smear_area": 0.045, "smear_chroma": 22.0, "smear_vs_lip": -11.5,
    "smear_teeth_max": 0.05, "close_gaps": 1, "dilate": 1, "dilate_open": 0.03, "donor_open": 0.1, "same_grey": 0.2,
    "donor_grey": 0.45, "donor_void_max": 0.7, "donor_balance": 0.05, "donor_max_dist": 0, "warp": "tps",
    "tps_reg": 0.001, "src_shrink": 0.88, "feather": 0.22, "feather_min_px": 1.5, "mask_erode": 1.0, "strength": 1.0,
    "temporal_sigma": 0.8, "lm_sigma": 0.7, "colour": "lab", "colour_gain_clip": (0.8, 1.25), "interior_gain": 1.0,
    "anime_policy": "skip", "lip_color_fix": True, "lip_jump": 10.0, "lip_jump_min": 5.0, "lip_ref_agree": 6.0,
    "lip_raw_max": 2.0, "lip_max_len": 3, "lip_fix_mode": "blend"}


def _cfg_from_cli(im, argv):
    a = im.build_parser().parse_args(["s.mp4", "r.mp4", "-o", "o.mp4"] + argv)
    return a, im.Config(**{f.name: getattr(a, f.name) for f in im.dataclasses.fields(im.Config)
                           if f.name != "colour_gain_clip" and getattr(a, f.name, None) is not None})


def test_defaults_are_the_approved_l1c2_settings(im):
    assert im.Config().to_dict() == L1C2
    a, cfg = _cfg_from_cli(im, [])  # no flags at all
    assert cfg.to_dict() == L1C2 and a.face_style is None  # -> detector default "auto" (lazy anime)
    # the explicit L1c2 command line gives the same config as no flags
    _, explicit = _cfg_from_cli(im, ["--lip-color-fix", "--lip-fix-mode", "blend", "--mask-erode", "1",
                                     "--open-thr", "0.06", "--dilate", "1"])
    assert explicit == cfg
    _, off = _cfg_from_cli(im, ["--no-lip-color-fix"])
    assert off.lip_color_fix is False


# ------------------------------------------------------------------ lazy anime model in face-style auto
class _FakeFD:
    """Stands in for ls_face_detector.FaceDetector: MediaPipe 'misses' the frames whose pixel [0,0,0] == 1."""
    made = []

    def __init__(self, device, task_path=None, style=None, face_box=None, anime=None):
        self.style, self.anime_arg, self.task_path = style, anime, task_path
        self._anime = "UPFRONT" if (style == "anime" and anime is not False) else None
        self.last_source, self._last_ext, self.calls = None, None, []
        _FakeFD.made.append(self)

    def _mp_points(self, rgb, off=(0, 0)):
        return []

    def detect(self, frame):
        self.calls.append((int(frame[0, 0, 0]), self._anime))
        if frame[0, 0, 0] == 1:
            return (np.zeros((106, 2)), "anime", (0, 0, 10, 10)) if self._anime else (None, "miss", None)
        return np.zeros((106, 2)), "mediapipe", (0, 0, 10, 10)

    def _detect_one(self, frame):
        lmk, src, ext = self.detect(frame)
        self.last_source = src
        return (None, None) if lmk is None else ((0, 0, 10, 10), lmk)

    def report(self):
        return {"style": self.style}


class _FakeFDM:
    FaceDetector = _FakeFD
    DEFAULT_TASK = "/nonexistent/face_landmarker.task"

    @staticmethod
    def smooth_landmarks(stacks, sigma):
        return stacks


def _tracker(im, monkeypatch, style, factory_calls):
    monkeypatch.setattr(im, "_load_detector_module", lambda: _FakeFDM)
    monkeypatch.delenv("OPENSOUL_LS_FACE_STYLE", raising=False)
    monkeypatch.delenv("OPENSOUL_LS_ANIME", raising=False)

    def factory():
        factory_calls.append(1)
        return "ANIME"
    tr = im.LipTracker(style=style)
    tr.anime_factory = factory
    return tr


def _frames(misses, n=5):
    fr = [np.zeros((4, 4, 3), np.uint8) for _ in range(n)]
    for i in misses:
        fr[i][0, 0, 0] = 1
    return fr


def test_auto_never_loads_the_anime_model_when_mediapipe_finds_every_face(im, monkeypatch):
    calls = []
    tr = _tracker(im, monkeypatch, None, calls)  # default style = auto
    assert tr.fd.style == "auto" and tr.fd.anime_arg is False and tr.fd._anime is None
    lms = tr.track(_frames([]), sigma=0)
    assert calls == [] and all(l is not None for l in lms)
    assert tr.report()["anime_model"] == "not_needed" and tr.report()["anime_retry_frames"] == 0


def test_auto_loads_the_anime_model_once_and_only_for_mediapipe_misses(im, monkeypatch):
    calls = []
    tr = _tracker(im, monkeypatch, "auto", calls)
    lms = tr.track(_frames([1, 3]), sigma=0)
    assert calls == [1]  # created once, on the first miss
    assert [l["source"] for l in lms] == ["mediapipe", "anime", "mediapipe", "anime", "mediapipe"]
    # MediaPipe hits never see the anime model; misses are retried with it, then it is detached again
    assert [c[1] for c in tr.fd.calls] == [None, None, "ANIME", None, None, "ANIME", None]
    assert tr.fd._anime is None and tr.report()["anime_model"] == "loaded" and tr.report()["anime_retry_frames"] == 2


def test_auto_without_the_anime_package_tries_once(im, monkeypatch):
    calls = []
    tr = _tracker(im, monkeypatch, "auto", calls)
    tr.anime_factory = lambda: calls.append(1)  # returns None: not installed
    lms = tr.track(_frames([1, 3]), sigma=0)
    assert calls == [1] and lms[1] is None and lms[3] is None and tr.report()["anime_model"] == "unavailable"


def test_real_never_and_anime_up_front(im, monkeypatch):
    calls = []
    tr = _tracker(im, monkeypatch, "real", calls)
    tr.track(_frames([1]), sigma=0)
    assert calls == [] and tr.report()["anime_model"] == "off"
    tr = _tracker(im, monkeypatch, "anime", calls)
    assert tr.fd.anime_arg is None and tr.fd._anime == "UPFRONT" and tr.report()["anime_model"] == "loaded"


def test_task_path_falls_back_to_cwd_models(im, monkeypatch, tmp_path):
    monkeypatch.delenv("OPENSOUL_MP_FACE_TASK", raising=False)
    monkeypatch.chdir(tmp_path)
    assert im.resolve_task(None, _FakeFDM) is None
    assert im.resolve_task("x.task", _FakeFDM) == "x.task"
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "face_landmarker.task").write_bytes(b"t")
    assert im.resolve_task(None, _FakeFDM) == str(tmp_path / "models" / "face_landmarker.task")
    monkeypatch.setenv("OPENSOUL_MP_FACE_TASK", "/env.task")
    assert im.resolve_task(None, _FakeFDM) == "/env.task"


# ------------------------------------------------------------------ self donor (pure a2v take: raw = the take itself)
def test_self_donor_fixes_voids_from_the_takes_own_teeth_and_nothing_else(im):
    kinds = ["teeth", "teeth", "void", "void", "teeth", "closed", "teeth", "teeth"]
    opens = [10, 10, 12, 12, 10, 1, 10, 10]
    syn, _, sl, _ = clip(im, kinds, opens)
    cfg = im.Config()
    out, log = im.process(syn, syn, sl, sl, cfg)
    assert {2, 3} <= set(log["fixed"]) and set(log["applied"]) <= {0, 1, 2, 3, 4}
    for i in (2, 3):  # the black slot gets the take's own lit interior
        m = im.fill_mask(syn[i].shape, im.shrink(sl[i]["inner"], 0.6)) > 0.5
        assert out[i][m].mean() > syn[i][m].mean() + 30
    for i in (0, 1, 4):  # lit neighbours touched only by the fade: their own interior onto themselves (near no-op)
        assert np.abs(out[i].astype(int) - syn[i]).mean() < 1.0
    for i in (5, 6, 7):  # closed frame and frames away from the run: untouched
        assert np.array_equal(out[i], syn[i])
    # the lip-flash detector never fires when the donor is the take itself
    sc = [im.lip_colour(f, l) for f, l in zip(syn, sl)]
    assert im.detect_lip_jumps(sc, sc, cfg) == []


def test_self_donor_without_any_lit_frame_changes_nothing(im):
    kinds = ["void"] * 6
    syn, _, sl, _ = clip(im, kinds, [12] * 6)
    out, log = im.process(syn, syn, sl, sl, im.Config())
    assert log["applied"] == [] and all(np.array_equal(o, s) for o, s in zip(out, syn))
