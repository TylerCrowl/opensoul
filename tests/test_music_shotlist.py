import glob
"""The shot list is cut to the bar lines, fits LTX clip lengths and never drifts off the song."""
import json
from pathlib import Path

from opensoul import storyboard as sb
from opensoul.music import beats as B
from opensoul.music import shotlist as S

ROOT = Path(__file__).resolve().parents[1]


def _bm(bpm=120, lead=0.5, sections=((8, "a"), (8, "b"), (8, "a"))):
    return B.analyze_samples(B.click_track(bpm=bpm, bars=sum(n for n, _ in sections), lead_in_s=lead, sections=list(sections)))


def test_cut_covers_the_song_frame_exact_on_bar_lines():
    bm = _bm()
    cut = S.shot_list(bm)
    assert cut[0].start_frame == 0
    assert sum(c.frames for c in cut) == round(bm.duration_s * S.FPS)
    for a, b in zip(cut, cut[1:]):
        assert a.start_frame + a.frames == b.start_frame
        assert any(abs(b.start_s - t) <= 1 / S.FPS for t in bm.bars) or b.section in ("intro", "outro")
    for c in cut:
        assert c.render_frames >= c.frames and (c.render_frames - 1) % 8 == 0 and c.trim_frames == c.render_frames - c.frames
        assert c.frames / S.FPS <= S.MAX_SHOT_S + S.TOL_S + 1 / S.FPS


def test_loud_sections_cut_faster_than_quiet_ones():
    cut = S.shot_list(_bm())
    by = {}
    for c in cut:
        by.setdefault(c.energy, []).append(c.frames)
    assert sorted(by["high"])[len(by["high"]) // 2] < sorted(by["low"])[len(by["low"]) // 2]  # medians


def test_draft_clips_stay_within_four_seconds_and_fixed_bars_work():
    bm = _bm()
    assert all(c.frames / S.FPS <= S.DRAFT_MAX_S + S.TOL_S + 1 / S.FPS for c in S.shot_list(bm, quality="draft"))
    two = S.shot_list(bm, bars_per_shot=2)
    assert all(c.bars in (2, 0) or c is two[-1] or c is two[0] for c in two)


def test_a_bar_longer_than_a_clip_is_split_on_beats():
    bm = _bm(bpm=60, lead=0.5, sections=((4, "a"),))  # 4 s bars
    cut = S.shot_list(bm, max_shot_s=3.0)
    assert all(c.frames / S.FPS <= 3.0 + S.TOL_S + 1 / S.FPS for c in cut)
    assert sum(c.frames for c in cut) == round(bm.duration_s * S.FPS)


def test_lipsync_follows_the_vocal_regions():
    bm = _bm()
    cut = S.shot_list(bm, vocal_regions=[(17.0, 31.0)])
    sung = [c for c in cut if c.lipsync]
    assert sung and all(c.end_s > 17.0 and c.start_s < 31.0 for c in sung)
    assert not any(c.lipsync for c in S.shot_list(bm))


def test_storyboard_rows_are_valid_shots_with_real_camera_presets():
    cams = {json.loads(p.read_text())["id"] for p in (ROOT / "presets/camera").glob("*.json")}
    assert {c for v in S.CAMERA_BY_ENERGY.values() for c in v} <= cams
    exp = {json.load(open(f)).get("id") for f in glob.glob("presets/camera/*.json") if json.load(open(f)).get("experimental")}
    assert not exp & {c for v in S.CAMERA_BY_ENERGY.values() for c in v}
    cut = S.shot_list(_bm(), vocal_regions=[(10.0, 20.0)])
    rows = S.storyboard_shots(cut, "Kestrel", idea="a rooftop at dusk")
    shots = sb.check_shots(rows)
    assert len(shots) == len(cut) and all(s.characters == ["Kestrel"] for s in shots)
    assert all(s.camera in cams for s in shots)
    assert any(s.lipsync for s in shots) and any(not s.lipsync for s in shots)


def test_ltx_render_frames_rule():
    assert [S.ltx_render_frames(n) for n in (1, 9, 10, 48, 49, 50)] == [9, 9, 17, 49, 49, 57]



def _bm120(bars, lead=0.0, tail=0.0, sections=None):
    return B.analyze_samples(B.click_track(bpm=120, bars=bars, lead_in_s=lead, tail_s=tail, sections=sections))


def test_bar_math_at_120_bpm_whole_bars_and_labels_match():
    bm = _bm120(16)
    assert len(bm.bars) == 16 and bm.bars[0] < 0.05 and abs(bm.duration_s - 32.0) < 0.01
    for q in ("final", "draft"):
        cut = S.shot_list(bm, quality=q)
        assert sum(c.bars for c in cut) == 16
        for c in cut:
            assert abs(c.frames / S.FPS - 2.0 * c.bars) < 0.05 and c.extra_s == 0
            assert c.bars_label == f"{c.bars} bar{'' if c.bars == 1 else 's'}"


def test_no_shot_under_one_bar_pickup_and_tail_join_a_neighbour():
    bm = _bm120(15, lead=0.5, tail=0.5)  # 0.5 s pickup + 15 bars + 0.5 s tail
    assert len(bm.bars) == 15  # the tail is not a bar
    for q in ("final", "draft"):
        cut = S.shot_list(bm, quality=q)
        assert all(c.frames / S.FPS >= 2.0 - 0.05 for c in cut), [c.frames for c in cut]
        assert sum(c.bars for c in cut) == 15 and sum(c.frames for c in cut) == round(bm.duration_s * S.FPS)
        assert cut[0].extra_s == 0.5 and cut[0].bars_label.endswith("+ 0.5 s")
        assert cut[-1].extra_s == 0.5
        assert all(c.frames / S.FPS <= (4.0 if q == "draft" else 8.0) + 0.5 + S.TOL_S for c in cut)


def test_quiet_named_sections_hold_longer_than_the_chorus():
    from opensoul.music.beats import Section

    bm = _bm120(24)
    bm.sections = [Section("A", 0, 8, 0.0, 16.0, 0.9, name="Chorus"), Section("B", 8, 16, 16.0, 32.0, 0.9, name="Bridge"),
                   Section("A", 16, 24, 32.0, 48.0, 0.1, name="Verse")]
    cut = S.shot_list(bm)
    avg = lambda name: sum(c.bars for c in cut if c.section == name) / sum(1 for c in cut if c.section == name)  # noqa: E731
    assert avg("Bridge") > avg("Verse") > avg("Chorus")  # the tag wins over loudness


def test_each_lyric_line_belongs_to_one_shot_and_the_rest_are_cutaways():
    from opensoul.music import lrc as L

    bm = _bm120(8)
    lines = L.parse("[00:01.00]one line across a cut\n[00:05.00]\n[00:09.00]a second line\n[00:11.50]", duration=bm.duration_s)
    cut = S.shot_list(bm, lyrics=lines, bars_per_shot=1)
    owners = [c.index for c in cut for _ in c.lines]
    assert len(owners) == len(set(owners)) == 2 or sorted(i for c in cut for i in c.lines) == [ln.index for ln in lines]
    assert sorted(i for c in cut for i in c.lines) == sorted(ln.index for ln in lines)
    assert [c.lipsync for c in cut].count(True) == 2 and all(c.lipsync == bool(c.lines) for c in cut)


def test_camera_labels_come_from_the_camera_presets():
    labels = {json.load(open(f))["id"]: json.load(open(f))["label"] for f in glob.glob(str(ROOT / "presets/camera/*.json"))}
    cut = S.shot_list(_bm120(16))
    assert all(c.camera_label == labels[c.camera] for c in cut)
    assert S.camera_labels()["fpv"] == "FPV drone"


def test_final_never_takes_a_second_lyric_line_into_a_verse_shot():
    """The preview song's 3-bar verse with two lines: Final cuts it 2 + 1 bars like Draft (it used to sing both in 6 s)."""
    from opensoul.music import lrc as L
    from opensoul.music.beats import Section

    bm = _bm120(7)
    bm.sections = [Section("A", 0, 3, 0.0, 6.0, 0.5, name="Verse"), Section("B", 3, 7, 6.0, 14.0, 0.9, name="Chorus")]
    lines = L.parse("[00:00.30]my kettle hums\n[00:02.55]\n[00:03.30]the toast is cold\n[00:05.55]\n"
                    "[00:06.80]run to the bus\n[00:09.70]\n[00:10.80]nobody waits\n[00:13.70]", duration=bm.duration_s)
    final, draft = (S.shot_list(bm, quality=q, lyrics=lines) for q in ("final", "draft"))
    seg = lambda cut: [(c.start_frame, c.frames, c.lines) for c in cut]  # noqa: E731
    assert seg(final) == seg(draft)
    assert [c.bars for c in final if c.section == "Verse"] == [2, 1]
    assert all(len(c.lines) <= 1 for c in final)
