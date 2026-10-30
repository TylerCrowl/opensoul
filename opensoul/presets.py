"""Shot presets (camera moves, viral effects, eras, voices) as data files.

Presets live in ``presets/camera/*.json`` and ``presets/effects/*.json`` so the
GPU side can consume them directly. ``build_shot_plan`` maps a user's choices
onto the ComfyUI workflow params for ``workflows/04_i2v_ltx_api.json`` (node 1
image, node 20 positive text, nodes 35/43 seed) plus optional TTS and an Era
post-process step. The workflow JSON itself is read-only here.
"""

from __future__ import annotations

import json
import os
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRESETS = ROOT / "presets"
I2V_WORKFLOW = "workflows/04_i2v_ltx_api.json"
TTS_WORKFLOW = "workflows/03_tts_api.json"
TTS_WORKFLOWS = {"orpheus": "workflows/03c_tts_orpheus_api.json", "kokoro": TTS_WORKFLOW,
                 "chatterbox": "workflows/03b_tts_chatterbox_api.json", "voxcpm2": "workflows/03d_tts_voxcpm2_api.json"}
DEFAULT_TTS = "orpheus"
LIPSYNC_WORKFLOW = "workflows/05_lipsync_api.json"
HASHTAG = "#OpenSoul #AIvideo"  # OS-044: no other company's product name in a default caption
AI_LABEL = "Videos made with OpenSoul are AI-generated."  # every shared caption says so (LTX-2.x Community License: AI-generated content is labelled)

# Node ids in 04_i2v_ltx_api.json that the app sets (see its .meta.json).
NODE_IMAGE = "1"
NODE_TEXT = "20"
NODE_SEEDS = ("35", "43")
NODE_OUTPUT = "51"
NODE_SCALE = "2"        # ImageScale: final output size
NODE_LATENT = "30"      # EmptyLTXVLatentVideo: stage-1 size (half) + frame count
NODE_AUDIO_LATENT = "32"
NODE_SIGMAS_1 = "37"    # stage-1 sigmas (8 steps in the template)
NODE_SIGMAS_2 = "45"    # stage-2 (2x upscaled) refine sigmas (3 steps)
NODE_NEGATIVE = "21"
NODE_PREPROCESS = "3"      # LTXVPreprocess img_compression (template 18)
NODE_IMG_STRENGTH_1 = "31"  # stage-1 LTXVImgToVideoInplace strength (template 0.85)
NEGATIVE_BASE = ("pc game, console game, video game, cartoon, childish, ugly, distorted face, text, watermark, walking toward camera, "
                 "zoom in, morphing, face distortion, extra fingers, blurry face, squinting, closed eyes, frowning, pained expression, grimace")
NEGATIVE_ANTI_GHOST = ("ghosting, smearing, double exposure, motion trails, fog, haze, smoke cloud, background warping, melting objects, "
                       "flicker, refocus, frozen animal")

# Quality tiers for a shot. "final" = the full two-stage LTX render (+ lip-sync when there is a line).
# "draft" = a fast preview to judge framing and motion: ~512 px short side, shorter clip, fewer sampler
# steps, no voice / lip-sync. Pick a keeper in draft, then re-render that keeper with "final".
QUALITY: dict[str, dict] = {
    "final": {"label": "Final", "short_side": 704, "max_seconds": None,
              "sigmas_1": None, "sigmas_2": None, "lipsync": True},
    "draft": {"label": "Draft", "short_side": 512, "max_seconds": 4.0,
              "sigmas_1": "1.0, 0.9875, 0.909375, 0.725, 0.421875, 0.0",
              "sigmas_2": "0.85, 0.4219, 0.0", "lipsync": False},
}
LONG_SIDE = {704: 1280, 512: 896}


def ltx_frames(seconds: float, fps: int = 24) -> int:
    """LTX wants 8k+1 frames."""
    return max(9, int(round(float(seconds) * fps / 8)) * 8 + 1)


def quality_size(quality: str, landscape: bool) -> tuple[int, int]:
    """(width, height) of the finished clip; both multiples of 64 so the half-size stage 1 fits the latent grid."""
    q = QUALITY[quality]
    short = q["short_side"]
    long_ = LONG_SIDE.get(short, int(round(short * 16 / 9 / 64)) * 64)
    return (long_, short) if landscape else (short, long_)


def _load_dir(kind: str) -> list[dict]:
    d = PRESETS / kind
    items = [json.loads(p.read_text()) for p in sorted(d.glob("*.json"))] if d.is_dir() else []
    return sorted(items, key=lambda x: (x.get("order", 999), x["id"]))


def load_presets() -> dict:
    return {
        "camera": _load_dir("camera"),
        "effects": _load_dir("effects"),
        "eras": list(json.loads((PRESETS / "eras.json").read_text()).values()),
        "voices": json.loads((PRESETS / "voices.json").read_text()),
    }


def _find(items: list[dict], pid: str | None) -> dict | None:
    if not pid:
        return None
    for it in items:
        if it["id"] == pid:
            return it
    raise KeyError(pid)


def shuffle_choice(seed: int | None = None) -> dict:
    rng = random.Random(seed)
    p = load_presets()
    use_effect = rng.random() < 0.4
    return {
        "camera": None if use_effect else rng.choice(p["camera"])["id"],
        "effect": rng.choice(p["effects"])["id"] if use_effect else None,
        "era": rng.choice(p["eras"])["id"],
        "seed": rng.randint(1, 2**31 - 1),
    }


def build_shot_plan(
    camera: str | None = None,
    effect: str | None = None,
    era: str = "iphone_ugc",
    line: str = "",
    voice: str | None = None,
    character_prompt: str = "",
    image_path: str = "",
    seed: int = 42,
    overrides: dict | None = None,
    lipsync_backend: str | None = None,
    tts_backend: str | None = None,
    quality: str = "final",
    camera_moves: list[str] | None = None,
    speaker: str = "",
    pronoun: str | None = None,
    pack_dir: str = "",
    speaks: bool = False,
) -> dict:
    """Map preset choices to ComfyUI workflow params. Raises KeyError on unknown ids.

    ``quality`` is "final" (default) or "draft" (see QUALITY). Size, frame count and sampler steps go into
    the plan's node inputs (nodes 2/30/32/37/45), so the workflow file itself stays read-only.

    A talking shot (a ``line``, an assigned ``speaker``, or ``speaks`` for a line rendered elsewhere) gets the
    lip-sync articulation sentence in the speaker's pronoun (``pronoun``, else the pack at ``pack_dir``, else 'they'): opensoul.lipsync.articulate, the same
    template speaker_prompt uses. Shots that don't talk keep their prompt unchanged."""
    if quality not in QUALITY:
        raise KeyError(quality)
    q = QUALITY[quality]
    p = load_presets()
    stack: list[str] = []
    if camera_moves and len([m for m in camera_moves if m]) > 1:
        # Stacked moves (opensoul/camera_moves.py): prompt-only, never with an effect, first move drives the checks.
        from opensoul import camera_moves as cm

        stack = cm.check(camera_moves, {c["id"]: c for c in p["camera"]})
        cm.check_quality(stack, quality)
        if effect:
            raise cm.MoveError("You cannot combine an effect with stacked camera moves. Pick one move or the effect.")
        camera = stack[0]
    elif camera_moves:
        camera = next(m for m in camera_moves if m)
    cam = _find(p["camera"], camera)
    eff = _find(p["effects"], effect)
    if not cam and not eff:
        cam = _find(p["camera"], "static")
    era_p = _find(p["eras"], era) or _find(p["eras"], "iphone_ugc")
    from opensoul import orpheus

    spoken = orpheus.normalize_tags(line) if line.strip() else ""   # raises orpheus.TagError on a typo'd <tag>
    words = orpheus.strip_tags(spoken) if spoken else ""            # what the video prompt and captions see
    try:
        vo = _find(p["voices"], voice) if words else None
    except KeyError:  # an older project or caller naming a Kokoro voice: use its Orpheus twin
        try:
            vo = _find(p["voices"], orpheus.resolve_voice(voice))
        except ValueError:
            raise KeyError(voice) from None
    if words and not vo:
        vo = p["voices"][0]

    main = eff or cam
    params = dict(main["defaults"])
    if overrides:
        params.update({k: v for k, v in overrides.items() if k in params})
    notes: list[str] = []
    # reverse: true = render the opposite move (render_prompt) and reverse the frames in post
    # (video only), e.g. Earth zoom out = a zoom-IN onto the character, played backwards.
    reverse = bool(main.get("reverse"))
    move_prompt = (main.get("render_prompt") or main["prompt"]) if reverse else main["prompt"]
    if stack:
        from opensoul import camera_moves as cm

        move_prompt = cm.stack_prompt(stack, {c["id"]: c for c in p["camera"]})
        notes.append(f"Camera moves: {cm.label(stack, {c['id']: c for c in p['camera']})} (prompt only, no LoRA; "
                     "the motion check looks at the first move only).")
    parts = [character_prompt.strip(), move_prompt]
    if eff and cam and not reverse:
        parts.append(cam["prompt"])
    elif eff and cam and reverse:
        notes.append(f"{eff['label']} is rendered in reverse, so the {cam['label']} camera move is not added.")
        cam = None
    # The motion the finished clip must show (checked by opensoul.motion_check after each take).
    expect = (eff or {}).get("expect_motion", "any") if eff else None
    if (expect in (None, "any")) and cam:
        expect = cam.get("expect_motion", "any")
    if words:
        parts.append(f'The subject speaks to camera, saying: "{words}"')
    if words or speaker.strip() or speaks:
        from opensoul import lipsync as L

        pro = pronoun if pronoun else L.pronoun_for_pack_dir(pack_dir)
        parts = [L.articulate(" ".join(x for x in parts if x), pro)]
    parts.append(era_p["prompt_suffix"])
    from opensoul.lipsync import eyes_safe

    # no eyes-shut phrasing in any generated prompt (opensoul.lipsync.eyes_safe): eyes open, brief glance, then hold
    prompt = eyes_safe(" ".join(x for x in parts if x))

    loras = [] if stack else [x["lora"] for x in (cam, eff) if x and x.get("lora")]
    if reverse:
        # The reversed clip ends on the user's picture: the 04 workflow anchors the still as the
        # render's first frame, and reversing puts it last.
        notes.append(f"{main['label']}: rendered as the opposite move and played in reverse (video only).")
    # node_id -> {input: value}, the shape comfy_client.run_workflow_file takes.
    inputs: dict[str, dict] = {NODE_TEXT: {"text": prompt}}
    if image_path:
        inputs[NODE_IMAGE] = {"image": image_path}
    for n in NODE_SEEDS:
        inputs[n] = {"noise_seed": seed}
    landscape = int(params.get("width", 704)) > int(params.get("height", 1280))
    if quality == "final" and "width" in params and "height" in params:
        w, h = int(params["width"]), int(params["height"])
    else:
        w, h = quality_size(quality, landscape)
    inputs[NODE_SCALE] = {"width": w, "height": h}
    inputs[NODE_LATENT] = {"width": w // 2, "height": h // 2}
    if q["max_seconds"]:
        # Draft: a shorter clip. Final keeps the workflow's own length (169 frames, ~7 s) so a spoken
        # line still fits before lip-sync.
        fps = int(params.get("fps", 24))
        frames = ltx_frames(min(float(params.get("duration_s", 5)), q["max_seconds"]), fps)
        inputs[NODE_LATENT]["length"] = frames
        inputs[NODE_AUDIO_LATENT] = {"frames_number": frames}
        params.update({"frames": frames, "duration_s": round(frames / fps, 2)})
    params.update({"width": w, "height": h})
    if q["sigmas_1"]:
        inputs[NODE_SIGMAS_1] = {"sigmas": q["sigmas_1"]}
    if q["sigmas_2"]:
        inputs[NODE_SIGMAS_2] = {"sigmas": q["sigmas_2"]}
    if quality == "draft":
        notes.append(f"Draft: {w}x{h}, {params['frames']} frames, fewer steps"
                     + (", no lip-sync" if words else "") + ". Use Final on the keeper for the full render.")

    # Anti-ghosting defaults (18 Oct, Lumi rough cut A/B, see docs/VIDEO_QUALITY_FIXES.md): extra negatives
    # for every shot; for locked-off shots also full first-frame conditioning and lighter preprocessing, so the
    # background is pinned and does not smear or drift when the subject moves her head.
    inputs[NODE_NEGATIVE] = {"text": NEGATIVE_BASE + ", " + NEGATIVE_ANTI_GHOST}
    if (expect or "any") == "static":
        inputs[NODE_IMG_STRENGTH_1] = {"strength": 1.0}
        inputs[NODE_PREPROCESS] = {"img_compression": 10}
    stages = [{"stage": "video", "workflow": I2V_WORKFLOW, "output_node": NODE_OUTPUT, "inputs": inputs, "loras": loras,
               "params": params, "reverse": reverse, "expect_motion": expect or "any", "quality": quality}]
    if words and q["lipsync"]:
        tts = (tts_backend or os.environ.get("OPENSOUL_TTS", DEFAULT_TTS)).lower()
        # Orpheus reads the emotion tags; the other engines get the plain words and their own voice id.
        text, vid = (spoken, vo["id"]) if tts == "orpheus" else (words, vo.get(tts, vo.get("kokoro", vo["id"])))
        if tts == "voxcpm2":  # VoxCPM2 gets the plain words (no tags or style notes); its voice is a clip, not an id
            from opensoul.voice_engine import voxcpm_text

            text, vid = voxcpm_text(spoken), vo["id"]
        stages.insert(0, {"stage": "voice", "backend": tts, "workflow": TTS_WORKFLOWS.get(tts, TTS_WORKFLOW),
                          "inputs": {"text": text, "voice": vid}})
        from opensoul import lipsync as L
        from opensoul.speak import estimate_seconds

        backend = (lipsync_backend or os.environ.get("OPENSOUL_LIPSYNC", L.DEFAULT_BACKEND)).lower()
        if backend == "ltx_av":
            # LTX joint audio+video IS the lip-sync: the video stage becomes workflow 04b with the voice frozen in.
            a2v = L.a2v_stage(prompt=prompt, audio_s=estimate_seconds(spoken), seed=seed, width=w, height=h,
                              quality=quality)
            stages[stages.index(next(x for x in stages if x["stage"] == "video"))] = a2v
            params.update({"frames": a2v["frames"], "duration_s": a2v["params"]["duration_s"]})
        else:
            stages.append({"stage": "lipsync", "backend": backend,
                           "workflow": LIPSYNC_WORKFLOW if backend == "latentsync" else None, "inputs": {}})
    if stack:  # room for every move: 2 moves >= 5 s, 3 moves >= 7 s (the voice is padded, never cut)
        from opensoul import camera_moves as cm

        for st_ in stages:
            note = cm.stretch_video(st_, stack)
            if note:
                notes.append(note)
                params.update({"frames": st_["params"]["frames"], "duration_s": st_["params"]["duration_s"]})
    stages.append({"stage": "era", "post": era_p["post"], "era": era_p["id"]})
    return {
        "camera": cam["id"] if cam else None,
        "camera_moves": stack or ([cam["id"]] if cam else []),
        "effect": eff["id"] if eff else None,
        "era": era_p["id"],
        "voice": vo["id"] if vo else None,
        "title": " → ".join(next(c["label"] for c in p["camera"] if c["id"] == m) for m in stack) if stack
        else " + ".join(x["label"] for x in (eff, cam) if x),
        "prompt": prompt,
        "seed": seed,
        "quality": quality,
        "expect_motion": expect or "any",
        "notes": notes,
        "stages": stages,
    }


def caption_for(plan: dict, name: str = "My character") -> str:
    title = str(plan.get("title") or "a new shot").rstrip(". ")
    return f"{name} — {title}. Made with OpenSoul. {AI_LABEL} {HASHTAG}"
