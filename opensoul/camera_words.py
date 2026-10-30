"""OS-039: camera moves in words of what the viewer sees, not of the gear.

LTX reads gear words literally: 'Crane/jib rising' on an empty street drew a real crane, a tripod and a crew member.
So a story take's video prompt names the move by its effect ('the view rises slowly'), and the negative prompt
asks for no camera gear in the picture. A shot with no cast drops the 'keep the subject framed' words."""
from __future__ import annotations

import re

# (pattern, replacement), applied in order. Case-insensitive; replacements are plain viewer words.
_SWAPS: list[tuple[str, str]] = [
    (r"Crane/jib rising vertically", "The view rises slowly and smoothly"),
    (r"Crane/jib descending", "The view comes down slowly and smoothly"),
    (r"\bcranes? (up|down)\b", r"rises \1"),
    (r"Locked-off tripod shot", "Locked-off shot"),
    (r"on a locked-off tripod", "perfectly still"),
    (r"Smooth motorized dolly push-in", "Smooth, slow push-in"),
    (r"Smooth dolly pull-back", "Smooth, slow pull-back"),
    (r"FPV racing-drone flythrough", "Fast flying view"),
    (r"an FPV drone camera glides", "the view glides"),
    (r"Lateral track to the (left|right) on a level slider", r"The view slides sideways to the \1"),
    (r"\b(?:on a |level )?slider\b", ""),
    (r"\btrucks (left|right)\b", r"slides \1"),
    (r"\bdollies (in|back)\b", r"moves \1"),
]
_NO_CAST_DROP = [r",?\s*(?:the )?(?:camera )?(?:gentle )?tilts? (?:up|down)(?: slightly)? to keep the subject framed", r",?\s*subject (?:stays|holds) (?:frame-)?cent(?:ered|er)(?: and in focus)?"]
GEAR_NEGATIVE = "camera crane, jib arm, tripod, dolly track, slider rail, film crew, camera operator, boom microphone, film equipment"


def viewer_words(text: str, has_cast: bool = True) -> str:
    out = str(text or "")
    for pat, rep in _SWAPS:
        out = re.sub(pat, rep, out, flags=re.IGNORECASE)
    if not has_cast:
        for pat in _NO_CAST_DROP:
            out = re.sub(pat, "", out, flags=re.IGNORECASE)
    out = re.sub(r"\s+,", ",", out)
    return re.sub(r"\s{2,}", " ", out).strip()


def negative(neg: str) -> str:
    """The negative prompt plus 'no camera gear in the picture' (added once)."""
    neg = str(neg or "").strip()
    if "camera crane" in neg:
        return neg
    return f"{neg}, {GEAR_NEGATIVE}" if neg else GEAR_NEGATIVE
