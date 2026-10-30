"""One switch for the demo characters' origin and disclosure wording (presets/character_origin.json).

``character_origin_mode`` is 'rebuild' (the look is being rebuilt from text with open models; the default) or
'disclose' (keep the current look and say it was made from concept images by a closed (non-open) image generator).
Every place that carries the wording is listed below: JSON fields are rewritten in place, and text files carry the
wording between ``<!-- origin:KEY -->`` and ``<!-- /origin:KEY -->`` markers. Switch with
``scripts/set_character_origin.py disclose`` (or ``rebuild``), then commit."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = "presets/character_origin.json"
MODES = ("rebuild", "disclose")
FIELDS = [  # (file, JSON key path, text key)
    ("assets/lumi/character.json", ("origin",), "lumi_origin"),
    ("assets/mio/character.json", ("origin",), "couple_origin"),
    ("assets/ren/character.json", ("origin",), "couple_origin"),
    ("presets/demo_images.json", ("first_run_still", "caption"), "start_caption"),  # start card
    ("presets/demo_images.json", ("cast", "lumi", "note"), "lumi_card_note"),       # Lumi's card
]
MARKED = {  # file -> text keys marked in it
    "README.md": ["readme_note"],
    "assets/lumi/README.md": ["lumi_readme"],
    "assets/mio/README.md": ["couple_readme"],
    "assets/ren/README.md": ["couple_readme"],
    "docs/ASSET_PROVENANCE.md": ["provenance_note"],
    "app/web/index.html": ["demo_legal", "credits_characters"],  # demo legal line, credits Characters line
}


def config(root: Path = ROOT) -> dict:
    return json.loads((root / CONFIG).read_text(encoding="utf-8"))


def mode(root: Path = ROOT) -> str:
    m = config(root).get("character_origin_mode", "rebuild")
    if m not in MODES:
        raise ValueError(f"character_origin_mode must be one of {MODES}, not {m!r}")
    return m


def _marker(key: str) -> re.Pattern:
    return re.compile(rf"(<!-- origin:{key} -->)(.*?)(<!-- /origin:{key} -->)", re.S)


def _get(d, path):
    for k in path:
        d = d[k]
    return d


def render(m: str, root: Path = ROOT) -> dict[str, str]:
    """{file: new text} for every listed file in mode ``m`` (unchanged files included)."""
    if m not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    texts = config(root)["texts"]
    out: dict[str, str] = {}
    for rel, keys in MARKED.items():
        if not (root / rel).is_file():  # e.g. docs/drafts/ is left out of release archives
            continue
        s = (root / rel).read_text(encoding="utf-8")
        for key in keys:
            pat = _marker(key)
            if not pat.search(s):
                raise ValueError(f"{rel}: no <!-- origin:{key} --> marker")
            s = pat.sub(lambda mt: mt.group(1) + texts[key][m] + mt.group(3), s)
        out[rel] = s
    for rel, path, key in FIELDS:
        s = out.get(rel) or (root / rel).read_text(encoding="utf-8")
        old, new = _get(json.loads(s), path), texts[key][m]
        if old != new:
            for enc in (json.dumps(old, ensure_ascii=False), json.dumps(old)):
                if s.count(enc) == 1:
                    s = s.replace(enc, json.dumps(new, ensure_ascii=False))
                    break
            else:
                raise ValueError(f"{rel}: can't place {'.'.join(path)} safely")
            assert _get(json.loads(s), path) == new
        out[rel] = s
    return out


def stale(root: Path = ROOT) -> list[str]:
    """Files whose wording doesn't match the configured mode (empty when in sync)."""
    return [rel for rel, s in render(mode(root), root).items() if (root / rel).read_text(encoding="utf-8") != s]


def switch(m: str, root: Path = ROOT) -> list[str]:
    """Set the mode and rewrite every listed file. Returns the files changed."""
    changed = []
    for rel, s in render(m, root).items():
        if (root / rel).read_text(encoding="utf-8") != s:
            (root / rel).write_text(s, encoding="utf-8")
            changed.append(rel)
    cfg_path = root / CONFIG
    raw = cfg_path.read_text(encoding="utf-8")
    new = re.sub(r'("character_origin_mode":\s*)"[a-z]+"', rf'\1"{m}"', raw, count=1)
    if new != raw:
        cfg_path.write_text(new, encoding="utf-8")
        changed.append(CONFIG)
    return changed
