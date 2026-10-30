"""OS-068: original designs. A story has an Avoid list: words for things the pictures and takes must not show.

* The default list names the traits that make a design read as a famous one (a V-shaped head fin on a robot, a
  twin-eye mecha face, a tricolor hero-robot chest, a glowing eye power, mascot or superhero logos). It is on unless
  the story turns it off. The user adds their own words.
* Both image models in OpenSoul run at cfg 1 (4-step and turbo distills), where a negative prompt is not read. Naming
  a trait in the picture prompt, even after "do not show", draws it (studio check, Oct 29: "Do not show: V-shaped head
  fin" gave a V-antenna helmet). So the default traits go only into negative prompts (the video model, any setup with
  guidance), and the picture prompt gets a positive design sentence instead when the words ask for a robot, armor or
  a glowing eye. The user's own Avoid words go into the picture prompt as "Do not show: ...".
* A shot whose words name a known franchise or character gets a note: describe your own design instead.
The default list is descriptive words only. It never names a franchise, so it never pulls the model toward one."""
from __future__ import annotations

import re

DEFAULT_AVOID = (
    "V-shaped head fin or antenna on a robot",
    "twin-eye robot face with a mouth grille",
    "blue, white, red and yellow robot armor",
    "glowing magic symbols in an eye",
    "famous cartoon mascots",
    "superhero emblems and brand logos",
)
MAX_AVOID = 400

# Names that ask a model for someone else's design. Lower case, whole words. Kept short: the note is the guard.
WATCH = (
    "gundam", "zaku", "evangelion", "eva unit", "macross", "valkyrie fighter", "transformers", "optimus prime",
    "autobot", "decepticon", "pokemon", "pokémon", "pikachu", "sharingan", "rinnegan", "naruto", "sasuke",
    "goku", "super saiyan", "one piece", "luffy", "sailor moon", "totoro", "studio ghibli", "ghibli", "mickey mouse",
    "disney", "pixar", "marvel", "spider-man", "spiderman", "iron man", "batman", "superman", "star wars", "jedi",
    "lightsaber", "darth vader", "stormtrooper", "hello kitty", "mario", "zelda", "sonic the hedgehog", "minecraft",
    "fortnite", "harry potter", "hogwarts", "attack on titan", "demon slayer", "jujutsu", "my little pony",
)
_WATCH = re.compile(r"\b(" + "|".join(re.escape(w) for w in WATCH) + r")\b", re.I)


def clean(text: str | None) -> str:
    """The user's Avoid words: one line, commas between items, 400 characters at most."""
    items = [" ".join(x.split()) for x in re.split(r"[,\n;]+", str(text or ""))]
    return ", ".join(x for x in items if x)[:MAX_AVOID]


def items(user: str = "", defaults: bool = True) -> list[str]:
    out = list(DEFAULT_AVOID) if defaults else []
    out += [x.strip() for x in clean(user).split(",") if x.strip()]
    seen, uniq = set(), []
    for x in out:
        if x.lower() not in seen:
            seen.add(x.lower())
            uniq.append(x)
    return uniq


# (words in the shot, positive design sentence for the picture prompt)
GUARDS = (
    (re.compile(r"\b(robots?|mecha|mechs?|androids?|cyborgs?|armou?r\w*|power suits?|exosuits?|helmets?|knights?)\b", re.I),
     "Original design: a smooth rounded helmet with a plain flat top and sides, one plain dark visor, and armor in one "
     "or two muted colors."),
    (re.compile(r"\b(glow\w* eyes?|eyes? (?:that )?glow\w*|eye (?:power|beam|flare)s?)\b", re.I),
     "Plain eyes with no symbols or patterns in them."),
)


def guards(text: str) -> list[str]:
    """Positive design sentences for the picture prompt, for the words that call for them."""
    return [g for rx, g in GUARDS if rx.search(text or "")]


def sentence(avoid: list[str], text: str = "", defaults: bool = True) -> str:
    """The picture-prompt part: positive design sentences (default list on) and the user's own words as 'Do not show'.
    The default traits themselves are never named here (cfg 1 models draw what they read)."""
    own = [x for x in avoid if x not in DEFAULT_AVOID]
    parts = (guards(text) if defaults else []) + ([f"Do not show: {'; '.join(own)}."] if own else [])
    return " ".join(parts)


def negative(neg: str, avoid: list[str]) -> str:
    """The negative prompt with the Avoid items added (once each)."""
    have = [x.strip() for x in str(neg or "").split(",") if x.strip()]
    low = {x.lower() for x in have}
    return ", ".join(have + [x for x in avoid if x.lower() not in low])


def names_in(text: str) -> list[str]:
    """Known franchise or character names in the text, in order, once each."""
    seen, out = set(), []
    for m in _WATCH.finditer(text or ""):
        k = m.group(1).lower()
        if k not in seen:
            seen.add(k)
            out.append(m.group(1))
    return out


def note(text: str) -> str:
    found = names_in(text)
    if not found:
        return ""
    return (f"The words name {', '.join(found[:3])}. OpenSoul makes original designs: the model can copy a known "
            "design from a name. Describe your own design instead, and add what to avoid under Avoid.")


def for_project(p) -> list[str]:
    return items(getattr(p, "avoid", "") or "", bool(getattr(p, "avoid_defaults", True)))
