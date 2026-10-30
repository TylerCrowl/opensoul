"""Vocal stem for lip-sync. One path only: the registry's default splitter (ACE-Step 1.5's own ``extract`` task, MIT,
which needs the optional XL base model). No other splitter is tried in its place (Demucs is blocked). OpenSoul ships
without stem separation: until that splitter is set up, the status says so and lip-sync uses the full mix. Preview
mode uses the preview hum.
A usable splitter's ``runner.module`` must provide ``extract_vocals(song: Path, out_dir: Path) -> Path``.
"""
from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from opensoul.music import registry as R

FULL_MIX = "Syncing to the full song (this studio has no vocal-only track)."


def sync_target(available: bool) -> str:
    """What the Sync buttons and lip-sync labels name: the vocal only when the vocal-only track is set up."""
    return "the vocal" if available else "the song"


def status(preview: bool, path: str | Path | None = None) -> dict[str, Any]:
    data = R.load(path)
    mid = R.default_id("stems", data, preview)
    try:
        m = R.get(mid, path)
    except R.RegistryError:
        return {"model": mid, "label": "", "available": False, "why": "no vocal splitter is chosen",
                "note": FULL_MIX}
    why = R.why_not_usable(m, data)
    why = [w for w in why if w != "not enabled"] or why
    if not why and not R.installed(m):
        why = [f"its files aren't installed: ./scripts/download_models.sh {m.get('download_group') or ''}".strip()]
    if why:
        return {"model": mid, "label": m["name"], "available": False, "why": why[0],
                "note": FULL_MIX}
    note = ("Preview vocal: the hum stands in for the singer." if m.get("preview_only")
            else f"Vocal stem from {m['name']}.")
    return {"model": mid, "label": m["name"], "available": True, "why": "", "note": note}


def extract_vocals(song: Path, out_dir: Path, path: str | Path | None = None) -> Path:
    """Run the default splitter (studio only). Raises RuntimeError with the plain reason when it isn't available."""
    st = status(False, path)
    if not st["available"]:
        raise RuntimeError(st["note"])
    mod = importlib.import_module(R.get(st["model"], path)["runner"]["module"])
    return Path(mod.extract_vocals(Path(song), Path(out_dir)))
