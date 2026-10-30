"""GPU gate for the Music tab's studio mode: yield the GPU to other work before queueing a song or stem job.

Patterns come from presets/music_models.json ``gpu_gate.yield_to`` (tmux session name globs, e.g. ``mv_*`` for a
music-video render running in the studio's tmux). The check only *lists* session names (read-only
``tmux list-sessions``); it never attaches to, sends keys to or kills a session. Preview mode never calls it.
``OPENSOUL_GPU_GATE=off`` disables it (a studio without tmux).
"""
from __future__ import annotations

import fnmatch
import os
import shutil
import subprocess
import time
from typing import Callable

DEFAULT_YIELD_TO = ("mv_*",)


def tmux_sessions() -> list[str]:
    """Names of the local tmux sessions ([] when tmux is missing or no server runs). Read-only."""
    exe = shutil.which("tmux")
    if not exe:
        return []
    r = subprocess.run([exe, "list-sessions", "-F", "#{session_name}"], capture_output=True, text=True, timeout=5)
    return [s.strip() for s in r.stdout.splitlines() if s.strip()] if r.returncode == 0 else []


def busy(sessions: list[str], patterns: tuple[str, ...] | list[str] = DEFAULT_YIELD_TO) -> list[str]:
    """The sessions we must yield to."""
    return [s for s in sessions if any(fnmatch.fnmatchcase(s, p) for p in patterns)]


def patterns_from(registry: dict) -> tuple[str, ...]:
    return tuple((registry.get("gpu_gate") or {}).get("yield_to") or DEFAULT_YIELD_TO)


def wait_turn(patterns, *, lister: Callable[[], list[str]] | None = None, on_wait: Callable[[list[str]], None] | None = None,
              cancelled: Callable[[], bool] = lambda: False, interval_s: float = 30.0, max_wait_s: float = 7200.0,
              sleep: Callable[[float], None] | None = None) -> bool:
    """Block until no session matches ``patterns``. True = go; False = cancelled or waited too long."""
    if os.environ.get("OPENSOUL_GPU_GATE", "").strip().lower() == "off":
        return True
    lister = lister or tmux_sessions
    sleep = sleep or time.sleep
    waited = 0.0
    while True:
        b = busy(lister(), patterns)
        if not b:
            return True
        if cancelled() or waited >= max_wait_s:
            return False
        if on_wait:
            on_wait(b)
        sleep(interval_s)
        waited += interval_s
