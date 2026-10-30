"""Text-only master: a character made from words alone (no photo of anyone).

The fields a user fills in (look, outfit, age range, style) become one look lock; the master picture drawn from it
(workflow 07z, Z-Image-Turbo, on the studio computer, or 07t as a fallback; a labelled placeholder in preview mode) becomes the pack's ``refs/ref_00``,
which the character sheet and every angle start from. ``origin_record`` is what pack.json keeps under
``meta.origin`` so the pack says how its look was made."""
from __future__ import annotations

import re

# Adults only. Labels shown in the picker -> words added to the look.
AGE_RANGES = {
    "": "",
    "18-25": "in their early twenties",
    "26-35": "in their late twenties to early thirties",
    "36-50": "in their late thirties to forties",
    "51-65": "in their fifties to early sixties",
    "65+": "in their late sixties or older",
}
# Photo styles add words to the look. Drawn styles (OS-006) add none: opensoul/looks.py swaps the template's style
# sentence and the negative instead, so the subject slot never holds style words.
STYLES = {
    "": "",
    "natural": "natural photo look",
    "cinematic": "cinematic film-still look, soft contrast",
    "editorial": "soft editorial portrait look",
    "anime": "",
    "toon3d": "",
    "illustration": "",
}
DRAWN_STYLES = ("anime", "toon3d", "illustration")
# Look words that name an art style, not the person (OS-006, OS-007): they pick the look and leave the subject slot.
_STYLE_HINTS = (
    ("anime", re.compile(r"\b(anime|manga|cel[- ]?shad\w*|2d (?:cel|anime|animation)|japanese animation)\b", re.I)),
    ("toon3d", re.compile(r"\b(3d (?:cartoon|toon|animated|animation)|pixar[- ]style|cartoon 3d)\b", re.I)),
    ("illustration", re.compile(r"\b(painted illustration|storybook illustration|watercolou?r|gouache|oil painting)\b", re.I)),
)
_STYLE_SEGMENT = re.compile(r"\b(style|styled|anime|manga|cel[- ]?shad\w*|illustration|illustrated|cartoon|toon|"
                            r"line art|2d|3d render|artwork|art)\b", re.I)


def look_of(look: str = "", style: str = "") -> str:
    """The art look for these fields: a drawn style picked in the menu, else one named in the Look words, else
    'photo'."""
    if style in DRAWN_STYLES:
        return style
    for lid, rx in _STYLE_HINTS:
        if rx.search(look or ""):
            return lid
    return "photo"


def strip_style_words(look: str) -> str:
    """The look without the segments that only name an art style ('anime style, 2D cel-shaded anime illustration,
    a cheerful woman' -> 'a cheerful woman')."""
    segs = [s.strip() for s in re.split(r"[,.;]", look or "") if s.strip()]
    keep = [s for s in segs if not (_STYLE_SEGMENT.search(s) and len(s.split()) <= 6 and not re.search(
        r"\b(woman|man|girl|boy|person|robot|she|he|they|hair|eyes)\b", s, re.I))]
    return ", ".join(keep) if keep else (look or "")
WORKFLOW = "workflows/07t_character_from_text_api.json"
MIN_LOOK = 8
MAX_FIELD = 400


def _clean(s: str | None, n: int = MAX_FIELD) -> str:
    return " ".join(str(s or "").split())[:n].strip(" ,.")


def fields(look: str = "", outfit: str = "", age: str = "", style: str = "") -> dict:
    """Cleaned fields; unknown age or style values are dropped (never passed to the model)."""
    return {"look": _clean(look), "outfit": _clean(outfit), "age": age if age in AGE_RANGES else "",
            "style": style if style in STYLES else ""}


def compose(look: str = "", outfit: str = "", age: str = "", style: str = "") -> str:
    """One look lock from the fields, e.g. 'a tall courier with copper hair, in their late twenties to early
    thirties, wearing a teal raincoat, natural photo look'. Same rule as app.js composeLook()."""
    f = fields(look, outfit, age, style)
    parts = [f["look"], AGE_RANGES[f["age"]], f"wearing {f['outfit']}" if f["outfit"] else "", STYLES[f["style"]]]
    return re.sub(r"\s{2,}", " ", ", ".join(p for p in parts if p))


# ---- the 07z master prompt (Z-Image-Turbo runs at cfg 1, so the negative prompt does nothing: the positive prompt
# alone has to carry identity, wardrobe and what must be visible) ----
EAR = re.compile(r"\b(?:ears?|earrings?|earlobes?|elf|elves|elven|elfin)\b", re.I)
# hair long enough to cover the ears unless it's tied back
LONG_HAIR = re.compile(r"\b(?:braid(?:s|ed)?|plait(?:s|ed)?|pony-?tails?|buns?|chignon|dreadlocks|long(?:\s+[\w-]+){0,3}?\s+(?:hair|locks|mane))\b", re.I)
# a teeth trait (gap, braces, fangs, bite): the master shows it with lips slightly parted. Lip / mouth words alone
# (a scar on the lip, full lips) stay in the description and keep the plain neutral face.
MOUTH = re.compile(r"\b(?:teeth|tooth|toothed|gap-toothed|braces|fangs?|overbite|underbite)\b", re.I)
# No smile in any master: a grin reads wrong in every later shot of the film. At cfg 1 even "no smile" primes one, so
# no master prompt holds the words smile, grin or smirk at all. A teeth trait stays in the description only.
NEUTRAL = "Serious calm face, mouth relaxed and closed at the corners"
TEETH_SHOWN = NEUTRAL + ", lips just slightly apart"
EARS_SEEN = ", both ears clearly visible"  # every master: the template's default {hair}
EARS_TUCKED = (", hair slicked straight back from the forehead and temples, both ears completely exposed{tie}"
               + EARS_SEEN)
# tied-back hair: where it goes once the hair is off the ears
_TIED = re.compile(r"\b(?:braid(?:s|ed)?|plait(?:s|ed)?|pony-?tails?|buns?|chignon)\b", re.I)
_SUBJECT_END = re.compile(r",|\s(?=(?:with|who|whose|has|having)\s)", re.I)
_SEGMENTS = re.compile(r",|;|\s+and\s+|\s+with\s+", re.I)


def _subject(look: str) -> tuple[str, str]:
    """('a tall woman', 'with a long silver-grey braid, ...'): the subject words, then the rest of the look."""
    m = _SUBJECT_END.search(look)
    if not m or m.start() == 0:
        return look, ""
    return look[:m.start()].strip(), look[m.start():].lstrip(" ,").strip()


def mouth_traits(text: str) -> list[str]:
    """The phrases of the spec that describe the teeth, verbatim ('a small gap between her front teeth')."""
    return [seg.strip() for seg in _SEGMENTS.split(text or "") if seg.strip() and MOUTH.search(seg)]


def wants_ears(text: str) -> bool:
    """The spec mentions ears (or an ear trait), or long / braided hair that would cover them."""
    return bool(EAR.search(text or "") or LONG_HAIR.search(text or ""))


# The age words in the character's own pronoun ("in her fifties"), never "their" for a she/he character.
_SHE = re.compile(r"\b(?:she|her|hers|herself|woman|women|girl|lady|female|mother|grandmother|aunt|sister|daughter|wife|queen|actress|waitress)\b", re.I)
_HE = re.compile(r"\b(?:he|him|his|himself|man|men|boy|gentleman|male|father|grandfather|uncle|brother|son|husband|king|actor|waiter)\b", re.I)
_POSSESSIVE = {"she": "her", "he": "his", "they": "their"}


def pronoun_key(pronoun) -> str:
    """'she', 'he' or 'they' from a pack pronoun field ('she', 'He/him', ['they', 'them'], ...); else 'they'."""
    if isinstance(pronoun, (list, tuple)):
        pronoun = pronoun[0] if pronoun else ""
    first = str(pronoun or "").strip().lower().replace(",", "/").split("/")[0].strip()
    return first if first in _POSSESSIVE else "they"


def pronoun_for(f: dict, pronoun=None) -> str:
    """The pack's pronoun when given, else read from the description words (only one of she/he words: that one;
    both or neither: 'they')."""
    if str(pronoun or "").strip():
        return pronoun_key(pronoun)
    text = f"{f.get('look', '')} {f.get('outfit', '')}"
    she, he = bool(_SHE.search(text)), bool(_HE.search(text))
    return "she" if she and not he else "he" if he and not she else "they"


def age_words(age: str, pronoun: str = "they") -> str:
    """AGE_RANGES words in this pronoun: 'in her fifties to early sixties'."""
    return re.sub(r"\btheir\b", _POSSESSIVE[pronoun_key(pronoun)], AGE_RANGES.get(age, ""))


def _tie(text: str, pronoun: str) -> str:
    """', the long silver-grey braid hidden behind her back, not over her shoulder' (a ponytail the same; a bun: 'at the
    back of her head'), from the spec's own words."""
    seg = next((x.strip() for x in _SEGMENTS.split(text or "") if _TIED.search(x)), "")
    word = _TIED.search(seg).group(0).lower() if seg else ""
    if not word:
        return ""
    phrase = seg if len(seg.split()) <= 6 else word
    phrase = re.sub(r"^(?:an?|the|one|her|his|their)\s+", "", phrase, flags=re.I)
    pos = _POSSESSIVE[pronoun_key(pronoun)]
    where = (f"at the back of {pos} head" if re.match(r"buns?|chignon", word)
             else f"hidden behind {pos} back, not over {pos} shoulder")
    return f", the {phrase} {where}"


_GARMENT_END = re.compile(r",|;|\s(?=(?:with|featuring|that|which|open|worn|zipped|buttoned)\s)", re.I)
_LAYER = re.compile(r"\b(over|under|beneath|on top of)\s+((?:an?|the|her|his|their)\s+[^,;]+?)(?=\s+(?:with|and)\s|[,;.]|$)", re.I)


def outfit_short(outfit: str) -> str:
    """The outfit in a few words for the repeat near the end: the main garment as written, plus what it's over
    ('a hip-length mustard-yellow waxed-cotton field jacket over a navy cable-knit sweater'). Never paraphrased: only
    the user's own words, cut at the first detail clause."""
    o = _clean(outfit).rstrip(".")
    m = _GARMENT_END.search(o)
    main = o[:m.start()].strip() if m and m.start() > 0 else o
    if main == o:
        return o
    lay = _LAYER.search(o[len(main):])
    return f"{main} {lay.group(1).lower()} {lay.group(2).strip()}" if lay else main


def wearing_line(outfit: str, pronoun: str) -> str:
    """'She wears a ... jacket over a ... sweater.' (they: 'They wear'), the outfit's one repeat near the end."""
    if not _clean(outfit):
        return ""
    who = {"she": "She wears", "he": "He wears", "they": "They wear"}[pronoun_key(pronoun)]
    return f" {who} {outfit_short(outfit)}."


# ---- no smile words in the master prompt: a smiling master grins in every talking shot (the talk-shot grin check
# rejects it). Stripped before the prompt is built; every other word of the look stays as typed.
SMILE_NOUN = r"(?:smiles?|grins?|smirks?)"
SMILE_ING = r"(?:smiling|grinning|smirking)"
SMILE_ANY = re.compile(rf"\b(?:{SMILE_NOUN}|{SMILE_ING}|smiley)\b", re.I)
_ARTICLE = r"(?:a|an|the|one|her|his|their|its|my|your)"
_STOP = r"(?!(?:a|an|the|one|her|his|their|its|my|your|with|and|who|that|in|of|on|over|under)\b)"
_MOD_C = rf"(?:{_STOP}[\w'-]+,?\s+){{0,4}}?"      # with an article: modifiers may have commas ('a calm, sleepy smile')
_MOD = rf"(?:{_STOP}[\w'-]+\s+){{0,3}}?"          # without one: the words right before it ('big grin')
_CONN = r"(?P<conn>\b(?:with|and)\s+)?"
_NP_ART = re.compile(rf"{_CONN}\b{_ARTICLE}\s+{_MOD_C}{SMILE_NOUN}\b", re.I)
_NP_BARE = re.compile(rf"{_CONN}\b{_MOD}{SMILE_NOUN}\b", re.I)
_VERB = re.compile(r"\b(?:who|that)\s+(?:\w+ly\s+)?(?:smiles|grins|smirks)\b[^,;.]*", re.I)
_ING = re.compile(rf"(?:\b(?:and|is|are)\s+)?\b{SMILE_ING}\b(?:\s+\w+ly\b)?", re.I)
_ADJ = re.compile(r"\bsmiley\b", re.I)


def _tidy(t: str) -> str:
    for _ in range(2):
        t = re.sub(r"\s{2,}", " ", t)
        t = re.sub(r"\s+([,;.])", r"\1", t)
        t = re.sub(r"([,;])(?:\s*[,;])+", r"\1", t)
        t = re.sub(r"\b(?:and|with|in)\s*(?=[,;.]|$)", "", t)      # a connector left hanging
        t = re.sub(r"\bwith\s+and\b", "with", t)
        t = re.sub(r"^\s*(?:and|with)\b", "", t)
    return t.strip(" ,;").lstrip(". ")


def strip_smiles(text: str) -> tuple[str, list[str]]:
    """``text`` without smile / grin / smirk words -> (text, the phrases removed). The whole smile phrase is
    dropped cleanly: 'and a calm, sleepy smile', 'with a smile', 'big grin' (with its own modifiers and article),
    'who smiles a lot', 'grinning widely', 'smiley'; a 'with' stays when the look goes on with 'and ...'; commas are
    tidied. Every other word stays as typed ('laugh lines', 'smoky eyes' are untouched). A text without such words
    comes back unchanged."""
    if not text or not SMILE_ANY.search(text):
        return text, []
    removed: list[str] = []

    def drop(m: re.Match) -> str:
        removed.append(m.group(0).strip())
        conn = (m.groupdict().get("conn") or "").strip().lower()
        if conn == "with" and re.match(r"\s+and\b", m.string[m.end():]):
            return " with "
        return " "

    out = text
    for rx in (_VERB, _NP_ART, _NP_BARE, _ING, _ADJ):
        out = rx.sub(drop, out)
    return _tidy(out), removed


def without_smiles(f: dict) -> tuple[dict, list[str]]:
    """The fields with smile words stripped from the look and the outfit (strip_smiles: no master prompt holds the
    words smile, grin or smirk anywhere), and what was removed (look first, then outfit)."""
    look, removed = strip_smiles(f.get("look", ""))
    outfit, removed_o = strip_smiles(f.get("outfit", ""))
    return {**f, "look": look, "outfit": outfit}, removed + removed_o


def master_parts(f: dict, pronoun=None) -> dict:
    """The pieces of the 07z prompt for these fields (presets/text_master.json "prompt" fills them in).

    description: the subject, then the outfit verbatim right after it (identity-critical wardrobe early), then age,
    the rest of the look and the style (the age in the pack's pronoun, or the one the words use; else 'their').
    outfit_line: the outfit's one repeat, at the end, in a short form of the user's own words ("She wears ...").
    expression: never a smile, and no smile / grin / smirk word at all: 'Serious calm face, mouth relaxed and closed
    at the corners', with a teeth trait '..., lips just slightly apart' (the trait itself stays in the description
    only). hair: ', both ears clearly visible' on every master; when the spec mentions ears or has long, braided, tied
    or bun hair: 'hair slicked straight back from the forehead and temples, both ears completely exposed' (a braid /
    ponytail 'hidden behind her back, not over her shoulder', a bun 'at the back of her head'). Smile / grin / smirk
    words are stripped from the look first (strip_smiles)."""
    f, _smiles = without_smiles(fields(**{k: f.get(k, "") for k in ("look", "outfit", "age", "style")}))
    pro = pronoun_for(f, pronoun)
    look_id = look_of(f["look"], f["style"])
    if look_id != "photo":  # OS-007: style words pick the look; they never become the subject
        f = {**f, "look": strip_style_words(f["look"])}
    subject, rest = _subject(f["look"]) if f["look"] else ("a person", "")
    lead = f"{subject} wearing {f['outfit']}" if f["outfit"] else subject
    description = re.sub(r"\s{2,}", " ", ", ".join(p for p in (lead, age_words(f["age"], pro), rest, STYLES[f["style"]]) if p))
    spec = f"{f['look']}, {f['outfit']}"
    traits = mouth_traits(spec)
    expression = TEETH_SHOWN if traits else NEUTRAL
    hair = EARS_TUCKED.format(tie=_tie(f["look"], pro)) if wants_ears(spec) else EARS_SEEN
    return {"description": description, "outfit_line": wearing_line(f["outfit"], pro), "expression": expression, "hair": hair,
            "look": look_id}


def problem(look: str = "", outfit: str = "") -> str:
    """Why a master can't be drawn yet ("" when it can)."""
    if len(_clean(look)) + len(_clean(outfit)) < MIN_LOOK:
        return "Describe your character in a few words (look, hair, outfit)."
    return ""


def origin_record(prompt: str, seed: int, f: dict, *, preview: bool, master: str = "refs/ref_00.png",
                  workflow: str = WORKFLOW) -> dict:
    return {"kind": "text", "prompt": prompt, "seed": int(seed), "fields": f, "workflow": workflow or WORKFLOW,
            "preview": bool(preview), "master": master, "reference_image": None}
