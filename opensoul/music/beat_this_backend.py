"""Optional beat_this backend (CPJKU/beat_this, MIT code and weights; see docs/MUSIC.md).

beat_this needs torch, which the app's .venv deliberately does not have. It runs in the studio env (the Python env
next to ComfyUI) and is imported here only when it is installed. It loads ONE local checkpoint file, never a
download: the path comes from env ``OPENSOUL_BEAT_THIS_CKPT`` or ``runner.checkpoint`` of the ``beat_this`` entry in
presets/music_models.json, and the file must match the sha256 pinned there (``revision.checkpoint_sha256``, the
upstream ``final0`` checkpoint). If anything is missing or different, :func:`available` is False and
:func:`opensoul.music.beats.analyze_with` uses the built-in CPU tracker instead.
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path

ENV = "OPENSOUL_BEAT_THIS_CKPT"
CHECKPOINT_SHA256 = "8c328b45f59d8dd3dff219253ff6a8d6482be57d0133a29140e2febbf8eb8331"  # upstream 'final0'
_sums: dict[tuple[str, int, float], str] = {}


def _entry() -> dict:
    try:
        from opensoul.music import registry

        return registry.get("beat_this")
    except Exception:  # noqa: BLE001  (no registry / no entry: env only, default sha)
        return {}


def expected_sha256() -> str:
    rev = _entry().get("revision") or {}
    return str(rev.get("checkpoint_sha256") or CHECKPOINT_SHA256) if isinstance(rev, dict) else CHECKPOINT_SHA256


def checkpoint_path() -> Path | None:
    raw = os.environ.get(ENV) or (_entry().get("runner") or {}).get("checkpoint")
    return Path(raw).expanduser() if raw else None


def sha256(path: Path) -> str:
    st = path.stat()
    key = (str(path.resolve()), st.st_size, st.st_mtime)
    if key not in _sums:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        _sums[key] = h.hexdigest()
    return _sums[key]


def why_not_available() -> str:
    """'' when beat_this can run; otherwise a plain reason (the CPU tracker is used instead)."""
    if importlib.util.find_spec("beat_this") is None or importlib.util.find_spec("torch") is None:
        return "beat_this is not installed (it needs torch; studio env only)"
    p = checkpoint_path()
    if p is None:
        return f"no beat_this checkpoint set (env {ENV})"
    if not p.is_file():
        return "the beat_this checkpoint file is missing"
    if sha256(p) != expected_sha256():
        return "the beat_this checkpoint file does not match the pinned sha256"
    return ""


def available() -> bool:
    return not why_not_available()


def beats_and_downbeats(path: str | Path, device: str = "cpu") -> tuple[list[float], list[float]]:
    """(beat times, downbeat times) in seconds from the verified local checkpoint. Never downloads anything."""
    why = why_not_available()
    if why:
        raise RuntimeError(why)
    from beat_this.inference import File2Beats  # noqa: PLC0415  (optional dependency)

    # ASSUMED API (beat_this README): File2Beats takes a local checkpoint file path; confirm on the studio env.
    f2b = File2Beats(checkpoint_path=str(checkpoint_path()), device=device, dbn=False)
    beats, downbeats = f2b(str(path))
    return [float(t) for t in beats], [float(t) for t in downbeats]
