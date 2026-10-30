"""Orpheus TTS (Canopy Labs, Apache-2.0; Built with Llama) helpers: voices, emotion tags, token maths.

Pure Python, no model imports, so the app, tests and the ComfyUI node all share it. The model itself runs in
its own venv (``custom_nodes/opensoul_nodes/runners/orpheus_tts.py``: llama.cpp GGUF + SNAC 24 kHz decoder).

Emotion tags go inline in a line, where they should happen: ``"Whole milk. <chuckle> Anything hotter..."``.
The line editor also accepts ``[laugh]``, ``(laughs)`` and ``*sighs*``; :func:`normalize_tags` turns those into
Orpheus tags. Other TTS backends and the video prompt get the line with the tags removed (:func:`strip_tags`).
"""

from __future__ import annotations

import re

# Built-in speakers of canopylabs/orpheus-3b-0.1-ft (no cloning, no reference audio).
VOICES: list[dict[str, str]] = [
    {"id": "tara", "label": "Tara", "gender": "female", "blurb": "warm, conversational"},
    {"id": "leah", "label": "Leah", "gender": "female", "blurb": "clear, composed"},
    {"id": "jess", "label": "Jess", "gender": "female", "blurb": "bright, lively"},
    {"id": "mia", "label": "Mia", "gender": "female", "blurb": "soft, young"},
    {"id": "zoe", "label": "Zoe", "gender": "female", "blurb": "breezy"},
    {"id": "zac", "label": "Zac", "gender": "male", "blurb": "boyish, earnest"},
    {"id": "leo", "label": "Leo", "gender": "male", "blurb": "deep, calm"},
    {"id": "dan", "label": "Dan", "gender": "male", "blurb": "easygoing"},
]
VOICE_IDS = tuple(v["id"] for v in VOICES)
DEFAULT_VOICE = "tara"

# Nonverbal / emotion tags the fine-tuned model was trained on.
TAGS = ("laugh", "chuckle", "sigh", "gasp", "cough", "sniffle", "groan", "yawn")

# Friendly spellings people type -> Orpheus tag.
_ALIASES = {
    "laugh": "laugh", "laughs": "laugh", "laughing": "laugh", "giggle": "laugh", "giggles": "laugh",
    "chuckle": "chuckle", "chuckles": "chuckle", "heh": "chuckle",
    "sigh": "sigh", "sighs": "sigh", "exhale": "sigh", "exhales": "sigh",
    "gasp": "gasp", "gasps": "gasp",
    "cough": "cough", "coughs": "cough", "clears throat": "cough",
    "sniffle": "sniffle", "sniffles": "sniffle", "sniff": "sniffle", "sniffs": "sniffle",
    "groan": "groan", "groans": "groan",
    "yawn": "yawn", "yawns": "yawn",
}
_ANGLE = re.compile(r"<\s*([a-zA-Z][a-zA-Z ]*?)\s*>")
_FRIENDLY = re.compile(r"\[\s*([a-zA-Z][a-zA-Z ]*?)\s*\]|\(\s*([a-zA-Z][a-zA-Z ]*?)\s*\)|\*\s*([a-zA-Z][a-zA-Z ]*?)\s*\*")


class TagError(ValueError):
    """A line uses a tag Orpheus doesn't know."""


def normalize_tags(text: str) -> str:
    """``[laughs]`` / ``(sighs)`` / ``*gasp*`` -> ``<laugh>`` / ``<sigh>`` / ``<gasp>``.

    Bracketed words that aren't a known alias (``(quietly)``, ``[beat]``) are left alone: they are direction for
    a person, not a sound. Unknown ``<tags>`` raise :class:`TagError` so a typo never gets read out loud."""
    def friendly(m: re.Match) -> str:
        word = (m.group(1) or m.group(2) or m.group(3) or "").strip().lower()
        tag = _ALIASES.get(word)
        return f"<{tag}>" if tag else m.group(0)

    out = _FRIENDLY.sub(friendly, text or "")
    bad = sorted({m.group(1).strip().lower() for m in _ANGLE.finditer(out)} - set(TAGS) - set(_ALIASES))
    if bad:
        raise TagError(f"Unknown emotion tag{'s' if len(bad) > 1 else ''}: {', '.join('<' + b + '>' for b in bad)}. "
                       f"Use one of: {', '.join('<' + t + '>' for t in TAGS)}.")
    out = _ANGLE.sub(lambda m: f"<{_ALIASES[m.group(1).strip().lower()]}>", out)
    return re.sub(r"\s{2,}", " ", out).strip()


def tags_in(text: str) -> list[str]:
    return [m.group(1) for m in _ANGLE.finditer(normalize_tags(text))]


def strip_tags(text: str) -> str:
    """The words only: for captions, the LTX speech prompt, duration estimates and non-Orpheus backends."""
    out = _ANGLE.sub(" ", normalize_tags(text))
    out = re.sub(r"\s+([,.!?;:])", r"\1", out)
    return re.sub(r"\s{2,}", " ", out).strip()


# Older projects / env defaults name a Kokoro voice; map it to the closest Orpheus speaker (mirrors presets/voices.json).
FROM_KOKORO = {"af_heart": "tara", "bf_emma": "leah", "af_bella": "jess", "af_nicole": "mia", "af_sarah": "zoe",
               "am_puck": "zac", "am_michael": "leo", "am_fenrir": "dan",
               "af_kore": "zoe", "am_adam": "dan"}  # OS-055: Dan and Zoe now use am_adam / af_kore


def resolve_voice(voice: str | None) -> str:
    """An Orpheus voice id for anything a caller passes: an Orpheus id, a known Kokoro id, or nothing (default)."""
    v = (voice or "").strip().lower()
    if v in VOICE_IDS:
        return v
    if v in FROM_KOKORO:
        return FROM_KOKORO[v]
    if not v or v[:3] in {"af_", "am_", "bf_", "bm_"}:
        return DEFAULT_VOICE
    return check_voice(v)


def check_voice(voice: str | None) -> str:
    v = (voice or DEFAULT_VOICE).strip().lower()
    if v not in VOICE_IDS:
        raise ValueError(f"Unknown Orpheus voice {voice!r}. Choose one of: {', '.join(VOICE_IDS)}")
    return v


# ---------------------------------------------------------------- token maths (shared with the runner)
START_HUMAN, END_TEXT, END_HUMAN = 128259, 128009, 128260
START_SPEECH, END_SPEECH = 128257, 128258
AUDIO_OFFSET = 128266          # first <custom_token> id that carries an audio code
CODEBOOK = 4096
SAMPLE_RATE = 24000


def prompt_text(text: str, voice: str) -> str:
    return f"{check_voice(voice)}: {normalize_tags(text)}"


def wrap_prompt(text_ids: list[int]) -> list[int]:
    """[start-of-human] + tokenizer(text incl. BOS) + [end-of-text, end-of-human]."""
    return [START_HUMAN, *text_ids, END_TEXT, END_HUMAN]


def audio_codes(generated: list[int]) -> list[int]:
    """Generated ids -> raw audio codes: keep what follows the last start-of-speech, stop at end-of-speech."""
    ids = list(generated)
    if START_SPEECH in ids:
        ids = ids[len(ids) - ids[::-1].index(START_SPEECH):]
    if END_SPEECH in ids:
        ids = ids[: ids.index(END_SPEECH)]
    codes = [i - AUDIO_OFFSET for i in ids if i >= AUDIO_OFFSET]
    return codes[: len(codes) // 7 * 7]


def snac_layers(codes: list[int]) -> tuple[list[int], list[int], list[int]]:
    """7 codes per 12 ms frame -> the three SNAC codebook layers (1, 2 and 4 codes per frame)."""
    l1: list[int] = []
    l2: list[int] = []
    l3: list[int] = []
    for i in range(len(codes) // 7):
        f = codes[7 * i: 7 * i + 7]
        l1.append(f[0])
        l2 += [f[1] - CODEBOOK, f[4] - 4 * CODEBOOK]
        l3 += [f[2] - 2 * CODEBOOK, f[3] - 3 * CODEBOOK, f[5] - 5 * CODEBOOK, f[6] - 6 * CODEBOOK]
    clamp = lambda xs: [min(max(x, 0), CODEBOOK - 1) for x in xs]  # noqa: E731
    return clamp(l1), clamp(l2), clamp(l3)
