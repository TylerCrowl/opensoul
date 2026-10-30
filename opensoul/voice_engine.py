"""Which voice engine a line is spoken with, and the speaker's own reference clip (docs/VOICE_ENGINE_PROPOSAL.md).

Order for a story's line: ``OPENSOUL_TTS`` (forces one engine everywhere, the rollback switch) > the speaker's pack
pin (``voice.engine``) > the story's ``tts_engine`` > orpheus. A story saved before engines existed has no
``tts_engine``, so it stays on Orpheus with the same voices: nothing switches on its own. New stories take
``OPENSOUL_TTS_DEFAULT`` or ``tts_default_new`` from presets/voice_engine.json (VoxCPM2; rollback
``OPENSOUL_TTS_DEFAULT=orpheus``). VoxCPM2 speaks in the speaker's own clip: when the speaker has no usable clip
(none saved, no consent, missing or changed), :func:`resolve` speaks the line with Orpheus and says why.

Reference clips (cloning engines): the pack's ``voice`` block names ``ref_clip`` (in the pack folder), ``ref_text``,
``ref_sha256``, ``ref_made_with`` (provenance) and ``consent``. A clip without consent, provenance or a matching
sha256 is never used: :class:`VoiceRefError` stops the render with a plain message."""
from __future__ import annotations

import hashlib
import json
import re
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRESET = ROOT / "presets" / "voice_engine.json"
ENGINES = ("orpheus", "kokoro", "chatterbox", "voxcpm2")
CLONING = ("chatterbox", "voxcpm2")  # engines that take a reference clip
FALLBACK = "orpheus"
CONSENT_TEXT = ("This clip is my own voice, a voice I made (for example with a voice-design model), or a voice I "
                "have written permission to use. It is not a real person I am imitating.")


class VoiceRefError(ValueError):
    """The speaker's reference clip can't be used (no consent, no provenance, missing or changed file)."""


def check(name: str | None) -> str:
    e = str(name or "").strip().lower()
    if e not in ENGINES:
        raise ValueError(f"Unknown voice engine {name!r}. Choose one of: {', '.join(ENGINES)}")
    return e


LABELS = {"orpheus": "Orpheus", "kokoro": "Kokoro", "chatterbox": "Chatterbox", "voxcpm2": "VoxCPM2"}


def studio_engines() -> dict[str, bool] | None:
    """{engine: its node is on the studio} in studio mode (opensoul.studio_info), else None (not known)."""
    try:
        from opensoul import studio_info

        return studio_info.tts_engines()
    except Exception:  # noqa: BLE001  never block a story on the check
        return None


def no_clip_fallback(engines: dict[str, bool] | None = None) -> str:
    """The engine for a VoxCPM2 line whose speaker has no usable clip: Orpheus, or Kokoro when the studio has no
    Orpheus node (OS-054)."""
    if engines and not engines.get(NO_CLIP_FALLBACK) and engines.get("kokoro"):
        return "kokoro"
    return NO_CLIP_FALLBACK


def usable(engine: str, engines: dict[str, bool] | None) -> bool:
    """True when the engine can speak on this studio (unknown studio: True). VoxCPM2 also needs its no-clip engine."""
    if engines is None:
        return True
    if not engines.get(engine):
        return False
    return engine != "voxcpm2" or bool(engines.get(no_clip_fallback(engines)))


def default_for_new(engines: dict[str, bool] | None = None) -> str:
    """The engine a NEW story is created with: OPENSOUL_TTS_DEFAULT, else the preset's tts_default_new. In studio
    mode, an engine whose node is not on the studio is skipped for the first one that is (OS-054)."""
    env = os.environ.get("OPENSOUL_TTS_DEFAULT", "").strip()
    if env:
        return check(env)
    try:
        want = check(json.loads(PRESET.read_text(encoding="utf-8")).get("tts_default_new") or FALLBACK)
    except (OSError, ValueError):
        want = FALLBACK
    engines = studio_engines() if engines is None else engines
    if usable(want, engines):
        return want
    return next((e for e in ("kokoro", "orpheus", "chatterbox") if usable(e, engines)), want)


def available_voice_ids(data_dir=None) -> set[str] | None:
    """OS-055: the app voice ids that can speak on this studio when it speaks with Kokoro only (no Orpheus node):
    the ones whose Kokoro twin is there. None = not known, or every voice works."""
    engines = studio_engines()
    if not engines or engines.get("orpheus") or not engines.get("kokoro"):
        return None
    try:
        from opensoul import studio_info

        have = studio_info.kokoro_voices(data_dir)
        rows = json.loads((ROOT / "presets" / "voices.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    return None if have is None else {r["id"] for r in rows if r.get("kokoro") in have}


def kokoro_substitute(voice: str, available: set[str] | None) -> str | None:
    """OS-055: an app voice id whose Kokoro twin is on the studio, same gender as ``voice`` (``voice`` itself when its
    twin is there; None when no voice of that gender is there). ``available`` None = not known: ``voice``."""
    if available is None:
        return voice
    try:
        rows = json.loads((ROOT / "presets" / "voices.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return voice
    me = next((r for r in rows if r.get("id") == voice), None)
    if me is None or me.get("kokoro") in available:
        return voice
    return next((r["id"] for r in rows if r.get("gender") == me.get("gender") and r.get("kokoro") in available), None)


def voice_block(pack: dict | None) -> dict:
    """The pack's voice block, migrated read-only: a pack saved before engines existed has none, so it means
    'orpheus, no clip' (the Orpheus voice itself still comes from character_voices). Nothing is written."""
    v = (pack or {}).get("voice")
    v = dict(v) if isinstance(v, dict) else {}
    return {"engine": (str(v["engine"]).lower() if v.get("engine") in ENGINES else None),
            "orpheus_voice": v.get("orpheus_voice"), "ref_clip": v.get("ref_clip") or None,
            "ref_text": v.get("ref_text") or "", "ref_sha256": v.get("ref_sha256") or "",
            "ref_made_with": v.get("ref_made_with") or "", "consent": v.get("consent") is True}


def engine_for(project_engine: str | None = None, pack: dict | None = None) -> str:
    """The engine one line is spoken with (see the module doc for the order)."""
    forced = os.environ.get("OPENSOUL_TTS", "").strip()
    if forced:
        return check(forced)
    pin = voice_block(pack)["engine"]
    if pin:
        return pin
    return check(project_engine) if project_engine else FALLBACK


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def ref_for(engine: str, pack: dict | None, pack_dir: str | Path | None) -> dict | None:
    """{"clip", "text", "sha256"} for a cloning engine when the speaker's pack has a usable clip, else None.

    A clip that is named but not usable raises VoiceRefError: no consent, no provenance, missing, or changed since
    it was saved (sha256). Orpheus and Kokoro never use a clip."""
    if engine not in CLONING:
        return None
    v = voice_block(pack)
    if not v["ref_clip"]:
        return None
    if not v["consent"]:
        raise VoiceRefError("This character's voice clip has no consent ticked. Tick the consent box, or remove the clip.")
    if not v["ref_made_with"]:
        raise VoiceRefError("This character's voice clip doesn't say how it was made, so it can't be used.")
    clip = (Path(pack_dir) / v["ref_clip"]).resolve() if pack_dir else None
    if clip is None or not clip.is_file() or (pack_dir and Path(pack_dir).resolve() not in clip.parents):
        raise VoiceRefError("This character's voice clip is missing from their folder.")
    digest = sha256(clip)
    if v["ref_sha256"] and digest != v["ref_sha256"]:
        raise VoiceRefError("This character's voice clip changed since it was saved. Save it again to use it.")
    return {"clip": str(clip), "text": v["ref_text"], "sha256": digest}


NO_CLIP_FALLBACK = "orpheus"  # engine for a VoxCPM2 line whose speaker has no usable clip


def resolve(project_engine: str | None, pack: dict | None, pack_dir: str | Path | None,
            who: str = "") -> tuple[str, dict | None, str]:
    """(engine, reference clip, note) for one line. VoxCPM2 without a usable clip (none saved, no consent ticked,
    no provenance, missing or changed file) falls back to Orpheus with a plain note, so a fresh install or a
    character without a clip still speaks in their named Orpheus voice. Other engines behave as before: a clip that
    can't be used raises VoiceRefError."""
    engine = engine_for(project_engine, pack)
    if engine != "voxcpm2":
        return engine, ref_for(engine, pack, pack_dir), ""
    name = who or "This character"
    alt = no_clip_fallback(studio_engines())
    lab = LABELS[alt]
    try:
        ref = ref_for(engine, pack, pack_dir)
    except VoiceRefError as e:
        return alt, None, f"{name} is spoken with {lab}: {e} VoxCPM2 needs a usable voice clip."
    if ref is None:
        return alt, None, (f"{name} is spoken with {lab}: VoxCPM2 needs a voice clip with consent. "
                           "Add one under Voices to hear VoxCPM2.")
    return engine, ref, ""


def engine_voice(engine: str, voice: str) -> str:
    """The voice id the engine takes: Orpheus ids as they are, Kokoro's mapped twin (presets/voices.json); the
    cloning engines ignore it (their voice is the clip)."""
    if engine != "kokoro":
        return voice
    try:
        rows = json.loads((ROOT / "presets" / "voices.json").read_text(encoding="utf-8"))
        return next((r.get("kokoro", voice) for r in rows if r.get("id") == voice), voice)
    except (OSError, ValueError):
        return voice


STYLE = {"laugh": "laughing", "chuckle": "amused, a small chuckle", "sigh": "with a sigh", "gasp": "surprised",
         "groan": "groaning", "yawn": "sleepy", "cough": "clearing the throat", "sniffle": "sniffling"}
"""Readable names for the Orpheus tags (UI and notes only). They are never sent to a TTS engine as text."""

_ANGLE = re.compile(r"<\s*/?\s*[A-Za-z][^<>]*>")       # Orpheus-style <sigh>, <laugh>, also unknown <tags>
_DIRECTION = re.compile(r"\([^()]*\)|\[[^\[\]]*\]")    # (amused, a small chuckle) or [whispering] style/stage notes


def drop_directions(text: str) -> str:
    """Remove (style) and [stage] notes, keep everything else (Orpheus <tags> stay)."""
    out = _DIRECTION.sub(" ", text or "")
    return re.sub(r"\s+([,.!?;:])", r"\1", re.sub(r"\s+", " ", out)).strip()


def spoken_words(tagged: str) -> str:
    """Only the words to say: no <tags>, no (style) prefix, no [stage] notes. '(amused)<chuckle> Ren... it's a can.'
    -> "Ren... it's a can." Engines read text literally, so a style note left in the text is spoken aloud."""
    return drop_directions(_ANGLE.sub(" ", tagged or ""))


def voxcpm_text(tagged: str) -> str:
    """VoxCPM2 gets the plain words only. A '(style)' prefix is read aloud when the speaker's clip is used as the
    continuation prompt (clip + transcript), so no tag or style text is ever passed to it."""
    return spoken_words(tagged)


def engine_text(engine: str, tagged: str) -> str:
    """What the engine reads: Orpheus keeps its inline <tags> (it performs them) minus any (style)/[stage] notes;
    every other engine gets the plain words."""
    if engine == "orpheus":
        return drop_directions(tagged)
    return spoken_words(tagged)
