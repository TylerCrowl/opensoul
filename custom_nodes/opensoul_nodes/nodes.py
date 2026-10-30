"""OpenSoul custom nodes.

Each node shells out to a runner script inside the model's own venv (see ``runners/``).
Paths are configured with environment variables (defaults match setup_spark.sh):

  OPENSOUL_HOME            ~/OpenSoul
  OPENSOUL_KOKORO_PY       $OPENSOUL_HOME/tts-env/bin/python
  OPENSOUL_KOKORO_DIR      $OPENSOUL_HOME/models/kokoro            (hexgrad/Kokoro-82M)
  OPENSOUL_CHATTERBOX_PY   $OPENSOUL_HOME/chatterbox-env/bin/python (ResembleAI/chatterbox)
  OPENSOUL_ORPHEUS_PY      $OPENSOUL_HOME/tts-envs/orpheus/bin/python (llama-cpp-python + snac)
  OPENSOUL_ORPHEUS_GGUF    $OPENSOUL_HOME/models/orpheus/Orpheus-3b-FT-Q4_K_M.gguf (canopylabs/orpheus-3b-0.1-ft)
  OPENSOUL_LATENTSYNC_PY   $OPENSOUL_HOME/latentsync-env/bin/python
  OPENSOUL_LATENTSYNC_DIR  $OPENSOUL_HOME/LatentSync               (ByteDance/LatentSync-1.6)
  OPENSOUL_IDSIM_PY        $OPENSOUL_HOME/latentsync-env/bin/python (needs insightface; only for
                           the optional backend="arcface" identity gate)
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
RUNNERS = HERE / "runners"
CATEGORY = "OpenSoul"

ORPHEUS_VOICES = ["tara", "leah", "jess", "mia", "zoe", "zac", "leo", "dan"]  # = opensoul.orpheus.VOICE_IDS
KOKORO_VOICES = ["am_michael", "am_adam", "am_fenrir", "am_puck", "af_heart", "af_bella",
                 "af_nicole", "af_sarah", "af_kore", "bm_george", "bm_lewis", "bf_emma"]


def kokoro_voices() -> list[str]:
    """OS-055: the voice files that are really in the Kokoro voices folder, so the app only offers installed voices
    (it reads this list from /object_info). The fixed list when the folder can't be read."""
    d = Path(os.environ.get("OPENSOUL_KOKORO_DIR") or (_home() / "models/kokoro")) / "voices"
    try:
        have = sorted(p.stem for p in d.glob("*.pt"))
    except OSError:
        have = []
    return have or list(KOKORO_VOICES)


def _home() -> Path:
    return Path(os.environ.get("OPENSOUL_HOME", str(Path.home() / "OpenSoul"))).expanduser()


def _env(name: str, default: Path) -> str:
    return os.environ.get(name) or str(default)


def _run(cmd: list[str], cwd: str | None = None, timeout: int = 3600) -> str:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"{Path(cmd[1]).name} failed ({p.returncode}):\n{p.stderr[-3000:]}")
    return p.stdout


# ---------------------------------------------------------------- audio helpers
def wav_to_audio(path: str | Path) -> dict:
    """Read a PCM16 WAV into ComfyUI's AUDIO dict: waveform [1, C, T] float32 in [-1, 1]."""
    import torch

    with wave.open(str(path), "rb") as w:
        sr, ch, sw, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
        raw = w.readframes(n)
    if sw != 2:
        raise ValueError(f"expected 16-bit PCM wav, got {8 * sw}-bit")
    a = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    a = a.reshape(-1, ch).T.copy()
    return {"waveform": torch.from_numpy(a).unsqueeze(0), "sample_rate": sr}


def audio_to_wav(audio: dict, path: str | Path) -> Path:
    wf = audio["waveform"]
    a = wf[0].detach().float().cpu().numpy() if hasattr(wf, "detach") else np.asarray(wf)[0]
    a = np.clip(a, -1.0, 1.0)
    pcm = (a.T * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(a.shape[0])
        w.setsampwidth(2)
        w.setframerate(int(audio["sample_rate"]))
        w.writeframes(pcm.tobytes())
    return Path(path)


def _save_images(images, folder: Path, prefix: str) -> list[Path]:
    from PIL import Image

    out = []
    for i, img in enumerate(images):
        arr = (img.detach().cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
        p = folder / f"{prefix}_{i:03d}.png"
        Image.fromarray(arr).save(p)
        out.append(p)
    return out


# ---------------------------------------------------------------- TTS
class OpenSoulKokoroTTS:
    """Kokoro-82M (Apache-2.0) text-to-speech."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "text": ("STRING", {"multiline": True, "default": "Hello from OpenSoul."}),
            "voice": (kokoro_voices(), {"default": "am_michael"}),
            "speed": ("FLOAT", {"default": 1.0, "min": 0.5, "max": 2.0, "step": 0.05}),
        }}

    DESCRIPTION = 'Kokoro-82M (Apache-2.0) text to speech. Runs in its own venv; no deps added to ComfyUI.'
    RETURN_TYPES = ("AUDIO",)
    FUNCTION = "run"
    CATEGORY = CATEGORY

    def run(self, text, voice, speed):
        home = _home()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "kokoro.wav"
            _run([_env("OPENSOUL_KOKORO_PY", home / "tts-env/bin/python"), str(RUNNERS / "kokoro_tts.py"),
                  "--model-dir", _env("OPENSOUL_KOKORO_DIR", home / "models/kokoro"),
                  "--voice", voice, "--speed", str(speed), "--text", text, "--out", str(out)])
            return (wav_to_audio(out),)


class OpenSoulChatterboxTTS:
    """Chatterbox (MIT, Resemble AI) expressive TTS. Output carries Resemble's Perth watermark."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "text": ("STRING", {"multiline": True, "default": "Hello from OpenSoul."}),
            "exaggeration": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 2.0, "step": 0.05}),
            "cfg_weight": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.05}),
            "seed": ("INT", {"default": 0, "min": 0, "max": 2**31 - 1}),
        }, "optional": {"voice_reference": ("AUDIO",)}}

    DESCRIPTION = 'Chatterbox (MIT) expressive text to speech, optional voice reference. Output is Perth-watermarked.'
    RETURN_TYPES = ("AUDIO",)
    FUNCTION = "run"
    CATEGORY = CATEGORY

    def run(self, text, exaggeration, cfg_weight, seed, voice_reference=None):
        home = _home()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "chatterbox.wav"
            cmd = [_env("OPENSOUL_CHATTERBOX_PY", home / "chatterbox-env/bin/python"),
                   str(RUNNERS / "chatterbox_tts.py"), "--text", text, "--exaggeration", str(exaggeration),
                   "--cfg-weight", str(cfg_weight), "--seed", str(seed), "--out", str(out)]
            if voice_reference is not None:
                cmd += ["--ref", str(audio_to_wav(voice_reference, Path(td) / "ref.wav"))]
            _run(cmd)
            return (wav_to_audio(out),)


class OpenSoulVoxCPM2TTS:
    """VoxCPM2 (Apache-2.0, openbmb) TTS. Runs in its own venv (scripts/setup_tts_voxcpm2.sh), denoiser off."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "text": ("STRING", {"multiline": True, "default": "Hello from OpenSoul."}),
            "cfg_value": ("FLOAT", {"default": 2.0, "min": 0.5, "max": 5.0, "step": 0.1}),
            "inference_timesteps": ("INT", {"default": 10, "min": 4, "max": 50}),
            "seed": ("INT", {"default": 0, "min": 0, "max": 2**31 - 1}),
        }, "optional": {"voice_reference": ("AUDIO",),
                        "ref_text": ("STRING", {"multiline": False, "default": ""})}}

    DESCRIPTION = ('VoxCPM2 (Apache-2.0) text to speech. Give it the words only: <tags>, (style) and [stage] notes '
                   'are removed, because it would read them aloud. An optional voice reference clones a voice you '
                   'made or may use. 48 kHz.')
    RETURN_TYPES = ("AUDIO",)
    FUNCTION = "run"
    CATEGORY = CATEGORY

    def run(self, text, cfg_value, inference_timesteps, seed, voice_reference=None, ref_text=""):
        home = _home()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "voxcpm2.wav"
            cmd = [_env("OPENSOUL_VOXCPM2_PY", home / "voxcpm2-env/bin/python"), str(RUNNERS / "voxcpm2_tts.py"),
                   "--text", text, "--cfg", str(cfg_value), "--steps", str(inference_timesteps), "--seed", str(seed),
                   "--model-dir", _env("OPENSOUL_VOXCPM2_DIR", home / "models/voxcpm2"), "--out", str(out)]
            if voice_reference is not None:
                cmd += ["--ref", str(audio_to_wav(voice_reference, Path(td) / "ref.wav"))]
                if ref_text:
                    cmd += ["--ref-text", ref_text]
            _run(cmd)
            return (wav_to_audio(out),)


class OpenSoulOrpheusTTS:
    """Orpheus 3B (Apache-2.0, Built with Llama) expressive TTS with inline emotion tags. Default OpenSoul voice."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "text": ("STRING", {"multiline": True, "default": "Hello from OpenSoul. <chuckle> Nice to meet you."}),
            "voice": (ORPHEUS_VOICES, {"default": "tara"}),
            "temperature": ("FLOAT", {"default": 0.6, "min": 0.1, "max": 1.5, "step": 0.05}),
            "seed": ("INT", {"default": 0, "min": 0, "max": 2**31 - 1}),
        }}

    DESCRIPTION = ('Orpheus 3B (Apache-2.0; Built with Llama) text to speech with tags like <laugh> <sigh> <chuckle> '
                   '<gasp>. Built-in voices only. Runs in its own venv (llama.cpp GGUF + SNAC).')
    RETURN_TYPES = ("AUDIO",)
    FUNCTION = "run"
    CATEGORY = CATEGORY

    def run(self, text, voice, temperature, seed):
        home = _home()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "orpheus.wav"
            _run([_env("OPENSOUL_ORPHEUS_PY", home / "tts-envs/orpheus/bin/python"), str(RUNNERS / "orpheus_tts.py"),
                  "--text", text, "--voice", voice, "--temperature", str(temperature), "--seed", str(seed),
                  "--gguf", _env("OPENSOUL_ORPHEUS_GGUF", home / "models/orpheus/Orpheus-3b-FT-Q4_K_M.gguf"),
                  "--out", str(out)])
            return (wav_to_audio(out),)


# ---------------------------------------------------------------- lip-sync
# Runner exit codes (runners/latentsync_run.py) -> the app adapter's error codes (opensoul/lipsync.py LipSyncError).
# The node raises with a "[lipsync:<code>]" marker so the app can tell them apart from a crash.
LATENTSYNC_EXIT_CODES = {3: "ambiguous_face", 4: "no_face"}


def parse_face_box(face_box: str) -> str:
    """"x,y,w,h" (pixels on frame 0) -> normalised string for --face-box; "" = none. Raises ValueError if malformed."""
    s = (face_box or "").strip()
    if not s:
        return ""
    vals = [float(v) for v in s.replace(" ", "").split(",")]
    if len(vals) != 4 or vals[2] <= 0 or vals[3] <= 0 or min(vals[:2]) < 0:
        raise ValueError("face_box must be x,y,w,h with a positive width and height")
    return ",".join(str(int(round(v))) for v in vals)


def latentsync_cmd(py: str, ls_dir: str, vin, ain, vout, steps, guidance, seed, face_box: str = "") -> list[str]:
    cmd = [py, str(RUNNERS / "latentsync_run.py"), "--latentsync-dir", ls_dir, "--video", str(vin), "--audio", str(ain),
           "--out", str(vout), "--steps", str(steps), "--guidance", str(guidance), "--seed", str(seed)]
    fb = parse_face_box(face_box)
    return cmd + (["--face-box", fb] if fb else [])


def latentsync_env(face_style: str = "", base: dict | None = None) -> dict:
    """The runner's environment: OPENSOUL_LS_FACE_STYLE set when a style is given (real = MediaPipe only)."""
    env = dict(os.environ if base is None else base)
    style = (face_style or "").strip().lower()
    if style:
        if style not in ("auto", "real", "anime"):
            raise ValueError(f"face_style must be auto, real or anime, not {face_style!r}")
        env["OPENSOUL_LS_FACE_STYLE"] = style
    return env


def latentsync_error(rc: int, stderr: str) -> RuntimeError:
    code = LATENTSYNC_EXIT_CODES.get(rc)
    tail = (stderr or "")[-3000:]
    if code:
        return RuntimeError(f"[lipsync:{code}] latentsync_run.py exit {rc}:\n{tail}")
    return RuntimeError(f"latentsync_run.py failed ({rc}):\n{tail}")


def sidecar_text(vout) -> str:
    """The runner's <out>.lipsync.json as text ("" if it wrote none). Handed back as this node's text output so the
    app (opensoul/comfy_client -> node<id>_report.txt) can store it next to the take."""
    p = Path(str(vout) + ".lipsync.json")
    try:
        return json.dumps(json.loads(p.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return ""


class OpenSoulLatentSync:
    """LatentSync 1.6 (ByteDance; code Apache-2.0, weights OpenRAIL++) audio-driven lip-sync.

    Output node: besides the VIDEO it returns the runner's stats sidecar as UI text (see ``sidecar_text``)."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "video": ("VIDEO",),
            "audio": ("AUDIO",),
            "inference_steps": ("INT", {"default": 50, "min": 5, "max": 50}),
            "guidance_scale": ("FLOAT", {"default": 1.5, "min": 1.0, "max": 3.0, "step": 0.1}),
            "seed": ("INT", {"default": 1247, "min": 0, "max": 2**31 - 1}),
        }, "optional": {
            "face_box": ("STRING", {"default": "", "tooltip": "Speaker's face on frame 0: x,y,w,h in pixels. "
                                                               "Needed when the shot has more than one face."}),
            "face_style": ("STRING", {"default": "", "tooltip": "Face detector style for the runner: real = MediaPipe "
                                                                 "only, auto / anime; empty = the runner default."}),
        }}

    DESCRIPTION = "LatentSync 1.6 lip-sync: re-syncs the video's mouth to the audio. Runs in its own venv."
    RETURN_TYPES = ("VIDEO",)
    FUNCTION = "run"
    CATEGORY = CATEGORY
    OUTPUT_NODE = True  # so its UI text (the stats sidecar) reaches the job outputs

    def run(self, video, audio, inference_steps, guidance_scale, seed, face_box="", face_style=""):
        import folder_paths
        from comfy_api.input_impl import VideoFromFile

        home = _home()
        td = Path(tempfile.mkdtemp(prefix="opensoul_ls_", dir=folder_paths.get_temp_directory()))
        vin, ain, vout = td / "in.mp4", td / "in.wav", td / "latentsync.mp4"
        video.save_to(str(vin))
        audio_to_wav(audio, ain)
        ls_dir = _env("OPENSOUL_LATENTSYNC_DIR", home / "LatentSync")
        cmd = latentsync_cmd(_env("OPENSOUL_LATENTSYNC_PY", home / "latentsync-env/bin/python"), ls_dir, vin, ain, vout,
                             inference_steps, guidance_scale, seed, face_box)
        p = subprocess.run(cmd, cwd=ls_dir, capture_output=True, text=True, timeout=3600,
                           env=latentsync_env(face_style))
        if p.returncode != 0:
            raise latentsync_error(p.returncode, p.stderr)
        text = sidecar_text(vout)
        result = (VideoFromFile(str(vout)),)
        return {"ui": {"text": [text]}, "result": result} if text else result


# ---------------------------------------------------------------- consistency gate
GATE_BACKENDS = ["patch", "arcface"]
# Default pass thresholds per backend (patch matches opensoul.consistency.DEFAULT_SHEET_THRESHOLD).
GATE_THRESHOLDS = {"patch": 0.70, "arcface": 0.45}


def _to_rgb_array(img) -> np.ndarray:
    """One ComfyUI IMAGE frame (H, W, C float 0..1, torch or numpy) -> uint8 RGB array."""
    a = img.detach().cpu().numpy() if hasattr(img, "detach") else np.asarray(img)
    a = np.clip(a[..., :3] * 255.0, 0, 255).astype(np.uint8)
    return a


def patch_embedding_array(rgb: np.ndarray, grid: int = 8) -> np.ndarray:
    """Apache-2.0, dependency-free identity proxy: same method as opensoul.consistency.patch_embedding
    (mean-centred patch colours + luma/gradient histograms), so no third-party weights are needed."""
    from PIL import Image
    im = Image.fromarray(rgb).convert("RGB").resize((224, 224), Image.Resampling.BICUBIC)
    arr = np.asarray(im, dtype=np.float32) / 255.0
    arr_n = arr - arr.mean(axis=(0, 1), keepdims=True)
    h, w, _ = arr.shape
    gh, gw = h // grid, w // grid
    color = np.concatenate([arr_n[i * gh:(i + 1) * gh, j * gw:(j + 1) * gw].mean(axis=(0, 1))
                            for i in range(grid) for j in range(grid)])
    luma = 0.2126 * arr_n[..., 0] + 0.7152 * arr_n[..., 1] + 0.0722 * arr_n[..., 2]
    hist, _ = np.histogram(luma, bins=32, range=(-0.5, 0.5), density=True)
    gy = np.abs(np.diff(luma, axis=0, prepend=luma[:1]))
    gx = np.abs(np.diff(luma, axis=1, prepend=luma[:, :1]))
    ghist, _ = np.histogram(np.sqrt(gx * gx + gy * gy), bins=24, range=(0.0, 1.0), density=True)
    vec = np.concatenate([color, hist.astype(np.float32) * 0.25, ghist.astype(np.float32) * 0.4])
    return (vec / (np.linalg.norm(vec) + 1e-12)).astype(np.float32)


def patch_scores(anchor, candidates) -> list:
    a = patch_embedding_array(_to_rgb_array(anchor[0]))
    return [float(np.dot(a, patch_embedding_array(_to_rgb_array(c)))) for c in candidates]


class OpenSoulIdentityGate:
    """Identity-consistency gate: scores every candidate frame against the anchor and passes only
    on-model frames. If none pass, the best frame is returned and ``passed`` is False (or the node
    raises, with fail_on_reject).

    backend="patch" (default): in-process patch embedding, Apache-2.0, no extra weights.
    backend="arcface" (optional): InsightFace buffalo_l face embeddings. Stronger for faces, but the
    buffalo_l weights are licensed for non-commercial research only; opt in knowingly.
    threshold < 0 means "use the backend default" (patch 0.70, arcface 0.45)."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "anchor": ("IMAGE",),
            "candidates": ("IMAGE",),
            "threshold": ("FLOAT", {"default": -1.0, "min": -1.0, "max": 1.0, "step": 0.01}),
            "fail_on_reject": ("BOOLEAN", {"default": False}),
        }, "optional": {
            "backend": (GATE_BACKENDS, {"default": "patch"}),
        }}

    DESCRIPTION = 'Scores each candidate frame against the anchor and passes only on-model frames, so a graph can auto re-roll off-model views. Default patch backend needs no weights.'
    RETURN_TYPES = ("IMAGE", "FLOAT", "BOOLEAN", "STRING")
    RETURN_NAMES = ("passed_images", "best_score", "passed", "report")
    OUTPUT_NODE = True
    FUNCTION = "run"
    CATEGORY = CATEGORY

    def run(self, anchor, candidates, threshold, fail_on_reject, backend="patch"):
        if backend not in GATE_BACKENDS:
            raise ValueError(f"unknown identity gate backend {backend!r}; choose one of {GATE_BACKENDS}")
        if threshold is None or threshold < 0:
            threshold = GATE_THRESHOLDS[backend]
        if backend == "patch":
            scores = patch_scores(anchor, candidates)
        else:
            scores = self._arcface_scores(anchor, candidates)
        report = gate_report(scores, threshold)
        report["backend"] = backend
        if fail_on_reject and not report["passed"]:
            raise RuntimeError(f"OpenSoul identity gate rejected all frames: {report}")
        keep = report["kept"] or [report["best_index"]]
        text = json.dumps(report)
        return {"ui": {"text": [text]}, "result": (candidates[keep], float(report["best_score"]), report["passed"], text)}

    @staticmethod
    def _arcface_scores(anchor, candidates) -> list:
        home = _home()
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            a = _save_images(anchor[:1], td, "anchor")[0]
            cands = _save_images(candidates, td, "cand")
            out = _run([_env("OPENSOUL_IDSIM_PY", home / "latentsync-env/bin/python"),
                        str(RUNNERS / "idsim_json.py"), str(a), *map(str, cands)])
        return json.loads(out.strip().splitlines()[-1])["scores"]


def gate_report(scores: list, threshold: float) -> dict:
    """Pure scoring logic (unit-tested on CPU). ``None`` means no face found."""
    vals = [(-1.0 if s is None else float(s)) for s in scores]
    kept = [i for i, s in enumerate(vals) if s >= threshold]
    best = int(np.argmax(vals)) if vals else 0
    return {"threshold": threshold, "scores": scores, "kept": kept, "best_index": best,
            "best_score": vals[best] if vals else -1.0, "passed": bool(kept)}


NODE_CLASS_MAPPINGS = {
    "OpenSoulKokoroTTS": OpenSoulKokoroTTS,
    "OpenSoulChatterboxTTS": OpenSoulChatterboxTTS,
    "OpenSoulVoxCPM2TTS": OpenSoulVoxCPM2TTS,
    "OpenSoulOrpheusTTS": OpenSoulOrpheusTTS,
    "OpenSoulLatentSync": OpenSoulLatentSync,
    "OpenSoulIdentityGate": OpenSoulIdentityGate,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "OpenSoulKokoroTTS": "OpenSoul Kokoro TTS",
    "OpenSoulChatterboxTTS": "OpenSoul Chatterbox TTS",
    "OpenSoulVoxCPM2TTS": "OpenSoul VoxCPM2 TTS",
    "OpenSoulOrpheusTTS": "OpenSoul Orpheus TTS",
    "OpenSoulLatentSync": "OpenSoul LatentSync Lip-Sync",
    "OpenSoulIdentityGate": "OpenSoul Identity Gate",
}
