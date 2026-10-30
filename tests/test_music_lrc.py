"""LRC lyric timestamps time the shot list and the lip-sync windows (synthetic LRC, original words)."""
from opensoul.music import beats as B
from opensoul.music import lrc as L
from opensoul.music import shotlist as S
from opensoul.music import song as SONG

SAMPLE = """[ti:Late for the Bus]
[ar:OpenSoul test]
[00:01.00]My kettle hums a morning tune
[00:04.50]
[00:05.00]The toast is cold
[00:09.00][00:25.00]RUN RUN RUN to the bus
[00:12.00]
[Chorus]
not a timed line
"""


def test_parse_handles_metadata_gaps_and_repeated_stamps():
    lines = L.parse(SAMPLE, duration=30.0)
    assert [(ln.start, ln.end, ln.text) for ln in lines] == [
        (1.0, 4.5, "My kettle hums a morning tune"), (5.0, 9.0, "The toast is cold"),
        (9.0, 12.0, "RUN RUN RUN to the bus"), (25.0, 30.0, "RUN RUN RUN to the bus")]
    assert [ln.index for ln in lines] == [0, 1, 2, 3]
    assert L.windows(lines) == [(1.0, 4.5), (5.0, 12.0), (25.0, 30.0)]


def test_write_and_parse_round_trip():
    rows = [(0.94, 4.21, "one"), (5.3, 8.57, "two"), (8.57, 10.0, "three")]
    back = L.parse(L.write(rows))
    assert [(ln.start, ln.end, ln.text) for ln in back] == rows


def test_shot_list_uses_lrc_for_lipsync_and_avoids_cutting_lines():
    y = B.click_track(bpm=120, bars=16, lead_in_s=0.5, sections=[(8, "a"), (8, "b")])
    bm = B.analyze_samples(y)
    lrc_text = "[00:02.80]first line here\n[00:05.20]\n[00:18.60]second line\n[00:21.40]\n"
    lines = L.parse(lrc_text, duration=bm.duration_s)
    cut = S.shot_list(bm, lyrics=lines)
    for c in cut[:-1]:
        assert not L.inside_line(c.end_s, lines), c.end_s  # no cut through a sung line
    sung = [c for c in cut if c.lipsync]
    assert {c.lyric for c in sung} == {"first line here", "second line"}
    first = next(c for c in sung if c.lyric == "first line here")
    w = first.sing_windows[0]
    assert abs(first.start_s + w[0] - 2.8) < 0.01 and abs(first.start_s + w[1] - 5.2) < 0.01
    assert all(not c.lipsync for c in cut if not c.lines)


def test_sections_take_their_names_from_the_lyric_tags(tmp_path):
    lyr = "[Verse]\nMy kettle hums a morning tune\nThe toast is cold, the cat is soon\n[Chorus]\nRUN RUN RUN to the bus\nNobody waits for us"
    r = SONG.placeholder_song(tmp_path, lyrics=lyr, style="110 BPM", seconds=24)
    bm = B.analyze(r["song"])
    lines = L.parse(r["lrc"].read_text(), duration=bm.duration_s)
    assert len(lines) == 4
    L.name_sections(bm.sections, SONG.parse_lyrics(lyr), lines)
    names = [s.name for s in bm.sections]
    assert names[0] == "Verse" and "Chorus" in names


def test_known_lyric_parts_set_the_sections(tmp_path):
    lyr = ("[Verse]\nMy kettle hums a morning tune\nThe toast is cold, the cat is soon\n[Chorus]\nRUN RUN RUN to the bus\n"
           "Nobody waits for us\n[Bridge]\nOne more stop, one more song\n[Chorus]\nRUN RUN RUN to the bus")
    r = SONG.placeholder_song(tmp_path, lyrics=lyr, style="120 BPM", seconds=30)
    bm = B.analyze(r["song"])
    lines = L.parse(r["lrc"].read_text(), duration=bm.duration_s)
    secs = L.sections_from_lyrics(bm, SONG.parse_lyrics(lyr), lines)
    assert [s.name for s in secs] == ["Verse", "Chorus", "Bridge", "Chorus"]
    assert [s.label for s in secs] == ["A", "B", "C", "B"] and secs[0].start_bar == 0
    assert all(a.end_bar == b.start_bar for a, b in zip(secs, secs[1:])) and secs[-1].end_bar == len(bm.bar_bounds())
    for s in secs[1:]:  # each part starts on the bar where its first line is sung
        first = next(ln for ln in lines if ln.start >= s.start_s - 0.3)
        assert first.start - s.start_s < 60 / bm.tempo_bpm * 4
