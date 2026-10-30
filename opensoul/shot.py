"""Run a shot plan (from presets.build_shot_plan) end to end.

voice (Kokoro) -> video (LTX I2V) [-> reverse] [-> motion check, re-seed] -> lipsync (pluggable) -> era (ffmpeg)

After each live take the camera-motion direction is checked (``opensoul.motion_check``) against
the preset's ``expect_motion``; a take that moves the wrong way is re-rendered with a new seed
(up to ``max_reseeds``, default 2, env ``OPENSOUL_MOTION_RESEEDS``) and the result notes say
"fixed automatically: camera direction". ``reverse: true`` presets render the opposite move and
are reversed with ffmpeg (video only) before the check.

The video stage is behind ``VideoBackend.render(stage, image, dest)``. Dry-run
uses an ffmpeg push-in on the still; live runs ``workflows/04_i2v_ltx_api.json``
through the Comfy SDK with the plan's node inputs (the workflow file is read only).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from opensoul import media
from opensoul.era import apply_era
from opensoul.speak import LipSyncBackend, TTSBackend, _dry, get_lipsync, get_tts

ROOT = Path(__file__).resolve().parents[1]


class VideoBackend(Protocol):
    def render(self, stage: dict, image: Path, dest: Path) -> Path: ...


@dataclass
class DryRunVideo:
    def render(self, stage: dict, image: Path, dest: Path) -> Path:
        secs = min(float(stage.get("params", {}).get("duration_s", 3)), 3.0)
        return media.still_to_clip(image, dest, seconds=secs)


def with_loras(graph: dict, loras: list[dict], model_node: str = "10",
               guider_nodes: tuple[str, ...] | str = ("34", "95")) -> dict:
    """Chain LoraLoaderModelOnly nodes (ids 70, 71, ...) between the UNet loader and every DualCFG guider.

    Camera-locked a2v graphs have two guiders (34 stage-1, 95 stage-2); both must take the LoRA-wrapped model.
    ``guider_nodes`` may be a single id (legacy) or a sequence; missing ids are skipped.
    """
    g = json.loads(json.dumps(graph))
    nodes = (guider_nodes,) if isinstance(guider_nodes, str) else tuple(guider_nodes)
    src = [model_node, 0]
    for i, lo in enumerate(loras):
        nid = str(70 + i)
        g[nid] = {"class_type": "LoraLoaderModelOnly",
                  "inputs": {"model": src, "lora_name": lo["name"], "strength_model": float(lo.get("strength", 1.0))}}
        src = [nid, 0]
    if loras:
        for gn in nodes:
            if gn in g and "inputs" in g[gn]:
                g[gn]["inputs"]["model"] = src
    return g


@dataclass
class ComfyLtxVideo:
    """Live LTX render. Camera LoRAs from the preset are chained in only with OPENSOUL_APPLY_LORAS=1
    (some preset LoRAs aren't on every GPU box; a missing file would fail the whole take)."""

    def render(self, stage: dict, image: Path, dest: Path) -> Path:
        from opensoul import lipsync as L
        from opensoul.comfy_client import run_workflow_file

        inputs = dict(stage["inputs"])
        inputs["1"] = {"image": str(image)}
        wf = ROOT / stage["workflow"]
        graph = json.loads(wf.read_text())
        dirty = False
        # Camera lock (native LTXVAddGuide): default for ltx_av talk takes; OPENSOUL_A2V_CAMLOCK=off skips it.
        want_lock = stage.get("cam_lock")
        if want_lock is None:
            want_lock = stage.get("lipsync") == "ltx_av" and L.cam_lock_enabled()
        if want_lock:
            graph = L.apply_cam_lock(graph)
            dirty = True
            hold = (stage.get("hold_guide") or {}).get("frame_idx")
            if hold is not None:  # OS-056: closed, still mouth after the line
                graph = L.apply_hold_guide(graph, int(hold), float(stage["hold_guide"].get("strength", 0.8)))
        if stage.get("loras") and _env_flag("OPENSOUL_APPLY_LORAS"):
            graph = with_loras(graph, stage["loras"])
            dirty = True
        if dirty:
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.parent / "_workflow_a2v.json"
            tmp.write_text(json.dumps(graph))
            wf = tmp
        paths = run_workflow_file(wf, inputs=inputs,
                                  output_node_id=stage.get("output_node", "51"), out_dir=dest.parent)
        if not paths:
            raise RuntimeError("Video workflow returned no file.")
        return paths[0]


@dataclass
class ShotResult:
    video: Path
    steps: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    seconds: float = 0.0  # wall time of the whole shot


FIXED_NOTE = "fixed automatically: camera direction"


def _env_flag(name: str) -> bool | None:
    v = os.environ.get(name)
    if v is None or not v.strip():
        return None
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _reseed(stage: dict, seed: int) -> dict:
    st = dict(stage)
    inputs = {k: dict(v) for k, v in stage.get("inputs", {}).items()}
    for n, v in inputs.items():
        if "noise_seed" in v:
            v["noise_seed"] = seed
    st["inputs"] = inputs
    return st


def _stage_seed(stage: dict, default: int = 42) -> int:
    for v in stage.get("inputs", {}).values():
        if "noise_seed" in v:
            return int(v["noise_seed"])
    return default


def _studio_timing(t0: float) -> dict:
    """OS-041: queue wait and render time of the studio job that just ran in this thread ({} when unknown)."""
    try:
        from opensoul.comfy_client import last_timing
    except Exception:  # noqa: BLE001
        return {}
    t = last_timing()
    return t if t and t.get("run_s", 0) <= time.time() - t0 + 1 else {}


def _render_checked(st: dict, image: Path, out: Path, video_backend: "VideoBackend", steps: list[dict],
                    notes: list[str], check: bool, max_reseeds: int) -> Path:
    """Render the video stage; reverse it if the preset says so; check the camera direction and re-seed on a mismatch."""
    expect = st.get("expect_motion", "any")
    mc = None
    if check and expect not in (None, "any"):
        try:
            from opensoul import motion_check as mc  # needs opencv-python-headless
        except ImportError:
            notes.append("motion check skipped: opencv-python-headless is not installed")
            mc = None
    seed0 = _stage_seed(st)
    tries = 1 + (max(0, int(max_reseeds)) if mc else 0)
    take: Path | None = None
    last: dict | None = None
    for k in range(tries):
        seed = seed0 if k == 0 else (seed0 + 7919 * k) % (2**31 - 1) or 1
        stk = st if k == 0 else _reseed(st, seed)
        dest = out / ("video.mp4" if k == 0 else f"video_try{k + 1}.mp4")
        t0 = time.time()
        take = Path(video_backend.render(stk, image, dest))
        steps.append({"stage": "video", "file": str(take), "seed": seed, "try": k + 1,
                      "quality": st.get("quality", "final"), "secs": round(time.time() - t0, 1), **_studio_timing(t0)})
        if st.get("reverse"):
            take = media.reverse_video(take, take.with_name(take.stem + "_reversed.mp4"))
            steps.append({"stage": "reverse", "file": str(take)})
        if mc is None:
            return take
        try:
            last = mc.check(take, expect)
        except Exception as e:  # noqa: BLE001  unreadable clip etc.: never block the shot on the checker
            notes.append(f"motion check skipped: {e}")
            return take
        steps.append({"stage": "motion_check", "try": k + 1, "seed": seed, "ok": last["ok"], "label": last["label"],
                      "confidence": last["confidence"], "expected": last["expected"], "uncertain": last.get("uncertain", False)})
        if last["ok"]:
            if k > 0:
                notes.append(FIXED_NOTE)
            return take
    assert take is not None and last is not None
    if tries == 1:  # OS-017: no automatic re-render. Keep the take and tell the user.
        notes.append(f"The camera move looks like {last['label'].replace('_', ' ')}, not "
                     f"{' or '.join(e.replace('_', ' ') for e in last['expected'])}. Keep this take if it looks right. "
                     "If not, click Regenerate for a new seed.")
        return take
    notes.append(f"camera direction still off after {tries - 1} re-seed(s): wanted {' or '.join(last['expected'])}, "
                 f"got {last['label']}. Try another seed or a different move.")
    return take


def _best_of_video(st: dict, image: Path, out: Path, video_backend: "VideoBackend", steps: list[dict],
                   notes: list[str], scorer) -> dict:
    """Best-of-N seeds for an a2v stage (opensoul.lipsync.best_of_seeds). Each seed renders into
    ``<take>/seeds/s<seed>/``; the chosen file is the take and the others stay there (never deleted). The choice and
    every seed's metrics go into the steps and ``<chosen>.best_of.json`` (with out_sha256 / out_frames of the file)."""
    from opensoul import lipsync as L
    from opensoul.speak import stamp_output, write_json_atomic

    def render(stk: dict, seed: int) -> Path:
        dest = out / "seeds" / f"s{seed}" / "video.mp4"
        dest.parent.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        f = Path(video_backend.render(stk, image, dest))
        steps.append({"stage": "video", "file": str(f), "seed": seed, "best_of": True,
                      "quality": st.get("quality", "final"), "secs": round(time.time() - t0, 1)})
        return f

    res = L.best_of_seeds(st, render, scorer)
    rec = {"method": L.REBUILT_METHOD, "recipe": res.get("recipe") or st.get("recipe") or L.RECIPE_LEGACY,
           "best_of": res}
    if res.get("recipe") == L.RECIPE_L1C:
        rec["stage1"] = {"seed": res["seed"], "file": res["file"], "why": res.get("pick_why"),
                         "order_seeds": res.get("order_seeds"), "passes_all_gates": res.get("stage1_passes_all_gates")}
    write_json_atomic(Path(res["file"] + ".best_of.json"), stamp_output(rec, Path(res["file"])))
    steps.append({"stage": "best_of", **{k: v for k, v in res.items()}})
    notes[:] = [n for n in notes if not n.startswith("Best of ")]  # the plan's "will render" note -> the outcome
    notes.append(L.best_of_note(res))
    return res


def _l1c_stage2(st: dict, best_of: dict, current: Path, voice: Path, out: Path, lipsync, steps: list[dict],
                notes: list[str], scorer, inner_mouth=None) -> Path:
    """L1c stage 2 (opensoul.lipsync.run_l1c_stage2): trim each passing base to the voice, LatentSync with the
    stage-2 params (MediaPipe only), the optional inner-mouth pass (experimental toggle, off by default), score the output and re-check the camera; a grin or post-LS cam fail re-picks the next base. Work files go under
    ``<take>/seeds/s<seed>/l1c/`` (kept). The final file gets ``<final>.best_of.json`` (recipe L1c, the stage-1 pick
    and why, the stage-2 params and the output scores; out_sha256 from the final file, written atomically)."""
    from opensoul import lipsync as L
    from opensoul.speak import count_frames, restamp_take, stamp_output, write_json_atomic

    run, why = L.l1c_stage2_decision(best_of, st)
    if best_of.get("status") == "dry_run":
        steps.append({"stage": "lipsync_skipped", "recipe": L.RECIPE_L1C, "reason": why})
        return current
    bo_step = next((x for x in reversed(steps) if x.get("stage") == "best_of"), None)
    if not run:
        rec = {"recipe": L.RECIPE_L1C, "ran": False, "skip_reason": why, "params": st.get("params")}
        best_of["stage2"] = rec
        if bo_step is not None:
            bo_step["stage2"] = rec
        steps.append({"stage": "lipsync_skipped", "recipe": L.RECIPE_L1C, "reason": why})
        notes.append(L.l1c_note(rec))
        _write_l1c_record(best_of, Path(current), stamp_output, write_json_atomic, st)
        return current

    def wdir(seed) -> Path:
        d = out / "seeds" / f"s{seed}" / "l1c"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def latentsync(trimmed: Path, seed):
        dest = wdir(seed) / "latentsync.mp4"
        f, note = L.run_latentsync_stage(lipsync, trimmed, voice, dest, st)
        if note is None:
            sc = L.read_sidecar(Path(f)) or {}
            steps.append({"stage": "lipsync", "backend": getattr(lipsync, "name", "latentsync"), "recipe": L.RECIPE_L1C,
                          "base_seed": seed, "file": str(f), "detector_counts": sc.get("detector_counts")})
        return f, note

    params = st.get("params") or L.l1c_stage2_params()
    im = inner_mouth or (lambda synced, raw, seed: L.run_inner_mouth_cli(synced, raw, wdir(seed) / "mouth.mp4", params))
    score = L.output_scorer(scorer)
    from opensoul import media

    rec = L.run_l1c_stage2(best_of, audio_s=media.duration(Path(voice)), frames_of=count_frames,
                           trim=lambda b, n, seed: L.trim_to_frames(b, wdir(seed) / "base_trim.mp4", n),
                           latentsync=latentsync, inner_mouth=im, score=score,
                           grin_review_only=bool(st.get("grin_review_only")))
    rec["decision"] = why
    best_of["stage2"] = rec
    if bo_step is not None:
        bo_step["stage2"] = rec
    steps.append({"stage": "l1c_stage2", **rec})
    notes.append(L.l1c_note(rec))
    final = Path(rec["file"]) if rec.get("file") else Path(current)
    kept = next((a for a in rec["attempts"] if a.get("file") == rec.get("file")), {})
    synced = kept.get("synced_file")
    if synced and Path(synced) != final:
        restamp_take(final, Path(synced), "inner_mouth")  # LatentSync's .lipsync.json follows the final file
    _write_l1c_record(best_of, final, stamp_output, write_json_atomic, st)
    return final


def _write_l1c_record(best_of: dict, final: Path, stamp_output, write_json_atomic, stage: dict | None = None) -> None:
    from opensoul import lipsync as L

    s2 = best_of.get("stage2") or {}
    rec = {"method": L.REBUILT_METHOD, "recipe": L.RECIPE_L1C, "best_of": best_of,
           "stage1": {"seed": best_of.get("seed"), "file": best_of.get("file"), "why": best_of.get("pick_why"),
                      "order_seeds": best_of.get("order_seeds"),
                      "passes_all_gates": best_of.get("stage1_passes_all_gates"),
                      "eyeline": next((r.get("eyeline") for r in best_of.get("seeds") or [] if r.get("chosen")), None),
                      "cam": best_of.get("cam") or next(
                          (r.get("cam") for r in best_of.get("seeds") or [] if r.get("chosen")), None),
                      "cam_lock": best_of.get("cam_lock"),
                      "warnings": list(best_of.get("warnings") or [])},
           "stage2": {k: s2.get(k) for k in ("ran", "skip_reason", "decision", "params", "kept_base_seed", "repicks",
                                             "output_scores", "output_reasons", "needs_review", "needs_review_reasons",
                                             "flags", "audio_frames", "eyeline", "warnings", "cam", "cam_lock")
                      if k in s2},
           "final_file": str(final)}
    # warn only: the eyeline of the file that ships (the mouth-pass output when it ran, else the stage-1 pick)
    final_warn = s2.get("warnings") if s2.get("ran") and s2.get("file") else best_of.get("warnings")
    rec["warnings"] = [w for w in final_warn or [] if w == L.EYELINE_WARNING]
    if stage:  # TTS voice id, and the pack's voice label (metadata only) as the lip-sync side reads it
        rec["voice"] = {k: stage.get(k) for k in ("voice", L.VOICE_LABEL_KEY, "voice_canonical", "voice_label_notes",
                                                  "rebuilt", "stage2_default_why") if k in stage}
    write_json_atomic(Path(str(final) + ".best_of.json"), stamp_output(rec, final))


def run_shot(
    plan: dict,
    image: str | Path,
    out_dir: str | Path,
    *,
    video_backend: VideoBackend | None = None,
    tts: TTSBackend | None = None,
    lipsync: LipSyncBackend | None = None,
    motion_check: bool | None = None,
    max_reseeds: int | None = None,
    scorer=None,
    inner_mouth=None,
) -> ShotResult:
    """``motion_check`` defaults to on in live mode, off in dry-run (env ``OPENSOUL_MOTION_CHECK`` overrides).
    ``scorer(video) -> result dict`` for a best-of a2v stage (default: the configured external lip-sync scorer,
    see opensoul.lipsync.best_of_seeds); dry-run never renders the extra seeds. ``inner_mouth(synced, raw, seed) ->
    Path``: the L1c inner-mouth step, used only when its experimental toggle is on (default: the ls_inner_mouth runner
    with its L1c2 defaults)."""
    t_start = time.time()
    dry = _dry()
    if motion_check is None:
        env = _env_flag("OPENSOUL_MOTION_CHECK")
        motion_check = (not dry) if env is None else env
    if max_reseeds is None:
        max_reseeds = int(os.environ.get("OPENSOUL_MOTION_RESEEDS", "0") or 0)  # OS-017: one render; a note if off
    notes: list[str] = list(plan.get("notes", []))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    image = Path(image)
    video_backend = video_backend or (DryRunVideo() if dry else ComfyLtxVideo())
    steps: list[dict] = []
    audio: Path | None = None
    current: Path | None = None
    best_of: dict | None = None  # the best-of-seeds result of this shot's a2v stage, when it has one
    voice_raw: Path | None = None  # the unpadded voice (L1c trims the base to it)
    for st in plan["stages"]:
        kind = st["stage"]
        if kind == "voice" and st.get("file"):
            # A ready audio file is the voice (the song slice of a sung music shot, OS-023): no TTS.
            audio = Path(st["file"])
            if not audio.is_file():
                raise RuntimeError("The song slice for this shot is missing. Send the shots from Music again.")
            voice_raw = audio
            steps.append({"stage": kind, "file": str(audio), "source": st.get("source", "file")})
        elif kind == "voice":
            tts = tts or get_tts(name=st.get("backend"))
            ref = st["inputs"].get("ref")  # the speaker's own clip (cloning engines only)
            audio = (tts.synthesize(st["inputs"]["text"], st["inputs"]["voice"], out / "voice.wav", ref=ref) if ref
                     else tts.synthesize(st["inputs"]["text"], st["inputs"]["voice"], out / "voice.wav"))
            voice_raw = Path(audio)
            steps.append({"stage": kind, "file": str(audio)})
        elif kind == "video" and st.get("audio_from") == "voice":
            # LTX joint audio+video (workflow 04b): the voice is the input, padded with silence to the frame count.
            if audio is None:
                raise RuntimeError("This take renders to the voice, but there's no voice track.")
            from opensoul.lipsync import fit_a2v_to_voice, pad_audio

            if st.get("shape_voice"):
                # OS-056/OS-059: short silence around the words, the take as long as the shot's planned length
                from opensoul.voice_shape import shape_voice

                shaped = shape_voice(audio, out / "voice_padded.wav", target_s=float(st.get("target_s") or 0),
                                     min_frames=int(st.get("min_frames") or 0))
                st = fit_a2v_to_voice(st, shaped)
                padded = Path(shaped["file"])
                steps.append({"stage": "voice_shape", **st["voice_shape"], "frames": st["frames"],
                              "hold_guide": st.get("hold_guide")})
            else:
                padded = pad_audio(audio, out / "voice_padded.wav", float(st["pad_audio_to_s"]))
                st = {**st, "inputs": {**st["inputs"], "60": {"audio": str(padded)}}}
            if st.get("best_of", 1) > 1 and not dry:
                best_of = _best_of_video(st, image, out, video_backend, steps, notes, scorer)
                current = Path(best_of["file"])
            else:
                current = _render_checked(st, image, out, video_backend, steps, notes, False, 0)
                if st.get("best_of", 1) > 1:  # dry-run: one stand-in, no extra renders, no scorer
                    best_of = {"status": "dry_run", "n": 1, "seed": _stage_seed(st), "file": str(current),
                               "skipped_seeds": list(st.get("seeds") or [])[1:], "latentsync_fallback_allowed": False}
                    steps.append({"stage": "best_of", **best_of})
                    notes[:] = [n for n in notes if not n.startswith("Best of ")]
                    notes.append(f"Best of {st['best_of']} takes runs in Studio mode; the preview renders one.")
            if dry:  # the stand-in clip has no sound: put the voice on it
                from opensoul.lipsync import mux_voice

                current = mux_voice(current, padded, out / "a2v_preview.mp4")
            audio = padded
        elif kind == "video":
            current = _render_checked(st, image, out, video_backend, steps, notes, motion_check, max_reseeds)
        elif kind == "mux":
            if current is None or audio is None:
                raise RuntimeError("Adding the voice needs both a video and a voice track.")
            from opensoul.lipsync import mux_voice
            from opensoul.speak import restamp_take

            prev = current
            current = mux_voice(current, audio, out / "with_voice.mp4")
            restamp_take(current, prev, "mux")  # a synced take's sidecars follow it, hashed from the new file
            steps.append({"stage": kind, "file": str(current)})
        elif kind == "lipsync" and st.get("only_if") == "l1c_stage2":
            if current is None or audio is None:
                raise RuntimeError("Lip-sync needs both a video and a voice track.")
            lipsync = lipsync or get_lipsync(st.get("backend"))
            current = _l1c_stage2(st, best_of or {"status": "dry_run"}, current, voice_raw or audio, out, lipsync,
                                  steps, notes, scorer, inner_mouth)
        elif kind == "lipsync":
            if st.get("only_if") == "best_of_all_rejected" and not (best_of and best_of.get("latentsync_fallback_allowed")):
                steps.append({"stage": "lipsync_skipped", "reason": "best-of kept a seed that passed the checks"
                              if best_of and best_of.get("status") == "picked" else "no rejected best-of to fix"})
                continue
            if current is None or audio is None:
                raise RuntimeError("Lip-sync needs both a video and a voice track.")
            a2v_take = current
            lipsync = lipsync or get_lipsync(st.get("backend"))
            from opensoul.lipsync import run_latentsync_stage

            current, note = run_latentsync_stage(lipsync, current, audio, out / "lipsync.mp4", st)
            if note:  # no_face: the LTX take stands, without the LatentSync pass
                notes.append(note)
                steps.append({"stage": kind, "backend": lipsync.name, "error": "no_face", "file": str(current)})
            else:
                steps.append({"stage": kind, "backend": lipsync.name, "file": str(current)})
                if best_of is not None and Path(current) != Path(a2v_take):
                    from opensoul.speak import restamp_take

                    restamp_take(current, a2v_take, "latentsync")  # the best-of record follows the kept take
        elif kind == "era":
            if current is None:
                raise RuntimeError("Era needs a rendered video.")
            from opensoul.speak import restamp_take

            prev = current
            current = apply_era(current, out / "final.mp4", st["era"])
            restamp_take(current, prev, "era")
            steps.append({"stage": kind, "era": st["era"], "file": str(current)})
    if current is None:
        raise RuntimeError("Plan produced no video.")
    return ShotResult(video=current, steps=steps, notes=notes, seconds=round(time.time() - t_start, 1))


def lipsync_backend_name() -> str:
    return os.environ.get("OPENSOUL_LIPSYNC", "ltx_av")
