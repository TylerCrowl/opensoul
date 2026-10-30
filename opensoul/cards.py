"""OS-063: title and end cards. A card is text on a plain color, drawn on this computer with Pillow (no image model,
no GPU), so the words are exactly what you typed. It is a still take; the export shows it for the shot's Length."""
from __future__ import annotations

import re
from pathlib import Path

BACKGROUNDS = {"black": ("#000000", "#F5F5F7"), "white": ("#FFFFFF", "#1D1D1F"), "night": ("#0B1026", "#F5F5F7"),
               "red": ("#5A0C0C", "#F5F5F7")}
MAX_TITLE, MAX_SUB = 80, 160
# Fonts the computer already has (bold first). None found: Pillow's own font.
FONT_FILES = (
    "/System/Library/Fonts/SFNS.ttf", "/System/Library/Fonts/Helvetica.ttc", "/Library/Fonts/Arial Bold.ttf",
    "C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
)


class CardError(ValueError):
    pass


def clean(title: str | None, sub: str | None, bg: str | None) -> dict:
    """Checked card fields. Raises CardError with a plain message."""
    t = " ".join(str(title or "").split())[:MAX_TITLE]
    s = " ".join(str(sub or "").split())[:MAX_SUB]
    b = str(bg or "black").strip().lower()
    if b not in BACKGROUNDS and not re.fullmatch(r"#[0-9a-f]{6}", b):
        raise CardError("Pick black, white, night, red, or a color like #102030.")
    return {"card_title": t, "card_sub": s, "card_bg": b}


def colors(bg: str) -> tuple[str, str]:
    if bg in BACKGROUNDS:
        return BACKGROUNDS[bg]
    r, g, b = (int(bg[i:i + 2], 16) for i in (1, 3, 5))
    return bg, ("#1D1D1F" if (0.299 * r + 0.587 * g + 0.114 * b) > 150 else "#F5F5F7")


def _font(size: int):
    from PIL import ImageFont

    for f in FONT_FILES:
        if Path(f).is_file():
            try:
                return ImageFont.truetype(f, size)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # very old Pillow
        return ImageFont.load_default()


def _wrap(d, text: str, font, width: int) -> list[str]:
    out, cur = [], ""
    for w in text.split():
        t = f"{cur} {w}".strip()
        if d.textlength(t, font=font) <= width or not cur:
            cur = t
        else:
            out.append(cur)
            cur = w
    return out + ([cur] if cur else [])


def render(title: str, sub: str, bg: str, dest: str | Path, aspect: str = "16:9") -> Path:
    """Draw the card (1920x1080, or 1080x1920 for 9:16) and save it as PNG at ``dest``."""
    from PIL import Image, ImageDraw

    if not (title or sub):
        raise CardError("Type the words for the card first.")
    w, h = (1080, 1920) if aspect == "9:16" else (1920, 1080)
    back, ink = colors(bg)
    img = Image.new("RGB", (w, h), back)
    d = ImageDraw.Draw(img)
    big, small = _font(int(min(w, h) * 0.11)), _font(int(min(w, h) * 0.04))
    lines = [(x, big) for x in _wrap(d, title, big, int(w * 0.84))] if title else []
    sub_lines = [(x, small) for x in _wrap(d, sub, small, int(w * 0.78))] if sub else []

    def lh(f):
        a, b = f.getbbox("Hg")[1], f.getbbox("Hg")[3]
        return int((b - a) * 1.3)

    gap = int(min(w, h) * 0.05) if lines and sub_lines else 0
    total = sum(lh(f) for _, f in lines) + gap + sum(lh(f) for _, f in sub_lines)
    y = (h - total) // 2
    for i, (text, f) in enumerate(lines + sub_lines):
        if i == len(lines) and gap:
            y += gap
        tw = d.textlength(text, font=f)
        d.text(((w - tw) / 2, y), text, font=f, fill=ink if f is big else _soft(ink, back))
        y += lh(f)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest)
    return dest


def _soft(ink: str, back: str) -> str:
    """The small line: the text color, a little toward the background."""
    a = [int(ink[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(back[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{int(x * 0.75 + y * 0.25):02x}" for x, y in zip(a, b))
