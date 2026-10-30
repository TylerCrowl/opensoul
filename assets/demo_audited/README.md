# Demo pictures that passed visual review

The default UI only shows pictures from this folder for the demo cast, the demo story and the camera tiles.
Which file goes in which slot is set in `presets/demo_images.json`, so after Lumi's redesign the pictures can be swapped there without code changes.
Every file is a read-only copy (crop or scale only, no edits) of an approved source:

| File | Source | Frames / crop |
|---|---|---|
| lumi_card_v8e_f24.jpg | production/takes/SHOT01_doodling_v8e.mp4 | frame 24 (1.000 s), in the approved range f12-f34 (0.50-1.42 s); crop x380-880 y101-768 → 480x640 |
| shot01_cold_open_v8e_f24.jpg | same | frame 24 (1.000 s), full frame → 960x549 |
| tile_still_v8e_f24.jpg | same | frame 24 (1.000 s); crop x470-790 y200-768 → 270x480 |
| konbini_master.jpg | production/setbible/MASTER_PLATE_konbini.png (md5 b0d66e9c) | full frame → 960x549 |
| konbini_window_side.jpg | same | crop x852-1344 y0-600 (the stage sheet v6 'window side' panel) |
| konbini_register.jpg | same | crop x0-704 y240-768 |
| stage_konbini_sheet_v6.jpg | production/takes/stage_konbini_sheet_v6.jpg (AUDIT_v8e: PASS) | re-saved as JPEG q88 |
| placeholder_mio.svg, placeholder_ren.svg, placeholder_frame.svg | drawn for OpenSoul | stylised placeholders (Mio and Ren have no passed picture yet) |

All of these are original characters and sets made for the Lumi – Night Shift demo. They contain no real people and no personal data, and the JPEGs carry no EXIF metadata.
| lumi_talk_l04_s171_f13_c318.jpg | lipsync/L1/out/l04_verdict_s171_ls2.0_mp.mp4, frame 13 of 172 (0.520 s, 25 fps), lips closed | crop x318–818 y0–667 → 480x640 | Approved for a still only (Oct 18 22:31). Not wired into the UI. |
| lumi_card_v8f_f18.jpg | production/takes/SHOT01_doodling_v8f.mp4, frame 18 of 109 (0.750 s, 24 fps) | crop x390–890 y101–768 → 480x640 | AUDIT_v8f_20261018_2254 PASS (whole clip). Lumi card and Starring chip. |
| shot01_cold_open_v8f_f28.jpg | SHOT01_doodling_v8f.mp4, frame 28 of 109 (1.167 s) | full frame → 960x549 | Same audit. Shot 1 card, take poster, start-card still. |
| shot01_doodling_v8f.mp4 | SHOT01_doodling_v8f.mp4, byte copy (md5 b1f0e306…) | whole clip, 4.542 s | Same audit. Shot 1's approved take (approved_takes). |
| tile_still_v8f_f24.jpg | SHOT01_doodling_v8f.mp4, frame 24 of 109 (1.000 s) | crop x390–710 y140–708 → 270x480 | Same audit; content review 23:04 moved the tiles to v8f (frames f0–f30 only). |

## Not exported (content review, Oct 18 2026 23:37)

Every picture and clip in this folder except the drawn `placeholder_*.svg` files is cut from the konbini stage plate or a
Lumi render, which descend from closed (non-open) generator concept images. They stay in the live app but are left out of
every export: the story export, the vertical share clip and `git archive` / release zips (`opensoul/export_guard.py`,
`.gitattributes`). In the app, exporting the demo story says Shot 1's take is a preview that plays in the app only.

## Hidden demo takes (`hide_takes_before`, approved in content review, Oct 18 2026 23:37)

`projects.lumi-night-shift.hide_takes_before` in `presets/demo_images.json` (2026-10-18T22:31:00-04:00, the visual review's
check) hides the demo story's seeded concept stills and every take made before that time, unless the take is listed in
`approved_takes`. Hidden takes stay in the data (never deleted or rewritten), show as "No approved take yet", carry none of
their old wording and are skipped by Export. Takes the user makes after that time show as usual.
