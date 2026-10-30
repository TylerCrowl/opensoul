"""Per-character voice picks (built-in Orpheus voices), saved as one small JSON file in the app's data folder.

One voice per character name (case-insensitive), so a character keeps the same voice in every shot and story.
Lumi / Mio / Ren default to the voices we picked on Oct 18 2026 (tara / leah / zac); Pixel gets jess, so no
example character shares Lumi's voice."""

from __future__ import annotations

import json
import re
from pathlib import Path

from opensoul.orpheus import DEFAULT_VOICE, check_voice

DEFAULTS = {"lumi": "tara", "mio": "leah", "ren": "zac", "pixel": "jess"}  # Pixel (the robot example) has its own voice
FILENAME = "character_voices.json"


def _key(name: str) -> str:
    return " ".join(str(name or "").split()).lower()


def load(data_dir: str | Path) -> dict[str, str]:
    p = Path(data_dir) / FILENAME
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {_key(k): v for k, v in raw.items() if isinstance(v, str)} if isinstance(raw, dict) else {}


def voice_for(data_dir: str | Path, name: str) -> str:
    k = _key(name)
    return load(data_dir).get(k) or DEFAULTS.get(k) or DEFAULT_VOICE


def set_voice(data_dir: str | Path, name: str, voice: str) -> str:
    k = _key(name)
    if not k:
        raise ValueError("Give the character a name.")
    v = check_voice(voice)
    cur = load(data_dir)
    cur[k] = v
    p = Path(data_dir) / FILENAME
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(dict(sorted(cur.items())), indent=2), encoding="utf-8")
    tmp.replace(p)
    return v


def voice_for_shot(data_dir: str | Path, speaker: str = "", override: str | None = None) -> tuple[str, str]:
    """The one voice resolver (Create's quick shot and every Storyboard shot use it): (voice id, where it came from).

    "shot" = this shot's own pick (the Advanced override), "character" = the speaker's saved voice (the default),
    "default" = nobody speaks, so the app's default voice."""
    if override:
        return override, "shot"  # checked when it was saved (and Create's engines have their own voice ids)
    who = " ".join(str(speaker or "").split())
    if who:
        return voice_for(data_dir, who), "character"
    return DEFAULT_VOICE, "default"


_FEMALE = re.compile(r"\b(she|her|hers|herself|woman|women|girl|girls|female|lady|queen|princess|"
                     r"mother|sister|daughter|wife|actress|heroine|empress|duchess|madam|mrs|ms)\b", re.I)
_MALE = re.compile(r"\b(he|him|his|himself|man|men|boy|boys|male|gentleman|king|prince|father|brother|son|husband|"
                   r"actor|hero|emperor|duke|sir|mr|lord)\b", re.I)


def gender_of(pronoun: str = "", text: str = "") -> str:
    """OS-048: 'female', 'male' or '' from a pronoun ('she', 'he/him') or, when the pronoun says nothing, the look
    words ('a tall lean adult man', 'a young woman'). More hits of one kind win; a tie is ''."""
    p = str(pronoun or "").strip().lower().split("/")[0]
    if p == "she":
        return "female"
    if p == "he":
        return "male"
    f, m = len(_FEMALE.findall(text or "")), len(_MALE.findall(text or ""))
    return "female" if f > m else "male" if m > f else ""


def voice_gender(voice: str) -> str:
    try:
        rows = json.loads((Path(__file__).resolve().parents[1] / "presets" / "voices.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return next((r.get("gender", "") for r in rows if r.get("id") == voice), "")


def free_voice(data_dir: str | Path, name: str = "", gender: str = "", available: set[str] | None = None) -> str:
    """A voice no other character uses yet (never Lumi's 'tara' for a new character); when every voice is taken,
    the one used least. ``gender`` ('female' / 'male', OS-048): only voices of that gender, unless none is left.
    ``available``: only these voice ids (the ones the studio has, OS-055), unless none is left."""
    from opensoul.orpheus import VOICE_IDS

    k = _key(name)
    used = [v for n, v in {**DEFAULTS, **load(data_dir)}.items() if n != k]
    pool = [v for v in VOICE_IDS if v != DEFAULTS["lumi"]]
    if available is not None:
        pool = [v for v in pool if v in available] or pool
    if gender:
        pool = [v for v in pool if voice_gender(v) == gender] or pool
    free = [v for v in pool if v not in used]
    if free:
        return free[0]
    return min(pool, key=lambda v: (used.count(v), pool.index(v)))


def ensure_voice(data_dir: str | Path, name: str, *, pronoun: str = "", text: str = "",
                 available: set[str] | None = None) -> str:
    """A new character's voice: keeps a saved or built-in pick, else saves a free one (so it never shares by accident)
    of the character's gender (from ``pronoun`` or the look words in ``text``, OS-048)."""
    k = _key(name)
    if not k:
        return DEFAULT_VOICE
    have = load(data_dir).get(k) or DEFAULTS.get(k)
    return have or set_voice(data_dir, name, free_voice(data_dir, name, gender_of(pronoun, text), available))
