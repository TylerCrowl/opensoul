"""The bundled demo character, for tests that need "the demo" or "anyone else". Tests import these instead of
hard-coding a name, so switching the demo (app/server.py DEMO_NAME / DEMO_PACKS) never means editing tests."""
from pathlib import Path

import app.server as _server

ROOT = Path(__file__).resolve().parents[1]
DEMO_NAME = _server.DEMO_NAME                  # the main demo character (Create's "Use the demo character")
DEMO_PACK = _server.DEMO_PACK                  # its bundled pack (never modified)
DEMO_PACKS = dict(_server.DEMO_PACKS)          # every bundled demo pack by name (main first)
SECOND_DEMO = [n for n in DEMO_PACKS if n != DEMO_NAME][0]
DEMO_POSTER = ROOT / (_server._poster_url() or "").removeprefix("/")
DEMO_SHEET = ROOT / (_server._sheet_url(display=False) or "").removeprefix("/")
OTHER_NAME = "Brindle"                         # a made-up user character that is never a demo or library name


def demo_ref() -> Path:
    from opensoul.character_pack import CharacterPack

    return Path(CharacterPack.load(DEMO_PACK).ref_images[0])
