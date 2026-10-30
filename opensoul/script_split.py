"""Start from a script: split a short pasted script into named shots, with suggested cast and camera.

Rule-based and local (no model, no network): the app has no local-LLM hook for text, and this must
never touch a running LLM server. Every result is only a suggestion; the user edits it before the
story is made, and every shot stays editable afterwards.

What it understands (any mix):
- Screenplay sluglines (``INT. STORE - NIGHT``), markdown headings (``## Cold open``),
  ``Scene 3: ...`` / ``Shot 2 - ...`` labels and numbered or bulleted lines each start a shot.
- Otherwise paragraphs (blank-line separated) are shots; a single paragraph is split by sentence.
- Dialogue: ``LUMI: Hi.`` or a screenplay ALL-CAPS name line followed by the line.
- Cast: speakers, plus any character from the user's own library named in the text.
- Camera: plain words ("pull back", "close on", "circles around", "drone") or ``[camera: orbit]``.
"""

from __future__ import annotations

import re

MAX_SHOTS = 40
MAX_CHARS = 20000

# (camera preset id, regex, short reason) - first match wins, so the more specific moves come first.
CAMERA_RULES: list[tuple[str, str, str]] = [
    ("dolly_zoom", r"\b(dolly zoom|vertigo)\b", "dolly zoom"),
    ("crash_zoom", r"\b(crash zoom|snap zoom|whip zoom|zooms? in fast)\b", "crash zoom"),
    ("fpv", r"\b(fpv|drone|flies through|fly-?through|swoops?)\b", "flying camera"),
    ("orbit", r"\b(orbits?|circles? (around|her|him|them)|360)\b", "circles around"),
    ("jib_up", r"\b(crane up|jib up|rises above|rising|lifts? up to|from above|overhead)\b", "rises up"),
    ("jib_down", r"\b(crane down|jib down|descends?|lowers? down)\b", "comes down"),
    # "pull back" only when it is the camera ("She pulls back the curtain" is not a camera move)
    ("dolly_out", r"((camera|we|lens)\s+(slowly\s+)?pull(s|ing)? (back|out)|(^|[.!?]\s+)(slowly\s+)?pull(ing)? (back|out)\b|"
                  r"pull(s|ing)? back to reveal|\bdolly out|\bto reveal|\bwide reveal|camera backs? away)", "pulls back"),
    ("dolly_left", r"\b(tracks? left|truck left|slides? left)\b", "tracks left"),
    ("dolly_right", r"\b(tracks? right|truck right|slides? right|follows? (her|him|them))\b", "tracks along"),
    ("dolly_in", r"\b(push(es|ing)? in|dolly in|camera moves? in|closer and closer)\b", "pushes in"),
    ("push_in_gentle", r"\b(close[- ]?up|close on|tight on|ecu|cu)\b", "close-up"),
    ("static", r"\b(static|locked off|still frame|holds? on|wide shot|establishing)\b", "holds still"),
]

_SLUG = re.compile(r"^\s*(?:\d+\.?\s*)?(INT\.?|EXT\.?|INT\./EXT\.?|I/E\.?)\s+(.+)$", re.I)
_HEAD = re.compile(r"^\s*#{1,6}\s+(.+?)\s*#*\s*$")
_LABEL = re.compile(r"^\s*(?:scene|shot|beat)\s*(\d+)?\s*[:.\-–—]\s*(.*)$", re.I)
_LABEL_ONLY = re.compile(r"^\s*(?:scene|shot|beat)\s+(\d+)\s*$", re.I)
_LIST = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+(.+)$")
_DIALOGUE = re.compile(r"^\s*([A-Z][A-Za-z' .-]{0,30}?)\s*(?:\([^)]*\))?\s*:\s+(.+)$")
_CAPS_NAME = re.compile(r"^\s*([A-Z][A-Z' .-]{1,30}?)\s*(?:\([^)]*\))?\s*$")
_CAM_TAG = re.compile(r"\[\s*(?:camera\s*[:=]\s*)?([a-z _-]+)\]", re.I)
_TITLE = re.compile(r"^\s*(?:#\s+(.+)|title\s*:\s*(.+))$", re.I)
_NOT_NAMES = {"INT", "EXT", "CUT TO", "FADE IN", "FADE OUT", "THE END", "CONTINUED", "SCENE", "SHOT", "NOTE",
              "CAMERA", "TITLE", "V.O", "O.S", "LATER", "MORNING", "NIGHT", "DAY", "SOUND", "MUSIC", "SFX", "VFX",
              "INSERT", "MONTAGE", "ANGLE", "POV", "FPV", "ECU", "CU", "OTS", "CGI", "TV", "OK", "BACK TO", "INTERCUT",
              "SUPER", "CHYRON", "SUBTITLE", "LOCATION", "TIME", "WIDE", "CLOSE", "STATIC", "DRONE", "SLOW MOTION"}
# first words that mean "this is a shot description", not a speaker ("Wide establishing shot: ...")
_SHOT_WORDS = {"wide", "close", "closeup", "close-up", "tight", "static", "establishing", "shot", "camera", "drone", "fpv",
               "angle", "insert", "pov", "note", "sound", "music", "sfx", "title", "later", "cut", "fade", "montage",
               "crane", "dolly", "pan", "tilt", "zoom", "crash", "slow", "overhead", "aerial", "ecu", "cu", "ots", "medium",
               "extreme", "location", "time", "setting", "scene", "beat", "action", "dialogue", "voice", "narrator", "then"}
_TRANSITION = re.compile(r"^\s*(fade in|fade out|fade to black|fade to|cut to|smash cut to|match cut to|dissolve to|"
                         r"cut to black|back to|intercut|the end)\s*[:.]?\s*$", re.I)
_PAREN = re.compile(r"^\s*\([^)]*\)\s*$")
_CAPS_WORD = re.compile(r"(?<![A-Za-z'])([A-Z][A-Z'-]{2,}(?:\s+[A-Z][A-Z'-]{1,})*)(?![a-z])")
_CAM_LEAD = re.compile(r"^(?:the\s+)?camera\s+\w+(?:\s+(?:in|back|out|up|down|away|around|over|along))?"
                       r"(?:\s+(?:on|to|over|around|across|into|through|past|toward|towards))?\s+|"
                       r"^(?:(?:extreme\s+)?close(?:[- ]?up)?|tight|wide(?:\s+shot)?|crash\s+zoom|insert)\s+(?:on|of)\s+", re.I)
_STOP = {"a", "an", "the", "and", "then", "but", "so", "as", "while", "at", "in", "on", "of", "to", "with", "into",
         "down", "up", "out", "over", "from", "for", "by", "her", "his", "their", "its", "camera"}
_PRONOUN = re.compile(r"\b(she|he|they|her|him|his|them|their)\b", re.I)
_INLINE_DIALOGUE = re.compile(r"(?<![A-Za-z])([A-Z][A-Za-z'-]{1,20})(?:\s*\([^)]*\))?:\s+")
# "Sam rolls over", "Biscuit sits": a capitalised word starting a sentence, then a verb in -s, is probably someone
_SUBJECT = re.compile(r"(?:^|(?<=[.!?\"”]\s))([A-Z][a-z]{1,15})\s+(?:[a-z]+s|is|has|was)\b")
_NOT_SUBJECT = {"the", "a", "an", "this", "that", "it", "she", "he", "they", "we", "everyone", "everything", "nobody",
                "nothing", "someone", "something", "rain", "snow", "night", "time", "smoke", "wind", "light", "water",
                "music", "silence", "sound", "fire", "dust", "fog", "mist", "darkness", "day", "dawn", "dusk", "morning",
                "evening", "sunlight", "moonlight", "traffic", "thunder", "lightning", "camera", "there", "here", "who",
                "what", "then", "now", "suddenly", "outside", "inside", "waves", "steam", "sun", "moon", "life", "nature",
                "home", "work", "school", "love", "hope", "fear", "both", "one", "each", "all", "nothing", "noise"}


# OS-050: titles and ranks in front of a name ("Regent Octavia", "Lord Strategist") are not part of a character's name
_TITLES = {"lord", "lady", "regent", "commander", "captain", "general", "sir", "dame", "dr", "doctor", "mr", "mrs", "ms",
           "miss", "king", "queen", "prince", "princess", "strategist", "agent", "officer", "sergeant", "colonel",
           "major", "professor", "the", "old", "young", "little", "big", "uncle", "aunt", "grandma", "grandpa"}
# OS-051: a title or end card is text on screen, nobody is cast from its words
_TEXT_CARD = re.compile(r"\b(title card|end card|text card|title screen|logo|caption|on-?screen text|coming soon|"
                        r"credits|intertitle|super)\b", re.I)


_CARD = re.compile(r"^(\s*(?:\d+[.)]\s*)?)(?:title card|end card|end title|card|super)\s*[:–-]\s*(.+?)\s*$", re.I)
_CARD_TOKEN = "Opensoulcardline"


def _lib_aliases(lib: dict[str, str]) -> dict[str, str]:
    """{first or last name (lower case): library name} for each library character, only for words that point to one
    character ('aldric' -> 'Aldric Vane'). Titles and short words are left out."""
    seen: dict[str, set[str]] = {}
    for full in lib.values():
        for w in full.split():
            w = w.strip(".,'’").lower()
            if len(w) >= 3 and w not in _TITLES and w not in _STOP and w not in lib:
                seen.setdefault(w, set()).add(full)
    return {w: next(iter(f)) for w, f in seen.items() if len(f) == 1}


def _lib_name(name: str, lib: dict[str, str], alias: dict[str, str]) -> str | None:
    """The library character a script name means: the full name, a first or last name, or a name with a title
    ('Regent Octavia'). None when no one (or more than one) matches."""
    low = _clean(name).strip(".").lower()
    if low in lib:
        return lib[low]
    words = [w.strip(".,'’") for w in low.split() if w.strip(".,'’") not in _TITLES]
    hits = {alias[w] for w in words if w in alias}
    return next(iter(hits)) if len(hits) == 1 else None


def _speaker_ok(name: str) -> bool:
    n = _clean(name).strip(".")
    words = n.split()
    if not words or len(words) > 3 or n.upper() in _NOT_NAMES or words[0].lower() in _SHOT_WORDS:
        return False
    return all(w[:1].isupper() for w in words)  # "Old Man: ..." yes; "Wide establishing shot: ..." no


def _inline_dialogue(s: str) -> tuple[str, list[tuple[str, str]]]:
    """'Theo leans in. Juno: You're early. Theo: Always.' -> ('Theo leans in.', [(Juno, ..), (Theo, ..)]).
    CAPS names count anywhere; Mixed-case names only at the start of a sentence."""
    hits = []
    for m in _INLINE_DIALOGUE.finditer(s):
        who = m.group(1)
        before = s[:m.start()].rstrip()
        if not _speaker_ok(who):
            continue
        if who.isupper() or not before or before[-1] in ".!?\"”’)":
            hits.append(m)
    if not hits:
        return s, []
    action = s[:hits[0].start()].strip()
    said = []
    for i, m in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(s)
        words = _clean(s[m.end():end]).strip().strip("\"“”")
        if words:
            said.append((_title_case_name(m.group(1)), words))
    return action, said


_PAREN_WORDS = re.compile(r"\(\s*([^)]*?)\s*\)")


def _line_text(words: str, lead_tag: str = "") -> str:
    """What the TTS reads: friendly sounds -> Orpheus tags ("(sighs)" -> "<sigh>"); other parentheticals
    ("(quietly)") are acting notes, so they're dropped instead of read out; unknown <tags> are removed."""
    from opensoul import orpheus

    t = _clean(f"{lead_tag} {words}").strip("\"“”")
    try:
        t = orpheus.normalize_tags(t)
    except orpheus.TagError:
        t = orpheus._ANGLE.sub(lambda m: m.group(0) if m.group(1).strip().lower() in orpheus.TAGS else " ", t)
        t = orpheus.normalize_tags(t)
    t = _PAREN_WORDS.sub(" ", t)
    t = re.sub(r"\s+([,.!?;:])", r"\1", t)
    return _clean(t).strip("\"“”")


def _paren_tag(s: str) -> str:
    """A lone "(sighs)" line under a screenplay name -> "<sigh>" (else "")."""
    from opensoul import orpheus

    m = _PAREN_WORDS.fullmatch(s.strip())
    tag = orpheus._ALIASES.get((m.group(1) if m else "").strip().lower())
    return f"<{tag}>" if tag else ""


def _line_name(words: str) -> str:
    """Shot name words from a spoken line: up to 4 words before the first pause ("Come on, come on." -> "Come on")."""
    from opensoul import orpheus

    t = re.split(r"[.,!?;:…—–]", orpheus.strip_tags(words) if words else "", maxsplit=1)[0]
    toks = [w.strip("\"'“”()") for w in t.split()][:4]
    return " ".join(w for w in toks if w)


def _clean(s: str) -> str:
    return " ".join(str(s or "").split())


def _camera_ids() -> set[str]:
    try:
        from opensoul.presets import load_presets

        return {c["id"] for c in load_presets()["camera"]}
    except Exception:  # noqa: BLE001  presets missing: suggestions still work, validated later by the API
        return {r[0] for r in CAMERA_RULES}


def suggest_camera(text: str, cameras: set[str] | None = None) -> tuple[str, str]:
    """(camera id, why). Explicit [camera: x] tags win; otherwise plain-word rules; default static."""
    cameras = cameras or _camera_ids()
    for tag in _CAM_TAG.findall(text or ""):
        cid = re.sub(r"[\s-]+", "_", tag.strip().lower())
        if cid in cameras:
            return cid, f"you wrote [{tag.strip()}]"
    low = (text or "").lower()
    for cid, rx, why in CAMERA_RULES:
        if cid in cameras and re.search(rx, low):
            return cid, f"“{why}”"
    return "static", ""


def short_name(text: str, words: int = 4) -> str:
    """A short shot name from a line: the first few meaningful words, sentence case."""
    t = _CAM_TAG.sub("", text or "")
    t = re.sub(r"^[^A-Za-z0-9]+", "", _clean(t))
    head, sep, rest = t.partition(":")
    if sep and rest.strip() and any(w.lower().strip(".,") in _SHOT_WORDS for w in head.split()):
        t = rest.strip()  # "Wide establishing shot: an empty skatepark" -> "an empty skatepark"
    rest = _CAM_LEAD.sub("", t, count=1)
    if rest != t and re.match(r"(?:the|a|an|his|her|their|its)\s", rest, re.I):
        t = rest  # "The camera pulls back on the empty road" -> "the empty road" (but keep "Circles around Lumi")
    t = re.split(r"(?<=[.!?;:])\s|\s[–—-]\s|,|\s(?:as|while|when|because|until|before|after|so that)\s", t)[0] if t else ""
    t = re.sub(r"\b(\d{1,2})\s+(AM|PM|am|pm)\b", "\\1\u00a0\\2", t)  # keep "4 AM" together
    toks = [w.strip(".,;:!?\"'()“”") for w in t.split(" ")]
    toks = [w for w in toks if w]
    while toks and toks[0].lower() in _STOP:
        toks.pop(0)
    out: list[str] = []
    content = 0
    for w in toks:  # up to `words - 1` meaningful words (small words in between are kept), at most 5 words total
        if content >= max(1, words - 1) or len(out) >= 5:
            break
        out.append(w)
        if w.lower() not in _STOP:
            content += 1
    while out and out[-1].lower() in _STOP:
        out.pop()
    name = " ".join(out).replace("\u00a0", " ")
    return (name[:1].upper() + name[1:])[:60] if name else ""


def _title_case_name(n: str) -> str:
    n = _clean(n).strip(".")
    return " ".join(w[:1].upper() + w[1:].lower() if w.isupper() else w for w in n.split())


def _blocks(lines: list[str]) -> list[dict]:
    """Group lines into shot blocks: {"heading": str|None, "lines": [...]}"""
    marked = any(_SLUG.match(l) or _HEAD.match(l) or _LABEL.match(l) or _LABEL_ONLY.match(l) for l in lines)
    listed = not marked and sum(1 for l in lines if _LIST.match(l)) >= 2
    blocks: list[dict] = []
    cur: dict | None = None

    def start(heading: str | None):
        nonlocal cur
        cur = {"heading": heading, "lines": []}
        blocks.append(cur)

    for raw in lines:
        line = raw.rstrip()
        if marked:
            m = _SLUG.match(line)
            h = _HEAD.match(line)
            lab = _LABEL.match(line)
            lab_only = _LABEL_ONLY.match(line)
            if m:
                place, when = (re.split(r"\s+[-–—]\s+", m.group(2), maxsplit=1) + [""])[:2]
                start(_title_case_name(place))
                cur["when"] = _title_case_name(when)
                continue
            if h:
                start(_clean(h.group(1)))
                continue
            if lab_only:
                start(None)
                continue
            if lab:
                rest = _clean(lab.group(2))
                start(None)
                if rest:
                    cur["lines"].append(rest)
                continue
            if cur is None:
                if not line.strip():
                    continue
                start(None)
            cur["lines"].append(line)
        elif listed:
            m = _LIST.match(line)
            if m:
                start(None)
                cur["lines"].append(m.group(1))
            elif line.strip() and cur is not None:
                cur["lines"].append(line)
            elif line.strip():
                start(None)
                cur["lines"].append(line)
        else:
            if not line.strip():
                cur = None
                continue
            if cur is None:
                start(None)
            cur["lines"].append(line)
    blocks = [b for b in blocks if any(l.strip() for l in b["lines"]) or b["heading"]]
    # One paragraph of prose: one shot per sentence (or pair of short sentences).
    if not marked and not listed and len(blocks) == 1 and not any(_DIALOGUE.match(l) for l in blocks[0]["lines"]):
        text = _clean(" ".join(blocks[0]["lines"]))
        sents = [s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z\"'])", text) if s.strip()]
        if len(sents) > 1:
            blocks = [{"heading": None, "lines": [s]} for s in sents]
    return blocks


def split_script(text: str, cast: list[str] | None = None) -> dict:
    """Split a pasted script into suggested shots. Nothing is saved here.

    Returns {"title": str, "shots": [{"beat", "prompt", "characters", "camera", "line", "why"}], "notes": [...]}"""
    text = str(text or "")[:MAX_CHARS].replace("\r\n", "\n").replace("\r", "\n")
    cast = [c for c in (cast or []) if _clean(c)]
    cameras = _camera_ids()
    lines = text.split("\n")
    title = ""
    for i, l in enumerate(lines):
        if not l.strip():
            continue
        m = _TITLE.match(l)
        if m and not l.lstrip().startswith("##"):
            title = _clean(m.group(1) or m.group(2))
            lines = lines[:i] + lines[i + 1:]
        break
    # OS-063: "TITLE CARD: The Last Lighthouse / Coming soon" is a card (text drawn with no model), not a line of
    # dialogue. The words are kept aside and the line becomes a token that the shot list then turns into a card.
    card_words: list[str] = []
    for i, l in enumerate(lines):
        m = _CARD.match(l)
        if m:
            card_words.append(m.group(2))
            lines[i] = f"{m.group(1)}{_CARD_TOKEN}{len(card_words) - 1}."
    notes: list[str] = []
    # Pass 1: read every block (action, dialogue, CAPS introductions) so names seen anywhere are known everywhere.
    parsed: list[dict] = []
    known: dict[str, str] = {_clean(c).lower(): _clean(c) for c in cast}
    lib = dict(known)
    alias = _lib_aliases(lib)
    known.update(alias)  # OS-050: 'Aldric' in the script is the library's 'Aldric Vane'

    def lib_or(n: str, default: str) -> str:
        return _lib_name(n, lib, alias) or default
    for b in _blocks(lines):
        action: list[str] = []
        spoken: list[str] = []
        speakers: list[str] = []
        pending_speaker: str | None = None
        pending_tag = ""
        last_said = False

        def say(who: str, words: str) -> None:
            nonlocal pending_tag, last_said
            words = _line_text(words, pending_tag)
            pending_tag = ""
            if not words:
                return
            if last_said and speakers and speakers[-1] == who:  # the same person keeps talking: one line
                spoken[-1] = f"{spoken[-1]} {words}"
            else:
                speakers.append(who)
                spoken.append(f"{who}: {words}")
            last_said = True

        for l in b["lines"]:
            s = _CAM_TAG.sub("", l).strip()
            if not s:
                pending_speaker = None
                continue
            if _TRANSITION.match(s):
                continue
            if _PAREN.match(s):  # (beat), (dry): acting notes under a screenplay name; (sighs) becomes <sigh>
                pending_tag = (pending_tag + " " + _paren_tag(s)).strip()
                continue
            cap = _CAPS_NAME.match(s)
            if cap and len(s) <= 32 and s.upper() == s and any(ch.isalpha() for ch in s) \
                    and _clean(cap.group(1)).strip(".").upper() not in _NOT_NAMES:
                pending_speaker = _title_case_name(cap.group(1))
                continue
            d = _DIALOGUE.match(s)
            if d and _speaker_ok(d.group(1)) and " " in _clean(d.group(1)):  # "Old Man: ..." (one-word names below)
                said = [(_title_case_name(d.group(1)), _clean(d.group(2)).strip("\"“”"))]
                act = ""
            else:
                act, said = _inline_dialogue(s)
            if said:
                if act:
                    action.append(_clean(act))
                    last_said = False
                for who, words in said:
                    say(who, words)
                pending_speaker = None
                continue
            if pending_speaker:
                say(pending_speaker, s)
                continue
            action.append(_clean(s))
            last_said = False
        prose = _clean(" ".join(action))
        if not _clean(" ".join([b["heading"] or "", prose, *spoken])):
            continue
        for sp in speakers:
            known.setdefault(sp.lower(), lib_or(sp, sp))
        card = bool(_TEXT_CARD.search(" ".join([b["heading"] or "", prose])))  # OS-051: words on a card aren't people
        if prose.upper() != prose and not card:  # screenplay habit: a character's first appearance is in CAPS
            for m in _CAPS_WORD.finditer(prose):
                n = _clean(m.group(1))
                if n.upper() not in _NOT_NAMES and not any(w in _NOT_NAMES for w in n.split()) and len(n) <= 30:
                    known.setdefault(n.lower(), lib_or(n, _title_case_name(n)))
        for m in _SUBJECT.finditer(prose if not card else ""):
            n = m.group(1)
            if n.lower() not in _NOT_SUBJECT and n.lower() not in _STOP and n.lower() not in _SHOT_WORDS:
                known.setdefault(n.lower(), lib_or(n, n))
        tags = " ".join(f"[{t}]" for t in _CAM_TAG.findall(" ".join(b["lines"])))
        if len(spoken) > 1:  # one spoken line per shot, so every line has exactly one speaker
            for i, (who, said_line) in enumerate(zip(speakers, spoken)):
                parsed.append({"b": b, "prose": prose, "spoken": [said_line], "speakers": [who], "tags": tags,
                               "turn": i + 1, "all_spoken": spoken, "all_speakers": speakers})
        else:
            parsed.append({"b": b, "prose": prose, "spoken": spoken, "speakers": speakers, "tags": tags})

    # Pass 2: build the shots.
    shots: list[dict] = []
    used: dict[str, int] = {}
    for p in parsed:
        b, prose, spoken = p["b"], p["prose"], p["spoken"]
        whole = " ".join([b["heading"] or "", prose, *p.get("all_spoken", spoken)])
        # The cast is the speakers plus anyone named in the action / heading. A name inside a spoken line is not in
        # the picture (OS-051: "Aldric, they're everywhere!" does not cast Aldric).
        cast_text = " ".join([b["heading"] or "", prose])
        found: dict[str, int] = {}
        for low, n in known.items():
            flags = re.I if low in lib else 0  # your own characters: any case; names found in the script: as written
            if low in alias:  # a first or last name of a library character, written with a capital
                pat = re.escape(low.capitalize())
            else:
                pat = re.escape(n) if not flags else re.escape(low)
            hits = [re.search(rf"(?<![A-Za-z]){pat}(?![A-Za-z])", cast_text, flags)]
            if not flags:
                hits.append(re.search(rf"(?<![A-Za-z]){re.escape((low if low in alias else n).upper())}(?![A-Za-z])",
                                      cast_text))
            hits = [h.start() for h in hits if h]
            if hits:
                found[n] = min(hits + [found.get(n, len(whole) + 1)])
        for sp in p["speakers"] if p.get("turn") else p.get("all_speakers", p["speakers"]):
            n = known.get(sp.lower(), sp)
            if p.get("turn"):
                found[n] = -1  # a turn's speaker leads its cast
            else:
                found.setdefault(n, len(whole))
        names = sorted(found, key=lambda n: found[n])
        carried = False
        if not names and shots and shots[-1]["characters"] and _PRONOUN.search(whole):
            names = list(shots[-1]["characters"])  # "She sprints..." carries on with the previous shot's cast
            carried = True
        cam, why = suggest_camera(f"{p['tags']} {whole}", cameras)
        first_words = spoken[0].split(": ", 1)[-1] if spoken else ""
        who0 = known.get(p["speakers"][0].lower(), p["speakers"][0]) if p["speakers"] and spoken else ""
        if who0 and (p.get("turn") or (not b["heading"] and not prose)):
            # a dialogue shot: "Kai – Come on" (or "Bus Stop – Kai" under a heading), never just the first word
            beat = f"{b['heading']} – {who0}" if b["heading"] else f"{who0} – {_line_name(first_words) or 'line'}"
        else:
            beat = b["heading"] or short_name(prose or first_words) or f"Shot {len(shots) + 1}"
        key = beat.lower()
        if key in used:  # two scenes in the same place: "Kitchen", then "Kitchen, Morning"
            used[key] += 1
            when = b.get("when") or ""
            beat = f"{beat}, {when}" if when and f"{beat}, {when}".lower() not in used else f"{beat} {used[key]}"
        used.setdefault(beat.lower(), 1)
        # OS-052: the spoken line stays in What they say. What happens never carries the quoted words (the start
        # frame drew them as garbled text on screens).
        prompt = _CAM_TAG.sub("", prose).strip() or (b["heading"] or "")
        if not prompt and who0:
            prompt = f"{who0} talks."
        shots.append({"beat": beat[:120], "prompt": _clean(prompt)[:2000], "characters": names,
                      "camera": cam, "line": " ".join(x.split(": ", 1)[1] for x in spoken)[:500],
                      "speaker": who0,
                      "why": {"camera": why, "characters": ("same as the shot before" if carried else "named in this part") if names else ""}})
        if len(shots) >= MAX_SHOTS:
            notes.append(f"Only the first {MAX_SHOTS} shots were kept. Split longer scripts into two stories.")
            break
    out = []
    for sh in shots:  # OS-063: a card line becomes its own card shot, after what came before it in the block
        found = [int(x) for x in re.findall(rf"{_CARD_TOKEN}(\d+)", sh["prompt"] + " " + sh["beat"])]
        found = [x for x in dict.fromkeys(found) if x < len(card_words)]
        if found:
            rest = _clean(re.sub(rf"\s*{_CARD_TOKEN}\d+\.?", "", sh["prompt"]))
            if rest or sh.get("line"):
                sh["prompt"] = rest
                if _CARD_TOKEN in sh["beat"]:
                    sh["beat"] = short_name(rest or sh.get("line") or "") or "Shot"
                out.append(sh)
            for k in found:
                words = [x.strip(" \"“”'") for x in re.split(r"\s+[/|]\s+|\s+[–—]\s+", card_words[k], maxsplit=1)]
                out.append({"beat": "End card" if re.search(r"coming soon|the end", card_words[k], re.I) else "Title card",
                            "prompt": "", "characters": [], "camera": "static", "line": "", "speaker": "",
                            "why": {"camera": "", "characters": ""}, "kind": "card", "card_title": words[0][:80],
                            "card_sub": (words[1] if len(words) > 1 else "")[:160]})
        else:
            out.append(sh)
    shots = out[:MAX_SHOTS]
    if not shots:
        notes.append("Couldn't find any shots. Put each shot on its own line or paragraph.")
    return {"title": title, "shots": shots, "notes": notes}
