# Lumi (story lead)

**Current look: v3** (photoreal live-action, outfit B picked by us on Oct 17 2026): `lumi_ref_v3.jpg`, `lumi_character_sheet_v3.jpg`, concept `concepts/lumi_real_B.jpg`. Known gap: the ears are still too long and stick out sideways; the owner wants shorter, subtler ears close to the head (v3.1 = edit the reference ears first, then rebuild the sheet). v1 files below are kept for history; v2 was rejected and not committed.

An original AI character, with no photo of any person. She is not based on any existing anime or game character. She does not use any existing character's outfit, props or name.

<!-- origin:lumi_readme -->**Origin (corrected Oct 18 2026):** the current v3 look descends from a concept image made with a closed (non-open) image generator (`concepts/lumi_real_B.jpg`). The v3 sheet and references, the `concepts/v3_*` start frames and the demo film's stills all come from it. It is being replaced by a text-only rebuild with open models. Concept files and v3-derived files are left out of every export (`opensoul/export_guard.py`, `.gitattributes`). The v1 files below were drawn from text with open models.<!-- /origin:lumi_readme -->

Lumi is a 1,000-year-old elf who works as a barista in a modern coffee shop: calm, deadpan and ageless. She is a coffee-bean snob (single-origin beans, roast dates, grind size) and a fan of real whole milk. The full persona, look and props are in `character.json`.

| File | What | How it was made |
|---|---|---|
| `lumi_ref_00.jpg` | Reference portrait (the sheet's input) | Workflow `07t_character_from_text_api.json` (Qwen-Image-Edit-2511 bf16 + Lightning, no input image), seed 8 of 7–10, picked by eye. Oct 17 2026, DGX Spark. **Live app only; not in release archives** (`opensoul/export_guard.py` PRE_REBUILD) until the open-model rebuild replaces it. |
| `lumi_character_sheet_v1.jpg` | Six-view sheet | `scripts/sheet_run.py --gate local` (workflow 07 + auto-fix). Run log: `docs/evidence/CHARACTER_SHEET.md` § Lumi. **Live app only; not in release archives** (`opensoul/export_guard.py` PRE_REBUILD) until the open-model rebuild replaces it. |
| `lumi_still_01.jpg` | Still behind a coffee counter (first video frame) | Workflow 02 (consistent stills), seed 11, input `lumi_ref_00.jpg`, checked by eye. **Live app only; not in release archives** (`opensoul/export_guard.py` PRE_REBUILD) until the open-model rebuild replaces it. |
| `concepts/*.jpg` (5) | 1280x720 concept images (kissaten pour-over, konbini register with book + cat, canned coffee, coffee break by the window, milk pour under cherry blossoms). Used as clearly labelled **placeholder** takes in the Storyboard demo "Lumi – Night Shift" | Copied as-is from the Oct 17 2026 concept review batch; made with a closed (non-open) image generator. Not exported |
| `character.json` | Description (prompt lock), persona, look, props | Written for the test; the persona follows the project's notes |

License: not decided by the project yet. Until then, treat these files as all rights reserved (see `/ASSETS_LICENSE`).

## Story start frames (`concepts/v3_*.jpg`)
`v3_cold_open.jpg`, `v3_real_coffee.jpg` and `v3_ending.jpg` are start frames for the *Lumi – Night Shift* demo story. They were made on Oct 18 2026 with workflow `08_scene_compose_api.json` (Qwen-Image-Edit-2511 + Lightning) from the v3 sheet, with an invented store and no brands. The older `A_*`, `B*_*` and `C_*` concepts are the retired anime look, kept for history only.

## v3 ear trim (18 Oct 2026)

`lumi_character_sheet_v3_trimmed.jpg` and `lumi_ref_v3_trim.jpg` are the v3 views with the ear
tips shortened in post (`scripts/ear_trim/`), to match the note: short, subtle pointed ears close
to the head. Use `lumi_ref_v3_trim.jpg` as the close-up reference for new start frames.
