"""Story start frames: put up to three cast members into one scene picture (workflow 08, Qwen-Image-Edit-2511
multi-image edit, local open weights). Used by the Storyboard ("New start frame") and scripts/story_frames.py.

A start frame is a still take; a Draft/Final video take of the shot then starts from it (image-to-video).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "workflows/08_scene_compose_api.json"
OUTPUT_NODE = "9"
IMAGE_NODES = ("5", "51", "52")
MAX_CAST = 3
STYLE = ("Photorealistic live-action film still, natural skin, cinematic light, 16:9. "
         "No real brand names, no logos, no readable text.")
ORDINAL = ("picture 1", "picture 2", "picture 3")


def frame_inputs(images: list, prompt: str, seed: int, width: int = 1344, height: int = 768) -> dict:
    """Node inputs for workflow 08. With fewer than three pictures the last one is repeated."""
    if len(list(images)) > MAX_CAST:
        raise ValueError(f"A start frame fits up to {MAX_CAST} character pictures.")
    imgs = [str(x) for x in images]
    if not imgs:
        raise ValueError("A start frame needs at least one character picture.")
    imgs += [imgs[-1]] * (MAX_CAST - len(imgs))
    return {IMAGE_NODES[0]: {"image": imgs[0]}, IMAGE_NODES[1]: {"image": imgs[1]}, IMAGE_NODES[2]: {"image": imgs[2]},
            "6": {"prompt": prompt}, "3": {"seed": int(seed)}, "8": {"width": int(width), "height": int(height)}}


from opensoul.ear_trim import HIDDEN_EARS_PHRASE, wants_subtle_ears  # noqa: E402


def location_sentence(name: str, description: str = "", angle: str = "", angle_note: str = "") -> str:
    """Picture 1 is the stage plate (the master, or the shot's stage angle): keep the set itself,
    change only who is in it and what they do."""
    desc = (description or "").strip().rstrip(".")
    what = f"the {angle} angle of the stage" if angle else "the master plate of the location"
    note = (angle_note or "").strip().rstrip(".")
    return (f"Picture 1 is {what} ({name}): keep its camera position, set, layout, props, "
            "window view, lighting and colors exactly the same; only the people and their action change."
            + (f" This angle: {note}." if note else "")
            + (f" The set: {desc}." if desc else ""))


def cast_prompt(cast: list[dict], scene: str, style: str = STYLE, location: dict | None = None) -> str:
    """One sentence per cast member ("keep the person from picture N exactly the same: <look>"), then the scene.
    With ``location`` ({"name", "description"}), picture 1 is the set's master plate and the cast starts at picture 2."""
    parts = []
    off = 1 if location else 0
    if location:
        parts.append(location_sentence(location.get("name", ""), location.get("description", ""),
                                       location.get("angle", ""), location.get("angle_note", "")))
    for i, c in enumerate(cast[:MAX_CAST - off]):
        look = (c.get("prompt_lock") or "").strip().rstrip(".")
        who = f" ({c['name']})" if c.get("name") else ""
        parts.append(f"Keep the person from {ORDINAL[i + off]}{who} exactly the same (face, hair, ears, outfit)" + (f": {look}." if look else "."))
        if wants_subtle_ears(look):  # "subtle elf ears" alone still draws long spikes; hiding them in the hair works
            parts.append(HIDDEN_EARS_PHRASE)
    if len(cast) > 1:
        parts.append(f"All {len(cast[:MAX_CAST - off])} of them are in the same scene, each appearing exactly once.")
    parts.append(scene.strip().rstrip(".") + ".")
    parts.append(style)
    return " ".join(p for p in parts if p.strip(". "))


def size_for(aspect: str) -> tuple[int, int]:
    return (768, 1344) if aspect == "9:16" else (1344, 768)


NEGATIVE_NODE = "7"


def frame_negative(avoid: list[str] | None) -> str | None:
    """OS-068: workflow 08's negative prompt with the story's Avoid items added (None = leave it as it is)."""
    if not avoid:
        return None
    import json

    from opensoul.originality import negative

    try:
        base = json.loads(WORKFLOW.read_text(encoding="utf-8"))[NEGATIVE_NODE]["inputs"]["prompt"]
    except (OSError, ValueError, KeyError):
        base = ""
    return negative(base, avoid)


def compose_frame(images: list, prompt: str, seed: int, dest: str | Path, *, aspect: str = "16:9",
                  runner: Callable | None = None, avoid: list[str] | None = None) -> Path:
    """Render one start frame and save it at ``dest`` (png)."""
    if runner is None:
        from opensoul.comfy_client import run_workflow_file as runner  # noqa: N806
    w, h = size_for(aspect)
    dest = Path(dest)
    tmp = dest.parent / f"_{dest.stem}"
    inputs = frame_inputs(images, prompt, seed, w, h)
    neg = frame_negative(avoid)
    if neg:
        inputs[NEGATIVE_NODE] = {"prompt": neg}
    got = runner(WORKFLOW, inputs=inputs, output_node_id=OUTPUT_NODE, out_dir=tmp)
    if not got:
        raise RuntimeError("The start-frame workflow returned no picture.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    Path(got[0]).replace(dest)
    return dest


TEXT_WORKFLOW = ROOT / "workflows/07z_master_from_text_zimage_api.json"
TEXT_OUTPUT_NODE = "10"
NO_PEOPLE = "No people in the frame."


def text_prompt(scene: str, style: str = STYLE, no_people: bool = True) -> str:
    """OS-066: the prompt of a start frame made from words only (a shot with no cast and no stage)."""
    parts = [scene.strip().rstrip(".") + "."]
    if no_people and not re.search(r"\b(no|without) (people|person|one|humans?)\b|\bnobody\b", scene, re.I):
        parts.append(NO_PEOPLE)
    parts.append(style)
    return " ".join(p for p in parts if p.strip(". "))


def text_frame(prompt: str, seed: int, dest: str | Path, *, aspect: str = "16:9", negative: str = "",
               runner: Callable | None = None) -> Path:
    """OS-066: a start frame from words only, for a shot with no cast and no stage (establishing or action shots).
    Z-Image-Turbo (workflow 07z, Apache-2.0) as text-to-image at the story's size; saved at ``dest`` (png)."""
    if runner is None:
        from opensoul.comfy_client import run_workflow_file as runner  # noqa: N806
    from opensoul import zimage_master as zm

    files = zm.load_config().get("files") or {}
    w, h = size_for(aspect)
    inputs = {"5": {"text": prompt}, "6": {"text": negative or "text, watermark, logo"},
              "7": {"width": w, "height": h, "batch_size": 1}, "8": {"seed": int(seed)}}
    for node, key, name in (("1", "unet_name", files.get("unet")), ("2", "clip_name", files.get("clip")),
                            ("3", "vae_name", files.get("vae"))):
        if name:
            inputs[node] = {key: name}
    dest = Path(dest)
    tmp = dest.parent / f"_{dest.stem}"
    got = runner(TEXT_WORKFLOW, inputs=inputs, output_node_id=TEXT_OUTPUT_NODE, out_dir=tmp)
    if not got:
        raise RuntimeError("The start-frame workflow returned no picture.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    Path(got[0]).replace(dest)
    return dest


def preview_frame(images: list, dest: str | Path, *, aspect: str = "16:9", label: str = "",
                  title: str = "Start frame · preview") -> Path:
    """Dry-run stand-in: the cast pictures side by side on a neutral card, clearly stamped PREVIEW. ``title`` is the big
    line (a stage angle passes its own name, so a built stage sheet never reads "Start frame" on every tile)."""
    from PIL import Image, ImageDraw, ImageFont, ImageOps

    w, h = (720, 1280) if aspect == "9:16" else (1280, 720)
    card = Image.new("RGB", (w, h), "#E8E8ED")
    pics = [Path(p) for p in images[:MAX_CAST] if Path(p).is_file()]
    if pics:
        cw = w // len(pics)
        for i, p in enumerate(pics):
            card.paste(ImageOps.fit(Image.open(p).convert("RGB"), (cw, h)), (i * cw, 0))
    d = ImageDraw.Draw(card, "RGBA")
    try:
        big, small = ImageFont.load_default(size=h // 20), ImageFont.load_default(size=h // 34)
    except TypeError:
        big = small = ImageFont.load_default()
    d.rectangle((0, int(h * 0.78), w, h), fill=(0, 0, 0, 150))
    d.text((40, int(h * 0.81)), title[:60], fill="white", font=big)
    d.text((40, int(h * 0.90)), (label or "In Studio mode this is composed with Qwen-Image-Edit (workflow 08).")[:120],
           fill=(235, 235, 240), font=small)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    card.save(dest)
    return dest
