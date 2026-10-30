#!/usr/bin/env python3
"""Switch the demo characters' origin wording: set_character_origin.py rebuild|disclose  (or --check).

Rewrites every file listed in opensoul/character_origin.py from presets/character_origin.json. Commit the result."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from opensoul import character_origin as co  # noqa: E402

if __name__ == "__main__":
    arg = (sys.argv[1:] or ["--check"])[0]
    if arg == "--check":
        bad = co.stale()
        print(f"mode {co.mode()}: " + ("in sync" if not bad else "out of sync: " + ", ".join(bad)))
        sys.exit(1 if bad else 0)
    if arg not in co.MODES:
        sys.exit(f"usage: {sys.argv[0]} rebuild|disclose|--check")
    changed = co.switch(arg)
    print(f"mode {arg}: " + (", ".join(changed) if changed else "nothing to change"))
