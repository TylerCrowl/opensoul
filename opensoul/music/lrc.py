"""LRC lyric timestamps -> lyric lines with start/end -> shot timing and lip-sync windows.

ACE-Step 1.5's LM can write LRC lyric timestamps for the song it makes (see docs/MUSIC.md);
the preview song writes a matching LRC too. Format: ``[mm:ss.xx]text``, several stamps per line allowed,
``[ar:...]``-style metadata and section tag lines (``[Chorus]``) ignored. A line lasts until the next line starts
(capped at ``max_line_s``); an empty timed line ends the one before it (an instrumental gap).
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

STAMP = re.compile(r"\[(\d{1,3}):(\d{1,2}(?:[.:]\d{1,3})?)\]")
META = re.compile(r"^\[[a-zA-Z]+:.*\]$")


@dataclass
class LyricLine:
    index: int
    start: float
    end: float
    text: str

    def to_dict(self) -> dict:
        return asdict(self)


def _secs(m: re.Match) -> float:
    return int(m.group(1)) * 60 + float(m.group(2).replace(":", "."))


def parse(text: str, *, duration: float | None = None, max_line_s: float = 8.0) -> list[LyricLine]:
    stamps: list[tuple[float, str]] = []
    for raw in (text or "").replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line or (META.match(line) and not STAMP.match(line)):
            continue
        found = list(STAMP.finditer(line))
        if not found or found[0].start() != 0:
            continue
        words = " ".join(STAMP.sub("", line).split())
        for m in found:
            stamps.append((_secs(m), words))
    stamps.sort(key=lambda x: x[0])
    out: list[LyricLine] = []
    for k, (t, words) in enumerate(stamps):
        nxt = stamps[k + 1][0] if k + 1 < len(stamps) else (duration if duration is not None else t + max_line_s)
        if not words:
            continue  # an empty stamp only ends the previous line
        end = min(nxt, t + max_line_s)
        if duration is not None:
            end = min(end, duration)
        if end > t:
            out.append(LyricLine(index=len(out), start=round(t, 3), end=round(end, 3), text=words))
    return out


def fmt(t: float) -> str:
    m, s = divmod(max(0.0, t), 60)
    return f"[{int(m):02d}:{s:05.2f}]"


def write(lines: list[tuple[float, float, str]]) -> str:
    """LRC text for (start, end, text) lines; an empty stamp marks each gap after a line."""
    rows = []
    for k, (a, b, words) in enumerate(lines):
        rows.append(f"{fmt(a)}{words}")
        nxt = lines[k + 1][0] if k + 1 < len(lines) else None
        if nxt is None or nxt - b > 0.05:
            rows.append(fmt(b))
    return "\n".join(rows) + "\n"


def windows(lines: list[LyricLine]) -> list[tuple[float, float]]:
    """Sung regions for the shot list's lip-sync flag (adjacent lines merged)."""
    out: list[list[float]] = []
    for ln in lines:
        if out and ln.start - out[-1][1] <= 0.05:
            out[-1][1] = max(out[-1][1], ln.end)
        else:
            out.append([ln.start, ln.end])
    return [(a, b) for a, b in out]


def inside_line(t: float, lines: list[LyricLine], margin: float = 0.25) -> bool:
    """True if a cut at ``t`` would split a sung line (more than ``margin`` from both of its ends)."""
    return any(ln.start + margin < t < ln.end - margin for ln in lines)


def lines_in(start: float, end: float, lines: list[LyricLine]) -> list[LyricLine]:
    return [ln for ln in lines if ln.end > start and ln.start < end]


def name_sections(sections: list, lyric_sections: list[dict], lines: list[LyricLine]) -> list:
    """Give beat-map sections the lyric tag sung in most of them (lyrics parsed by opensoul.music.song.parse_lyrics;
    LRC lines in the same order as the lyric lines). Sections with no sung line keep their letter."""
    tags: list[str] = []
    for sec in lyric_sections:
        tags += [sec["tag"]] * len(sec["lines"])
    for s in sections:
        votes: dict[str, float] = {}
        for ln in lines:
            if ln.index < len(tags):
                ov = min(s.end_s, ln.end) - max(s.start_s, ln.start)
                if ov > 0:
                    votes[tags[ln.index]] = votes.get(tags[ln.index], 0.0) + ov
        if votes:
            s.name = max(votes, key=votes.get).title()
    return sections


def sections_from_lyrics(bm, lyric_sections: list[dict], lines: list[LyricLine]) -> list:
    """Sections cut where the lyric tag changes (first line of each part, snapped back to its bar line), named by the
    tag; parts with the same tag share a letter. Energy comes from the overlapping sound-based sections. Use when the
    line times are real (model or preview LRC), not estimated. Returns [] when there's nothing to go on."""
    from opensoul.music.beats import Section

    tags: list[str] = []
    for sec in lyric_sections:
        tags += [sec["tag"]] * len(sec["lines"])
    bounds = bm.bar_bounds()
    if not bounds or not lines or len(tags) < len(lines):
        return []
    half = 30.0 / bm.tempo_bpm  # half a beat

    def bar_at(t: float) -> int:
        return max([i for i, (s, _) in enumerate(bounds) if s <= t + half] or [0])

    starts: list[tuple[int, str]] = []
    for ln in lines:
        tag = tags[ln.index]
        if not starts or tag != starts[-1][1]:
            b = 0 if not starts else bar_at(ln.start)
            if starts and b <= starts[-1][0]:
                starts[-1] = (starts[-1][0], starts[-1][1])  # too close: keep the earlier part
                continue
            starts.append((b, tag))
    letters: dict[str, str] = {}
    out = []
    for k, (b, tag) in enumerate(starts):
        e = starts[k + 1][0] if k + 1 < len(starts) else len(bounds)
        s_s, e_s = bounds[b][0], bounds[e - 1][1]
        ov = [(min(e_s, x.end_s) - max(s_s, x.start_s), x.energy) for x in bm.sections]
        w = sum(o for o, _ in ov if o > 0)
        energy = sum(o * en for o, en in ov if o > 0) / w if w else 0.5
        letters.setdefault(tag, chr(ord("A") + len(letters)))
        out.append(Section(label=letters[tag], start_bar=b, end_bar=e, start_s=round(s_s, 4), end_s=round(e_s, 4),
                           energy=round(energy, 3), name=tag.title()))
    return out
