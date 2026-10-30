"""What the connected studio has: its GPU and memory (ComfyUI /system_stats) and its model files (ComfyUI
GET /models/<folder>). Used in studio mode so the Models screen, Settings and the top note judge the studio, not
this computer (OS-005).

Read-only GET requests to the studio address the user saved (OPENSOUL_COMFYUI_URL). Results are cached for a short
time, so a page load makes at most a few small requests. Never raises: on any error the callers fall back to this
computer and say so.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

CACHE_S = 60.0
TIMEOUT_S = 4.0
MODEL_FOLDERS = ("diffusion_models", "checkpoints", "text_encoders", "vae", "loras", "clip_vision",
                 "upscale_models", "audio_encoders", "latent_upscale_models")
_lock = threading.Lock()
_cache: dict[str, tuple[float, Any]] = {}


def studio_mode(env: dict | None = None) -> bool:
    env = os.environ if env is None else env
    dry = (env.get("OPENSOUL_DRY_RUN", "1") or "").strip().lower() in {"1", "true", "yes", ""}
    return not dry and bool((env.get("OPENSOUL_COMFYUI_URL") or "").strip())


def studio_url(env: dict | None = None) -> str:
    env = os.environ if env is None else env
    return (env.get("OPENSOUL_COMFYUI_URL") or "").strip().rstrip("/")


def _get_json(url: str, timeout: float = TIMEOUT_S, opener=None) -> Any:
    opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({})).open
    with opener(urllib.request.Request(url, headers={"Accept": "application/json"}), timeout=timeout) as r:
        return json.loads(r.read(5_000_000).decode("utf-8", "replace"))


def _cached(key: str, fn, refresh: bool = False):
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and not refresh and now - hit[0] < CACHE_S:
            return hit[1]
    val = fn()
    with _lock:
        _cache[key] = (now, val)
    return val


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def hardware_from_stats(stats: dict[str, Any], base: str = "") -> dict[str, Any] | None:
    """A hardware dict (the shape opensoul.hardware.detect returns) built from ComfyUI /system_stats."""
    from opensoul import hardware as HW
    from opensoul.launcher import _gpu_name

    if not isinstance(stats, dict) or not isinstance(stats.get("system"), dict):
        return None
    devs = [d for d in stats.get("devices") or [] if isinstance(d, dict)]
    gpus = []
    for d in devs:
        if str(d.get("type") or "").lower() == "cpu":
            continue
        vt = d.get("vram_total")
        gpus.append({"name": _gpu_name(d.get("name")) or "GPU",
                     "vram_gb": round(vt / 1024 ** 3, 1) if isinstance(vt, (int, float)) and vt > 0 else None})
    ram = stats["system"].get("ram_total")
    mem = round(ram / 1024 ** 3, 1) if isinstance(ram, (int, float)) and ram > 0 else None
    cls = HW.classify_gpu(gpus)
    if cls["gpu_class"] == "spark" and gpus and gpus[0].get("vram_gb"):
        mem = gpus[0]["vram_gb"]  # unified memory: the GPU's figure is the one the studio test showed
    return {"simulated": False, "studio": True, "studio_url": base, "gpus": gpus, "memory_gb": mem, **cls,
            "platform": "cpu" if cls["gpu_class"] == "none" else "nvidia",
            "notes": ["studio /system_stats"]}


def hardware(refresh: bool = False, opener=None) -> dict[str, Any] | None:
    """The studio's hardware, or None when not in studio mode or the studio does not answer."""
    if not studio_mode():
        return None
    base = studio_url()

    def fetch():
        try:
            return hardware_from_stats(_get_json(base + "/system_stats", opener=opener), base)
        except (urllib.error.URLError, OSError, ValueError, TimeoutError):
            return None
    return _cached("hw:" + base, fetch, refresh)


def model_files(refresh: bool = False, opener=None) -> set[str] | None:
    """Every model file on the studio as 'folder/name' (ComfyUI GET /models/<folder>), or None if unknown."""
    if not studio_mode():
        return None
    base = studio_url()

    def fetch():
        out: set[str] = set()
        ok = False
        for folder in MODEL_FOLDERS:
            try:
                names = _get_json(f"{base}/models/{folder}", opener=opener)
            except urllib.error.HTTPError:
                continue  # an unknown folder on this ComfyUI version
            except (urllib.error.URLError, OSError, ValueError, TimeoutError):
                return None
            ok = True
            for n in names or []:
                if isinstance(n, str):
                    out.add(f"{folder}/{n}")
        return out if ok else None
    return _cached("files:" + base, fetch, refresh)


def installed_on_studio(files: list[str], have: set[str]) -> bool | None:
    """True / False when every file is a ComfyUI model file; None when a file lives outside ComfyUI's models folder
    ($OPENSOUL_HOME / $HOME paths), because OpenSoul can't see that folder on the studio."""
    if not files:
        return None
    if any(f.startswith("$") for f in files):
        return None
    return all(f in have for f in files)


# ---------------------------------------------------------------- voice engines and voices on the studio (OS-054, OS-055)
TTS_NODES = {"orpheus": "OpenSoulOrpheusTTS", "kokoro": "OpenSoulKokoroTTS", "chatterbox": "OpenSoulChatterboxTTS",
             "voxcpm2": "OpenSoulVoxCPM2TTS"}
MISSING_VOICES_FILE = "studio_missing_voices.json"   # Kokoro voices a studio take could not find (learned)


def _node_info(base: str, node: str, opener=None) -> dict | None:
    """ComfyUI GET /object_info/<node>: the node's info, {} when the studio has no such node, None on an error."""
    try:
        d = _get_json(f"{base}/object_info/{node}", opener=opener)
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None
    return (d or {}).get(node) or {} if isinstance(d, dict) else None


def tts_engines(refresh: bool = False, opener=None) -> dict[str, bool] | None:
    """{engine: True if its node is on the studio}, or None when not in studio mode or the studio does not answer."""
    if not studio_mode():
        return None
    base = studio_url()

    def fetch():
        out = {}
        for eng, node in TTS_NODES.items():
            info = _node_info(base, node, opener)
            if info is None:
                return None
            out[eng] = bool(info)
        return out
    return _cached("tts:" + base, fetch, refresh)


def kokoro_voices(data_dir=None, refresh: bool = False, opener=None) -> set[str] | None:
    """The Kokoro voice ids the studio's node offers, less the voices a take on this studio could not find. None when
    unknown (not in studio mode, no answer, or no Kokoro node)."""
    if not studio_mode():
        return None
    base = studio_url()

    def fetch():
        info = _node_info(base, TTS_NODES["kokoro"], opener)
        try:
            opts = info["input"]["required"]["voice"][0] if info else None
        except (KeyError, IndexError, TypeError):
            opts = None
        return set(opts) if isinstance(opts, list) and opts else None
    have = _cached("kokoro:" + base, fetch, refresh)
    if have is None:
        return None
    return have - missing_voices(data_dir)


def missing_voices(data_dir=None) -> set[str]:
    if data_dir is None:
        return set()
    try:
        d = json.loads((Path(data_dir) / MISSING_VOICES_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {str(x) for x in (d.get(studio_url()) or [])} if isinstance(d, dict) else set()


_MISSING_RE = None


def note_missing_voice(data_dir, message: str) -> str | None:
    """When a studio error says a Kokoro voice file is missing ('No such file: models/kokoro/voices/am_fenrir.pt'),
    remember that voice for this studio so the app stops offering it. Returns the voice id, or None."""
    import re

    global _MISSING_RE
    _MISSING_RE = _MISSING_RE or re.compile(r"kokoro/voices/([a-z]{2}_[a-z0-9_]+)\.pt")
    m = _MISSING_RE.search(message or "")
    if not m or data_dir is None:
        return None
    p = Path(data_dir) / MISSING_VOICES_FILE
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        d = d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        d = {}
    key = studio_url()
    d[key] = sorted({*(d.get(key) or []), m.group(1)})
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=1), encoding="utf-8")
    return m.group(1)
