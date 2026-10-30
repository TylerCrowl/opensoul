"""Auto-fix for the Character Sheet: local VLM consistency checks + corrective re-renders.

1. **Checklist (once per reference).** An open-weights VLM (default Qwen3-VL-8B-Instruct, Apache-2.0, run locally
   with transformers) reads the reference and fills a fixed attribute schema: headwear + orientation, glasses,
   sunglasses on the head, earbuds/earrings per ear, facial hair, clothing items and colours.
2. **View-aware yes/no questions.** For each rendered view we derive questions from the checklist with the answer
   we expect *for that view* (a backwards cap: strap toward the camera in front views, brim toward the camera in
   back views, brim toward the back of the head in side views; one earbud means "earbuds in both ears?" -> no;
   side views must face the left edge of the image; close-ups must not show legs or shoes; ...).
3. **Identity.** ArcFace (InsightFace buffalo_l, *non-commercial weights*, optional) where a face is visible,
   otherwise the Apache-2.0 patch gate. The patch gate alone overrates (see docs/evidence/CHARACTER_SHEET.md).
4. **Fix.** A failed check turns into a corrective prompt addition ("Only ONE earbud, in the person's left ear"),
   the view is re-rendered with a new seed (up to 2 retries) and the best try is kept. Views still failing are
   flagged with a plain-language note and can be regenerated from the UI.

No closed APIs. The VLM is loaded on demand and released after each evaluation round so it never sits next to
ComfyUI's models longer than needed; loading waits until MemAvailable leaves at least ``OPENSOUL_MIN_FREE_GB``
(default 12) after the model (~17.5 GB bf16 for Qwen3-VL-8B).
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol, Sequence

log = logging.getLogger("opensoul.sheet_check")
ROOT = Path(__file__).resolve().parents[1]

EXTRACT_PROMPT = """Look at the person in this photo and fill this JSON exactly (use null when not applicable).
Left/right always mean the PERSON'S OWN left/right, not the image side.
{"gender_word": "man|woman|person",
 "headwear": "none|baseball cap|beanie|hat|other",
 "headwear_color": "colour or null",
 "headwear_orientation": "forward|backward|null (for caps: backward means the brim/visor points behind the head)",
 "glasses": "none|eyeglasses|sunglasses",
 "glasses_color": "frame colour or null",
 "sunglasses_on_headwear_or_head": true|false,
 "earbud_left": true|false, "earbud_right": true|false,
 "earring_left": true|false, "earring_right": true|false,
 "facial_hair": "none|stubble|mustache|beard",
 "hair": "short description",
 "hair_color": "main hair colour, e.g. silver-lavender",
 "pointed_ears": true|false (long pointed elf-like ears visible),
 "top_layers": [{"item": "e.g. quilted vest", "color": "navy"}, {"item": "e.g. henley shirt", "color": "grey"}]
   (every visible upper-body layer, OUTERMOST first; include aprons, vests, jackets and overalls worn over the top),
 "bottom": {"item": "e.g. cargo pants", "color": "charcoal"} or null if not visible,
 "footwear": {"item": "e.g. work boots", "color": "brown"} or null if not visible}
Answer with the JSON only."""


# ------------------------------------------------------------------ VLM backends
class VLM(Protocol):
    def describe_json(self, image: str | Path, prompt: str) -> dict: ...
    def ask(self, image: str | Path, questions: Sequence[str]) -> list[bool | None]: ...
    def release(self) -> None: ...


def _parse_json(text: str):
    m = re.search(r"(\{.*\}|\[.*\])", text, re.S)
    if not m:
        raise ValueError(f"VLM returned no JSON: {text[:200]!r}")
    return json.loads(m.group(1))


def _yes_no(v) -> bool | None:
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s.startswith("y") or s == "true":
        return True
    if s.startswith("n") or s == "false":
        return False
    return None


def mem_available_gb() -> float | None:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable"):
                return int(line.split()[1]) / 1048576
    except OSError:
        return None
    return None


class QwenVLLocal:
    """Qwen3-VL / Qwen2.5-VL Instruct through transformers, on this machine. Loaded on first use."""

    MODEL_GB = 17.5

    def __init__(self, model_dir: str | Path | None = None, min_free_gb: float | None = None, wait_s: int = 900):
        self.model_dir = str(model_dir or os.environ.get("OPENSOUL_VLM_DIR")
                             or Path(os.environ.get("OPENSOUL_HOME", Path.home() / "OpenSoul")) / "models/Qwen3-VL-8B-Instruct")
        self.min_free_gb = float(min_free_gb if min_free_gb is not None else os.environ.get("OPENSOUL_MIN_FREE_GB", 12))
        self.wait_s = wait_s
        self._model = self._proc = None

    def _load(self):
        if self._model is not None:
            return
        t0 = time.time()
        while True:  # memory guard: never push a shared unified-memory box below min_free_gb
            free = mem_available_gb()
            if free is None or free - self.MODEL_GB >= self.min_free_gb:
                break
            if time.time() - t0 > self.wait_s:
                raise RuntimeError(f"not enough free memory for the VLM ({free:.0f} GB free, need "
                                   f"{self.MODEL_GB + self.min_free_gb:.0f} GB)")
            log.info("VLM waits for memory: %.1f GB free", free)
            time.sleep(10)
        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor

        self._proc = AutoProcessor.from_pretrained(self.model_dir)
        self._model = AutoModelForImageTextToText.from_pretrained(self.model_dir, dtype=torch.bfloat16)  # no accelerate needed
        self._model.to("cuda" if torch.cuda.is_available() else "cpu")
        self._model.eval()
        log.info("VLM loaded from %s in %.1fs", self.model_dir, time.time() - t0)

    def _generate(self, image, prompt: str, max_new_tokens: int = 512) -> str:
        import torch
        from PIL import Image

        self._load()
        im = Image.open(image).convert("RGB")
        im.thumbnail((1024, 1024))
        msgs = [{"role": "user", "content": [{"type": "image", "image": im}, {"type": "text", "text": prompt}]}]
        inputs = self._proc.apply_chat_template(msgs, tokenize=True, add_generation_prompt=True, return_dict=True,
                                                return_tensors="pt").to(self._model.device)
        with torch.no_grad():
            out = self._model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
        return self._proc.batch_decode(out[:, inputs["input_ids"].shape[1]:], skip_special_tokens=True)[0]

    def describe_json(self, image, prompt: str) -> dict:
        return _parse_json(self._generate(image, prompt))

    def ask(self, image, questions: Sequence[str]) -> list[bool | None]:
        if not questions:
            return []
        q = "\n".join(f"{i + 1}. {x}" for i, x in enumerate(questions))
        text = self._generate(image, "Answer each question about this image with yes or no, judging only what is "
                                     "visible. Left/right mean the PERSON'S OWN left/right.\n" + q +
                              f"\nReturn only a JSON list of {len(questions)} strings, each \"yes\" or \"no\".", 160)
        ans = _parse_json(text)
        ans = list(ans) + [None] * (len(questions) - len(ans))
        return [_yes_no(a) for a in ans[: len(questions)]]

    def release(self, force: bool = False) -> None:
        """Free the VLM (default, OPENSOUL_VLM_KEEP=never). OPENSOUL_VLM_KEEP=auto keeps it resident when
        MemAvailable >= min_free_gb + 50 GB, and =always keeps it. Loading Qwen3-VL-8B takes ~2 min on the
        Spark, so keeping it saves time, but on a shared box a video job can start later and take that room
        (on Oct 17 an LTX render dropped MemAvailable to ~27 GB with the VLM kept), so the default frees it."""
        if self._model is None:
            return
        keep = os.environ.get("OPENSOUL_VLM_KEEP", "never").lower()
        free = mem_available_gb()
        if not force and (keep == "always" or (keep == "auto" and free is not None and free >= self.min_free_gb + 50)):
            log.info("VLM kept loaded (%.0f GB free)", free or -1)
            return
        import gc

        import torch

        self._model = self._proc = None
        gc.collect()
        torch.cuda.empty_cache()
        log.info("VLM released")


# ------------------------------------------------------------------ identity (ArcFace, optional)
def arcface_scores(anchor: str | Path, images: Sequence[str | Path]) -> list[float | None] | None:
    """ArcFace cosine per image via the node pack's runner in the env named by OPENSOUL_IDSIM_PY.
    Returns None when that env is not set up (then the patch gate decides)."""
    py = os.environ.get("OPENSOUL_IDSIM_PY") or str(Path(os.environ.get("OPENSOUL_HOME", Path.home() / "OpenSoul"))
                                                    / "latentsync-env/bin/python")
    runner = ROOT / "custom_nodes/opensoul_nodes/runners/idsim_json.py"
    if not Path(py).is_file() or not images:
        return None
    try:
        p = subprocess.run([py, str(runner), str(anchor), *map(str, images)], capture_output=True, text=True, timeout=600)
        return json.loads(p.stdout.strip().splitlines()[-1])["scores"] if p.returncode == 0 else None
    except Exception as e:  # pragma: no cover - env specific
        log.warning("ArcFace unavailable: %s", e)
        return None


# ------------------------------------------------------------------ checks
@dataclass
class Check:
    id: str
    question: str
    expect: bool
    fix: str
    label: str
    answer: bool | None = None

    @property
    def passed(self) -> bool | None:
        return None if self.answer is None else self.answer == self.expect


# Failures that matter more (or less) when ranking tries: a cap turned the wrong way is obvious on a sheet;
# sunglasses on a cap are a few pixels in a full-body back view and Qwen3-VL often misses them there.
CHECK_WEIGHTS = {"cap_orientation": 2.0, "cap_strap": 2.0, "pointed_ears": 2.0, "ears_too_long": 2.0, "ears_stick_out": 2.0}
# ear_style "subtle" (set by the user, e.g. sheet_run.py --ears subtle; the VLM never sets it): short elf ears.
# Wording matters: "elf ears ... not long spikes" still made Qwen draw long sideways spikes (Lumi v3, v3.1 try 0).
# Describing the hair covering the ears, with only a small tip peeking out, is what worked by eye (ear_edit2 seed 44).
SUBTLE_EARS_FIX = ("Her long hair falls over her ears and covers most of them; only a small, short pointed ear tip peeks "
                   "out through the hair, lying close against her head, the same skin tone as her face. Keep the face the same.")
SUBTLE_EARS_PROMPT = ("her hair falls over her ears and covers most of them, only a small short pointed ear tip peeks out "
                      "through the hair, lying close to her head")
SMALL_IN_FULL_BODY = {"sunglasses_on_head": 0.5, "earrings_both": 0.5}


def failure_weight(checks, full_body: bool) -> float:
    w = 0.0
    for c in checks:
        cid, passed = (c["id"], c["passed"]) if isinstance(c, dict) else (c.id, c.passed)
        if passed is False:
            w += SMALL_IN_FULL_BODY.get(cid, 1.0) if full_body and cid in SMALL_IN_FULL_BODY else CHECK_WEIGHTS.get(cid, 1.0)
    return w


def _side(left: bool, right: bool) -> str:
    return "left" if left and not right else "right" if right and not left else ""


def checks_for_view(view: dict, cl: dict) -> list[Check]:
    """View-aware yes/no questions with the expected answer for this view."""
    vid = view["id"]
    close = view.get("framing") == "close" or vid.startswith("close")
    facing = "back" if vid.endswith("back") else "side" if vid.endswith("side") else "front"
    who = cl.get("gender_word") or "person"
    out: list[Check] = []
    hw = (cl.get("headwear") or "none").lower()
    if hw != "none":
        col = f"{cl.get('headwear_color')} " if cl.get("headwear_color") else ""
        out.append(Check("headwear", f"Is the {who} wearing a {col}{hw}?", True,
                         f"The {who} wears the same {col}{hw} as in the reference.", "Headwear"))
        if "cap" in hw and cl.get("headwear_orientation") in ("backward", "forward"):
            back = cl["headwear_orientation"] == "backward"
            if facing == "front":
                out.append(Check("cap_orientation", "Does the cap's brim (visor) point toward the camera?", not back,
                                 "The cap is worn BACKWARDS: in a front view the brim points away from the camera "
                                 "and the rear strap/closure faces the camera." if back else
                                 "The cap is worn forwards with the brim toward the camera.", "Cap orientation"))
            elif facing == "back" and back:
                # Seen from behind, "does the brim point at the camera?" was unreliable on the cap-wearing test sheet (Qwen3-VL
                # said no to correct visors and yes to a strap drawn above a visor); "is the strap visible?" matched
                # a by-eye review on all 16 back-view tries, so a backward cap is checked by its strap.
                out.append(Check("cap_strap", "Is the cap's adjustable strap or the strap opening visible?", False,
                                 "Seen from behind, the visor covers the back of the neck and points at the "
                                 "camera; no strap or strap opening is visible.", "Cap orientation"))
            elif facing == "back":
                out.append(Check("cap_orientation", "Does the cap's brim (visor) point toward the camera?", False,
                                 "Seen from behind, only the back of the cap with its strap is visible; the brim "
                                 "points away from the camera.", "Cap orientation"))
            else:
                out.append(Check("cap_orientation", "Does the cap's brim point toward the back of the person's head?",
                                 back, "The cap is worn BACKWARDS: in profile the brim sticks out behind the head."
                                 if back else "In profile the brim points forward over the face.", "Cap orientation"))
    if cl.get("sunglasses_on_headwear_or_head"):
        out.append(Check("sunglasses_on_head", "Are there sunglasses resting on top of the head or cap?", True,
                         "Keep the sunglasses resting on the cap/head exactly as in the reference.", "Sunglasses on cap"))
    if facing != "back":
        g = (cl.get("glasses") or "none").lower()
        if g == "eyeglasses":
            out.append(Check("glasses", f"Is the {who} wearing clear eyeglasses over the eyes?", True,
                             f"The {who} wears the same {cl.get('glasses_color') or ''} eyeglasses as in the reference.",
                             "Glasses"))
        elif g == "none":
            out.append(Check("glasses", f"Is the {who} wearing glasses over the eyes?", False,
                             "No glasses over the eyes.", "Glasses"))
        fh = (cl.get("facial_hair") or "").lower()
        if fh and fh != "none":
            out.append(Check("facial_hair", f"Does the {who} have {fh}?", True, f"Keep the same {fh}.", "Facial hair"))
    subtle = str(cl.get("ear_style") or "").lower() == "subtle"
    if cl.get("pointed_ears") is True and facing != "back":  # fantasy ears drift back to human ears easily
        if subtle:
            out.append(Check("pointed_ears", f"Does the {who} have pointed elf ears (ears with a pointed tip)?", True,
                             SUBTLE_EARS_FIX, "Pointed ears"))
        else:
            out.append(Check("pointed_ears", f"Does the {who} have long pointed elf-like ears?", True,
                             "Keep the long pointed elf ears from the reference, clearly visible through the hair.",
                             "Pointed ears"))
    if cl.get("pointed_ears") is True and subtle:  # every view, back included: spikes poke out past the hair
        out.append(Check("ears_too_long", f"Do the {who}'s ears stick far out sideways as long horizontal spikes, "
                         "much longer than a human ear?", False, SUBTLE_EARS_FIX, "Ear size"))
        # Qwen3-VL passes medium spikes on the question above (Lumi v3 try 0, by eye): ask about the angle too.
        out.append(Check("ears_stick_out", f"Do the {who}'s pointed ears stick out sideways away from the head, "
                         "instead of lying close against the side of the head?", False, SUBTLE_EARS_FIX, "Ear angle"))
    hc = str(cl.get("hair_color") or "").strip()
    if hc and hc.lower() not in {"null", "none"}:
        out.append(Check("hair_color", f"Is the {who}'s hair {hc}?", True, f"The hair is {hc}, the same as in the reference.",
                         "Hair colour"))
    for kind in ("earbud", "earring"):
        l, r = bool(cl.get(f"{kind}_left")), bool(cl.get(f"{kind}_right"))
        if facing != "side":  # a profile only shows one ear
            if l != r:
                out.append(Check(f"{kind}s_both", f"Are there {kind}s in BOTH ears?", False,
                                 f"Only ONE {kind}, in the person's {_side(l, r)} ear; the other ear has no {kind}.",
                                 f"{kind.capitalize()}s"))
            elif not l and kind == "earbud":
                out.append(Check("earbuds_any", "Is the person wearing earbuds?", False, "No earbuds.", "Earbuds"))
    layers = [x for x in (cl.get("top_layers") or []) if x and x.get("item")]
    for i, layer in enumerate(layers):
        desc = f"{layer.get('color') or ''} {layer['item']}".strip()
        if close and facing == "back" and any(w in layer["item"].lower() for w in ("apron", "overall", "dungaree")):
            continue  # chest-up from behind: the strap is under the hair and the ties are below the frame
        if i == 0 or facing == "front":
            q = f"Is the {who} wearing a {desc}?"
        elif facing == "back":
            continue  # an inner layer can't be identified from behind (only its sleeves show)
        else:  # profile: inner layers show as sleeves/collar under the outer layer
            q = f"Is a {layer.get('color') or ''} shirt or sleeve visible under the {layers[0]['item']}?".replace("  ", " ")
        out.append(Check(f"top:{layer['item']}", q, True, f"Wearing the same {desc} as in the reference.",
                         desc.capitalize()))
    if not close:
        for key in ("bottom", "footwear"):
            it = cl.get(key)
            if it and it.get("item"):
                desc = f"{it.get('color') or ''} {it['item']}".strip()
                out.append(Check(key, f"Is the {who} wearing {desc}?", True, f"Wearing the same {desc}.",
                                 desc.capitalize()))
        out.append(Check("framing_full", "Are the person's shoes visible at the bottom of the image (feet not cut off)?", True,
                         "Show the whole body from head to shoes with space below the feet.", "Full body framing"))
    else:
        out.append(Check("framing_close", "Are the person's legs, knees or shoes visible?", False,
                         "Close-up crop only: the frame ends at the upper chest, no legs or shoes.", "Close-up framing"))
        out.append(Check("framing_waist", "Is the person's waist visible in the image?", False,
                         "Tighter crop: the frame is cut at the upper chest, so the waist, belt line and any apron "
                         "ties or waistband are below the frame.", "Close-up crop"))
    if facing == "back":
        out.append(Check("facing_back", "Is the person's face visible?", False,
                         "Seen from directly behind: the face is not visible.", "Back view"))
    elif facing == "side":
        out.append(Check("facing_side", "Is the person shown in side profile, facing toward the LEFT edge of the image?",
                         True, "Exact side profile: nose and face point toward the LEFT edge of the image.", "Profile direction"))
    else:
        out.append(Check("facing_front", "Is the person facing the camera?", True,
                         "Facing the camera directly.", "Front view"))
    return out


# ------------------------------------------------------------------ evaluation
FACE_THRESHOLDS = {"close": 0.50, "full": 0.40}  # ArcFace; full-body faces are ~100 px so they score lower


@dataclass
class Evaluation:
    checks: list[dict] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)  # check ids
    arcface: float | None = None
    patch: float | None = None
    identity_ok: bool = True
    passed: bool = True
    rank: tuple = ()
    corrections: str = ""
    note: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["rank"] = list(self.rank)
        return d


def corrective_text(checks: Sequence[Check]) -> str:
    fixes = [c.fix for c in checks if c.passed is False]
    return ("CORRECTIONS (the previous attempt got these wrong): " + " ".join(fixes)) if fixes else ""


def evaluate(view: dict, image: str | Path, checklist: dict, vlm: VLM | None, *, patch: float | None = None,
             patch_ok: bool = True, arcface: float | None = None) -> Evaluation:
    checks = checks_for_view(view, checklist) if checklist else []
    if vlm is not None and checks:
        for c, a in zip(checks, vlm.ask(image, [c.question for c in checks])):
            c.answer = a
    failed = [c for c in checks if c.passed is False]
    close = view.get("framing") == "close" or view["id"].startswith("close")
    if arcface is not None:  # face visible + ArcFace available: it decides identity
        identity_ok = arcface >= FACE_THRESHOLDS["close" if close else "full"]
    else:
        identity_ok = patch_ok
    ev = Evaluation(
        checks=[{"id": c.id, "label": c.label, "question": c.question, "expect": c.expect, "answer": c.answer,
                 "passed": c.passed} for c in checks],
        failed=[c.id for c in failed], arcface=arcface, patch=patch, identity_ok=identity_ok,
        passed=identity_ok and not failed,
        rank=(failure_weight(checks, not close), 1 if identity_ok else 0, arcface if arcface is not None else -1.0, patch or 0.0),
        corrections=corrective_text(checks))
    if not ev.passed:
        bits = [c.label.lower() for c in failed] + ([] if identity_ok else ["face match"])
        ev.note = f"{view['label']}: {', '.join(bits)} may be wrong. Tap Regenerate to try again."
    return ev


def better(a: Evaluation | None, b: Evaluation) -> bool:
    """True if b is a better try than a: lower weighted check failures (CHECK_WEIGHTS), then identity ok,
    then ArcFace, then patch."""
    if a is None:
        return True
    return (-b.rank[0], b.rank[1], b.rank[2], b.rank[3]) > (-a.rank[0], a.rank[1], a.rank[2], a.rank[3])


def extract_checklist(reference: str | Path, vlm: VLM) -> dict:
    cl = vlm.describe_json(reference, EXTRACT_PROMPT)
    cl["_source"] = "vlm"
    return cl
