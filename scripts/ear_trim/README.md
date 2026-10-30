# Ear trim (post fix for Lumi's sheet)

Now built in: `opensoul/ear_trim.py` runs automatically in `make_character_sheet` when the description asks for
short/subtle elf ears (or `sheet_run.py --ears subtle`). These scripts are the original one-off versions.

Qwen-Image-Edit keeps drawing long sideways elf ears on a plain studio background,
whatever the prompt says. These small OpenCV tools shorten the tips afterwards.

- `trim_front_back.py`: front/back views. Finds skin patches that sit against the plain
  background and keeps only the inner part (`keep`, default 0.35), then inpaints the rest.
- `trim_side.py`: profile views (the ear lies over hair). `KEEP=0.58 python trim_side.py in.png out.png 0.45`
  writes `out.png_dbg.jpg` with the cut area in magenta.
- `colfill.py`: refills that magenta area along the hair strands (better than inpaint on hair).
  `python colfill.py in.png out.png_dbg.jpg fixed.png`

Always check the result by eye. Used on 18 Oct 2026 for `assets/lumi/lumi_character_sheet_v3_trimmed.jpg`.
