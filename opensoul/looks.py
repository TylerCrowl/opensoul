"""Story and character looks (OS-006, OS-010, OS-038): the art style every picture and video prompt follows.

"photo" is the old behaviour (photoreal live action). A drawn look (anime, 3D cartoon, painted illustration) swaps
the style sentence in every template and removes the words that fight it from the negative prompts ("cartoon",
"anime", "illustration", "3D render" ...). Prompts are built by the callers; this module only rewrites them, so a
story saved before looks existed (look "") renders exactly as before.
"""
from __future__ import annotations

import re

DEFAULT = "photo"

LOOKS: dict[str, dict] = {
    "photo": {
        "label": "Photo (live action)",
        "drawn": False,
        "still": "Photorealistic live-action film still.",
        "ref": "Photorealistic three-quarter-length reference photo of",
        "sheet": "Photorealistic photo, natural skin texture, sharp focus.",
        "video": "",
        "negative": "",
        "strip": (),
    },
    "anime": {
        "label": "Anime (2000s cel-shaded TV look)",
        "drawn": True,
        "still": ("2D anime film still in an early-2000s TV anime look: clean sharp line art, flat cel shading with "
                  "hard shadow edges, rich saturated colors, painted backgrounds, adult proportions."),
        "ref": "Three-quarter-length 2D anime character reference illustration of",
        "sheet": ("2D anime illustration in an early-2000s TV anime look: clean sharp line art, flat cel shading, the "
                  "same drawing style in every view, adult proportions."),
        "video": ("2D cel-shaded anime animation, early-2000s TV anime look, clean line art, flat colors, limited "
                  "animation style."),
        "negative": ("photo, photorealistic, realistic skin texture, live action, 3D render, CGI, chibi, child, "
                     "childlike proportions"),
        "strip": ("cartoon", "anime", "illustration", "cgi", "3d render", "plastic skin", "pc game", "console game",
                  "video game", "natural skin", "realistic"),
    },
    "toon3d": {
        "label": "3D cartoon",
        "drawn": True,
        "still": ("Stylized 3D animated film still: appealing cartoon proportions, soft global illumination, clean "
                  "materials."),
        "ref": "Three-quarter-length stylized 3D animated character reference render of",
        "sheet": "Stylized 3D animated character render, clean materials, the same style in every view.",
        "video": "Stylized 3D animated film, smooth animation.",
        "negative": "photo, photorealistic, live action, 2D, flat colors",
        "strip": ("cartoon", "cgi", "3d render", "plastic skin", "pc game", "console game", "video game",
                  "natural skin", "realistic"),
    },
    "illustration": {
        "label": "Painted illustration",
        "drawn": True,
        "still": "Painted storybook illustration: visible brush texture, soft colors, gentle light.",
        "ref": "Three-quarter-length painted character reference illustration of",
        "sheet": "Painted illustration, visible brush texture, the same painting style in every view.",
        "video": "Animated painted illustration, soft brush texture.",
        "negative": "photo, photorealistic, live action, 3D render, CGI",
        "strip": ("cartoon", "illustration", "anime", "cgi", "3d render", "plastic skin", "natural skin",
                  "realistic"),
    },
}
# The photoreal phrases in the templates (presets and code) that a drawn look replaces.
_STILL = re.compile(r"Photorealistic live-action film still(?:, natural skin, cinematic light, 16:9)?\.", re.I)
_REF = re.compile(r"Photorealistic three-quarter-length reference photo of", re.I)
_REF_SHORT = re.compile(r"Photorealistic reference photo of", re.I)
_SHEET = re.compile(r"Photorealistic photo, natural skin texture, sharp focus\.", re.I)
# Eye words that the video negative must drop when the shot asks for them (OS-038).
_EYES_ASKED = re.compile(r"\b(wink\w*|blink\w*|squint\w*|closed eyes|eyes closed|closes (?:her|his|their) eyes)\b", re.I)


def check(look: str | None) -> str:
    """'' or None -> '' (not set: the photo default); an unknown id raises ValueError."""
    look = (look or "").strip().lower()
    if look and look not in LOOKS:
        raise ValueError(f"Look must be one of: {', '.join(LOOKS)}.")
    return look


def get(look: str | None) -> dict:
    return LOOKS.get((look or "").strip().lower() or DEFAULT, LOOKS[DEFAULT])


def is_drawn(look: str | None) -> bool:
    return bool(get(look)["drawn"])


def choices() -> list[dict]:
    return [{"id": k, "label": v["label"], "drawn": v["drawn"]} for k, v in LOOKS.items()]


def prompt(text: str, look: str | None) -> str:
    """Swap the photoreal style phrases of a template for the look's own. 'photo' and '' leave it as it is."""
    L = get(look)
    if not L["drawn"]:
        return text
    out = _STILL.sub(L["still"], text)
    out = _REF.sub(L["ref"], out)
    out = _REF_SHORT.sub(L["ref"].replace("Three-quarter-length ", "").capitalize(), out)
    out = _SHEET.sub(L["sheet"], out)
    if L["still"] not in out and L["ref"] not in out and L["sheet"] not in out:
        out = out.rstrip() + " " + L["still"]
    return out


def _split(neg: str) -> list[str]:
    return [p.strip() for p in str(neg or "").split(",") if p.strip()]


def negative(neg: str, look: str | None, shot_text: str = "") -> str:
    """The negative prompt for the look: drop the words that fight a drawn look, add the look's own; drop 'closed
    eyes' / 'squinting' when the shot text asks for a wink, a blink or closed eyes."""
    L = get(look)
    parts = _split(neg)
    if L["drawn"]:
        strip = L["strip"]
        parts = [p for p in parts if not any(w in p.lower() for w in strip)]
    if shot_text and _EYES_ASKED.search(shot_text):
        parts = [p for p in parts if p.lower() not in {"squinting", "closed eyes", "closed eye"}]
    for p in _split(L["negative"]):
        if p.lower() not in {x.lower() for x in parts}:
            parts.append(p)
    return ", ".join(parts)


def video_prompt(text: str, look: str | None) -> str:
    """A video (LTX) prompt for the look: a drawn look puts its style sentence first."""
    L = get(look)
    if not L["drawn"] or not L["video"] or L["video"] in text:
        return text
    return f"{L['video']} {text}".strip()


def sheet_preset(preset: dict, look: str | None) -> dict:
    """presets/character_sheet.json for the look: the style line, the negatives and the from-text prompt."""
    if not is_drawn(look):
        return preset
    import copy

    p = copy.deepcopy(preset)
    p["style"] = prompt(p.get("style", ""), look)
    p["negative"] = negative(p.get("negative", ""), look)
    ft = p.get("from_text")
    if isinstance(ft, dict):
        if ft.get("prompt"):
            ft["prompt"] = prompt(ft["prompt"], look)
        if ft.get("negative"):
            ft["negative"] = negative(ft["negative"], look)
    return p
