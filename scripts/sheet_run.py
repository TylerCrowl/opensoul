#!/usr/bin/env python3
"""Make a six-view character sheet from one image through the Comfy SDK (workflow 07).

  COMFY_BASE_URL=http://127.0.0.1:8189 python scripts/sheet_run.py REF.png --out out/sheet \
      --subject "short brown hair, black-rimmed glasses, ..." [--gate local] [--pack data/packs/Name] --i-own-this-image
  Text only (no photo): --from-text renders the reference portrait from --subject first (workflow 07t);
  add --ref-seeds 7,8,9 --ref-only to render several candidates and stop, then pass the one you like as REF.
Use only with original characters or images you own or have permission to use.
"""
import argparse, json, logging, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from opensoul.character_sheet import make_character_sheet, make_reference_from_text, regenerate_view  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("reference", nargs="?", help="reference image (not needed with --regenerate)")
ap.add_argument("--out", default="outputs/character_sheet")
ap.add_argument("--subject", default="")
ap.add_argument("--seed", type=int, default=None)
ap.add_argument("--gate", choices=["graph", "local"], default=None)
ap.add_argument("--pack", default=None)
ap.add_argument("--name", default="My character")
ap.add_argument("--dry-run", action="store_true")
ap.add_argument("--reuse-from", default=None, help="earlier sheet dir: keep its views/<id>.png for views not in --only")
ap.add_argument("--only", default="", help="comma-separated view ids to (re)render, e.g. close_front,close_side")
ap.add_argument("--regenerate", default="", help="comma-separated view ids to re-render in the existing sheet at --out")
ap.add_argument("--strategy", choices=["side", "wording"], default=None,
                help="with --regenerate: force the back-view fallback (rotate from the side view / visor wording)")
ap.add_argument("--tries", type=int, default=None, help="with --regenerate: max renders per view")
ap.add_argument("--from-text", action="store_true", help="no photo: render the reference from --subject first")
ap.add_argument("--ref-seeds", default="", help="with --from-text: comma-separated seeds, one candidate each")
ap.add_argument("--ref-only", action="store_true", help="with --from-text: stop after the reference candidates")
ap.add_argument("--ears", choices=["subtle"], default=None,
                help="subtle = short pointed elf ears close to the head (prompted and checked in every view)")
ap.add_argument("--no-ear-trim", action="store_true", help="with --ears subtle: skip the automatic ear-tip trim (opensoul.ear_trim)")
ap.add_argument("--i-own-this-image", action="store_true", help="required: you own the image or have permission")
a = ap.parse_args()
# --ears subtle goes into the 07t / 07 prompts (subject) and into the auto-fix checklist for every view.
overrides = {"pointed_ears": True, "ear_style": "subtle"} if a.ears == "subtle" else None
if a.ears == "subtle":
    from opensoul.sheet_check import SUBTLE_EARS_PROMPT
    if "subtle pointed elf ears" not in a.subject:
        a.subject = f"{a.subject.rstrip(', ')}, {SUBTLE_EARS_PROMPT}" if a.subject.strip() else SUBTLE_EARS_PROMPT
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
if a.from_text:  # nothing uploaded, so there is no image ownership to confirm
    a.i_own_this_image = True
if not a.i_own_this_image:
    sys.exit("Pass --i-own-this-image to confirm you own this image or have permission to use it.")
log = lambda views, stage: logging.info("progress: %s", stage)  # noqa: E731
if a.regenerate:
    res = regenerate_view(a.out, [x.strip() for x in a.regenerate.split(",") if x.strip()], gate_mode=a.gate,
                          dry_run=a.dry_run or None, strategy=a.strategy, tries=a.tries, progress=log)
    print(json.dumps(res.to_dict(), indent=2))
    sys.exit(0)
if a.from_text and not a.reference:
    if not a.subject.strip():
        sys.exit("--from-text needs --subject (the character description)")
    seeds = [int(x) for x in a.ref_seeds.split(",") if x.strip()] or None
    refs = make_reference_from_text(a.subject, Path(a.out) / "reference", seeds=seeds, dry_run=a.dry_run or None)
    print(json.dumps({"references": [str(p) for p in refs]}, indent=2))
    if a.ref_only:
        sys.exit(0)
    a.reference = str(refs[0])
if not a.reference:
    sys.exit("reference image required (or use --from-text with --subject)")
reuse = {}
if a.reuse_from:
    only = {x.strip() for x in a.only.split(",") if x.strip()}
    for p in sorted(Path(a.reuse_from, "views").glob("*.png")):
        if p.stem not in only and "_try" not in p.stem:
            reuse[p.stem] = p
res = make_character_sheet(a.reference, a.out, consent=True, subject=a.subject, checklist_overrides=overrides, seed=a.seed, gate_mode=a.gate,
                           ear_trim=(a.ears == "subtle" and not a.no_ear_trim),
                           dry_run=a.dry_run or None, pack_dir=a.pack, name=a.name, reuse=reuse,
                           progress=lambda views, stage: logging.info("progress: %s", stage))
print(json.dumps(res.to_dict(), indent=2))
