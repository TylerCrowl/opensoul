"""App ↔ lip-sync adapter: the ONE place the app talks to lip-sync (the runner contract was
set on 2026-10-18). Storyboard routes, render job specs and run_shot go through here,
so a change to the runner interface lands in this module only. Pure Python + ffmpeg: never imports torch, LatentSync,
MediaPipe or ComfyUI.

Modes for a shot with a spoken line:

* **Draft** = TTS only: the voice track is muxed onto the (normal I2V) draft clip; no lip-sync pass.
* **Final, ``ltx_av``** (default) = TTS + LTX joint audio+video: the video stage itself is
  ``workflows/04b_a2v_ltx_api.json`` with the voice clip frozen in the audio latent, so picture and mouth are
  generated *to* that audio. The speaker goes in the prompt (no face box for this mode).
* **Final, ``latentsync``** = the same a2v take, then LatentSync 1.6 re-mouths it (post-video), only when LatentSync is
  installed; otherwise the take stays ltx_av and says so. The speaker is targeted with ``face_box`` (x, y, w, h on
  frame 0, output pixels): the runner picks the face box with the highest IoU, else the nearest centre, and tracks it.

The runner writes ``<out>.lipsync.json`` (stats, see :func:`read_sidecar`); missing sidecar -> stats are None.
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from opensoul.cam_lock import (
    CAMLOCK_ENV, SCALE_DRIFT_MAX_PCT, TRANS_MAX_PX, add_guide_ok, apply_cam_lock, cam_lock_enabled,
    cam_passes, cam_reject_reason, crop_guides_before_upsampler, is_cam_locked, score_cam, HOLD_STRENGTH,
    apply_hold_guide)

BACKENDS = ("ltx_av", "latentsync")
DEFAULT_BACKEND = "ltx_av"
BACKEND_LABELS = {"ltx_av": "LTX audio+video (joint)", "latentsync": "LatentSync 1.6 (after the video)"}
A2V_WORKFLOW = "workflows/04b_a2v_ltx_api.json"
LATENTSYNC_WORKFLOW = "workflows/05_lipsync_api.json"
FPS = 24
MAX_AUDIO_S = 20.0
# Pre-queue face-size check on the speaker's face_box (face height in output pixels). PROVISIONAL thresholds from the
# lip-sync runner work (2026-10-18; warn lowered 160 -> 128 after the face-detector work); revisit after real takes.
FACE_WARN_PX = 128
FACE_BLOCK_PX = 96
SIDECAR_KEYS = ("face_found_ratio", "held_frames", "frames", "detector_counts", "face_px_median", "face_px_min",
                "multi_face_frames", "backend", "steps", "guidance", "seed")

# 04b node ids (read from the workflow file; asserted in tests so a workflow edit can't silently break the patch).
N_IMAGE, N_SCALE, N_PROMPT, N_VIDEO_LATENT, N_AUDIO_LATENT, N_NOISE_1, N_NOISE_2, N_AUDIO, N_OUT = (
    "1", "2", "20", "30", "32", "35", "43", "60", "51")
N_GUIDER = "34"                     # LTXVDualCFGGuider: video_cfg / audio_cfg pinned by a2v_stage
# G tests (19 Oct 2026, internal lip-sync review): audio_cfg 3 shuts the mouth (l07 open_max 0.31 -> 0.02,
# LSE-C 4.2 -> 1.0); video_cfg 2 shuts it too and video_cfg 3 helps one line at 2x cost. Pin both so a workflow edit
# can't drift them.
GUIDER_CFG = {"video_cfg": 1.0, "audio_cfg": 1.0}
# G5: the articulation sentence is the only a2v lever that opened shut lines (l08 LSE-C 0.68 -> 6.12, l04 0.63 -> 5.59)
# and put teeth / interior in the open mouth. Cost: some over-acting (wide 'O's, a grin). G2nd: the SOFT wording (no
# "jaw moving with each word", plus "calm neutral expression") keeps LSE-C (+0.16 mean over 5 lines, same seeds) with
# fewer teeth (0.14 -> 0.10) and slightly less grin; it is the default. Written in the speaker's own pronoun
# (character pack "pronoun"/"pronouns"), 'they' when the character has none.
ARTICULATION = ("{Subj} {speaks} clearly, eyes open: {poss} lips open and close on every syllable, teeth visible on open vowels, "
                "calm neutral expression.")
ARTICULATION_MARK = "lips open and close on every syllable"
# OS-056: the a2v model fills silence with an open or moving mouth. This sentence goes after the speaking sentence
# of every talk prompt (the hold guide in the render does the rest; see opensoul.voice_shape).
SILENT_MOUTH = "Before the first word, in each pause and after the last word, {poss} lips are closed and still."
SILENT_MOUTH_MARK = "after the last word"
PRONOUNS = {"she": ("She", "speaks", "her"), "he": ("He", "speaks", "his"), "they": ("They", "speak", "their")}
DEFAULT_PRONOUN = "they"
N_LOAD_AUDIO = "60"                 # LoadAudio: the (padded) voice wav of an a2v stage
FROZEN_AUDIO_NODE = "63"            # SetLatentNoiseMask(LTXVAudioVAEEncode(LoadAudio 60), SolidMask 0.0)
AV_CONCAT_NODES = ("33", "42")      # base pass and refine pass: BOTH must take the frozen audio


class LipSyncError(RuntimeError):
    """A user-facing lip-sync problem. ``code`` is one of the contract's error states."""

    MESSAGES = {
        "no_line": "Write what they say first.",
        "no_speaker": "Pick who says this line.",
        "bad_audio": "The voice clip couldn't be read (or is longer than 20 s).",
        "no_face": "Couldn't find {speaker}'s face in this take. Try a closer shot or LTX lip-sync.",
        "ambiguous_face": "Several faces in the shot: pick who's speaking.",
        "face_too_small": "{speaker}'s face is too small for LatentSync ({px}px; needs {need}px). Use LTX lip-sync or a closer shot.",
        "backend_missing": "{backend} isn't installed. Run ./scripts/download_models.sh lipsync.",
        "oom": "Your computer ran out of memory. Try Draft or a shorter line.",
        "timeout": "Lip-sync took too long. Try a shorter line.",
        "runner_failed": "Lip-sync failed: {detail}",
    }

    def __init__(self, code: str, **kw):
        self.code = code
        super().__init__(self.MESSAGES.get(code, code).format(**{"speaker": "the speaker", **kw}))


_CODE = __import__("re").compile(r"\[lipsync:([a-z_]+)\]")


def error_code(message: str) -> str | None:
    """The contract error code a runner failure carries ("[lipsync:no_face]" from the ComfyUI node), else None.
    Runner exit codes: 3 = ambiguous_face, 4 = no_face (face on < 50% of frames; the runner keeps its mp4)."""
    m = _CODE.search(message or "")
    return m.group(1) if m and m.group(1) in LipSyncError.MESSAGES else None


def no_face_note(speaker: str = "") -> str:
    return (f"LatentSync couldn't find {speaker or 'the speaker'}'s face in enough frames, so this take is the "
            "LTX audio+video render without the LatentSync pass.")


def run_latentsync_stage(backend, video: Path, audio: Path, dest: Path, stage: dict) -> tuple[Path, str | None]:
    """Run a post-video LatentSync stage -> (video, note). no_face keeps the incoming (LTX) clip with a note;
    ambiguous_face and other contract errors raise LipSyncError; anything else re-raises."""
    fb = stage.get("face_box")
    if fb and hasattr(backend, "face_box"):
        backend.face_box = list(fb)
    for k, v in (stage.get("params") or {}).items():  # L1c stage-2 settings (steps, guidance, seed, face_style)
        if k in ("steps", "guidance", "seed", "face_style") and hasattr(backend, k):
            setattr(backend, k, v)
    try:
        return Path(backend.sync(Path(video), Path(audio), Path(dest))), None
    except RuntimeError as e:
        code = error_code(str(e))
        if code == "no_face":
            return Path(video), no_face_note(stage.get("speaker", ""))
        if code:
            raise LipSyncError(code, speaker=stage.get("speaker") or "the speaker") from e
        raise


@dataclass
class LipSyncRequest:
    audio: Path
    dest: Path
    backend: Literal["ltx_av", "latentsync"] = DEFAULT_BACKEND
    start_frame: Path | None = None      # ltx_av
    prompt: str = ""                     # ltx_av: video prompt (tags stripped, speaker named)
    video: Path | None = None            # latentsync: the clip to re-mouth
    speaker: str = ""
    face_ref: Path | None = None         # v1: only used to derive a face_box (no identity matching: ArcFace is non-commercial)
    face_box: tuple[int, int, int, int] | None = None   # x, y, w, h on frame 0, output pixels (latentsync only)
    seed: int = 1247
    steps: int | None = None
    guidance: float | None = None
    width: int = 704
    height: int = 1280
    fps: int = FPS


@dataclass
class LipSyncResult:
    video: Path
    backend: str
    seconds: float = 0.0
    frames: int = 0
    stats: dict | None = None            # the runner's sidecar (None when missing)
    placeholder: bool = False
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- pure helpers (tested without any GPU)
def check_backend(name: str | None) -> str:
    b = (name or DEFAULT_BACKEND).strip().lower()
    if b not in BACKENDS:
        raise ValueError(f"Unknown lip-sync option {name!r}. Choose {' or '.join(BACKENDS)}.")
    return b


def a2v_frames(audio_s: float, fps: int = FPS) -> int:
    """LTX a2v frame count for a voice clip: k = ceil((audio_s*fps - 1) / 8), frames = 8k + 1 (k >= 1)."""
    k = max(1, math.ceil((float(audio_s) * fps - 1) / 8))
    return 8 * k + 1


def padded_seconds(audio_s: float, fps: int = FPS) -> float:
    """The voice clip is padded with trailing silence to exactly frames / fps (never time-stretched)."""
    return a2v_frames(audio_s, fps) / fps


def face_check(face_box, backend: str, speaker: str = "") -> dict:
    """Pre-queue check on the speaker's face height (PROVISIONAL thresholds). ok / warn / block (block: latentsync only)."""
    if not face_box:
        return {"level": "unknown", "px": None, "message": ""}
    h = int(face_box[3])
    who = speaker or "The speaker"
    if h < FACE_BLOCK_PX and backend == "latentsync":
        return {"level": "block", "px": h, "message": str(LipSyncError("face_too_small", speaker=who, px=h, need=FACE_BLOCK_PX))}
    if h < FACE_WARN_PX:
        return {"level": "warn", "px": h,
                "message": f"{who}'s face is small ({h}px, under {FACE_WARN_PX}px): lip-sync may be soft. A closer shot helps."}
    return {"level": "ok", "px": h, "message": ""}


def pronoun_key(pronoun) -> str:
    """'she', 'he' or 'they' from a pronoun field ('she', 'She/her', 'he/him', ['they', 'them'] ...); else 'they'."""
    if isinstance(pronoun, (list, tuple)):
        pronoun = pronoun[0] if pronoun else ""
    first = str(pronoun or "").strip().lower().replace(",", "/").split("/")[0].strip()
    return first if first in PRONOUNS else DEFAULT_PRONOUN


def pronoun_from_meta(pack: dict | None) -> str:
    """The pronoun a character pack declares (top level or meta: "pronoun" / "pronouns"), else 'they'."""
    pack = pack or {}
    for src in (pack, pack.get("meta") or {}):
        for k in ("pronoun", "pronouns"):
            if src.get(k):
                return pronoun_key(src[k])
    return DEFAULT_PRONOUN


def articulation(pronoun=None) -> str:
    subj, verb, poss = PRONOUNS[pronoun_key(pronoun)]
    return ARTICULATION.format(Subj=subj, speaks=verb, poss=poss)


# Eyes (lip-sync eye check, 19 Oct 2026): 'slow blink' / 'glances down' in a talking-shot prompt gave eyes shut in all
# three checked takes. Generated prompts never carry them: the phrase becomes this sentence.
EYES_GLANCE = "eyes open, a brief glance down at {look_at}, then holds on {listener}"
EYES_HOLD = "eyes open, holding on {listener}"
EYES_TARGET = "the camera"
# L1c talk prompt: after the soft articulation sentence, the head is held and the eyes go to the listener (the camera
# when there is none). Talk shots never get a blink or glance-down beat (no EYES_GLANCE variant).
TALK_HOLD = "Head still, no tilt, eyes on {listener}."
TALK_HOLD_MARK = "Head still, no tilt"


def eyes_sentence(look_at: str = "", listener: str = "") -> str:
    """The eye direction that replaces eyes-shut phrasing. With the shot's object and listener: 'eyes open, a brief
    glance down at the counter, then holds on the customer'; listener only: 'eyes open, holding on <listener>';
    neither: 'eyes open, holding on the camera'. Never 'a slow blink' / 'glances down'."""
    look_at, listener = (look_at or "").strip(), (listener or "").strip()
    if look_at and listener:
        return EYES_GLANCE.format(look_at=look_at, listener=listener)
    return EYES_HOLD.format(listener=listener or EYES_TARGET)
_EYE_RISK = re.compile(
    r"(?:\b(?:gives|does|makes|offers|with|and)\s+)?(?:\b(?:a|one)\s+)?"
    r"(?:\bslow(?:ly)?[\s-]+blink(?:s|ing)?\b|\bblink(?:s|ing|ed)?\s+slowly\b|\bglanc(?:es|ing|ed)\s+down(?:wards?)?\b)"
    r"(?:\s*,?\s*(?:and|then)\b)?", re.I)


def eyes_safe(prompt: str, look_at: str = "", listener: str = "") -> str:
    """Drop 'slow blink' / 'blinks slowly' / 'glances down' (with a leading 'gives a' / 'and' and a trailing 'and' /
    'then') and add one sentence from :func:`eyes_sentence` ('Eyes open, holding on the camera.' unless the shot gives
    an object and / or listener). Other text is unchanged; a prompt without those phrases is returned as is."""
    if not prompt or not _EYE_RISK.search(prompt):
        return prompt
    out = _EYE_RISK.sub(" ", prompt)
    out = re.sub(r"\s+([,.;:!?])", r"\1", re.sub(r"\s{2,}", " ", out))
    out = re.sub(r"([.!?])\s*[,;]\s*", r"\1 ", out)
    out = re.sub(r"([,;])(?:\s*[,;])+", r"\1", out)
    out = re.sub(r",\s*([.!?])", r"\1", out).strip().rstrip(",;")
    safe = eyes_sentence(look_at, listener)
    if safe.lower() in out.lower():
        return out
    return f"{out}{'' if out.endswith(('.', '!', '?')) or not out else '.'} {safe[0].upper()}{safe[1:]}.".strip()


def talk_hold(listener: str = "") -> str:
    """'Head still, no tilt, eyes on <listener>.' (the camera when the shot has no single listener)."""
    return TALK_HOLD.format(listener=(listener or "").strip() or EYES_TARGET)


def articulate(prompt: str, pronoun=None, *, look_at: str = "", listener: str = "") -> str:
    """Talk prompt (L1c): 'small' -> 'clear natural mouth movements', the soft articulation sentence (once, in the
    speaker's pronoun, it says 'eyes open'), then 'Head still, no tilt, eyes on <listener>.' (once). Talk shots get no
    blink or glance-down beat: eyes_safe still drops those phrases, and ``look_at`` is ignored here (the 'brief glance
    down at <object>' variant is not used in talk shots). Only for talking shots (speaker_prompt, and
    build_shot_plan when the shot has a line or a speaker)."""
    prompt = eyes_safe((prompt or "").replace("small natural mouth movements", "clear natural mouth movements"),
                       "", listener)
    if ARTICULATION_MARK not in prompt:
        prompt = f"{prompt.rstrip()} {articulation(pronoun)}".strip()
    if TALK_HOLD_MARK.lower() not in prompt.lower():
        prompt = f"{prompt.rstrip()} {talk_hold(listener)}".strip()
    return prompt


def pronoun_for_pack_dir(pack_dir) -> str:
    """pronoun_from_meta of <pack_dir>/pack.json; 'they' when there is no readable pack."""
    try:
        return pronoun_from_meta(json.loads((Path(pack_dir) / "pack.json").read_text())) if pack_dir else DEFAULT_PRONOUN
    except (OSError, ValueError, TypeError):
        return DEFAULT_PRONOUN


def speaker_prompt(prompt: str, speaker: str, line_plain: str, pronoun=None, *, look_at: str = "",
                   listener: str = "") -> str:
    """ltx_av has no face box: the prompt says who talks (and the words, without tags), and asks for clear
    articulation in the speaker's own pronoun (G5). ``listener``: who the speaker's eyes hold on (talk_hold; the
    camera when empty). ``look_at`` is accepted for callers but not used: talk shots get no glance-down beat."""
    prompt = articulate(prompt, pronoun, look_at=look_at, listener=listener)
    if not speaker:
        return prompt
    said = f' "{line_plain}"' if line_plain else ""
    out = f"{prompt.rstrip()} {speaker} is the one speaking, lips moving with the words{said}; the others listen."
    return silent_mouth(out.strip(), pronoun)


def silent_mouth(prompt: str, pronoun=None) -> str:
    """OS-056: add 'Before the first word, in each pause and after the last word, <poss> lips are closed and still.'
    once."""
    if SILENT_MOUTH_MARK in (prompt or ""):
        return prompt
    poss = PRONOUNS[pronoun_key(pronoun)][2]
    return f"{(prompt or '').rstrip()} {SILENT_MOUTH.format(poss=poss)}".strip()


def a2v_stage(*, prompt: str, audio_s: float, seed: int, width: int = 704, height: int = 1280,
              quality: str = "final", fps: int = FPS, target_s: float = 0.0, shape: bool = False) -> dict:
    """Video stage that IS the lip-sync for ltx_av: workflow 04b with the voice clip as input (``audio_from``).

    Camera lock (native LTXVAddGuide last-frame pin) is the default: ``cam_lock`` is True unless
    ``OPENSOUL_A2V_CAMLOCK=off``. The render path applies :func:`opensoul.cam_lock.apply_cam_lock` to the graph.

    ``shape`` (talking shots, OS-056/OS-059): the render trims the voice's lead and tail silence and sizes the take
    to ``target_s`` (the shot's planned length; 0 = the line plus a short closed-mouth hold), see
    :func:`fit_a2v_to_voice`. The frame count here is then only the estimate shown before the render.
    """
    if shape:
        from opensoul.voice_shape import plan_length

        frames = plan_length(audio_s, target_s, fps=fps)
    else:
        frames = a2v_frames(audio_s, fps)
    out = {"stage": "video", "workflow": A2V_WORKFLOW, "output_node": N_OUT, "audio_from": "voice",
           "pad_audio_to_s": round(frames / fps, 4), "frames": frames, "quality": quality, "expect_motion": "any",
           "params": {"duration_s": round(frames / fps, 3), "fps": fps, "width": width, "height": height},
           "inputs": {N_SCALE: {"width": width, "height": height},
                      N_PROMPT: {"text": prompt},
                      N_VIDEO_LATENT: {"width": width // 2, "height": height // 2, "length": frames},
                      N_AUDIO_LATENT: {"frames_number": frames, "frame_rate": fps},
                      N_NOISE_1: {"noise_seed": seed}, N_NOISE_2: {"noise_seed": seed},
                      N_GUIDER: dict(GUIDER_CFG),
                      N_AUDIO: {"audio": "<voice.wav, padded>"}},
           "lipsync": "ltx_av", "gpu_verified": False, "cam_lock": cam_lock_enabled()}
    if shape:
        out.update({"shape_voice": True, "target_s": float(target_s or 0)})
    return out


HOLD_AFTER_S = 0.25      # the hold guide sits this long after the last word (the lips close in that time)
HOLD_MIN_TAIL_S = 0.5    # no hold guide when less silence than this follows the last word


def hold_frame(speech_end_s: float, frames: int, fps: int = FPS) -> int | None:
    """Frame index of the closed-mouth hold guide after the line, or None when the silent end is too short."""
    idx = int(math.ceil((float(speech_end_s) + HOLD_AFTER_S) * fps))
    if (frames - 1) / fps - float(speech_end_s) < HOLD_MIN_TAIL_S or idx >= frames - 4:
        return None
    return idx


def fit_a2v_to_voice(stage: dict, shaped: dict, fps: int = FPS) -> dict:
    """A copy of an a2v stage sized to the shaped voice (:func:`opensoul.voice_shape.shape_voice`): frame counts,
    duration, the padded clip, and the hold guide frame after the line (camera-locked takes only)."""
    frames = int(shaped["frames"])
    st = {**stage, "frames": frames, "pad_audio_to_s": round(frames / fps, 4),
          "params": {**(stage.get("params") or {}), "duration_s": round(frames / fps, 3), "frames": frames},
          "voice_shape": {k: shaped.get(k) for k in ("speech_start", "speech_end", "pauses", "source_s",
                                                      "cut_lead_s", "cut_tail_s", "target_s", "seconds")}}
    inputs = {k: dict(v) if isinstance(v, dict) else v for k, v in (stage.get("inputs") or {}).items()}
    if isinstance(inputs.get(N_VIDEO_LATENT), dict):
        inputs[N_VIDEO_LATENT]["length"] = frames
    if isinstance(inputs.get(N_AUDIO_LATENT), dict):
        inputs[N_AUDIO_LATENT]["frames_number"] = frames
    inputs[N_AUDIO] = {"audio": shaped["file"]}
    st["inputs"] = inputs
    hold = hold_frame(shaped.get("speech_end", 0), frames, fps) if stage.get("cam_lock") else None
    st["hold_guide"] = {"frame_idx": hold, "strength": HOLD_STRENGTH} if hold is not None else None
    return st


def _line_stage(line_ref: dict | None, wav=None) -> dict:
    ref = dict(line_ref or {})
    lid, src = resolve_line_id(ref.get("line"), ref.get("names") or (), wav or ref.get("wav"), ref.get("position"))
    return {"line_ref": ref, "line_id": lid, "line_id_from": src, "grin_review_only": grin_review_only_for(lid)}


def dialogue_stages(*, line: str, voice: str, quality: str, backend: str, prompt: str, speaker: str, seed: int,
                    width: int = 704, height: int = 1280, tts_backend: str = "orpheus", latentsync_installed: bool = False,
                    face_box=None, i2v_stage: dict | None = None, faces: int = 1,
                    pronoun=None, best_of: int = 1, line_ref: dict | None = None, listener: str = "",
                    look_at: str = "", rebuilt: bool = False,
                    voice_meta: dict | None = None, ref: dict | None = None,
                    mouth_refine: bool | None = None, target_s: float = 0.0,
                    scorer_ready: bool | None = None) -> tuple[list[dict], list[str], str]:
    """Render stages for a shot with a spoken line -> (stages, notes, mode).

    ``mouth_refine``: opt in to the LatentSync mouth pass (Stage 2) on a camera-locked take, where it is off by
    default because it pales the lips on AddGuide bases (None = env OPENSOUL_MOUTH_REFINE, default off).
    ``tts_backend``: the voice engine (opensoul.voice_engine.engine_for); ``ref``: the speaker's reference clip for a
    cloning engine (opensoul.voice_engine.ref_for), passed to the voice stage as ``inputs.ref``.

    mode: "tts_only" (Draft), "ltx_a2v" (Final, ltx_av or LatentSync not installed), "ltx_a2v+latentsync".
    ``best_of`` > 1 (rebuilt characters, :func:`best_of_for`): the ltx_av Final a2v stage renders that many seeds.
    Recipe L1c (default): the seeds are look-gated bases (:func:`choose_base`) and a LatentSync mouth stage
    (``only_if`` l1c_stage2, with the stage-2 params, voice and cost hint) follows when LatentSync can run on this
    shot; framing warnings come from ``face_box``. Recipe best_of_fallback (setting only): the older pick, LatentSync
    only when every seed is rejected. ``rebuilt``: the speaker is a rebuilt character (:func:`is_rebuilt`); L1c
    stage 2 is then on by default whatever the voice (:func:`stage2_default_why`). ``voice_meta``: the speaker's pack
    voice label (:func:`voice_label_of`), metadata for the lip-sync records only; the TTS voice stays ``voice``.
    ``scorer_ready``: False when the lip-sync scorer is not set up (opensoul.lipsync_scorer); best-of is then off
    and a note says so (OS-057). None: not checked here. ``target_s``: the shot's planned length (OS-059).
    ``line_ref``
    ({"line", "names", "wav", "position"}, see :func:`resolve_line_id`) decides grin_review_only; ``listener`` / ``look_at`` feed the eyes sentence (:func:`eyes_safe`)."""
    from opensoul.orpheus import normalize_tags, strip_tags
    from opensoul.speak import estimate_seconds

    backend = check_backend(backend)
    text = normalize_tags(line)
    plain = strip_tags(text)
    secs = estimate_seconds(text)
    from opensoul.voice_engine import engine_text, engine_voice

    voice_stage = {"stage": "voice", "backend": tts_backend,
                   "inputs": {"text": engine_text(tts_backend, text), "voice": engine_voice(tts_backend, voice)},
                   "seconds_est": secs}
    if ref:
        voice_stage["inputs"]["ref"] = dict(ref)
    notes: list[str] = []
    if quality != "final":
        vid = dict(i2v_stage or {"stage": "video", "workflow": "workflows/04_i2v_ltx_api.json"})
        notes.append("Draft: voice only, no lip-sync. Final renders the mouth to the voice.")
        return [voice_stage, vid, {"stage": "mux", "audio_from": "voice"}], notes, "tts_only"
    stages = [voice_stage, a2v_stage(prompt=speaker_prompt(prompt, speaker, plain, pronoun, look_at=look_at,
                                                    listener=listener), audio_s=secs, seed=seed,
                                     width=width, height=height, quality=quality, target_s=target_s,
                                     shape=True)]
    mode = "ltx_a2v"
    label = (voice_meta or {}).get(VOICE_LABEL_KEY) or ""
    vcanon = (voice_meta or {}).get("voice_canonical") or voice_canonical(label or voice)
    if label:  # metadata only: recorded on the take, never sent to the TTS
        stages[1].update({VOICE_LABEL_KEY: label, "voice_canonical": vcanon})
        notes.append(f"Lip-sync voice label: {vcanon}" + (f" ({label})" if label != vcanon else "")
                     + f" (metadata; the voice is made with {voice}).")
    notes += framing_from_face_box(face_box, height)  # talk shots: warning only, needs the shot's face_box
    if best_of > 1 and backend == "ltx_av" and scorer_ready is False:
        # OS-057: no scorer, no best-of. Render one take and say so before the render (no extra GPU time).
        notes.append(f"Best of {int(best_of)} is off: no lip-sync scorer is set up here, so one take is made "
                     "(not scored). Look at the take and make another one if the mouth is wrong. "
                     "See docs/LIPSYNC_SCORER.md.")
        best_of = 1
    if best_of > 1 and backend == "ltx_av":
        n = int(best_of)
        cfg = best_of_config()
        stages[1].update({"best_of": n, "seeds": best_of_seed_list(seed, n, cfg), "method": REBUILT_METHOD,
                          "recipe": cfg.recipe, "cam_lock": stages[1].get("cam_lock", cam_lock_enabled()),
                          **_line_stage(line_ref)})
        fc = face_check(face_box, "latentsync", speaker)
        ls_ok = latentsync_installed and (face_box or faces <= 1) and fc["level"] != "block"
        if cfg.recipe == RECIPE_L1C:
            notes.append(f"Best of {n} takes: {n} seeds are rendered and scored on look (grin, closed lips) "
                         "and camera drift; the best eyes are kept (L1c base).")
            frames = audio_frames(secs)
            on_why = stage2_default_why(voice, rebuilt, cfg, label=label)
            cam = bool(stages[1].get("cam_lock", cam_lock_enabled()))
            refine = mouth_refine_on() if mouth_refine is None else bool(mouth_refine)
            mode2 = stage2_mode(cfg)
            if cam and refine:
                on_why, mode2 = "on: Mouth refine (LatentSync) picked for this camera-locked take", "on"
            elif cam and mode2 != "on":  # the ruling: Stage 2 pales the lips on AddGuide bases
                on_why, mode2 = "", "off"
            on = bool(on_why)
            if ls_ok:
                stages.append({"stage": "lipsync", "backend": "latentsync", "workflow": LATENTSYNC_WORKFLOW,
                               "speaker": speaker, "face_box": list(face_box) if face_box else None,
                               "recipe": RECIPE_L1C, "only_if": ONLY_IF_L1C_STAGE2, "params": l1c_stage2_params(cfg),
                               "voice": voice, "voice_canonical": vcanon, VOICE_LABEL_KEY: label or None,
                               "voice_label_notes": (voice_meta or {}).get("voice_label_notes") if label else None,
                               "rebuilt": bool(rebuilt), "stage2_default_on": on, "stage2_default_why": on_why,
                               "stage2_mode": mode2, "cam_lock": cam, "mouth_refine": bool(cam and refine),
                               "frames_est": frames, "cost_est_s": latentsync_cost_s(frames, cfg),
                               "grin_review_only": stages[1].get("grin_review_only", False)})
                notes.append(f"L1c mouth pass (LatentSync, about {latentsync_cost_s(frames, cfg):.0f} s more): "
                             + (f"{on_why}." if on else MOUTH_REFINE_OFF_NOTE if cam and mode2 == "off"
                                else "runs only if the base fails a check."))
            else:
                notes.append("L1c mouth pass unavailable here (LatentSync isn't installed, or the face check "
                             "doesn't allow it): the base take is kept.")
        else:
            notes.append(f"Best of {n} takes: {n} seeds are rendered and scored, the best is kept.")
            if ls_ok:
                stages.append({"stage": "lipsync", "backend": "latentsync", "workflow": LATENTSYNC_WORKFLOW,
                               "speaker": speaker, "face_box": list(face_box) if face_box else None,
                               "only_if": ONLY_IF_ALL_REJECTED})
    if backend == "latentsync":
        fc = face_check(face_box, backend, speaker)
        if not face_box and faces > 1:
            notes.append(str(LipSyncError("ambiguous_face")) + " Kept LTX audio+video only.")
        elif fc["level"] == "block":
            notes.append(fc["message"] + " Kept LTX audio+video only.")
        elif not latentsync_installed:
            notes.append("LatentSync isn't installed: LTX audio+video only (./scripts/download_models.sh lipsync).")
        else:
            if fc["level"] == "warn":
                notes.append(fc["message"])
            stages.append({"stage": "lipsync", "backend": "latentsync", "workflow": LATENTSYNC_WORKFLOW,
                           "speaker": speaker, "face_box": list(face_box) if face_box else None})
            mode = "ltx_a2v+latentsync"
    if stages[1].get("cam_lock"):
        notes.append("Camera lock on (native LTXVAddGuide last-frame pin); "
                     f"set {CAMLOCK_ENV}=off for the old a2v graph.")
    return stages, notes, mode


# ---------------------------------------------------------------- rebuilt-character method (G recommendation)
# Config/policy only. The app keeps DEFAULT_BACKEND = ltx_av for every shot; this is the method for REBUILT characters
# (the text-only Lumi rebuild and later ones), run by a scoring runner that can measure SyncNet per take:
#   1. ltx_a2v_artic: an ltx_av take (04b, cfg 1.0/1.0, 24 fps, no lead-in, 8k+1 frames) with the articulation prompt;
#   2. if that take's fair LSE-C < LATENTSYNC_FALLBACK_LSE_C, LatentSync 1.6 runs on it and the higher fair LSE-C wins;
#   3. the inner-mouth pass (ls_inner_mouth.py, L1c2 settings, tool commit a410367) runs on the kept take.
REBUILT_METHOD = "ltx_a2v_artic"
LATENTSYNC_FALLBACK_LSE_C = 4.5
LATENTSYNC_STEPS = 50               # workflows/05_lipsync_api.json node 3 (L1/L1b used 50; 20 was never scored)
LATENTSYNC_FALLBACK = {"backend": "latentsync", "workflow": LATENTSYNC_WORKFLOW, "steps": LATENTSYNC_STEPS,
                       "guidance": 1.5, "seed": 1247}
INNER_MOUTH_PASS = {"runner": "custom_nodes/opensoul_nodes/runners/ls_inner_mouth.py", "settings": "L1c2",
                    "tool_commit": "a410367", "args": ["--face-style", "auto", "--lip-color-fix"]}


def rebuilt_method() -> dict:
    """The rebuilt-character lip-sync method as data (what the scoring runner does, in order)."""
    return {"method": REBUILT_METHOD, "base": {"backend": "ltx_av", "workflow": A2V_WORKFLOW, "fps": FPS,
                                               "lead_in_s": 0.0, "frames": "8k+1", "articulation": True,
                                               **GUIDER_CFG},
            "fallback": {**LATENTSYNC_FALLBACK, "when_lse_c_below": LATENTSYNC_FALLBACK_LSE_C, "keep": "higher_lse_c"},
            "post": dict(INNER_MOUTH_PASS, args=list(INNER_MOUTH_PASS["args"]))}


def needs_latentsync_fallback(lse_c) -> bool:
    """Fallback when the articulated take's fair LSE-C is below the threshold. No score (None: SyncNet found no
    face, or the scorer failed) is a scorer failure, never an automatic LatentSync fallback."""
    return lse_c is not None and float(lse_c) < LATENTSYNC_FALLBACK_LSE_C


def run_rebuilt_method(take_artic, score=None, run_latentsync=None, run_inner_mouth=None, *, ref=None) -> dict:
    """Pick the take for a rebuilt character. ``score(take) -> fair LSE-C or None`` (default: the configured
    lip-sync scorer CLI, opensoul.lipsync_scorer, with ``ref`` = the raw take; raises ScorerError when it isn't set
    up); ``run_latentsync(take) -> take``; ``run_inner_mouth(take) -> take``. Injected so tests and the box/Spark
    runner supply their own."""
    if run_latentsync is None or run_inner_mouth is None:
        raise TypeError("run_rebuilt_method needs run_latentsync and run_inner_mouth.")
    if score is None:
        from opensoul import lipsync_scorer

        score = lipsync_scorer.scorer(ref=ref)
    from opensoul.lipsync_scorer import ScorerError

    try:
        c_artic = score(take_artic)
    except ScorerError as e:  # e.g. lse_c null (SyncNet found no face): keep the a2v take, flag it
        c_artic, scorer_error = None, f"{e.code}: {e}"
    else:
        scorer_error = None if c_artic is not None else "no_score: the scorer returned no LSE-C (no face found?)"
    if scorer_error:
        return {"take": run_inner_mouth(take_artic), "method": REBUILT_METHOD, "lse_c": None, "lse_c_artic": None,
                "lse_c_latentsync": None, "fallback_ran": False, "scorer_failed": True, "flag": scorer_error}
    kept, c_kept, method, c_ls = take_artic, c_artic, REBUILT_METHOD, None
    if needs_latentsync_fallback(c_artic):
        take_ls = run_latentsync(take_artic)
        try:
            c_ls = score(take_ls)
        except ScorerError:  # an unscorable LatentSync take never wins
            c_ls = None
        if c_ls is not None and (c_artic is None or float(c_ls) > float(c_artic)):
            kept, c_kept, method = take_ls, c_ls, "latentsync"
    return {"take": run_inner_mouth(kept), "method": method, "lse_c": c_kept, "lse_c_artic": c_artic,
            "lse_c_latentsync": c_ls, "fallback_ran": needs_latentsync_fallback(c_artic), "scorer_failed": False,
            "flag": None}


# ---------------------------------------------------------------- best-of-N seeds for ltx_a2v_artic (G2nd)
# Rebuilt characters: the seed decides sync far more than the wording (LSE-C swings up to 5.8 between seeds on one
# line). Render N seeds, score each with the external scorer (opensoul.lipsync_scorer, `--score-only VIDEO
# [--ref RAW] --json`), reject bad ones, keep the highest LSE-C. All rejected -> the least bad by LSE-C, needs_review,
# and only then the LatentSync fallback. No scorer -> seed 1 only, flagged scorer_failed (no extra renders).
# Seed count, thresholds and the scorer's field names are NOT code constants: presets/lipsync_best_of.json, with env
# overrides (best_of_config). The final values / names are still to come from the lip-sync side.
BEST_OF_CONFIG = Path(__file__).resolve().parents[1] / "presets" / "lipsync_best_of.json"
METRICS = ("lse_c", "lse_d", "offset", "open_frac", "grin_frac", "grin_win_max", "grin_def", "eyes_open_frac",
           "eyes_shut_flag", "eyes_shut_max_s", "start_eye_blink", "start_face_h_frac", "start_yaw")
FRAME_FIELDS = ("eye_blink_frames", "eye_look_down_frames", "fps")   # per-frame series: fallback for eyes_shut
# Eyeline (warn only): how much the eyes look at the listener (1) vs drift to the lens (0), per frame (None = no face),
# or the scorer's own start / end values. Optional fields: a preset without them maps each to its own name.
EYELINE_FIELDS = ("start_eye_look_listener", "end_eye_look_listener", "eye_look_listener_frames", "eyeline_drift_warn")
FIELD_KEYS = METRICS + FRAME_FIELDS + EYELINE_FIELDS
START_FRAME_WARNING = "Eyes look closed in the start frame"
EYELINE_WARNING = "eyeline drifts to lens at end"
_REJECT_KEYS = ("abs_offset_min", "open_frac_max", "grin_frac_max", "grin_win_max")
_ENV_REJECT = {"abs_offset_min": "OPENSOUL_BEST_OF_ABS_OFFSET", "open_frac_max": "OPENSOUL_BEST_OF_OPEN_FRAC_MAX",
               "grin_frac_max": "OPENSOUL_BEST_OF_GRIN_FRAC_MAX", "grin_win_max": "OPENSOUL_BEST_OF_GRIN_WIN_MAX"}
GRIN_RULES = ("grin_frac", "grin_win_max")
GATE_RULES = ("offset", "open_frac", "grin_frac", "grin_win_max")
RECIPE_L1C = "L1c"                       # default: base gated on look, then the LatentSync mouth pass
RECIPE_LEGACY = "best_of_fallback"       # the older pick (highest LSE-C, LatentSync only when every seed is rejected)
RECIPE_ENV = "OPENSOUL_LIPSYNC_RECIPE"   # L1c | best_of_fallback
STAGE2_ENV = "OPENSOUL_L1C_STAGE2"       # auto (default) | on | off
STAGE2_VOICES_ENV = "OPENSOUL_L1C_STAGE2_VOICES"   # comma list of voice ids with stage 2 on by default
STAGE2_REBUILT_ENV = "OPENSOUL_L1C_STAGE2_REBUILT"  # on (default) | off: stage 2 on by default for rebuilt characters
INNER_MOUTH_ENV = "OPENSOUL_L1C_INNER_MOUTH"       # experimental toggle: on | off (default off)
# Review ruling: LatentSync Stage 2 pales the lips on camera-locked (AddGuide) bases, so on those takes it is OFF
# by default; "Mouth refine (LatentSync), may pale lips" is the per-shot opt-in, OPENSOUL_MOUTH_REFINE=on the global one.
MOUTH_REFINE_ENV = "OPENSOUL_MOUTH_REFINE"         # on | off (default off)
MOUTH_REFINE_LABEL = "Mouth refine (LatentSync), may pale lips"
MOUTH_REFINE_OFF_NOTE = ("off by default on camera-locked takes (it pales the lips); tick "
                         "'Mouth refine (LatentSync), may pale lips' to use it")


def mouth_refine_on() -> bool:
    return (os.environ.get(MOUTH_REFINE_ENV) or "off").strip().lower() in ("1", "on", "true", "yes")
INNER_MOUTH_CAVEAT = "it can leave black voids in the mouth and hold the mouth open into a pause"

# Camera lock (native LTXVAddGuide): default ON. OPENSOUL_A2V_CAMLOCK=off restores the old graph and skips the
# cam gate. Helpers live in opensoul.cam_lock (re-exported above).


@dataclass(frozen=True)
class BestOfConfig:
    seeds: int
    seed_step: int
    fields: dict            # metric -> key in the scorer's JSON result
    reject: dict            # _REJECT_KEYS -> number
    eyes_window: float = 0.3                    # tiebreak.eyes_open_frac_lse_c_window
    eyes_apply_to: tuple = ("ltx_av",)          # engines whose seed choice may look at the eyes at all
    eyes_shut: dict = field(default_factory=dict)   # eye_blink_min, look_down_max, min_duration_s (provisional)
    start_blink_warn: float | None = 0.5        # start_frame.eye_blink_warn (warning only)
    grin_review_only: tuple = ()                # line / shot ids: grin is a review flag there, not a reject
    info: dict = field(default_factory=dict)    # grin_def (expected), grin_smile_on
    report_fields: tuple = ()                   # recorded per seed when present, never gate
    recipe: str = "L1c"                         # L1c (default) | best_of_fallback (the older pick, by setting only)
    l1c: dict = field(default_factory=dict)     # the preset's "l1c" block (stage rules, stage-2 params, framing, cost)
    eyeline: dict = field(default_factory=dict)  # window_s, drop_warn, end_warn (provisional, warn only); {} = off

    def field(self, metric: str) -> str:
        return self.fields.get(metric) or metric


def best_of_config(path=None, env: dict | None = None) -> BestOfConfig:
    """presets/lipsync_best_of.json (or OPENSOUL_BEST_OF_CONFIG / ``path``), then the env overrides on top.
    A missing file or key raises: the shipped file holds every value (no second copy of the defaults in code)."""
    import os

    env = os.environ if env is None else env
    f = Path(path or env.get("OPENSOUL_BEST_OF_CONFIG") or BEST_OF_CONFIG)
    data = json.loads(f.read_text(encoding="utf-8"))
    fields = {k: str(data["fields"][k] if k not in EYELINE_FIELDS else data["fields"].get(k, k)) for k in FIELD_KEYS}
    reject = {k: float(data["reject"][k]) for k in _REJECT_KEYS}
    seeds, step = int(data["seeds"]), int(data.get("seed_step", 1))
    window = float(data["tiebreak"]["eyes_open_frac_lse_c_window"])
    review_only = [str(x) for x in data.get("grin_review_only") or []]
    for k, var in _ENV_REJECT.items():
        if (env.get(var) or "").strip():
            reject[k] = float(env[var])
    for k in FIELD_KEYS:
        v = (env.get(f"OPENSOUL_BEST_OF_FIELD_{k.upper()}") or "").strip()
        if v:
            fields[k] = v
    if (env.get("OPENSOUL_BEST_OF_SEEDS") or "").strip():
        seeds = int(env["OPENSOUL_BEST_OF_SEEDS"])
    if (env.get("OPENSOUL_BEST_OF_SEED_STEP") or "").strip():
        step = int(env["OPENSOUL_BEST_OF_SEED_STEP"])
    if (env.get("OPENSOUL_BEST_OF_EYES_TIEBREAK_WINDOW") or "").strip():
        window = float(env["OPENSOUL_BEST_OF_EYES_TIEBREAK_WINDOW"])
    if env.get("OPENSOUL_BEST_OF_GRIN_REVIEW_ONLY") is not None:
        review_only = [x.strip() for x in env["OPENSOUL_BEST_OF_GRIN_REVIEW_ONLY"].split(",") if x.strip()]
    if seeds < 1 or step < 1:
        raise ValueError("best-of seeds and seed_step must be at least 1")
    recipe = str((env.get(RECIPE_ENV) or "").strip() or data.get("recipe") or RECIPE_L1C)
    if recipe.lower() == RECIPE_L1C.lower():
        recipe = RECIPE_L1C
    elif recipe.lower() in (RECIPE_LEGACY, "legacy", "fallback"):
        recipe = RECIPE_LEGACY
    else:
        raise ValueError(f"Unknown lip-sync recipe {recipe!r}: {RECIPE_L1C} or {RECIPE_LEGACY}")
    l1c = json.loads(json.dumps(data.get("l1c") or {}))
    if recipe == RECIPE_L1C and not l1c:
        raise KeyError("l1c")
    if l1c:
        s2 = l1c.setdefault("stage2", {})
        if (env.get(STAGE2_ENV) or "").strip():
            s2["mode"] = env[STAGE2_ENV].strip().lower()
        if (env.get(STAGE2_REBUILT_ENV) or "").strip():
            s2["default_on_rebuilt"] = env[STAGE2_REBUILT_ENV].strip().lower() in ("1", "on", "true", "yes")
        if env.get(STAGE2_VOICES_ENV) is not None:
            s2["default_on_voices"] = [x.strip() for x in env[STAGE2_VOICES_ENV].split(",") if x.strip()]
        if (env.get(INNER_MOUTH_ENV) or "").strip():
            s2.setdefault("inner_mouth", {})["enabled"] = env[INNER_MOUTH_ENV].strip().lower() in (
                "1", "on", "true", "yes")
    return BestOfConfig(seeds=seeds, seed_step=step, fields=fields, reject=reject, eyes_window=window,
                        eyes_apply_to=tuple(data["eyes_rules_apply_to"]), eyes_shut=dict(data["eyes_shut"]),
                        start_blink_warn=data["start_frame"].get("eye_blink_warn"),
                        grin_review_only=tuple(review_only), info=dict(data["info"]),
                        report_fields=tuple(data.get("report_fields") or ()), recipe=recipe, l1c=l1c,
                        eyeline={k: v for k, v in (data.get("eyeline") or {}).items() if not k.startswith("_")})


_LINE_IN_NAME = re.compile(r"(?<![a-z0-9])l(\d{1,3})(?![0-9])", re.I)


def norm_line_id(x) -> str:
    """'l7' / 'L07' / '7' / 7 -> 'l07'; any other non-empty id -> lower-case as given; nothing -> ''."""
    t = str(x if x is not None else "").strip()
    m = re.fullmatch(r"[lL]?0*(\d{1,3})", t)
    return f"l{int(m.group(1)):02d}" if m else t.lower()


def resolve_line_id(line=None, names=(), wav=None, position: int | None = None) -> tuple[str, str | None]:
    """(line id, where it came from) for grin_review_only, in the tools' order: an explicit line field ('line'), else
    'lNN' in the take / shot name ('name'; ``names`` in order), else 'lNN' in the wav file name ('wav'). The app
    adds a last fallback the tools don't have: the shot's 1-based position in the story ('position', l07 = 7th)."""
    if str(line or "").strip():
        return norm_line_id(line), "line"
    for n in [names] if isinstance(names, str) else list(names or ()):
        m = _LINE_IN_NAME.search(str(n or ""))
        if m:
            return f"l{int(m.group(1)):02d}", "name"
    if wav:
        m = _LINE_IN_NAME.search(Path(str(wav)).name)
        if m:
            return f"l{int(m.group(1)):02d}", "wav"
    if position:
        return f"l{int(position):02d}", "position"
    return "", None


def grin_review_only_for(line_id, cfg: BestOfConfig | None = None) -> bool:
    """Is this line (an id, normalised by norm_line_id) listed in grin_review_only?"""
    cfg = cfg or best_of_config()
    return bool(line_id) and norm_line_id(line_id) in {norm_line_id(x) for x in cfg.grin_review_only}


def eyes_shut_of(m: dict | None, cfg: BestOfConfig | None = None) -> dict:
    """{"flag", "max_s", "from"} for one scored seed. The scorer's eyes_shut_flag / eyes_shut_max_s win when present
    ('scorer'; max_s only -> flag = max_s > min_duration_s, 'scorer_max_s'). Else the scorer's per-frame series
    (eye_blink_frames, eye_look_down_frames, fps; None = no face, breaks the run): a frame is shut when blink >=
    eye_blink_min and look-down < look_down_max ('frames'). Nothing usable -> flag None, 'from' None."""
    cfg = cfg or best_of_config()
    m = m or {}
    t = cfg.eyes_shut
    min_s = float(t.get("min_duration_s", 1.0))
    flag, max_s = m.get(cfg.field("eyes_shut_flag")), _num(m.get(cfg.field("eyes_shut_max_s")))
    if isinstance(flag, bool):
        return {"flag": flag, "max_s": max_s, "from": "scorer"}
    if max_s is not None:
        return {"flag": max_s > min_s, "max_s": max_s, "from": "scorer_max_s"}
    blink, down = m.get(cfg.field("eye_blink_frames")), m.get(cfg.field("eye_look_down_frames"))
    fps = _num(m.get(cfg.field("fps")))
    if isinstance(blink, list) and isinstance(down, list) and blink and fps and fps > 0:
        bmin, dmax = float(t.get("eye_blink_min", 0.6)), t.get("look_down_max")
        run = best = 0
        for b, d in zip(blink, down):
            b, d = _num(b), _num(d)
            shut = b is not None and b >= bmin and (dmax is None or (d is not None and d < float(dmax)))
            run = run + 1 if shut else 0
            best = max(best, run)
        max_s = round(best / fps, 3)
        return {"flag": max_s > min_s, "max_s": max_s, "from": "frames"}
    return {"flag": None, "max_s": None, "from": None}



def eyeline_of(m: dict | None, cfg: BestOfConfig | None = None) -> dict | None:
    """First/last eyeline check for one scored take (warn only: never a reject, a review reason or a fallback).

    The look score is how much the eyes look at the listener (1) rather than drift to the lens (0). Start / end come
    from the scorer's start_eye_look_listener / end_eye_look_listener ('scorer'), else from the per-frame series
    eye_look_listener_frames ('frames'): the mean over the first / last ``window_s`` (with fps; else one frame),
    frames without a face (None) left out. Warn when the end is below ``end_warn`` or falls by ``drop_warn`` or more
    from the start (provisional: 0.3 and 0.3; 0.68 -> 0.19 warns). No usable end value, or no eyeline block in the
    preset -> None (skipped quietly).

    The scorer's own ``eyeline_drift_warn`` (bool), when present, decides the warning ('scorer_flag'; the numbers are
    still recorded when there are any). Its per-frame values may be 1 / 0 (look >= 0.3 or not) with null for no face;
    the whole eyeline group is omitted when the shot has no listener."""
    cfg = cfg or best_of_config()
    t = cfg.eyeline
    if not t or not m:
        return None
    flag = m.get(cfg.field("eyeline_drift_warn"))
    flag = flag if isinstance(flag, bool) else None
    start = _num(m.get(cfg.field("start_eye_look_listener")))
    end = _num(m.get(cfg.field("end_eye_look_listener")))
    src, n = ("scorer" if end is not None else None), None
    series = m.get(cfg.field("eye_look_listener_frames"))
    if end is None and isinstance(series, list) and series:
        fps = _num(m.get(cfg.field("fps")))
        n = max(1, round(float(t.get("window_s", 0.25)) * fps)) if fps and fps > 0 else 1

        def mean(xs):
            xs = [x for x in (_num(v) for v in xs) if x is not None]
            return round(sum(xs) / len(xs), 3) if xs else None

        end = mean(series[-n:])
        start = start if start is not None else mean(series[:n])
        src = "frames" if end is not None else None
    if end is None and flag is None:
        return None
    end_warn, drop_warn = float(t.get("end_warn", 0.3)), float(t.get("drop_warn", 0.3))
    drop = round(start - end, 3) if start is not None and end is not None else None
    why = []
    if flag is not None:  # the scorer decided
        src = "scorer_flag"
        if flag:
            why.append(f"the scorer flags it ({cfg.field('eyeline_drift_warn')})")
    else:
        if end < end_warn:
            why.append(f"look at the listener ends at {end:.2f} (< {end_warn:g})")
        if drop is not None and drop >= drop_warn:
            why.append(f"falls {drop:.2f} from {start:.2f} (>= {drop_warn:g})")
    return {"start": start, "end": end, "drop": drop, "from": src, "window_frames": n, "warn": bool(why),
            "why": why, "scorer_flag": flag, "thresholds": {"end_warn": end_warn, "drop_warn": drop_warn}}


def eyeline_warnings(row: dict | None) -> list[str]:
    """[EYELINE_WARNING] when the row's eyeline check warns, else []."""
    e = (row or {}).get("eyeline")
    return [EYELINE_WARNING] if e and e.get("warn") else []


ONLY_IF_ALL_REJECTED = "best_of_all_rejected"   # the LatentSync stage's condition in a best-of plan
BEST_OF_ENV = "OPENSOUL_LIPSYNC_BEST_OF"        # auto (default: rebuilt characters only) | on | off
REBUILT_KEY = "rebuilt"                          # character pack field (top level or meta): true / false


def is_rebuilt(pack: dict | None) -> bool:
    """A rebuilt character: its pack says ``"rebuilt": true`` (top level or meta). Without the field, a pack made from
    text in Create (meta.origin.kind == "text", open models only) counts as rebuilt; ``"rebuilt": false`` opts out."""
    pack = pack or {}
    meta = pack.get("meta") or {}
    for src in (pack, meta):
        if isinstance(src.get(REBUILT_KEY), bool):
            return src[REBUILT_KEY]
    origin = meta.get("origin") if isinstance(meta.get("origin"), dict) else {}
    return origin.get("kind") == "text"


def best_of_for(pack: dict | None, env: dict | None = None) -> int:
    """How many seeds a Final ltx_av talking shot renders: the configured count for rebuilt characters (setting ``auto``, the
    default), for everyone (``on``) or nobody (``off``); 1 = the single-seed take."""
    import os

    v = ((os.environ if env is None else env).get(BEST_OF_ENV) or "auto").strip().lower()
    if v in ("0", "off", "false", "no"):
        return 1
    if v in ("1", "on", "true", "yes"):
        return best_of_config(env=env).seeds
    return best_of_config(env=env).seeds if is_rebuilt(pack) else 1


def scorer_enabled() -> bool:
    """OS-057: True only when the optional external lip-sync scorer is set up (opensoul.lipsync_scorer config)."""
    try:
        from opensoul import lipsync_scorer

        return bool(lipsync_scorer.load_config().enabled)
    except Exception:  # noqa: BLE001  a bad scorer config means no scorer
        return False


def best_of_seed_list(seed: int, n: int | None = None, cfg: BestOfConfig | None = None) -> list[int]:
    cfg = cfg or best_of_config()
    return [int(seed) + k * cfg.seed_step for k in range(max(1, int(n or cfg.seeds)))]


def reseed_a2v(stage: dict, seed: int) -> dict:
    """The a2v stage with both noise seeds set to ``seed`` (a copy)."""
    st = json.loads(json.dumps(stage))
    for nid in (N_NOISE_1, N_NOISE_2):
        st.setdefault("inputs", {}).setdefault(nid, {})["noise_seed"] = int(seed)
    return st


def _num(v):
    try:
        return None if v is None or isinstance(v, bool) else float(v)
    except (TypeError, ValueError):
        return None


def seed_checks(metrics: dict | None, cfg: BestOfConfig | None = None, *, grin_review_only: bool = False,
                rules_on=GATE_RULES) -> tuple[list[str], list[str], list[str]]:
    """(reject reasons, undecided rules 'scorer_failed:<field>', review flags) for one scored seed.

    Rejects: |offset|, open_frac, grin v2 (grin_frac, grin_win_max). A grin_def other than the expected one
    (info.grin_def) -> 'scorer_failed:grin_def' and the grin rules are not applied (the thresholds don't fit the old
    geometry); no grin_def reported = trusted. ``grin_review_only`` (the line is listed in grin_review_only): a grin
    becomes a review flag instead of a reject. Eyes never reject here (see choose_seed's tiebreak and eyes_shut_flag).
    ``rules_on``: the gate rules to apply (default all four; the L1c base uses open_frac and the grin rules only)."""
    cfg = cfg or best_of_config()
    m = metrics or {}
    r = cfg.reject
    reasons: list[str] = []
    unknown: list[str] = []
    review: list[str] = []
    want = cfg.info.get("grin_def")
    got = m.get(cfg.field("grin_def"))
    grin_ok = not (got not in (None, "") and want and str(got) != str(want))
    if not grin_ok and any(x in GRIN_RULES for x in rules_on):
        unknown.append(f"scorer_failed:{cfg.field('grin_def')}")
    rules = (  # metric, rejects(value), reason(value)
        ("offset", lambda v: abs(v) >= r["abs_offset_min"],
         lambda v: f"offset {v:g} frames (|offset| >= {r['abs_offset_min']:g})"),
        ("open_frac", lambda v: v <= r["open_frac_max"],
         lambda v: f"lips closed through the speech (open_frac {v:g})"),
        ("grin_frac", lambda v: v > r["grin_frac_max"], lambda v: f"grin (grin_frac {v:g} > {r['grin_frac_max']:g})"),
        ("grin_win_max", lambda v: v > r["grin_win_max"],
         lambda v: f"grin burst (grin_win_max {v:g} > {r['grin_win_max']:g})"),
    )
    for metric, bad, why in rules:
        if metric not in rules_on or (metric in GRIN_RULES and not grin_ok):
            continue
        key = cfg.field(metric)
        v = _num(m.get(key))
        if v is None:
            unknown.append(f"scorer_failed:{key}")
        elif bad(v):
            (review if metric in GRIN_RULES and grin_review_only else reasons).append(why(v))
    es = eyes_shut_of(m, cfg)
    if es["flag"]:
        review.append("eyes shut" + (f" {es['max_s']:.2f} s" if es["max_s"] is not None else "") + " (eyes_shut_flag)")
    return reasons, unknown, review


def choose_seed(seeds: list[dict], cfg: BestOfConfig | None = None, *, engine: str = "ltx_av",
                grin_review_only: bool = False) -> dict:
    """Pick among scored seeds. Each seed: {"seed", "file", "metrics": dict | None, "error": str | None}.

    * A seed with no numeric lse_c (scorer error, lse_c null) is scorer_failed and can't be ranked.
    * Survivors = scored seeds no rule rejects; the highest LSE-C wins. Seeds whose only problem is a missing field
      (the rule couldn't be decided) rank after fully checked survivors and keep a scorer_failed flag for that rule.
    * Tiebreak (``engine`` in eyes_rules_apply_to, i.e. ltx_av seeds only): among the survivors within
      tiebreak.eyes_open_frac_lse_c_window of the best LSE-C, the highest eyes_open_frac wins. Eyes never reject.
    * Every seed rejected -> the highest LSE-C among them, needs_review, LatentSync fallback allowed.
    * Nothing scored -> seed 1, scorer_failed.
    * Review flags on the chosen seed (eyes_shut_flag, a grin on a grin_review_only line) -> needs_review too, with
      the reason in needs_review_reasons; they never allow the LatentSync fallback (only all_rejected does).
    * Tiebreak: a seed with eyes_shut_flag loses ties to an unflagged one; ``tiebreak.decided`` says when it changed
      the pick. A start-frame eyeBlink >= start_frame.eye_blink_warn adds the warning START_FRAME_WARNING.
    Returns {"status": picked | all_rejected | scorer_failed, "chosen": index, "seed", "file", "lse_c", "needs_review",
    "review", "scorer_failed", "latentsync_fallback_allowed", "flags", "seeds": [per-seed record]}."""
    cfg = cfg or best_of_config()
    rows = []
    for i, s in enumerate(seeds):
        m = dict(s.get("metrics") or {})
        c = _num(m.get(cfg.field("lse_c")))
        row = {"seed": s.get("seed"), "file": str(s.get("file")) if s.get("file") else None,
               **{k: m.get(cfg.field(k)) for k in METRICS},
               "report": {k: m[k] for k in cfg.report_fields if k in m}, "error": s.get("error")}
        es = eyes_shut_of(m, cfg)
        row.update(eyes_shut_flag=es["flag"], eyes_shut_max_s=es["max_s"], eyes_shut_from=es["from"])
        row["eyeline"] = eyeline_of(m, cfg)
        if c is None:
            row.update(rejected=True, reasons=["scorer_failed" + (f": {s['error']}" if s.get("error") else
                                                                  f": no numeric {cfg.field('lse_c')}")],
                       unknown=[], review=[])
        else:
            reasons, unknown, review = seed_checks(m, cfg, grin_review_only=grin_review_only)
            row.update(rejected=bool(reasons), reasons=reasons, unknown=unknown, review=review)
        row["lse_c"] = c
        rows.append(row)
    scored = [i for i, r in enumerate(rows) if r["lse_c"] is not None]
    clean = [i for i in scored if not rows[i]["rejected"] and not rows[i]["unknown"]]
    partial = [i for i in scored if not rows[i]["rejected"] and rows[i]["unknown"]]
    best = lambda ids: max(ids, key=lambda i: (rows[i]["lse_c"], -i))  # noqa: E731  ties: the earlier seed
    flags: list[str] = []
    tiebreak = None
    if not scored:
        status, chosen = "scorer_failed", 0
        flags.append("scorer_failed")
    elif clean or partial:
        pool = clean or partial
        status, chosen = "picked", best(pool)
        if engine in cfg.eyes_apply_to:
            top, first = rows[chosen]["lse_c"], chosen
            near = [i for i in pool if top - rows[i]["lse_c"] <= cfg.eyes_window + 1e-9]
            eyes = lambda i: _num(rows[i]["eyes_open_frac"])  # noqa: E731
            shut = lambda i: rows[i]["eyes_shut_flag"] is True  # noqa: E731
            if len(near) > 1 and (any(eyes(i) is not None for i in near) or any(shut(i) for i in near)):
                # an eyes_shut_flag seed loses ties to an unflagged one, then the higher eyes_open_frac, then LSE-C
                chosen = max(near, key=lambda i: (not shut(i), eyes(i) if eyes(i) is not None else -1.0,
                                                  rows[i]["lse_c"], -i))
                by = None
                if chosen != first:
                    by = "eyes_shut_flag" if shut(first) and not shut(chosen) else "eyes_open_frac"
                tiebreak = {"by": by, "decided": chosen != first, "window": cfg.eyes_window,
                            "candidates": [rows[i]["seed"] for i in near], "highest_lse_c_seed": rows[first]["seed"],
                            "changed": chosen != first}
        if not clean:
            flags += ["scorer_failed"] + rows[chosen]["unknown"]
    else:
        status, chosen = "all_rejected", best(scored)
        flags.append("needs_review")
    for i, r in enumerate(rows):
        r["chosen"] = i == chosen
    c = rows[chosen]
    review = list(c.get("review") or [])
    if review and "needs_review" not in flags:
        flags.append("needs_review")
    reasons = (["every seed was rejected"] if status == "all_rejected" else []) + review
    starts = [_num(r.get("start_eye_blink")) for r in rows]
    start = next((x for x in starts if x is not None), None)
    warnings = []
    if start is not None and cfg.start_blink_warn is not None and start >= float(cfg.start_blink_warn):
        warnings.append(START_FRAME_WARNING)
    warnings += eyeline_warnings(c)
    return {"status": status, "chosen": chosen, "seed": c["seed"], "file": c["file"], "lse_c": c["lse_c"],
            "needs_review": status == "all_rejected" or bool(review), "review": review,
            "needs_review_reasons": reasons, "warnings": warnings, "start_eye_blink": start,
            "tiebreak_decided": bool(tiebreak and tiebreak["decided"]),
            "scorer_failed": "scorer_failed" in flags, "latentsync_fallback_allowed": status == "all_rejected",
            "flags": flags, "n": len(rows), "engine": engine, "tiebreak": tiebreak, "grin_review_only": grin_review_only,
            "method": REBUILT_METHOD, "rules": dict(cfg.reject), "fields": dict(cfg.fields), "info": dict(cfg.info),
            "eyes_shut_thresholds": {k: v for k, v in cfg.eyes_shut.items() if not k.startswith("_")},
            "seeds": rows}


# ---------------------------------------------------------------- L1c (default recipe for talking shots)
# Grin-gated + camera-locked a2v base (eyes open, looking at the listener) -> LatentSync, MediaPipe only.
# Stage 1 (base): best-of-N a2v seeds gated on LOOK (open_frac, grin v2; never offset or lse_c) and on CAMERA
# (scale drift ≤ 0.5%, translation ≤ 1 px; a fail re-seeds, never LatentSync). Ranked by eyes_open_frac then lse_c.
# The a2v graph itself pins the last frame with native LTXVAddGuide (OPENSOUL_A2V_CAMLOCK=off restores the old graph).
# Stage 2 (mouth): LatentSync 1.6 through the OpenSoul wrapper (MediaPipe face detector only, guidance 2.0, 50 steps,
# seed 1247). The camera is re-checked on the output (same limits); a post-LS cam fail or a grin re-picks the next
# base (never re-runs LatentSync with other settings). The inner-mouth pass (L1c2) is optional, off by default. All
# numbers live in presets/lipsync_best_of.json ("l1c").
ONLY_IF_L1C_STAGE2 = "l1c_stage2"   # the L1c mouth stage's condition in a plan (run_shot decides with l1c_stage2_decision)


def l1c_cfg(cfg: BestOfConfig | None = None) -> dict:
    return (cfg or best_of_config()).l1c


def cam_cfg(cfg: BestOfConfig | None = None) -> dict:
    """l1c.cam thresholds (scale_drift_max_pct, trans_max_pct); empty when the preset has no cam block."""
    return dict(l1c_cfg(cfg).get("cam") or {})


def l1c_stage2_params(cfg: BestOfConfig | None = None) -> dict:
    """The stage-2 settings as recorded and passed to the wrapper (no defaults in code: the preset holds them)."""
    s2 = l1c_cfg(cfg)["stage2"]
    im = s2["inner_mouth"]
    return {"backend": s2["backend"], "version": s2["version"], "face_detector": s2["face_detector"],
            "face_style": s2["face_style"], "guidance": float(s2["guidance"]), "steps": int(s2["steps"]),
            "seed": int(s2["seed"]),
            "inner_mouth": {"enabled": bool(im.get("enabled", False)), "experimental": bool(im.get("experimental", True)),
                            "runner": im["runner"], "settings": im["settings"], "args": list(im.get("args") or [])}}


def stage2_mode(cfg: BestOfConfig | None = None) -> str:
    m = str(l1c_cfg(cfg)["stage2"].get("mode") or "auto").lower()
    return {"1": "on", "true": "on", "yes": "on", "0": "off", "false": "off", "no": "off"}.get(m, m)


def voice_canonical(voice: str, cfg: BestOfConfig | None = None) -> str:
    """The canonical voice id for ``voice``: l1c.stage2.voice_aliases maps a canonical id ('F') to its other ids
    ('clip_F', 'revoice_F', 'qwen3_F'), matched case-insensitively; a canonical id given in any case comes back as
    written in the preset. Any other id comes back as given (stripped)."""
    v = str(voice or "").strip()
    aliases = l1c_cfg(cfg)["stage2"].get("voice_aliases") or {}
    for canon, alts in aliases.items():
        if canon.startswith("_") or not isinstance(alts, list):
            continue
        if v.lower() in {canon.strip().lower(), *(str(a).strip().lower() for a in alts)}:
            return canon.strip()
    return v


VOICE_LABEL_KEY = "voice_label"                              # optional pack field: lip-sync metadata only
VOICE_LABEL_NOTES_KEYS = ("voice_label_notes", "voice_notes")   # optional notes block next to it (either name)


def voice_label_of(pack: dict | None, cfg: BestOfConfig | None = None) -> dict:
    """The pack's optional ``voice_label`` (top level, else meta) resolved through the voice aliases:
    {"voice_label": 'F', "voice_canonical": 'F', "voice_label_notes": {...} | None}; {} without a label.
    Metadata for lip-sync notes and records only: the TTS never reads it (character_voices decides the voice)."""
    pack = pack if isinstance(pack, dict) else {}
    meta = pack.get("meta") if isinstance(pack.get("meta"), dict) else {}
    raw = next((str(src[VOICE_LABEL_KEY]).strip() for src in (pack, meta)
                if isinstance(src.get(VOICE_LABEL_KEY), str) and src[VOICE_LABEL_KEY].strip()), "")
    if not raw:
        return {}
    notes = next((src[k] for src in (pack, meta) for k in VOICE_LABEL_NOTES_KEYS if isinstance(src.get(k), dict)),
                 None)
    return {VOICE_LABEL_KEY: raw, "voice_canonical": voice_canonical(raw, cfg), "voice_label_notes": notes}


def stage2_default_on(voice: str, cfg: BestOfConfig | None = None) -> bool:
    """Stage 2 defaults ON for the voices in l1c.stage2.default_on_voices (voice ids, case-insensitive; 'F'), aliases
    included (voice_canonical: 'clip_F', 'revoice_F', 'qwen3_F' count as 'F')."""
    v = voice_canonical(voice, cfg).lower()
    return bool(v) and v in {str(x).strip().lower() for x in l1c_cfg(cfg)["stage2"].get("default_on_voices") or []}


def stage2_default_on_rebuilt(cfg: BestOfConfig | None = None) -> bool:
    """l1c.stage2.default_on_rebuilt (env OPENSOUL_L1C_STAGE2_REBUILT on/off overrides)."""
    return bool(l1c_cfg(cfg)["stage2"].get("default_on_rebuilt", False))


def stage2_default_why(voice: str, rebuilt: bool = False, cfg: BestOfConfig | None = None, *, label: str = "") -> str:
    """Why stage 2 is on by default for this take ('' = it isn't): 'on by default for rebuilt characters' (a rebuilt
    speaker, l1c.stage2.default_on_rebuilt, whatever the voice), and/or 'voice F' / 'voice F (clip_F)' (the voice or
    one of its aliases is in default_on_voices). A pack ``label`` (voice_label) stands in for the voice id here:
    'voice F (voice_label F)'."""
    cfg = cfg or best_of_config()
    label = str(label or "").strip()
    v = label or str(voice or "").strip()
    canon = voice_canonical(v, cfg)
    if not stage2_default_on(v, cfg):
        vtxt = ""
    elif label:
        vtxt = f"voice {canon} (voice_label {label})"
    else:
        vtxt = f"voice {canon}" + (f" ({v})" if v and v != canon else "")
    if rebuilt and stage2_default_on_rebuilt(cfg):
        return "on by default for rebuilt characters" + (f" ({vtxt})" if vtxt else "")
    return f"on by default for {vtxt}" if vtxt else ""


def latentsync_cost_s(frames: int, cfg: BestOfConfig | None = None) -> float:
    """LatentSync GPU time hint: ceil(frames / 16) chunks x 35.3 s (measured on a DGX Spark)."""
    c = l1c_cfg(cfg)["cost"]
    n = max(0, int(frames))
    return round(math.ceil(n / int(c["latentsync_chunk_frames"])) * float(c["latentsync_s_per_chunk"]), 1)


def audio_frames(audio_s: float, fps: int = FPS) -> int:
    """Frames that cover the voice (the length the base is trimmed to)."""
    return max(1, math.ceil(float(audio_s) * fps - 1e-6))


def framing_warnings(face_h_frac=None, yaw=None, cfg: BestOfConfig | None = None) -> list[str]:
    """Warning only (talk shots): face taller than framing.face_h_frac_warn of the frame, or |yaw| over
    framing.abs_yaw_warn. No data -> no warning."""
    f = l1c_cfg(cfg).get("framing") or {}
    lo, hi = (f.get("recommend_face_h_frac") or [0.25, 0.30])[:2]
    tip = (f"A medium start frame (face about {lo * 100:.0f}-{hi * 100:.0f}% of the frame height), cropped in during "
           "the edit, lip-syncs better.")
    out = []
    h, y = _num(face_h_frac), _num(yaw)
    if h is not None and f.get("face_h_frac_warn") is not None and h > float(f["face_h_frac_warn"]):
        out.append(f"Framing: the face is {h * 100:.0f}% of the frame height (over "
                   f"{float(f['face_h_frac_warn']) * 100:.0f}%). {tip}")
    if y is not None and f.get("abs_yaw_warn") is not None and abs(y) > float(f["abs_yaw_warn"]):
        out.append(f"Framing: the head is turned (yaw {y:+.2f}, over {float(f['abs_yaw_warn']):.2f}). "
                   "A start frame facing the listener or camera syncs better.")
    return out


def framing_from_face_box(face_box, frame_h, cfg: BestOfConfig | None = None) -> list[str]:
    """framing_warnings from the shot's face_box (x, y, w, h on frame 0, output pixels); none without a box."""
    if not face_box or not frame_h:
        return []
    return framing_warnings(float(face_box[3]) / float(frame_h), None, cfg)


def choose_base(seeds: list[dict], cfg: BestOfConfig | None = None, *, grin_review_only: bool = False,
                cam_lock: bool | None = None) -> dict:
    """L1c stage 1: pick the base among scored seeds, gated on look and (when on) camera.

    * Reject: l1c.base_reject (open_frac == 0, grin_frac > 0.3, grin_win_max > 0.15); never offset, never lse_c.
    * Camera (default on, :func:`cam_lock_enabled`): each seed may carry ``cam`` (from :func:`score_cam`). A FAIL or
      ERROR rejects that base (re-seed / next best-of-N); LatentSync is never run on a cam-fail base. Missing ``cam``
      when the lock is on is not a reject (the caller didn't score it — tests / dry-run).
    * Rank the passing bases: an eyes_shut_flag base after unflagged ones, then eyes_open_frac, then lse_c (missing
      values rank last). ``order`` lists every passing base in that order (stage 2 re-picks down it).
    * A seed with no metrics at all (scorer error) is scorer_failed; no seed scored -> seed 1, scorer_failed.
    * Every seed rejected -> the best-ranked among them, needs_review; no LatentSync fallback (it can't fix a grin
      or a drifting camera).
    Same record shape as choose_seed, plus recipe, order, pick_why, cam on each seed, and stage1_passes_all_gates
    (the pick passes every output gate, offset included, with nothing undecided, and cam PASS when checked)."""
    cfg = cfg or best_of_config()
    l1 = cfg.l1c
    base_rules = tuple(l1["base_reject"])
    out_rules = tuple(l1["output_reject"])
    lock = cam_lock_enabled() if cam_lock is None else bool(cam_lock)
    ccfg = cam_cfg(cfg)
    rows = []
    for s in seeds:
        m = dict(s.get("metrics") or {})
        cam = s.get("cam")
        row = {"seed": s.get("seed"), "file": str(s.get("file")) if s.get("file") else None,
               **{k: m.get(cfg.field(k)) for k in METRICS},
               "report": {k: m[k] for k in cfg.report_fields if k in m}, "error": s.get("error"),
               "cam": cam}
        es = eyes_shut_of(m, cfg)
        row.update(eyes_shut_flag=es["flag"], eyes_shut_max_s=es["max_s"], eyes_shut_from=es["from"])
        row["eyeline"] = eyeline_of(m, cfg)
        row["lse_c"] = _num(m.get(cfg.field("lse_c")))
        if not s.get("metrics"):
            row.update(rejected=True, reasons=["scorer_failed" + (f": {s['error']}" if s.get("error") else
                                                                  ": no result")], unknown=[], review=[],
                       gate_reasons=[], scored=False)
        else:
            reasons, unknown, review = seed_checks(m, cfg, grin_review_only=grin_review_only, rules_on=base_rules)
            g_reasons, g_unknown, _ = seed_checks(m, cfg, grin_review_only=grin_review_only, rules_on=out_rules)
            if lock and cam is not None and not cam_passes(cam):
                why = cam_reject_reason(cam, ccfg)
                if why:
                    reasons.append(why)
            row.update(rejected=bool(reasons), reasons=reasons, unknown=unknown, review=review,
                       gate_reasons=g_reasons, gate_unknown=g_unknown, scored=True)
        rows.append(row)

    def rank(i):
        r = rows[i]
        e, c = _num(r["eyes_open_frac"]), r["lse_c"]
        return (r["eyes_shut_flag"] is not True, e if e is not None else -1.0, c if c is not None else -1e9, -i)

    scored = [i for i, r in enumerate(rows) if r["scored"]]
    clean = sorted([i for i in scored if not rows[i]["rejected"] and not rows[i]["unknown"]], key=rank, reverse=True)
    partial = sorted([i for i in scored if not rows[i]["rejected"] and rows[i]["unknown"]], key=rank, reverse=True)
    flags: list[str] = []
    if not scored:
        status, chosen, order = "scorer_failed", 0, [0]
        flags.append("scorer_failed")
    elif clean or partial:
        order = clean + partial
        status, chosen = "picked", order[0]
        if not clean:
            flags += ["scorer_failed"] + rows[chosen]["unknown"]
    else:
        status, order = "all_rejected", []
        chosen = max(scored, key=rank)
        flags.append("needs_review")
    for i, r in enumerate(rows):
        r["chosen"] = i == chosen
    c = rows[chosen]
    review = list(c.get("review") or [])
    if review and "needs_review" not in flags:
        flags.append("needs_review")
    reasons = (["every base was rejected on look or camera (grin, closed lips, or camera drift)"] if status == "all_rejected" else []) + review
    e = _num(c["eyes_open_frac"])
    if status == "picked":
        why = (f"passes the look checks; best eyes_open_frac ({e:.2f})" if e is not None else
               "passes the look checks (no eyes_open_frac)")
        why += f", lse_c {c['lse_c']:.2f}" if c["lse_c"] is not None else ""
        if c["eyes_shut_flag"]:
            why += "; eyes_shut_flag (every passing base is flagged)"
        if len(order) > 1:
            why += f"; next passing bases {[rows[i]['seed'] for i in order[1:]]}"
    elif status == "all_rejected":
        why = "no base passed the look checks; kept the best-ranked one"
    else:
        why = "not scored: the lip-sync scorer isn't available"
    cam_ok = (not lock) or c.get("cam") is None or cam_passes(c.get("cam"))
    passes = (status == "picked" and not c.get("gate_reasons") and not c.get("gate_unknown") and cam_ok)
    starts = [_num(r.get("start_eye_blink")) for r in rows]
    start = next((x for x in starts if x is not None), None)
    warnings = []
    if start is not None and cfg.start_blink_warn is not None and start >= float(cfg.start_blink_warn):
        warnings.append(START_FRAME_WARNING)
    warnings += eyeline_warnings(c)
    fh = next((x for x in (_num(r.get("start_face_h_frac")) for r in rows) if x is not None), None)
    yw = next((x for x in (_num(r.get("start_yaw")) for r in rows) if x is not None), None)
    warnings += framing_warnings(fh, yw, cfg)
    return {"status": status, "chosen": chosen, "seed": c["seed"], "file": c["file"], "lse_c": c["lse_c"],
            "eyes_open_frac": c["eyes_open_frac"], "needs_review": status == "all_rejected" or bool(review),
            "review": review, "needs_review_reasons": reasons, "warnings": warnings, "start_eye_blink": start,
            "tiebreak_decided": False, "tiebreak": None,
            "scorer_failed": "scorer_failed" in flags, "latentsync_fallback_allowed": False,
            "flags": flags, "n": len(rows), "engine": "ltx_av", "grin_review_only": grin_review_only,
            "method": REBUILT_METHOD, "recipe": RECIPE_L1C, "order": order,
            "order_seeds": [rows[i]["seed"] for i in order], "pick_why": why,
            "stage1_passes_all_gates": passes, "base_rules": list(base_rules), "output_rules": list(out_rules),
            "rank_by": ["not eyes_shut_flag", *l1["base_rank"]],
            "rules": dict(cfg.reject), "fields": dict(cfg.fields), "info": dict(cfg.info),
            "eyes_shut_thresholds": {k: v for k, v in cfg.eyes_shut.items() if not k.startswith("_")},
            "cam_lock": lock, "cam": c.get("cam"), "seeds": rows}


def l1c_stage2_decision(base_res: dict | None, stage: dict, cfg: BestOfConfig | None = None) -> tuple[bool, str]:
    """(run stage 2?, why). Setting off -> never; on -> always; default (auto): on for the voices in
    default_on_voices ('F'), else skipped when the stage-1 pick already passes every gate. A base that couldn't be
    picked (every base rejected on look) is never re-mouthed: LatentSync keeps the base's grin."""
    cfg = cfg or best_of_config()
    if not base_res or base_res.get("status") == "dry_run":
        return False, "dry run: the mouth pass runs in Studio mode"
    if base_res.get("status") == "all_rejected":
        return False, "no base passed the look checks (LatentSync can't remove a grin)"
    mode = stage.get("stage2_mode") or stage2_mode(cfg)
    if mode == "off":
        if stage.get("cam_lock") and not stage.get("mouth_refine"):
            return False, MOUTH_REFINE_OFF_NOTE
        return False, "off by setting"
    if mode == "on":
        return True, "on by setting"
    if stage.get("stage2_default_on"):
        why = stage.get("stage2_default_why")
        if not why:  # a plan from before stage2_default_why: the voice list
            v, canon = stage.get("voice"), stage.get("voice_canonical") or stage.get("voice")
            why = f"on by default for voice {canon}" + (f" ({v})" if v and v != canon else "")
        return True, why
    s2 = l1c_cfg(cfg)["stage2"]
    if s2.get("skip_when_stage1_passes", True) and base_res.get("stage1_passes_all_gates"):
        return False, "stage 1 already passes every check"
    why = "; ".join(next((r.get("gate_reasons") or [] for r in base_res.get("seeds") or [] if r.get("chosen")), []))
    return True, "stage 1 didn't pass every check" + (f" ({why})" if why else " (not fully scored)")


def run_l1c_stage2(base_res: dict, *, audio_s: float, frames_of, trim, latentsync, inner_mouth, score=None,
                   grin_review_only: bool = False, cfg: BestOfConfig | None = None, fps: int = FPS,
                   cam=None, cam_lock: bool | None = None) -> dict:
    """L1c stage 2 over the ranked passing bases (``base_res["order"]``). Injected steps (tests use fakes):
    ``frames_of(path) -> int | None``; ``trim(base, frames, seed) -> Path`` (first ``frames`` frames, never looped);
    ``latentsync(trimmed, seed) -> (Path, note | None)``; ``inner_mouth(synced, raw, seed) -> Path`` (only when the
    experimental inner-mouth toggle is on: params.inner_mouth.enabled);
    ``score(video, ref) -> dict`` (None: unscored); ``cam(video) -> dict`` (default :func:`score_cam` when camera lock
    is on).

    Per base: trim to the voice length (base shorter than the voice -> base_short, flagged for review, not
    re-mouthed); LatentSync with the stage-2 params; inner-mouth pass; score the OUTPUT with every gate; re-check the
    camera (same ≤ 0.5% / ≤ 1 px limits). A grin OR a post-LS cam fail in the output -> the next passing base
    (never LatentSync again with other settings). Other failing gates -> kept, needs_review. Every base grinning /
    cam-failing -> the first output is kept, needs_review. Returns the stage-2 record (each attempt records ``cam``).
    """
    from opensoul.lipsync_scorer import ScorerError

    cfg = cfg or best_of_config()
    l1 = cfg.l1c
    out_rules = tuple(l1["output_reject"])
    repick = set(l1.get("repick_on_output") or GRIN_RULES)
    lock = cam_lock_enabled() if cam_lock is None else bool(cam_lock)
    ccfg = cam_cfg(cfg)
    if cam is None and lock:
        cam = lambda v: score_cam(v, cfg_cam=ccfg)  # noqa: E731
    n_audio = audio_frames(audio_s, fps)
    rows = base_res.get("seeds") or []
    rec = {"recipe": RECIPE_L1C, "ran": True, "params": l1c_stage2_params(cfg), "audio_frames": n_audio,
           "base_length": l1.get("base_length", "trim"), "attempts": [], "repicks": 0, "file": None,
           "kept_base_seed": None, "output_scores": None, "output_reasons": [], "flags": [], "needs_review": False,
           "needs_review_reasons": [], "eyeline": None, "warnings": [], "cam_lock": lock, "cam": None}
    for k, idx in enumerate(base_res.get("order") or []):
        row = rows[idx]
        base = Path(row["file"])
        n_base = frames_of(base)
        att = {"base_seed": row["seed"], "base_file": str(base), "base_frames": n_base, "audio_frames": n_audio,
               "base_short": n_base is not None and n_base < n_audio}
        rec["attempts"].append(att)
        if att["base_short"]:
            att["skipped"] = (f"base_short: the base has {n_base} frames, the voice needs {n_audio} "
                              "(never looped)")
            if "base_short" not in rec["flags"]:
                rec["flags"].append("base_short")
            continue
        trimmed = Path(trim(base, n_audio, row["seed"]))
        att["trimmed_file"], att["trimmed_frames"] = str(trimmed), n_audio
        synced, note = latentsync(trimmed, row["seed"])
        if note:
            att["skipped"], att["latentsync_note"] = "latentsync: " + note, note
            continue
        att["synced_file"] = str(synced)
        out = Path(synced)
        if not rec["params"]["inner_mouth"]["enabled"] or inner_mouth is None:
            att["inner_mouth"] = "off (optional, experimental)"
        else:
            try:
                out = Path(inner_mouth(Path(synced), trimmed, row["seed"]))
                att["inner_mouth"] = "ok"
            except Exception as e:  # noqa: BLE001  keep the LatentSync output, flagged
                att["inner_mouth"] = f"failed: {str(e)[:200]}"
                if "inner_mouth_failed" not in rec["flags"]:
                    rec["flags"].append("inner_mouth_failed")
        att["file"] = str(out)
        scores, err = None, None
        if score is not None:
            try:
                scores = score(out, trimmed)
                if not isinstance(scores, dict):
                    scores, err = None, "bad_output: the scorer returned no result object"
            except ScorerError as e:
                err = f"{e.code}: {e}"
        att["scores"], att["score_error"] = scores, err
        att["eyeline"] = eyeline_of(scores, cfg)
        att_cam = cam(out) if cam is not None else None
        att["cam"] = att_cam
        if scores is None:
            att.update(reasons=[], unknown=["scorer_failed"], review=[], grin=False)
        else:
            reasons, unknown, review = seed_checks(scores, cfg, grin_review_only=grin_review_only, rules_on=out_rules)
            grin = any(r.startswith("grin") for r in reasons) and bool(repick & set(GRIN_RULES))
            att.update(reasons=reasons, unknown=unknown, review=review, grin=grin)
        cam_fail = bool(lock and att_cam is not None and not cam_passes(att_cam))
        att["cam_fail"] = cam_fail
        if att.get("grin") or cam_fail:
            more = k + 1 < len(base_res["order"])
            if att.get("grin") and cam_fail:
                why = "grin and camera drift in the output: the base was wrong"
            elif att.get("grin"):
                why = "grin in the output: the base was wrong"
            else:
                why = "camera drift after LatentSync: the base was wrong"
            att["result"] = why + ("; re-picking the next base" if more else "")
            if more:
                rec["repicks"] += 1
            continue
        att["result"] = "kept"
        break
    done = [a for a in rec["attempts"] if a.get("file")]
    kept = next((a for a in done if a.get("result") == "kept"), None)
    if kept is None and done:
        kept = done[0]
        kinds = []
        if any(a.get("grin") for a in done):
            kinds.append("grin")
        if any(a.get("cam_fail") for a in done):
            kinds.append("camera drift")
        rec["needs_review_reasons"].append(
            (" and ".join(kinds) if kinds else "fail") + " after the mouth pass on every passing base")
    if kept is not None:
        rec.update(file=kept["file"], kept_base_seed=kept["base_seed"], output_scores=kept.get("scores"),
                   output_reasons=list(kept.get("reasons") or []), output_unknown=list(kept.get("unknown") or []))
        rec["eyeline"] = kept.get("eyeline")
        rec["cam"] = kept.get("cam")
        rec["warnings"] = eyeline_warnings(kept)
        rec["needs_review_reasons"] += [r for r in kept.get("reasons") or [] if r not in rec["needs_review_reasons"]]
        rec["needs_review_reasons"] += list(kept.get("review") or [])
        if kept.get("cam_fail"):
            why = cam_reject_reason(kept.get("cam"), ccfg)
            if why and why not in rec["needs_review_reasons"]:
                rec["needs_review_reasons"].append(why)
        if kept.get("scores") is None:
            rec["flags"].append("scorer_failed")
    else:
        rec["needs_review_reasons"].append("no mouth pass output: the stage-1 take is kept")
    if "base_short" in rec["flags"]:
        rec["needs_review_reasons"].append("base_short: the base is shorter than the voice")
    rec["needs_review"] = bool(rec["needs_review_reasons"])
    if rec["needs_review"] and "needs_review" not in rec["flags"]:
        rec["flags"].append("needs_review")
    return rec


def l1c_note(rec: dict) -> str:
    """One line for the take about stage 2."""
    if not rec.get("ran"):
        return f"L1c mouth pass skipped: {rec.get('skip_reason')}."
    p = rec["params"]
    if not rec.get("file"):
        return f"L1c mouth pass: no output ({'; '.join(rec['needs_review_reasons'])}). Needs review."
    s = rec.get("output_scores") or {}
    c = _num(s.get("lse_c"))
    im = f" + inner mouth ({p['inner_mouth']['settings']}, experimental)" if p["inner_mouth"]["enabled"] else ""
    head = (f"L1c mouth pass: LatentSync {p['version']}, MediaPipe only (guidance {p['guidance']:g}, {p['steps']} "
            f"steps, seed {p['seed']}){im} over base seed {rec['kept_base_seed']}"
            + (f", LSE-C {c:.2f}" if c is not None else "") + ".")
    if rec.get("decision"):
        head += f" Ran because: {rec['decision']}."
    if rec.get("cam") and rec["cam"].get("cam_verdict"):
        camr = rec["cam"]
        head += (f" Camera after LatentSync: {camr.get('cam_verdict')}"
                 + (f" (scale {camr.get('scale_drift_max_pct')}%, trans {camr.get('trans_max_px')} px)."
                    if camr.get("scale_drift_max_pct") is not None else "."))
    if rec.get("repicks"):
        head += f" Re-picked the base {rec['repicks']}x (grin or camera drift in the output)."
    if rec.get("needs_review"):
        head += f" Needs review: {'; '.join(rec['needs_review_reasons'])}."
    head += "".join(f" Warning: {w}." for w in rec.get("warnings") or [])
    return head


def output_scorer(scorer=None):
    """``score(video, ref) -> dict`` for the L1c output: the caller's ``scorer(video)``, else the configured external
    scorer with the trimmed base as ``ref``, else None (not configured: the output is kept unscored, flagged)."""
    if scorer is not None:
        return lambda v, ref: scorer(v)
    from opensoul import lipsync_scorer

    if lipsync_scorer.enabled():
        return lambda v, ref: lipsync_scorer.score(v, ref=ref)
    return None


def trim_to_frames(src: Path, dest: Path, frames: int) -> Path:
    """The first ``frames`` frames of ``src`` (video only), re-encoded near-losslessly. Never loops."""
    from opensoul import media

    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-map", "0:v:0", "-frames:v", str(int(frames)),
           "-an", "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", str(dest)]
    return media._run(cmd, Path(dest))


def run_inner_mouth_cli(synced: Path, raw: Path, dest: Path, params: dict | None = None) -> Path:
    """The optional inner-mouth runner (``ls_inner_mouth.py SYNCED RAW -o OUT``; experimental toggle, off by default:
    it can leave black voids and hold the mouth open into a pause) with the L1c2 settings = its module defaults (no
    flags). Interpreter: OPENSOUL_INNER_MOUTH_PY, else this Python. Raises on failure."""
    import os
    import subprocess
    import sys

    im = (params or l1c_stage2_params())["inner_mouth"]
    py = os.environ.get("OPENSOUL_INNER_MOUTH_PY") or sys.executable
    runner = Path(__file__).resolve().parents[1] / im["runner"]
    cmd = [py, str(runner), str(synced), str(raw), "-o", str(dest), *im.get("args", [])]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if p.returncode != 0 or not Path(dest).is_file():
        raise RuntimeError(f"inner-mouth pass failed ({p.returncode}): {(p.stderr or '')[-400:]}")
    return Path(dest)


def best_of_seeds(stage: dict, render, score=None, *, ref=None, scorer_on: bool | None = None,
                  cfg: BestOfConfig | None = None, cam=None) -> dict:
    """Render and score the best-of seeds of an a2v ``stage`` (``stage["seeds"]``) and choose one (:func:`choose_seed`).

    ``render(stage_for_seed, seed) -> Path``; ``score(video) -> result dict`` (default: opensoul.lipsync_scorer.score
    with ``ref``; raises ScorerError). ``cam(video) -> dict`` (default: :func:`score_cam` when camera lock is on)
    attaches a camera check to each L1c seed; a FAIL re-seeds (never LatentSync). With no scorer (not configured)
    only the first seed is rendered: the take is kept as before, flagged scorer_failed. Nothing is deleted: the
    losing seeds' files stay where ``render`` put them."""
    from opensoul import lipsync_scorer

    cfg = cfg or best_of_config()
    lock = bool(stage.get("cam_lock")) if stage.get("cam_lock") is not None else cam_lock_enabled()
    if cam is None and lock and stage.get("recipe") == RECIPE_L1C:
        ccfg = cam_cfg(cfg)
        cam = lambda v: score_cam(v, cfg_cam=ccfg)  # noqa: E731
    if stage.get("line_id_from") not in ("line", "name"):  # the wav is known now: it comes before the position
        wav = ((stage.get("inputs") or {}).get(N_LOAD_AUDIO) or {}).get("audio")
        if wav:
            stage = {**stage, **_line_stage(stage.get("line_ref"), wav)}
    seeds = list(stage.get("seeds") or best_of_seed_list(_seed_of(stage), int(stage.get("best_of") or cfg.seeds), cfg))
    if score is None:
        on = lipsync_scorer.enabled() if scorer_on is None else scorer_on
        if on:
            score = lambda v: lipsync_scorer.score(v, ref=ref)  # noqa: E731
    if score is None:
        f = Path(render(reseed_a2v(stage, seeds[0]), seeds[0]))
        choose = choose_base if stage.get("recipe") == RECIPE_L1C else choose_seed
        row = {"seed": seeds[0], "file": f, "metrics": None,
               "error": "not_configured: the lip-sync scorer isn't set up"}
        if cam is not None:
            row["cam"] = cam(f)
        out = choose([row], cfg, grin_review_only=bool(stage.get("grin_review_only")),
                     **({"cam_lock": lock} if stage.get("recipe") == RECIPE_L1C else {}))
        out.update(line_id=stage.get("line_id"), line_id_from=stage.get("line_id_from"))
        out["skipped_seeds"] = seeds[1:]
        return out
    rows = []
    for sd in seeds:
        f = Path(render(reseed_a2v(stage, sd), sd))
        try:
            m, err = score(f), None
            if not isinstance(m, dict):
                m, err = None, "bad_output: the scorer returned no result object"
        except lipsync_scorer.ScorerError as e:  # lse_c null (no_face), timeout, bad output ...
            m, err = None, f"{e.code}: {e}"
        row = {"seed": sd, "file": f, "metrics": m, "error": err}
        if cam is not None:
            row["cam"] = cam(f)
        rows.append(row)
    if stage.get("recipe") == RECIPE_L1C:
        out = choose_base(rows, cfg, grin_review_only=bool(stage.get("grin_review_only")), cam_lock=lock)
    else:
        out = choose_seed(rows, cfg, engine="ltx_av", grin_review_only=bool(stage.get("grin_review_only")))
    out.update(line_id=stage.get("line_id"), line_id_from=stage.get("line_id_from"))
    out["skipped_seeds"] = []
    return out


def best_of_note(res: dict) -> str:
    """The one-line status for the take."""
    n = res.get("n", 1) + len(res.get("skipped_seeds") or [])
    if res["status"] == "scorer_failed":
        return f"Best of {n} takes skipped: the lip-sync scorer isn't available, so the first take is kept (not scored)."
    c = res.get("lse_c")
    warn = "".join(f" Warning: {w}." if w == EYELINE_WARNING else f" {w}." for w in res.get("warnings") or [])
    if res["status"] == "all_rejected":
        more = f" ({'; '.join(res['review'])})" if res.get("review") else ""
        cs = f", LSE-C {c:.2f}" if c is not None else ""
        return (f"Best of {n} takes: none passed the checks; kept the closest (seed {res['seed']}{cs}). "
                f"Needs review{more}.{warn}")
    extra = " Some checks couldn't be scored." if res.get("scorer_failed") else ""
    if res.get("review"):
        extra += f" Needs review: {'; '.join(res['review'])}."
    if res.get("recipe") == RECIPE_L1C:
        e = _num(res.get("eyes_open_frac"))
        why = ", ".join(x for x in (f"eyes open {e:.2f}" if e is not None else "",
                                    f"LSE-C {c:.2f}" if c is not None else "") if x)
        return f"Best of {n} takes: kept seed {res['seed']} (L1c base{': ' + why if why else ''}).{extra}{warn}"
    return f"Best of {n} takes: kept seed {res['seed']} (LSE-C {c:.2f}).{extra}{warn}"


def _seed_of(stage: dict) -> int:
    return int(((stage.get("inputs") or {}).get(N_NOISE_1) or {}).get("noise_seed") or 0)


def patch_graph(graph: dict, inputs: dict) -> dict:
    """Apply a stage's node inputs to a workflow graph (same merge the SDK run does), returning a copy."""
    g = json.loads(json.dumps(graph))
    for nid, vals in inputs.items():
        if nid in g:
            g[nid]["inputs"].update(vals)
    return g


def frozen_audio_feeds(graph: dict) -> dict[str, bool]:
    """For each AV concat node (base + refine pass): does its audio come from the frozen voice latent?
    (LTXVConcatAVLatent.audio_latent -> SetLatentNoiseMask(LTXVAudioVAEEncode(LoadAudio)))."""
    out = {}
    for nid in AV_CONCAT_NODES:
        src = (graph.get(nid, {}).get("inputs", {}).get("audio_latent") or [None])[0]
        node = graph.get(src or "", {})
        enc = graph.get((node.get("inputs", {}).get("samples") or [None])[0] or "", {})
        load = graph.get((enc.get("inputs", {}).get("audio") or [None])[0] or "", {})
        out[nid] = (node.get("class_type") == "SetLatentNoiseMask" and enc.get("class_type") == "LTXVAudioVAEEncode"
                    and load.get("class_type") == "LoadAudio")
    return out


def read_sidecar(out: Path) -> dict | None:
    """The runner's ``<out>.lipsync.json`` (only the agreed keys), or None when it's missing or unreadable."""
    p = Path(str(out) + ".lipsync.json")
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return {k: d.get(k) for k in SIDECAR_KEYS}


# ---------------------------------------------------------------- media (ffmpeg only)
def placeholder_voice(dest: Path, seconds: float) -> Path:
    """Dry-run voice: a quiet tone sized to the line (audible, so Speak previews visibly play)."""
    from opensoul import media

    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency=220:sample_rate=24000:duration={seconds:.2f}",
           "-af", "volume=0.08", "-ac", "1", str(dest)]
    return media._run(cmd, Path(dest))


def pad_audio(src: Path, dest: Path, seconds: float) -> Path:
    """Pad with trailing silence to ``seconds`` (and cut anything longer). Never time-stretches."""
    from opensoul import media

    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-af", f"apad=whole_dur={seconds:.4f}",
           "-t", f"{seconds:.4f}", str(dest)]
    return media._run(cmd, Path(dest))


def mux_voice(video: Path, wav: Path, dest: Path, seconds: float | None = None) -> Path:
    """Put the voice on a clip, exactly as long as the voice (the picture loops if shorter): ``media.mux``."""
    from opensoul import media

    return media.mux(Path(video), Path(wav), Path(dest))


def synth_line(text: str, voice: str, dest: Path, *, dry_run: bool | None = None, engine: str = "orpheus",
               ref: dict | None = None) -> tuple[Path, float, bool]:
    """Voice for a line -> (wav, seconds, placeholder). Live: ``engine`` (Orpheus unless the story says otherwise)
    via the TTS backend, with the speaker's clip ``ref`` for a cloning engine."""
    from opensoul.speak import _dry, estimate_seconds, get_tts

    dry = _dry() if dry_run is None else dry_run
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dry:
        secs = estimate_seconds(text)
        return placeholder_voice(dest, secs), secs, True
    from opensoul import media

    from opensoul.voice_engine import engine_text, engine_voice

    tts = get_tts(dry_run=False, name=engine)
    say, who = engine_text(engine, text), engine_voice(engine, voice)
    wav = tts.synthesize(say, who, dest, ref=ref) if ref else tts.synthesize(say, who, dest)
    return Path(wav), media.duration(Path(wav)), False


def lipsync(req: LipSyncRequest, *, dry_run: bool | None = None, installed: bool | None = None) -> LipSyncResult:
    """Post-video lip-sync (latentsync) over an existing clip. ltx_av has no post step (it's the a2v video stage)."""
    from opensoul import media
    from opensoul.speak import _dry, get_lipsync

    dry = _dry() if dry_run is None else dry_run
    backend = check_backend(req.backend)
    if backend == "ltx_av":
        raise ValueError("ltx_av is the video stage (workflow 04b), not a post step: use a2v_stage().")
    if req.video is None:
        raise LipSyncError("runner_failed", detail="no video to lip-sync")
    fc = face_check(req.face_box, backend, req.speaker)
    if fc["level"] == "block":
        raise LipSyncError("face_too_small", speaker=req.speaker or "the speaker", px=fc["px"], need=FACE_BLOCK_PX)
    if dry:
        out = mux_voice(Path(req.video), Path(req.audio), Path(req.dest))
        return LipSyncResult(video=out, backend=backend, placeholder=True, notes=["Dry run: voice muxed, no lip-sync."])
    if installed is False:
        raise LipSyncError("backend_missing", backend="LatentSync")
    be = get_lipsync("latentsync", dry_run=False)
    out, note = run_latentsync_stage(be, Path(req.video), Path(req.audio), Path(req.dest),
                                     {"face_box": req.face_box, "speaker": req.speaker})
    return LipSyncResult(video=out, backend=backend if note is None else "ltx_av",
                         stats=read_sidecar(out) if note is None else None, notes=[note] if note else [])


def latentsync_installed() -> bool:
    try:
        from opensoul.models_registry import backend_choices

        row = next((c for c in backend_choices() if c["stage"] == "lipsync"), None)
        return bool(row and any(o["id"] == "latentsync" and o["available"] for o in row["options"]))
    except Exception:  # noqa: BLE001
        return False
