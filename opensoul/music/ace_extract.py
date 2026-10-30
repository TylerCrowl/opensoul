"""ACE-Step 1.5 'extract' (vocal separation) runner: STUB, untested.

The extract task runs only on the ACE-Step 1.5 base / XL base models (``ACE-Step/acestep-v15-xl-base``, MIT, pinned in
presets/music_models.json), not on the XL Turbo model the song step uses. It needs the ACE-Step Python env next to
ComfyUI; nothing here runs in the app's .venv. Until this is built and checked on a GPU, the registry entry stays
disabled and the Music tab uses the full mix for lip-sync.
"""
from __future__ import annotations

from pathlib import Path


def extract_vocals(song: Path, out_dir: Path) -> Path:
    raise NotImplementedError("ACE-Step vocal extract is not built yet (untested; planned after the GPU smoke).")
