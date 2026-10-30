"""One-tap Character Sheet maker: one reference image -> six-view turnaround -> Soul Pack.

Views (presets/character_sheet.json): full body front / side / back and close-up front / side / back,
on a clean light gray background with the same lighting. Each view is a separate run of
``workflows/07_character_sheet_api.json`` (Qwen-Image-Edit-2511 bf16 + Lightning 4-step LoRA) through
the Comfy SDK (``opensoul.comfy_client.run_workflow_file``). Each view goes through the OpenSoul identity
gate (patch backend by default); an off-model view is re-rendered once with a new seed. The six views are
composited into a 3x2 grid with Pillow and added to the character's reference set (Soul Pack), so later
shots are gated against several angles instead of one photo.

Gate modes (``OPENSOUL_SHEET_GATE``):
  graph (default)  the gate node runs inside the workflow (needs custom_nodes/opensoul_nodes on the server).
                   comfy-api-proxy does not return the node's text report, so the verdict is recomputed
                   in-app with the node's own code on the saved image (identical pixels, identical score).
  local            for a ComfyUI without the OpenSoul node pack: node 20 is removed from the graph and the
                   same gate code runs in-app.

Policy: original characters or the user's own photos only (the caller must pass ``consent=True``).
There is deliberately no feature to replace a person in a video.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import re
import shutil
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
PRESET = ROOT / "presets" / "character_sheet.json"
WORKFLOW = ROOT / "workflows" / "07_character_sheet_api.json"
WORKFLOW_BACK_FROM_SIDE = ROOT / "workflows" / "07b_character_sheet_back_from_side_api.json"
NODE_IMAGE, NODE_POS, NODE_NEG, NODE_SEED, NODE_GATE, NODE_OUT = "5", "6", "7", "3", "20", "9"
NODE_LATENT = "8"
NODE_SOURCE = "21"  # 07b only: the side view the back view is rotated from
WORKFLOW_FROM_TEXT = ROOT / "workflows" / "07t_character_from_text_api.json"  # no input image: text -> reference

log = logging.getLogger("opensoul.sheet")


class ConsentRequired(ValueError):
    """Raised when the user has not confirmed they own the image or have permission."""


@dataclass
class ViewResult:
    id: str
    label: str
    path: str | None = None
    score: float | None = None
    passed: bool = False
    attempts: int = 0
    seed: int | None = None
    scores: list[float] = field(default_factory=list)
    status: str = "queued"  # queued | rendering | retrying | checking | done | failed
    error: str = ""
    arcface: float | None = None
    checks: list[dict] = field(default_factory=list)  # auto-fix VLM checks of the kept try
    note: str = ""  # plain-language warning when the view still fails after the retries
    corrections: str = ""  # corrective prompt addition used for the next try
    tries: list[dict] = field(default_factory=list)  # every try: seed, path, patch, arcface, failed checks


@dataclass
class SheetResult:
    sheet: str
    views: list[ViewResult]
    dry_run: bool
    gate: dict
    manifest: str = ""
    checklist: dict = field(default_factory=dict)
    checked: bool = True  # False when the auto-fix checker (VLM) did not run: only the face gate judged the views

    def to_dict(self) -> dict:
        d = asdict(self)
        d["views"] = [asdict(v) for v in self.views]
        return d


# ------------------------------------------------------------------ preset + prompts
def load_preset(path: str | Path = PRESET) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def view_prompt(view: dict, preset: dict, subject: str = "") -> str:
    """Full edit instruction for one view. ``subject`` is the character's locked look (optional)."""
    who = preset.get("subject_default", "the same person")
    text = view["prompt"].format(subject=who)
    parts = [text, preset["keep"]]
    if view.get("framing") == "close":  # lower-body details pull Qwen back to a full-body shot
        drop = [t.lower() for t in preset.get("close_drop_terms", [])]
        subject = ", ".join(p.strip() for p in subject.split(",") if not any(t in p.lower() for t in drop))
    if subject.strip():
        parts.append(f"Character details to preserve: {subject.strip()}.")
    parts.append(preset["style"])
    if view.get("framing") == "close":  # repeat the crop last: Qwen otherwise drifts back to full body
        parts.append("Remember: head-and-shoulders close-up only, cut at the upper chest.")
    return " ".join(parts)


def reference_prompt(description: str, preset: dict) -> str:
    """Prompt for the reference portrait of a character that exists only as a text description."""
    ft = preset.get("from_text") or {}
    tmpl = ft.get("prompt", "Front-facing reference portrait of {description}. {style}")
    return re.sub(r"\s{2,}", " ", tmpl.format(description=description.strip().rstrip("."), style=preset["style"])).strip()


def make_reference_from_text(description: str, out_dir: str | Path, *, seeds: list[int] | None = None,
                             runner: Callable | None = None, preset: dict | None = None,
                             dry_run: bool | None = None) -> list[Path]:
    """Text-only start: render reference portrait candidate(s) for ``description`` with workflow 07t (the sheet's
    own Qwen-Image-Edit model, no input image). Returns one image per seed; the sheet is then made from the one
    the user picks (or the first). No photo of anyone is involved."""
    if not description.strip():
        raise ValueError("Describe the character first (look, hair, outfit).")
    preset = preset or load_preset()
    ft = preset.get("from_text") or {}
    seeds = list(seeds or [int(ft.get("seed", 7))])
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    dry = _dry() if dry_run is None else dry_run
    paths: list[Path] = []
    for sd in seeds:
        if dry:
            p = out / f"reference_seed{sd}.png"
            img = Image.new("RGB", (int(ft.get("width", 832)), int(ft.get("height", 1248))), preset["grid"]["background"])
            ImageDraw.Draw(img).text((20, 20), "PREVIEW", fill="#9A9A9A", font=_font(32))
            img.save(p)
            paths.append(p)
            continue
        if runner is None:
            from opensoul.comfy_client import run_workflow_file as runner  # noqa: N806
        inputs = {NODE_POS: {"prompt": reference_prompt(description, preset)},
                  NODE_NEG: {"prompt": ft.get("negative", preset["negative"])},
                  NODE_SEED: {"seed": int(sd), "steps": int(preset["sampler"]["steps"]), "cfg": float(preset["sampler"]["cfg"])},
                  NODE_LATENT: {"width": int(ft.get("width", 832)), "height": int(ft.get("height", 1248))}}
        got = runner(WORKFLOW_FROM_TEXT, inputs=inputs, output_node_id=NODE_OUT, out_dir=out / f"seed{sd}")
        if got:
            dest = out / f"reference_seed{sd}{Path(got[0]).suffix or '.png'}"
            shutil.copyfile(got[0], dest)
            paths.append(dest)
    if not paths:
        raise RuntimeError("Couldn't render a reference from the description.")
    return paths


def view_seed(view: dict, preset: dict, base_seed: int | None, attempt: int) -> int:
    base = preset["sampler"]["seed"] if base_seed is None else int(base_seed)
    return base + int(view.get("seed_offset", 0)) + attempt * int(preset["gate"].get("retry_seed_offset", 1009))


def back_fallback_prompt(view: dict, preset: dict, subject: str, checklist: dict | None, strategy: str,
                         also: str = "") -> str:
    """Back-view fallback prompt (preset ``back_fallback``). Avoids 'backwards cap' wording, which Qwen keeps
    turning into a strap facing the camera; instead it describes what a camera behind the person sees."""
    fb = preset["back_fallback"]
    cl = checklist or {}
    subj = subject or preset.get("subject_default", "the same person")
    for term in fb.get("subject_drop", []):
        subj = re.sub(rf"\s*\b{re.escape(term)}\b", "", subj, flags=re.IGNORECASE)
    if view.get("framing") == "close":
        drop = [t.lower() for t in preset.get("close_drop_terms", [])]
        subj = ", ".join(p.strip() for p in subj.split(",") if not any(t in p.lower() for t in drop))
    subj = re.sub(r"\s{2,}", " ", subj).strip(" ,")
    hw = ""
    orient = str(cl.get("headwear_orientation") or "").lower()
    if cl.get("headwear") and "cap" in str(cl["headwear"]).lower() and "back" in orient:
        hw = fb["headwear_backward"].format(color=cl.get("headwear_color") or "")
        hw = re.sub(r"\s{2,}", " ", hw)
    if cl.get("sunglasses_on_headwear_or_head"):
        hw = f"{hw} {fb['sunglasses']}".strip()
    if hw:  # the headwear sentence replaces the subject's own cap description (and its 'brim' wording)
        word = str(cl.get("headwear") or "cap").lower().split()[-1]
        subj = ", ".join(p.strip() for p in subj.split(",") if word not in p.lower() and "sunglasses" not in p.lower())
    tmpl = fb["side_prompt"] if strategy == "side" else fb["wording_prompt"]
    text = tmpl.format(subject=subj, framing=fb["framing"][view.get("framing", "full")], headwear=hw)
    return re.sub(r"\s{2,}", " ", f"{text} {also} {preset['style']}").strip()


def view_inputs(ref: str | Path, view: dict, preset: dict, *, subject: str = "", seed: int,
                gate_in_graph: bool = True, corrections: str = "", prompt: str | None = None,
                source: str | Path | None = None) -> dict:
    """Node inputs for one run of workflow 07 (or 07b when ``source`` is given: the side view to rotate from).
    ``corrections`` (auto-fix) is appended to the view prompt; ``prompt`` replaces it (back-view fallback)."""
    prompt = prompt or view_prompt(view, preset, subject)
    if corrections:
        prompt = f"{prompt} {corrections}"
    inputs = {
        NODE_IMAGE: {"image": str(ref)},
        NODE_POS: {"prompt": prompt},
        NODE_NEG: {"prompt": preset["negative"]},
        NODE_SEED: {"seed": int(seed), "steps": int(preset["sampler"]["steps"]), "cfg": float(preset["sampler"]["cfg"])},
    }
    if view.get("width") and view.get("height"):
        inputs[NODE_LATENT] = {"width": int(view["width"]), "height": int(view["height"])}
    if source is not None:
        inputs[NODE_SOURCE] = {"image": str(source)}
    if gate_in_graph:
        inputs[NODE_GATE] = {"threshold": float(preset["gate"]["threshold"]), "backend": preset["gate"]["backend"]}
    return inputs


def graph_without_gate(graph: dict) -> dict:
    """Copy of workflow 07 with the gate node removed and SaveImage fed by VAEDecode."""
    g = json.loads(json.dumps(graph))
    gate = g.pop(NODE_GATE)
    g[NODE_OUT]["inputs"]["images"] = gate["inputs"]["candidates"]
    return g


# ------------------------------------------------------------------ identity gate (node code, in-app)
_NODES = None


def _nodes():
    """custom_nodes/opensoul_nodes/nodes.py, loaded without ComfyUI (it only needs numpy + PIL here)."""
    global _NODES
    if _NODES is None:
        spec = importlib.util.spec_from_file_location("opensoul_nodes_gate", ROOT / "custom_nodes/opensoul_nodes/nodes.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _NODES = m
    return _NODES


def gate_score(anchor: str | Path, candidate: str | Path, threshold: float, backend: str = "patch") -> dict:
    """Same scoring as the OpenSoulIdentityGate node's patch backend: returns its JSON report."""
    import numpy as np

    n = _nodes()
    if backend != "patch":  # arcface needs insightface in the ComfyUI env; in-app we fall back to patch
        backend = "patch"
    a = n.patch_embedding_array(np.asarray(Image.open(anchor).convert("RGB")))
    c = n.patch_embedding_array(np.asarray(Image.open(candidate).convert("RGB")))
    rep = n.gate_report([float(np.dot(a, c))], threshold)
    rep["backend"] = backend
    return rep


# ------------------------------------------------------------------ grid
def _font(size: int):
    for name in ("DejaVuSans.ttf", "Arial.ttf", "Helvetica.ttc"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def composite_grid(images: list[str | Path | Image.Image], labels: list[str] | None, out: str | Path, grid: dict,
                   title: str = "") -> Path:
    """3x2 turnaround grid on the preset's light gray. Row 1 full body, row 2 close-ups."""
    cols, rows = int(grid["cols"]), int(grid["rows"])
    cw, ch = int(grid["cell_width"]), int(grid["cell_height"])
    bg = grid.get("background", "#D8D8D8")
    pad = max(8, cw // 40)
    lab_h = (ch // 22) if grid.get("labels", True) and labels else 0
    W, H = cols * cw + (cols + 1) * pad, rows * (ch + lab_h) + (rows + 1) * pad
    sheet = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(sheet)
    font = _font(max(12, lab_h * 6 // 10)) if lab_h else None
    for i, src in enumerate(images[: cols * rows]):
        im = src if isinstance(src, Image.Image) else Image.open(src)
        im = ImageOps.fit(im.convert("RGB"), (cw, ch), Image.Resampling.LANCZOS, centering=(0.5, 0.4))
        r, c = divmod(i, cols)
        x, y = pad + c * (cw + pad), pad + r * (ch + lab_h + pad)
        sheet.paste(im, (x, y))
        if lab_h and labels and i < len(labels):
            draw.text((x + cw // 2, y + ch + lab_h // 2), labels[i], fill="#3A3A3A", font=font, anchor="mm")
    if title:
        draw.text((W - pad, H - pad // 2), title, fill="#6A6A6A", font=_font(max(10, pad)), anchor="rd")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, quality=92) if out.suffix.lower() in {".jpg", ".jpeg"} else sheet.save(out)
    return out


def _subject_mask(im: Image.Image) -> Image.Image | None:
    """Pixels that differ from the background (estimated from the four corners); None if no clear subject."""
    import numpy as np

    a = np.asarray(im.convert("RGB"), dtype=np.int16)
    h, w = a.shape[:2]
    k = max(2, min(h, w) // 20)
    # A studio backdrop is often lighter at the top than on the floor, and vignetted: blend the four corner colours
    # across the frame, so the floor and its shadow aren't taken for the subject. (A flat card: one colour, as before.)
    tl, tr = np.median(a[:k, :k].reshape(-1, 3), axis=0), np.median(a[:k, -k:].reshape(-1, 3), axis=0)
    bl, br = np.median(a[-k:, :k].reshape(-1, 3), axis=0), np.median(a[-k:, -k:].reshape(-1, 3), axis=0)
    ty = np.linspace(0.0, 1.0, h)[:, None, None]
    tx = np.linspace(0.0, 1.0, w)[None, :, None]
    bg = (tl * (1 - tx) + tr * tx) * (1 - ty) + (bl * (1 - tx) + br * tx) * ty
    m = np.abs(a - bg).max(axis=2) > 28
    frac = float(m.mean())
    if frac < 0.06 or frac > 0.9:  # a flat card / stamp, or no separable background: no usable subject
        return None
    m = np.asarray(Image.fromarray((m * 255).astype("uint8"), "L").filter(ImageFilter.MedianFilter(5))) > 0
    e = max(1, k // 2)  # a dark scan edge or vignette along the frame is not the subject
    m[:e], m[-e:], m[:, :e], m[:, -e:] = False, False, False, False
    m = _largest_part(m)  # first: a name line or a floor speck would otherwise join the figure
    # Solid outline, no holes: close small gaps, then fill whatever the outside can't reach. (Was a fill between each
    # row's outermost pixels, which turned a floor shadow beside the feet into a slab.)
    r = max(3, (min(h, w) // 60) | 1)
    im = Image.fromarray((m * 255).astype("uint8"), "L").filter(ImageFilter.MaxFilter(r)).filter(ImageFilter.MinFilter(r))
    outside = Image.new("L", (w + 2, h + 2), 0)
    outside.paste(im, (1, 1))
    ImageDraw.floodfill(outside, (0, 0), 128)
    solid = np.asarray(outside)[1:-1, 1:-1] != 128
    return Image.fromarray((solid * 255).astype("uint8"), "L").filter(ImageFilter.MedianFilter(7))


def _generic_silhouette(size: tuple[int, int], close: bool) -> Image.Image:
    """A plain head-and-shoulders (close-up) or full-figure mask, for when the reference has no clear subject."""
    w, h = size
    m = Image.new("L", size, 0)
    d = ImageDraw.Draw(m)
    if close:
        d.ellipse((w * 0.32, h * 0.12, w * 0.68, h * 0.58), fill=255)               # head
        d.rounded_rectangle((w * 0.12, h * 0.62, w * 0.88, h * 1.1), radius=int(w * 0.2), fill=255)  # shoulders
        d.rectangle((w * 0.43, h * 0.5, w * 0.57, h * 0.66), fill=255)              # neck
    else:
        d.ellipse((w * 0.41, h * 0.04, w * 0.59, h * 0.17), fill=255)
        d.rounded_rectangle((w * 0.33, h * 0.18, w * 0.67, h * 0.55), radius=int(w * 0.08), fill=255)
        d.rounded_rectangle((w * 0.36, h * 0.53, w * 0.49, h * 0.97), radius=int(w * 0.05), fill=255)
        d.rounded_rectangle((w * 0.51, h * 0.53, w * 0.64, h * 0.97), radius=int(w * 0.05), fill=255)
        d.rounded_rectangle((w * 0.25, h * 0.2, w * 0.33, h * 0.5), radius=int(w * 0.04), fill=255)
        d.rounded_rectangle((w * 0.67, h * 0.2, w * 0.75, h * 0.5), radius=int(w * 0.04), fill=255)
    return m


def _largest_part(m):
    """Keep the figure: blobs at least a tenth the size of the biggest one (a head separate from the body stays; the
    letters of a name line under the figure, and specks, go)."""
    import numpy as np

    h, w = m.shape
    step = max(1, max(h, w) // 240)
    small = m[::step, ::step]
    sh, sw = small.shape
    lab = np.zeros(small.shape, dtype=np.int32)
    sizes, cur = {}, 0
    for y0, x0 in zip(*np.nonzero(small)):
        if lab[y0, x0]:
            continue
        cur += 1
        lab[y0, x0] = cur
        stack, n = [(y0, x0)], 0
        while stack:
            y, x = stack.pop()
            n += 1
            for yy, xx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= yy < sh and 0 <= xx < sw and small[yy, xx] and not lab[yy, xx]:
                    lab[yy, xx] = cur
                    stack.append((yy, xx))
        sizes[cur] = n
    if not sizes:
        return m
    big = max(sizes.values())
    keep_ids = [i for i, n in sizes.items() if n >= big / 10]
    keep = np.repeat(np.repeat(np.isin(lab, keep_ids), step, axis=0), step, axis=1)[:h, :w]
    return m & keep


def _bg_colour(im: Image.Image) -> tuple:
    import numpy as np

    a = np.asarray(im.convert("RGB"))
    k = max(2, min(a.shape[:2]) // 20)
    corners = np.concatenate([a[:k, :k].reshape(-1, 3), a[:k, -k:].reshape(-1, 3), a[-k:, :k].reshape(-1, 3),
                              a[-k:, -k:].reshape(-1, 3)])
    return tuple(int(v) for v in np.median(corners, axis=0))


def placeholder_view(ref: str | Path, view: dict, cell: tuple[int, int], bg: str) -> Image.Image:
    """Dry-run stand-in: the reference framed like the view (close-ups crop the top, side views narrowed to suggest a
    profile, back views a dark silhouette of the subject's outline), stamped PREVIEW. No GPU, no model.

    Every view sits on the same card (the reference's own background, the same size in all six cells), so the
    panels line up: a side view narrows the figure inside the card, not the card, and a back view is a silhouette
    on that card. Only the main figure is silhouetted (a name line under it is not a bar under the feet).

    Nothing is mirrored: a reference that is itself a name card or a stamped preview carries text, and a mirrored
    copy read as backwards writing. All text on the cell is drawn last, the right way round."""
    import numpy as np

    cw, ch = cell
    im = Image.open(ref).convert("RGB")
    close = view["id"].startswith("close")
    if close:
        w, h = im.size
        im = im.crop((int(w * 0.1), 0, int(w * 0.9), int(h * 0.55)))
    card_bg = _bg_colour(im)
    im = ImageOps.contain(im, (int(cw * 0.86), int(ch * 0.82)))
    card = Image.new("RGB", im.size, card_bg)
    if view["id"].endswith("back"):
        mask = _subject_mask(im)
        if mask is not None and (np.asarray(mask) > 0).mean() < 0.04:
            mask = None
        mask = mask or _generic_silhouette(im.size, close)
        card.paste(Image.new("RGB", im.size, "#5A5A5A"), (0, 0), mask)
    elif view["id"].endswith("side"):
        narrow = im.resize((max(1, int(im.width * 0.72)), im.height), Image.Resampling.LANCZOS)
        card.paste(narrow, ((im.width - narrow.width) // 2, 0))
    else:
        card = im
    cell_im = Image.new("RGB", cell, bg)
    top = int(ch * 0.11)
    cell_im.paste(card, ((cw - card.width) // 2, top + (int(ch * 0.82) - card.height) // 2))
    d = ImageDraw.Draw(cell_im)
    d.text((cw // 2, top // 2), "PREVIEW", fill="#8A8A8A", font=_font(ch // 26), anchor="mm")
    return cell_im


# ------------------------------------------------------------------ Soul Pack
def add_views_to_pack(pack_dir: str | Path, views: list[ViewResult], sheet: str | Path, anchor: str | Path | None = None,
                      name: str = "My character", prompt_lock: str = "") -> Path:
    """Make the six views the character's reference set. The original photo stays first (anchor).
    Creates the pack if it does not exist. Returns pack.json."""
    from opensoul.character_pack import CharacterPack

    root = Path(pack_dir)
    if not (root / "pack.json").is_file():
        if anchor is None:
            raise FileNotFoundError("no pack.json and no anchor image to start one")
        CharacterPack(name=name, prompt_lock=prompt_lock, ref_images=[str(anchor)]).save(root)
    data = json.loads((root / "pack.json").read_text(encoding="utf-8"))
    refs_dir = root / "refs"
    refs_dir.mkdir(exist_ok=True)
    keep = [r for r in data.get("ref_images", []) if not Path(r).name.startswith("sheet_")]
    if not keep and anchor is not None and Path(anchor).is_file():
        # An existing pack with no picture yet (a character made from a description): the sheet's reference
        # becomes its anchor, so the pack is extended, not left without its first picture.
        a = refs_dir / f"reference{Path(anchor).suffix.lower() or '.png'}"
        shutil.copy2(anchor, a)
        keep = [str(Path("refs") / a.name)]
    added = []
    for v in views:
        if v.path and Path(v.path).is_file():
            dest = refs_dir / f"sheet_{v.id}{Path(v.path).suffix.lower() or '.png'}"
            shutil.copy2(v.path, dest)
            added.append({"id": v.id, "label": v.label, "path": str(Path("refs") / dest.name),
                          "score": v.score, "passed": v.passed, "attempts": v.attempts})
    sheet_dest = root / ("character_sheet" + Path(sheet).suffix.lower())
    if Path(sheet).resolve() != sheet_dest.resolve():
        shutil.copy2(sheet, sheet_dest)
    data["ref_images"] = keep[:1] + [a["path"] for a in added] + keep[1:]
    meta = data.setdefault("meta", {})
    meta["soul_pack"] = {"sheet": sheet_dest.name, "views": added, "anchor": keep[0] if keep else None,
                         "source": "character_sheet", "workflow": WORKFLOW.name}
    (root / "pack.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    return root / "pack.json"


# ------------------------------------------------------------------ main entry
def is_full_body_reference(ref: str | Path, checklist: dict | None, crop: dict) -> bool:
    """A reference that shows the whole figure: the checklist saw footwear, or (no checklist) it is tall."""
    if checklist:
        foot = checklist.get("footwear")
        return bool(foot and isinstance(foot, dict) and foot.get("item"))
    w, h = Image.open(ref).size
    return h / max(w, 1) >= float(crop.get("min_aspect", 1.4))


def _dry() -> bool:
    return os.environ.get("OPENSOUL_DRY_RUN", "").strip().lower() in {"1", "true", "yes"}


class _Ctx:
    """Everything one sheet needs to render, check and fix a view (shared by make + regenerate)."""

    def __init__(self, ref, out, preset, subject, seed, gate_mode, runner, vlm, checklist, use_arcface, note):
        self.ref, self.out, self.preset, self.subject, self.seed = Path(ref), Path(out), preset, subject, seed
        self.gate_mode, self.runner, self.vlm, self.checklist = gate_mode, runner, vlm, checklist or {}
        self.use_arcface, self.note = use_arcface, note
        self.by_id = {v["id"]: v for v in preset["views"]}
        self.results: dict[str, ViewResult] = {}  # the sheet's views, so a back view can use the side view
        self.strategy: str | None = None  # force a back-view fallback strategy ("side" | "wording"), e.g. from the CLI
        self._tmp = Path(tempfile.mkdtemp(prefix="opensoul_sheet_")) if gate_mode == "local" else None
        self.wf = self._workflow(WORKFLOW)

    def _workflow(self, path: Path) -> Path:
        if self._tmp is None:
            return path
        tmp = self._tmp / path.name
        if not tmp.is_file():
            tmp.write_text(json.dumps(graph_without_gate(json.loads(path.read_text())), indent=2))
        return tmp

    def render_ref(self, view: dict) -> Path:
        """Image the edit model sees for this view. Close-ups from a full-body reference start from a head-and-
        shoulders crop of it (preset ``close_ref_crop``), so the model sees the face large. On the Lumi sheet
        (Oct 17 2026) this alone did NOT tighten the waist-up framing (0 of 6 tries); ``chest_crop`` is what fixed
        it. The identity checks still compare against the full reference."""
        crop = self.preset.get("close_ref_crop")
        if view.get("framing") != "close" or not crop or not is_full_body_reference(self.ref, self.checklist, crop):
            return self.ref
        dest = self.out / "views" / f"_reference_close_crop{self.ref.suffix or '.png'}"
        if not dest.is_file():
            im = Image.open(self.ref)
            w, h = im.size
            box = tuple(int(round(f * d)) for f, d in zip(crop["box"], (w, h, w, h)))
            dest.parent.mkdir(parents=True, exist_ok=True)
            im.crop(box).save(dest)
        return dest

    def cleanup(self):
        if self._tmp is not None:
            shutil.rmtree(self._tmp, ignore_errors=True)

    def fallback(self, vr: ViewResult) -> tuple[str, Path | None] | None:
        """Back-view fallback: after ``after_failed_tries`` failed tries, rotate from the passed side view
        (strategy "side") or use the visor wording only ("wording"). Returns (strategy, side view path)."""
        fb = self.preset.get("back_fallback")
        if not fb or not vr.id.endswith("back"):
            return None
        failed = [t for t in vr.tries if isinstance(t.get("attempt"), int) and t.get("path") and not t.get("passed")]
        side = self.results.get(fb.get("source_view", {}).get(vr.id, ""))
        side_ok = side is not None and side.passed and side.path and Path(side.path).is_file()
        if self.strategy:
            strat = self.strategy
        elif len(failed) < int(fb.get("after_failed_tries", 2)):
            return None
        else:
            seq = fb.get("strategies") or ["side"]
            if isinstance(seq, dict):  # per framing: what worked on the cap-wearing test sheet differs for full vs close
                seq = seq.get(self.by_id[vr.id].get("framing", "full")) or ["side"]
            done = sum(1 for t in vr.tries if t.get("strategy"))
            strat = seq[min(done, len(seq) - 1)]
        if strat == "side" and not side_ok:
            strat = "wording"  # no trustworthy side view to rotate from
        return strat, (Path(side.path) if strat == "side" else None)

    def fallback_fixes(self, vr: ViewResult) -> str:
        """Fixes for the non-headwear checks this view failed on any try (e.g. a second earbud). The headwear
        and sunglasses fixes are left out: the fallback prompt describes those itself, without 'backwards'."""
        from opensoul.sheet_check import checks_for_view

        if not self.checklist:
            return ""
        failed = {f for t in vr.tries for f in (t.get("failed") or [])} - {"cap_orientation", "cap_strap", "sunglasses_on_head"}
        return " ".join(c.fix for c in checks_for_view(self.by_id[vr.id], self.checklist) if c.id in failed)

    def render(self, vr: ViewResult, attempt: int) -> Path | None:
        v = self.by_id[vr.id]
        seed = view_seed(v, self.preset, self.seed, attempt)
        vr.status = "rendering" if attempt == 0 else "retrying"
        fb = self.fallback(vr) if (attempt or self.strategy) else None
        wf, extra, info = self.wf, {}, {}
        if fb:
            strat, side = fb
            extra = {"prompt": back_fallback_prompt(v, self.preset, self.subject, self.checklist, strat,
                                                    also=self.fallback_fixes(vr))}
            if side is not None:
                wf = self._workflow(ROOT / self.preset["back_fallback"]["workflow"])
                extra["source"] = side
            info = {"strategy": strat, "source": str(side) if side else None}
            self.note(f"Fixing {vr.label} ({'rotating from the side view' if side else 'new wording'})")
        else:
            self.note(f"{'Rendering' if attempt == 0 else 'Fixing'} {vr.label}")
        corr = "" if fb else (vr.corrections if attempt else "")
        vdir = self.out / "views" / f"{vr.id}_try{attempt}"
        try:
            paths = self.runner(wf, inputs=view_inputs(self.render_ref(v), v, self.preset, subject=self.subject, seed=seed,
                                                       gate_in_graph=self.gate_mode == "graph", corrections=corr,
                                                       **extra),
                                output_node_id=NODE_OUT, out_dir=vdir)  # no job metadata: comfy-api-proxy rejects label maps
        except Exception as e:  # keep the other views going
            vr.error = str(e)[:400]
            log.warning("view %s attempt %d failed: %s", vr.id, attempt, e)
            vr.tries.append({"attempt": attempt, "seed": seed, "error": vr.error} | info)
            return None
        if not paths:
            vr.error = "no image returned"
            return None
        vr.tries.append({"attempt": attempt, "seed": seed, "path": str(paths[0]), "corrections": corr} | info)
        return Path(paths[0])

    def evaluate(self, items: list[tuple[ViewResult, Path]]) -> None:
        """Gate + ArcFace + VLM checks for a batch of new tries; keep each view's best try."""
        from opensoul import sheet_check as sc

        g = self.preset["gate"]
        faces = sc.arcface_scores(self.ref, [p for _, p in items]) if (self.use_arcface and items) else None
        for k, (vr, p) in enumerate(items):
            v = self.by_id[vr.id]
            vr.status = "checking"
            self.note(f"Checking {vr.label}")
            rep = _read_report(p.parent) or gate_score(self.ref, p, g["threshold"], g["backend"])
            face = faces[k] if faces else None
            if v["id"].endswith("back"):
                face = None  # no face expected from behind
            ev = sc.evaluate(v, p, self.checklist, self.vlm, patch=float(rep["best_score"]), patch_ok=bool(rep["passed"]),
                             arcface=face)
            vr.tries[-1].update(patch=ev.patch, arcface=ev.arcface, failed=ev.failed, passed=ev.passed)
            vr.scores.append(float(rep["best_score"]))
            best = getattr(vr, "_best", None)
            if sc.better(best, ev):
                vr._best = ev  # type: ignore[attr-defined]
                vr.path, vr.score, vr.passed, vr.arcface = str(p), ev.patch, ev.passed, ev.arcface
                vr.checks, vr.note = ev.checks, ev.note
            vr.corrections = ev.corrections or vr.corrections
            vr.status = "done"
            n_ok = sum(1 for c in ev.checks if c["passed"])
            self.note(f"{vr.label}: {'looks right' if ev.passed else 'needs a fix'} "
                      f"({n_ok}/{len(ev.checks)} checks{'' if ev.arcface is None else f', face {ev.arcface:.2f}'})")
        if self.vlm is not None:
            self.vlm.release()  # give the memory back to ComfyUI between rounds

    def run_rounds(self, views: list[ViewResult], max_parallel: int, first_attempt: int = 0,
                   rounds: int | None = None) -> None:
        retries = int(self.preset["gate"].get("retries", 2)) if rounds is None else rounds - 1
        todo = list(views)
        for attempt in range(first_attempt, first_attempt + retries + 1):
            if not todo:
                break
            with ThreadPoolExecutor(max_workers=max_parallel) as ex:
                got = list(ex.map(lambda vr: (vr, self.render(vr, attempt)), todo))
            self.evaluate([(vr, p) for vr, p in got if p is not None])
            for vr, p in got:
                if p is None and vr.path is None:
                    vr.status = "failed"
            todo = [vr for vr in todo if not vr.passed]
        self.chest_crop([vr for vr in todo if not vr.passed])

    def chest_crop(self, views: list[ViewResult]) -> None:
        """Last auto-fix step for close-ups whose ONLY problem is a loose crop (waist in frame): Qwen keeps the
        framing across seeds and corrective prompts (Lumi sheet: 7 tries, all waist-up), so cut the best try to
        chest-up (preset ``close_post_crop``), scale it back to the view size and check it again."""
        crop = self.preset.get("close_post_crop")
        if not crop:
            return
        items = []
        for vr in views:
            best = getattr(vr, "_best", None)
            if self.by_id[vr.id].get("framing") != "close" or not vr.path or best is None:
                continue
            failed = set(best.failed)
            if not failed or not failed <= set(crop.get("only_when_failed", ["framing_waist"])) or not best.identity_ok:
                continue
            src = Path(vr.path)
            dest = src.parent / f"{src.stem}_chestcrop.png"
            im = Image.open(src).convert("RGB")
            w, h = im.size
            box = tuple(int(round(f * d)) for f, d in zip(crop["box"], (w, h, w, h)))
            im.crop(box).resize((w, h), Image.LANCZOS).save(dest)
            vr.tries.append({"attempt": "chest_crop", "source": str(src), "path": str(dest), "strategy": "chest_crop"})
            items.append((vr, dest))
            self.note(f"Fixing {vr.label} (cropping to chest-up)")
        if items:
            self.evaluate(items)


def _finalize_views(views: list[ViewResult], out: Path) -> None:
    for vr in views:
        if vr.path:
            final = out / "views" / f"{vr.id}{Path(vr.path).suffix}"
            if Path(vr.path).resolve() != final.resolve():
                shutil.copy2(vr.path, final)
            vr.path = str(final)
            vr.status = "done"


from opensoul.ear_trim import wants_subtle_ears  # noqa: E402,F401  (re-exported for callers)


def trim_sheet_views(views: list[ViewResult], out: Path) -> None:
    """Shorten long sideways ear tips in every view (opensoul.ear_trim, local, no model). Keeps the untrimmed view
    next to it and a magenta debug image, and says so in the view note: check the result by eye."""
    from opensoul.ear_trim import trim_view

    for vr in views:
        if not vr.path:
            continue
        src = Path(vr.path)
        keep = src.with_name(f"{src.stem}_untrimmed{src.suffix}")
        shutil.copy2(src, keep)
        try:
            r = trim_view(keep, vr.id, out=src, debug=src.with_name(f"{src.stem}_eartrim.jpg"))
        except Exception as e:  # noqa: BLE001 - a failed trim keeps the rendered view
            log.warning("ear trim failed for %s: %s", vr.id, e)
            continue
        vr.tries.append({"attempt": "ear_trim", "path": str(src), "untrimmed": str(keep), "ears": r.ears,
                         "removed_px": r.removed_px})
        if r.changed:
            vr.note = (vr.note + " " if vr.note else "") + "Ear tips shortened automatically; check by eye."


def make_vlm(kind: str | None = None):
    """Auto-fix VLM from OPENSOUL_SHEET_VLM: 'qwen-vl' (default on a GPU box), 'none' to skip the checks."""
    kind = (kind or os.environ.get("OPENSOUL_SHEET_VLM") or "qwen-vl").strip().lower()
    if kind in {"none", "off", "0"}:
        return None
    import importlib.util

    from opensoul.sheet_check import QwenVLLocal

    vlm = QwenVLLocal()
    if not Path(vlm.model_dir).is_dir() or importlib.util.find_spec("torch") is None:
        log.warning("auto-fix checks off: no local VLM at %s (set OPENSOUL_VLM_DIR) or no torch", vlm.model_dir)
        return None
    return vlm


def make_character_sheet(
    reference: str | Path,
    out_dir: str | Path,
    *,
    consent: bool,
    subject: str = "",
    seed: int | None = None,
    dry_run: bool | None = None,
    gate_mode: str | None = None,
    pack_dir: str | Path | None = None,
    name: str = "My character",
    runner: Callable | None = None,
    progress: Callable[[list[ViewResult], str], None] | None = None,
    max_parallel: int = 6,
    preset: dict | None = None,
    reuse: dict[str, str | Path] | None = None,
    vlm=None,
    autofix: bool = True,
    checklist: dict | None = None,
    use_arcface: bool | None = None,
    checklist_overrides: dict | None = None,
    ear_trim: bool | None = None,
) -> SheetResult:
    """Render the six views, check + auto-fix each, composite the 3x2 grid, update the Soul Pack.

    ``runner`` defaults to ``opensoul.comfy_client.run_workflow_file`` (tests inject a fake). ``vlm`` is the
    auto-fix checker (default: local Qwen3-VL, loaded on demand); ``autofix=False`` falls back to the plain
    identity gate with one retry. Views are submitted together so they run back to back on the GPU."""
    if not consent:
        raise ConsentRequired("Confirm you own this image or have permission to use it.")
    ref = Path(reference)
    if not ref.is_file():
        raise FileNotFoundError(f"reference image not found: {ref}")
    preset = json.loads(json.dumps(preset or load_preset()))
    dry = _dry() if dry_run is None else dry_run
    gate_mode = (gate_mode or os.environ.get("OPENSOUL_SHEET_GATE") or "graph").strip().lower()
    if gate_mode not in {"graph", "local"}:
        raise ValueError("gate_mode must be 'graph' or 'local'")
    out = Path(out_dir)
    (out / "views").mkdir(parents=True, exist_ok=True)
    g = preset["gate"]
    views = [ViewResult(id=v["id"], label=v["label"]) for v in preset["views"]]
    by_id = {v["id"]: v for v in preset["views"]}

    def note(stage: str) -> None:
        if progress:
            progress(views, stage)

    cell = (preset["grid"]["cell_width"], preset["grid"]["cell_height"])
    if dry:
        from opensoul.sheet_check import checks_for_view

        for vr in views:
            p = out / "views" / f"{vr.id}.png"
            placeholder_view(ref, by_id[vr.id], cell, preset["grid"]["background"]).save(p)
            rep = gate_score(ref, p, g["threshold"], g["backend"])
            vr.path, vr.score, vr.passed, vr.attempts, vr.status = str(p), rep["best_score"], rep["passed"], 1, "done"
            vr.seed, vr.scores = view_seed(by_id[vr.id], preset, seed, 0), [rep["best_score"]]
            if checklist:  # show which checks would run; not judged in preview
                vr.checks = [{"id": c.id, "label": c.label, "question": c.question, "expect": c.expect,
                              "answer": None, "passed": None} for c in checks_for_view(by_id[vr.id], checklist)]
            note(f"{vr.label} ready (preview)")
    else:
        if runner is None:
            from opensoul.comfy_client import run_workflow_file as runner  # noqa: N806
        if not autofix:
            vlm, checklist = None, None
            g["retries"] = min(int(g.get("retries", 1)), 1)
        elif vlm is None:
            vlm = make_vlm()
        if vlm is not None and not checklist:
            note("Reading the reference (outfit, accessories, headwear)")
            from opensoul.sheet_check import extract_checklist

            checklist = extract_checklist(ref, vlm)
            vlm.release()  # don't hold the VLM while ComfyUI renders
        if checklist is not None and checklist_overrides:  # the user's word beats the VLM's reading
            checklist = {**checklist, **checklist_overrides}
        if use_arcface is None:
            use_arcface = autofix
        ctx = _Ctx(ref, out, preset, subject, seed, gate_mode, runner, vlm, checklist, use_arcface, note)
        ctx.results = {vr.id: vr for vr in views}
        try:
            todo, reused = [], []
            for vr in views:  # keep already-good views from an earlier run (e.g. re-render only the close-ups)
                src = (reuse or {}).get(vr.id)
                if src and Path(src).is_file():
                    vr.tries.append({"attempt": "reused", "path": str(src)})
                    reused.append((vr, Path(src)))
                else:
                    todo.append(vr)
            if reused:  # one check round for all reused views: the VLM is loaded once, not once per view
                ctx.evaluate(reused)
            t0 = time.time()
            ctx.run_rounds(todo, max_parallel)
            log.info("sheet views done in %.1fs", time.time() - t0)
        finally:
            ctx.cleanup()
        for vr in views:
            vr.attempts = sum(1 for t in vr.tries if isinstance(t.get("attempt"), int))
            vr.seed = next((t.get("seed") for t in vr.tries if t.get("path") == vr.path), vr.seed)
        _finalize_views(views, out)
        if ear_trim is None:
            ear_trim = str((checklist_overrides or {}).get("ear_style") or "").lower() == "subtle"
        if ear_trim:
            note("Shortening the ear tips")
            trim_sheet_views(views, out)

    missing = [vr.label for vr in views if not vr.path]
    if missing:
        errs = list(dict.fromkeys(v.error for v in views if v.error))  # OS-009: one line per distinct error
        if any("OpenSoul" in e and any(w in e.lower() for w in ("not found", "does not exist", "missing", "unknown"))
               for e in errs):
            raise RuntimeError("Your studio does not have the OpenSoul nodes. Install them on the studio (see the "
                               "README, 'Run it on your studio'). Then test the connection again.")
        raise RuntimeError(f"Couldn't render: {', '.join(missing)}. " + "; ".join(errs))
    res = _assemble(ref, out, views, preset, dry, gate_mode, subject, checklist or {}, pack_dir, name, note)
    note("Sheet ready")
    return res


def _assemble(ref, out, views, preset, dry, gate_mode, subject, checklist, pack_dir, name, note) -> SheetResult:
    note("Building the sheet")
    g = preset["gate"]
    sheet = composite_grid([vr.path for vr in views], [vr.label for vr in views], out / "character_sheet.jpg",
                           preset["grid"], title="PREVIEW · dry run" if dry else "")
    gate_info = {"backend": g["backend"], "threshold": g["threshold"], "mode": "dry-run" if dry else gate_mode,
                 "retries": g.get("retries", 2), "autofix": bool(checklist) and not dry}
    res = SheetResult(sheet=str(sheet), views=views, dry_run=dry, gate=gate_info, checklist=checklist,
                      checked=bool(dry or checklist))
    manifest = out / "sheet.json"
    payload = res.to_dict() | {"style": preset.get("style"), "negative": preset.get("negative"),  # the look (OS-010)
                               "reference": str(ref), "consent": True, "workflow": str(WORKFLOW.relative_to(ROOT)),
                               "subject": subject, "pack_dir": str(pack_dir) if pack_dir else None, "name": name,
                               "created": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    manifest.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    res.manifest = str(manifest)
    if pack_dir:
        add_views_to_pack(pack_dir, views, sheet, anchor=ref, name=name, prompt_lock=subject)
    return res


def regenerate_view(
    sheet_dir: str | Path,
    view_id: str | list[str],
    *,
    runner: Callable | None = None,
    vlm=None,
    dry_run: bool | None = None,
    gate_mode: str | None = None,
    progress: Callable[[list[ViewResult], str], None] | None = None,
    use_arcface: bool | None = None,
    strategy: str | None = None,
    tries: int | None = None,
) -> SheetResult:
    """Re-render ONE view of an existing sheet (the UI's Regenerate button), using that view's last
    corrections and fresh seeds, then rebuild the grid and the Soul Pack. A back view that already failed
    twice is rotated from the sheet's side view (preset ``back_fallback``); ``strategy`` forces "side" or
    "wording"; ``tries`` caps the number of renders (default: retries + 1). Several view ids are
    re-rendered side by side (one VLM load per round)."""
    out = Path(sheet_dir)
    man = json.loads((out / "sheet.json").read_text())
    preset = load_preset()
    for k in ("style", "negative"):  # the sheet's own look (a drawn style stays drawn on Regenerate, OS-010)
        if man.get(k):
            preset[k] = man[k]
    views = [ViewResult(**{k: v for k, v in d.items() if k in ViewResult.__dataclass_fields__}) for d in man["views"]]
    ids = [view_id] if isinstance(view_id, str) else list(view_id)
    sel = []
    for vid in ids:
        vr = next((v for v in views if v.id == vid), None)
        if vr is None:
            raise KeyError(f"no view {vid!r} in this sheet")
        sel.append(vr)
    dry = _dry() if dry_run is None else dry_run
    checklist = man.get("checklist") or {}

    def note(stage: str) -> None:
        if progress:
            progress(views, stage)

    ref = Path(man["reference"])
    if dry:
        for vr in sel:
            vr.tries.append({"attempt": len(vr.tries), "note": "preview: nothing re-rendered"})
            note(f"{vr.label} ready (preview)")
    else:
        if runner is None:
            from opensoul.comfy_client import run_workflow_file as runner  # noqa: N806
        if vlm is None and checklist:
            vlm = make_vlm()
        gm = (gate_mode or man.get("gate", {}).get("mode") or os.environ.get("OPENSOUL_SHEET_GATE") or "graph")
        gm = gm if gm in {"graph", "local"} else "graph"
        ctx = _Ctx(ref, out, preset, man.get("subject", ""), None, gm, runner, vlm, checklist,
                   bool(checklist) if use_arcface is None else use_arcface, note)
        ctx.results, ctx.strategy = {v.id: v for v in views}, strategy
        # seed the "best so far" with the current view so a worse try never replaces it
        from opensoul.sheet_check import Evaluation, failure_weight

        for vr in sel:
            failed = [c["id"] for c in vr.checks if c.get("passed") is False]
            vr._best = Evaluation(checks=vr.checks, failed=failed, arcface=vr.arcface, patch=vr.score,  # type: ignore[attr-defined]
                                  passed=vr.passed, rank=(failure_weight(vr.checks, not vr.id.startswith("close")),
                                                          1 if vr.passed or not failed else 0,
                                                          vr.arcface if vr.arcface is not None else -1.0, vr.score or 0.0))
            vr.passed = False
        n_tries = max(sum(1 for t in vr.tries if isinstance(t.get("attempt"), int)) + len(vr.tries) for vr in sel)
        start = 10 * (1 + n_tries // 10 + n_tries)
        try:
            ctx.run_rounds(sel, len(sel), first_attempt=start, rounds=tries)
        finally:
            ctx.cleanup()
        for vr in sel:
            vr.passed = bool(getattr(vr, "_best").passed)
            vr.attempts = sum(1 for t in vr.tries if isinstance(t.get("attempt"), int))
        _finalize_views(sel, out)
    return _assemble(ref, out, views, preset, dry, man.get("gate", {}).get("mode", "graph"), man.get("subject", ""),
                     checklist, man.get("pack_dir"), man.get("name", "My character"), note)


def _read_report(vdir: Path) -> dict | None:
    p = vdir / f"node{NODE_GATE}_report.txt"
    if not p.is_file():
        return None
    try:
        rep = json.loads(p.read_text())
        return rep if "best_score" in rep else None
    except ValueError:
        return None
