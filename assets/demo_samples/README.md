# Demo samples (preview mode)

The bundled demo characters that "Use the demo character" loads in preview (dry-run) mode, plus their pre-baked
pictures. Rebuild them with `python scripts/make_demo_samples.py` (CPU only).

- `lumi_pack/` — **Lumi** (main demo) in the live app only: its refs are crops of the pre-rebuild v3 sheet, so the
  whole folder is left out of release archives (`opensoul/export_guard.py` `DERIVED_DIRS`). A release offers Pixel only.
- `pixel_pack/` — **Pixel** (second demo), the Apache-2.0 geometric placeholder from `assets/example_character/`.
  Ships in releases.
- `lumi_still_01_front.png`, `_02_side.png`, `_03_close.png`, `lumi_sheet_preview.jpg`, `lumi_video_poster.png` and
  `lumi_still_reject_demo.png` — pre-rebuild Lumi pictures, live app only (left out of release archives). In a release
  the preview steps show no demo stills and the cards fall back to a text placeholder.
- `scores.json` — the preview look-check scores for those stills (ignored when a still isn't there).

Every file is re-encoded, so the demo pictures have their own fingerprints: the app never shows them under another
character's name (`app/server.py` `_demo_hashes`). License: see `assets/lumi/README.md` and `/ASSETS_LICENSE`.
