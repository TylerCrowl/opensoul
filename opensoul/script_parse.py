"""Parse a short-script markdown file (content/<character>/*.md) into spoken lines + shot list."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ParsedScript:
    title: str
    spoken: str
    tip: str
    shots: list[dict]  # {t, shot, action}


def friendly_title(stem: str) -> str:
    import re as _re

    return _re.sub(r"^\d+_", "", stem).replace("_", " ").capitalize() if stem else "Script"


def parse_script_markdown(md: str, stem: str = "") -> ParsedScript:
    title = friendly_title(stem) if stem else "Script"
    m = re.search(r"^#\s+(.+)$", md, re.M)
    if m:
        title = m.group(1).strip()

    spoken = ""
    tip = ""
    shots: list[dict] = []

    # Spoken script section
    m = re.search(
        r"##\s+Spoken script\s*(.*?)(?=\n##\s+|\Z)",
        md,
        re.S | re.I,
    )
    if m:
        block = m.group(1)
        # Drop stage directions in italics
        block = re.sub(r"^\*.*\*\s*$", "", block, flags=re.M)
        # Prefer quoted dialogue if present
        quotes = re.findall(r'"([^"]+)"', block, re.S)
        if quotes:
            spoken = "\n\n".join(q.strip() for q in quotes)
        else:
            spoken = block.strip()
        spoken = re.sub(r"[ \t]+\n", "\n", spoken)
        spoken = re.sub(r"\n{3,}", "\n\n", spoken).strip()
        # Normalize soft line breaks inside verses
        spoken = spoken.replace("  \n", "\n")

    m = re.search(
        r"##\s+Useful tip\s*(.*?)(?=\n##\s+|\Z)",
        md,
        re.S | re.I,
    )
    if m:
        tip = re.sub(r"\s+", " ", m.group(1)).strip()

    m = re.search(
        r"##\s+Shot list\s*(.*?)(?=\n##\s+|\Z)",
        md,
        re.S | re.I,
    )
    if m:
        table = m.group(1)
        for line in table.splitlines():
            line = line.strip()
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) < 3:
                continue
            if cells[0].lower() in {"t", "---", ":---"} or set(cells[0]) <= {"-", ":"}:
                continue
            if cells[0].startswith("-"):
                continue
            shots.append({"t": cells[0], "shot": cells[1], "action": cells[2]})

    return ParsedScript(title=title, spoken=spoken, tip=tip, shots=shots)
