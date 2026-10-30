"""Speak: text -> voice (Orpheus TTS by default) -> lip-sync (pluggable backend).

GPU work stays behind two small interfaces so the app, tests and dry-run never
import model code:

* ``TTSBackend.synthesize(text, voice, dest) -> Path`` (wav)
* ``LipSyncBackend.sync(video, audio, dest) -> Path`` (mp4)

Every live call runs a ComfyUI workflow through the Comfy SDK (``opensoul.comfy_client``);
TTS and LatentSync are ComfyUI nodes in ``custom_nodes/opensoul_nodes``.

TTS backends, chosen with ``OPENSOUL_TTS`` (default ``orpheus``): ``orpheus`` (workflow 03c; built-in
voices, inline emotion tags like ``<sigh>``), ``kokoro`` (workflow 03) or ``chatterbox`` (workflow 03b).
Kokoro and Chatterbox get the line with the emotion tags removed.

Lip-sync backends, chosen with ``OPENSOUL_LIPSYNC`` (default ``ltx_av``; plans go through ``opensoul/lipsync.py``):

* ``ltx_av`` (default): LTX joint audio+video. The video stage itself is workflow 04b with the TTS voice frozen in
  the audio latent, so as a post step this backend only swaps the voice onto the clip.
* ``latentsync`` (optional download): LatentSync 1.6 over a rendered clip (``workflows/05_lipsync_api.json``).
* ``infinitetalk``: InfiniteTalk (Wan 14B) via the kijai WanVideoWrapper. In progress:
  no workflow is committed yet, so it raises a clear error when live.

In dry-run every backend uses ffmpeg only: a silent wav sized to the line, and
a mux of that audio onto the clip.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from opensoul import media

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / "workflows"
BACKENDS = ("latentsync", "ltx_av", "infinitetalk")
TTS_BACKENDS = ("orpheus", "kokoro", "chatterbox", "voxcpm2")
DEFAULT_TTS = "orpheus"


def _dry() -> bool:
    return os.environ.get("OPENSOUL_DRY_RUN", "1").strip().lower() in {"1", "true", "yes", ""}


def estimate_seconds(text: str, wpm: float = 165.0) -> float:
    from opensoul.orpheus import TagError, strip_tags, tags_in

    try:
        words, extra = max(1, len(strip_tags(text).split())), 0.6 * len(tags_in(text))  # a laugh/sigh takes time too
    except TagError:
        words, extra = max(1, len(text.split())), 0.0
    return round(max(1.0, words / wpm * 60 + 0.4 + extra), 2)


class TTSBackend(Protocol):
    def synthesize(self, text: str, voice: str, dest: Path, ref: dict | None = None) -> Path: ...


class LipSyncBackend(Protocol):
    name: str

    def sync(self, video: Path, audio: Path, dest: Path) -> Path: ...


def _run_sdk(workflow: str, inputs: dict, output_node: str, dest: Path, what: str) -> Path:
    """Every live TTS / lip-sync call goes through the Comfy SDK (opensoul.comfy_client)."""
    from opensoul.comfy_client import run_workflow_file

    paths = run_workflow_file(WORKFLOWS / workflow, inputs=inputs, output_node_id=output_node, out_dir=dest.parent)
    if not paths:
        raise RuntimeError(f"{what} workflow {workflow} returned no output.")
    return paths[0]


@dataclass
class OrpheusTTS:
    """Orpheus 3B (Apache-2.0; Built with Llama) via the OpenSoulOrpheusTTS node, workflow ``03c`` (default).

    ``voice`` is a built-in Orpheus speaker (opensoul.orpheus.VOICE_IDS); emotion tags stay in the text."""

    dry_run: bool = True
    name: str = "orpheus"
    temperature: float = 0.6
    seed: int = 0

    def synthesize(self, text: str, voice: str, dest: Path, ref: dict | None = None) -> Path:  # ref: never used
        from opensoul import orpheus

        dest = Path(dest)
        text, voice = orpheus.normalize_tags(text), orpheus.resolve_voice(voice)
        if self.dry_run:
            return media.silent_wav(dest, estimate_seconds(text))
        return _run_sdk("03c_tts_orpheus_api.json",
                        {"1": {"text": text, "voice": voice, "temperature": self.temperature, "seed": self.seed}},
                        "2", dest, "TTS")


def _plain(text: str) -> str:
    """The words only: no <tags>, (style) or [stage] notes (opensoul.voice_engine.spoken_words)."""
    from opensoul.voice_engine import spoken_words

    return spoken_words(text)


@dataclass
class KokoroTTS:
    """Kokoro-82M (Apache-2.0) via the OpenSoulKokoroTTS node, workflow ``03_tts_api.json``."""

    dry_run: bool = True
    name: str = "kokoro"

    def synthesize(self, text: str, voice: str, dest: Path, ref: dict | None = None) -> Path:  # ref: never used
        dest = Path(dest)
        if self.dry_run:
            return media.silent_wav(dest, estimate_seconds(text))
        return _run_sdk("03_tts_api.json", {"1": {"text": _plain(text), "voice": voice}}, "2", dest, "TTS")


@dataclass
class ChatterboxTTS:
    """Chatterbox (MIT, Resemble AI) via the OpenSoulChatterboxTTS node, workflow ``03b``."""

    dry_run: bool = True
    name: str = "chatterbox"

    def synthesize(self, text: str, voice: str, dest: Path, ref: dict | None = None) -> Path:
        """``ref`` ({"clip", ...}, opensoul.voice_engine.ref_for): the speaker's own clip, workflow 03b_ref."""
        dest = Path(dest)
        if self.dry_run:
            return media.silent_wav(dest, estimate_seconds(text))
        if ref and ref.get("clip"):
            return _run_sdk("03b_tts_chatterbox_ref_api.json", {"1": {"text": _plain(text)}, "3": {"audio": ref["clip"]}},
                            "2", dest, "TTS")
        return _run_sdk("03b_tts_chatterbox_api.json", {"1": {"text": _plain(text)}}, "2", dest, "TTS")


@dataclass
class VoxCPM2TTS:
    """VoxCPM2 (Apache-2.0, openbmb) via the OpenSoulVoxCPM2TTS node, workflow ``03d`` (``03d_ref`` with the
    speaker's clip). Runs in its own venv (scripts/setup_tts_voxcpm2.sh); denoiser off. It gets the plain words only:
    tags and (style) notes are removed (opensoul.voice_engine.voxcpm_text). Preview mode: a silent wav sized to the line."""

    dry_run: bool = True
    name: str = "voxcpm2"
    seed: int = 0

    def synthesize(self, text: str, voice: str, dest: Path, ref: dict | None = None) -> Path:
        from opensoul.voice_engine import voxcpm_text

        dest = Path(dest)
        text = voxcpm_text(text)  # words only: a (style) note would be read aloud
        if self.dry_run:
            return media.silent_wav(dest, estimate_seconds(text))
        node = {"text": text, "seed": self.seed}
        if ref and ref.get("clip"):
            return _run_sdk("03d_tts_voxcpm2_ref_api.json",
                            {"1": {**node, "ref_text": ref.get("text") or ""}, "3": {"audio": ref["clip"]}},
                            "2", dest, "TTS")
        return _run_sdk("03d_tts_voxcpm2_api.json", {"1": node}, "2", dest, "TTS")


@dataclass
class LatentSyncLipSync:
    """LatentSync 1.6 via the OpenSoulLatentSync node, workflow ``05_lipsync_api.json`` (default)."""

    dry_run: bool = True
    name: str = "latentsync"
    face_box: list[int] | None = None  # speaker's face on frame 0 (x, y, w, h px) -> the node's --face-box
    # L1c stage 2 (opensoul.lipsync.l1c_stage2_params): None / "" = the workflow's own values
    steps: int | None = None
    guidance: float | None = None
    seed: int | None = None
    face_style: str = ""               # "real" = MediaPipe only (the node sets OPENSOUL_LS_FACE_STYLE for the runner)

    def node_inputs(self) -> dict:
        """Node 3 inputs for workflow 05 from this backend's settings (only the ones that are set)."""
        node: dict = {"face_box": ",".join(str(int(v)) for v in self.face_box)} if self.face_box else {}
        for k, key, cast in (("steps", "inference_steps", int), ("guidance", "guidance_scale", float),
                             ("seed", "seed", int)):
            if getattr(self, k) is not None:
                node[key] = cast(getattr(self, k))
        if self.face_style:
            node["face_style"] = str(self.face_style)
        return node

    def sync(self, video: Path, audio: Path, dest: Path) -> Path:
        if self.dry_run:
            return media.mux(video, audio, dest)
        node = self.node_inputs()
        report = Path(dest).parent / "node3_report.txt"  # the node's stats text (comfy_client writes it here)
        report.unlink(missing_ok=True)
        out = _run_sdk("05_lipsync_api.json", {"1": {"file": str(video)}, "2": {"audio": str(audio)},
                                               **({"3": node} if node else {})}, "9", Path(dest), "Lip-sync")
        check_detector(store_sidecar(report, out), out, keep=video)
        return out


def check_detector(sidecar: Path | None, video: Path, keep: Path | None = None) -> None:
    """Fail closed: keep a LatentSync take only if the OpenSoul runner proved it used its own face detector
    (MediaPipe, or the MIT anime fallback). No ``<take>.lipsync.json`` sidecar (an old runner, which used the
    upstream InsightFace detector) or ``detector_counts`` with 0 MediaPipe and 0 anime frames -> the take and its
    sidecar are dropped (never ``keep``, the input clip) and ``LipSyncError('runner_failed')`` is raised."""
    import json

    from opensoul.lipsync import LipSyncError

    counts = {}
    if sidecar is not None:
        try:
            counts = json.loads(Path(sidecar).read_text(encoding="utf-8")).get("detector_counts") or {}
        except (OSError, ValueError, AttributeError):
            counts = {}

    def n(key: str) -> int:
        try:
            return int(counts.get(key) or 0)
        except (TypeError, ValueError, AttributeError):
            return 0

    if sidecar is None:
        why = "LatentSync ran without the OpenSoul MediaPipe detector (no detector sidecar); refusing the take"
    elif n("mediapipe") + n("anime_fallback") + n("anime") <= 0:
        why = "LatentSync's detector sidecar shows 0 MediaPipe and 0 anime frames; refusing the take"
    else:
        return
    if keep is None or Path(video).resolve() != Path(keep).resolve():
        Path(video).unlink(missing_ok=True)
    if sidecar is not None:
        Path(sidecar).unlink(missing_ok=True)
    raise LipSyncError("runner_failed", detail=why)


def store_sidecar(report: Path, video: Path) -> Path | None:
    """Move the LatentSync node's stats text to ``<video>.lipsync.json`` (next to the take), if it is valid JSON.

    The node hashed the runner's own temp mp4, but the take is the file Comfy wrote, so ``out_sha256`` and
    ``out_frames`` are recomputed from ``video`` (the runner's values stay as ``runner_out_sha256`` /
    ``runner_out_frames``). Written atomically (temp file + os.replace)."""
    import json

    try:
        data = json.loads(Path(report).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    dest = Path(str(video) + ".lipsync.json")
    write_json_atomic(dest, stamp_output(data, video))
    Path(report).unlink(missing_ok=True)
    return dest


# ---------------------------------------------------------------- final-take provenance (out_sha256 / out_frames)
SIDECARS = (".lipsync.json", ".inner_mouth.json", ".best_of.json")  # best_of: opensoul.shot best-of seeds


def file_sha256(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def count_frames(path: Path) -> int | None:
    """Frames actually decoded from the first video stream (ffprobe -count_frames), None when it can't be read."""
    import shutil
    import subprocess

    probe = shutil.which("ffprobe")
    if not probe:
        return None
    try:
        r = subprocess.run([probe, "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                            "stream=nb_read_frames", "-of", "csv=p=0", str(path)], capture_output=True, text=True,
                           timeout=120)
        return int(r.stdout.strip().split(",")[0])
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


def write_json_atomic(dest: Path, data: dict) -> Path:
    """Temp file in the same folder, fsync, os.replace: readers see the old file or the new one, never a partial."""
    import json
    import tempfile

    dest = Path(dest)
    fd, tmp = tempfile.mkstemp(prefix=f".{dest.name}.", suffix=".tmp", dir=dest.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, indent=2))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, dest)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return dest


def stamp_output(data: dict, video: Path) -> dict:
    """``data`` with out_sha256 / out_frames of the file ``video``; the runner's first values are kept once as
    runner_out_sha256 / runner_out_frames. A missing ``video`` gets null values."""
    data = dict(data)
    for k in ("out_sha256", "out_frames"):
        if f"runner_{k}" not in data:
            data[f"runner_{k}"] = data.get(k)
    ok = Path(video).is_file()  # no file (never written): no hash, rather than the runner's temp-file hash
    data["out_sha256"] = file_sha256(video) if ok else None
    data["out_frames"] = count_frames(video) if ok else None
    return data


def restamp_take(take: Path, src: Path | None = None, step: str = "") -> list[Path]:
    """After the app writes or rewrites a take mp4: its sidecars get out_sha256 / out_frames of the file as it is now.
    ``src`` = the synced take this one was made from (re-mux, audio replace, era...): its sidecars are carried over to
    ``take`` (the originals stay with ``src``). ``<take>.inner_mouth.json`` also gets parent_sidecar(_sha256) of the
    stored ``<take>.lipsync.json``. Returns the sidecars written."""
    import json

    take = Path(take)
    origin = Path(src) if src is not None else take
    written: list[Path] = []
    lip_dest = Path(str(take) + ".lipsync.json")
    for suffix in SIDECARS:  # .lipsync.json first: the inner-mouth sidecar records its hash
        f = Path(str(origin) + suffix)
        if not f.is_file():
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        data = stamp_output(data, take)
        if src is not None and Path(src).resolve() != take.resolve():
            data["rewritten_by"] = [*(data.get("rewritten_by") or []), step or "app"]
        if suffix == ".inner_mouth.json" and lip_dest.is_file():
            data["parent_sidecar"] = lip_dest.name
            data["parent_sidecar_sha256"] = file_sha256(lip_dest)
        written.append(write_json_atomic(Path(str(take) + suffix), data))
    return written


@dataclass
class LtxAvLipSync:
    """LTX generates speech-synced motion from the prompt; we keep the picture and use the chosen voice."""

    dry_run: bool = True
    name: str = "ltx_av"

    def sync(self, video: Path, audio: Path, dest: Path) -> Path:
        return media.mux(video, audio, dest)


@dataclass
class InfiniteTalkLipSync:
    dry_run: bool = True
    name: str = "infinitetalk"

    def sync(self, video: Path, audio: Path, dest: Path) -> Path:
        if self.dry_run:
            return media.mux(video, audio, dest)
        raise NotImplementedError(
            "InfiniteTalk backend is in progress: no committed workflow yet. "
            "Use OPENSOUL_LIPSYNC=latentsync or ltx_av."
        )


def get_tts(dry_run: bool | None = None, name: str | None = None) -> TTSBackend:
    name = (name or os.environ.get("OPENSOUL_TTS", DEFAULT_TTS)).strip().lower()
    table = {"orpheus": OrpheusTTS, "kokoro": KokoroTTS, "chatterbox": ChatterboxTTS, "voxcpm2": VoxCPM2TTS}
    if name not in table:
        raise ValueError(f"Unknown TTS backend {name!r}. Choose one of: {', '.join(TTS_BACKENDS)}")
    return table[name](dry_run=_dry() if dry_run is None else dry_run)


def get_lipsync(name: str | None = None, dry_run: bool | None = None) -> LipSyncBackend:
    name = (name or os.environ.get("OPENSOUL_LIPSYNC", "ltx_av")).strip().lower()
    dr = _dry() if dry_run is None else dry_run
    table = {"latentsync": LatentSyncLipSync, "ltx_av": LtxAvLipSync, "infinitetalk": InfiniteTalkLipSync}
    if name not in table:
        raise ValueError(f"Unknown lip-sync backend {name!r}. Choose one of: {', '.join(BACKENDS)}")
    return table[name](dry_run=dr)
