# Ren (story character)

**All rights reserved until the project decides.** Not licensed under Apache-2.0 (see `/ASSETS_LICENSE`).

An original AI character, with no photo of any person, for the story
*Lumi – Night Shift*. He is the other half of the couple who stumble into Lumi's convenience store at 3 AM: tall,
warm and a little too loud. No name,
outfit, prop, pose or line from any existing work is used.

<!-- origin:couple_readme -->**Origin (corrected Oct 18 2026):** the look was developed from couple concept images made with a closed (non-open) image generator. The reference below was then rendered with workflow `07t` from a text prompt. It is being replaced by a text-only rebuild with open models.<!-- /origin:couple_readme -->

| File | What | How it was made |
|---|---|---|
| `ren_ref_00.jpg` | Reference portrait (the sheet's input) | Workflow `07t` (text only), seed 22 of 21–24, picked by eye. Oct 17 2026, DGX Spark. **Live app only; not in release archives** (`opensoul/export_guard.py` PRE_REBUILD) until the open-model rebuild replaces it. |
| `ren_character_sheet_v1.jpg` | Six-view sheet | `scripts/sheet_run.py --gate local` (workflow 07 + 07b + auto-fix). **Live app only; not in release archives** (`opensoul/export_guard.py` PRE_REBUILD) until the open-model rebuild replaces it. |
| `character.json` | Prompt lock, persona, look | Written for the story |
Face lock: Japanese (the earlier couple concepts disagreed; locked in every prompt from now on).
