# Motion-direction check: validation on the pt1/pt1b preset takes

> **Demo A** in this file is the retired first demo character (replaced by Lumi and Pixel on Oct 18 2026). Its files were removed from the tree; file names below were renamed to match.

Oct 17, 2026, ~9:50 PM ET. `opensoul/motion_check.py` (OpenCV Farneback dense flow on 160 px grey frames, every 2nd frame,
CPU on the box, ~1.3 s per 97-frame take). Takes: the 20 LTX-2.5 i2v preset renders from the Spark (`~/OpenSoul/v4/pt1_*.mp4`,
`pt1b_*.mp4`, md5-checked copies). By-eye verdicts: review brief (GOOD = crash zoom, day-to-night, dolly in/left/right,
dolly zoom, FPV, jib up, static, outfit switch, dolly out re-take; BAD = earth zoom out, jib down, orbit, orbit freeze).
The "15" set is the latest take per preset (pt1b supersedes pt1 for the 5 re-takes); the 5 superseded pt1 takes were all
judged wrong by eye earlier and are scored as extra BAD cases.

## Confusion table (by eye vs motion_check)

| | motion_check PASS | motion_check FLAG |
|---|---|---|
| by eye GOOD (11) | 10 | 1 (dolly right) |
| by eye BAD (4) | 0 | 4 |
| extra: superseded pt1 BAD (5) | 0 | 5 |

Of the 10 GOOD passes, 2 are not actually checked (`expect_motion: "any"`: dolly zoom, outfit switch) and 1 passes only
because the read is uncertain (dolly left, confidence 0.05 < 0.2). Honest strict count: 7 of 11 GOOD takes positively
confirmed, 1 contradicted.

## Per take

| set | preset | take | by eye | expect | motion_check | conf | verdict |
|---|---|---|---|---|---|---|---|
| 15 | crash_zoom | pt1_camera_crash_zoom | GOOD | zoom_in | zoom_in | 0.74 | PASS |
| 15 | day_to_night | pt1_effect_day_to_night | GOOD | static | static | 0.74 | PASS |
| 15 | dolly_in | pt1_camera_dolly_in | GOOD | zoom_in | zoom_in | 0.68 | PASS |
| 15 | dolly_left | pt1_camera_dolly_left | GOOD | truck_left/orbit_left | zoom_in | 0.05 | PASS (uncertain) |
| 15 | dolly_right | pt1_camera_dolly_right | GOOD | truck_right/orbit_right | truck_left | 0.59 | FLAG |
| 15 | dolly_zoom | pt1_camera_dolly_zoom | GOOD | any | zoom_in | 0.66 | PASS (not checked) |
| 15 | fpv | pt1_camera_fpv | GOOD | zoom_in | zoom_in | 0.11 | PASS |
| 15 | jib_up | pt1_camera_jib_up | GOOD | crane_up | crane_up | 0.91 | PASS |
| 15 | static | pt1_camera_static | GOOD | static | static | 0.81 | PASS |
| 15 | outfit_switch | pt1_effect_outfit_switch | GOOD | any | zoom_out | 0.98 | PASS (not checked) |
| 15 | dolly_out | pt1b_camera_dolly_out | GOOD | zoom_out | zoom_out | 0.64 | PASS |
| 15 | earth_zoom_out | pt1b_effect_earth_zoom_out | BAD | zoom_out | zoom_in | 0.58 | FLAG |
| 15 | jib_down | pt1b_camera_jib_down | BAD | crane_down | zoom_in | 0.55 | FLAG |
| 15 | orbit | pt1b_camera_orbit | BAD | orbit | zoom_in | 0.47 | FLAG |
| 15 | orbit_freeze | pt1b_effect_orbit_freeze | BAD | orbit | zoom_in | 0.53 | FLAG |
| superseded pt1 | dolly_out | pt1_camera_dolly_out | BAD | zoom_out | zoom_in | 0.61 | FLAG |
| superseded pt1 | earth_zoom_out | pt1_effect_earth_zoom_out | BAD | zoom_out | zoom_in | 0.58 | FLAG |
| superseded pt1 | jib_down | pt1_camera_jib_down | BAD | crane_down | truck_left | 0.35 | FLAG |
| superseded pt1 | orbit | pt1_camera_orbit | BAD | orbit | static | 0.79 | FLAG |
| superseded pt1 | orbit_freeze | pt1_effect_orbit_freeze | BAD | orbit | static | 0.61 | FLAG |

## Where the check disagrees with the by-eye GOOD, and why

- **Dolly right reads `truck_left` (0.59).** Checked frame by frame: the first half is near-static, then the camera pushes
  in while the frame content (Demo A and the post) slides **right**, which is what a camera moving *left* (or the subject
  stepping right) looks like. A truck right would slide him left. The by-eye "OK" was lenient; this take does not move
  the way the tile says. It stays committed for now (the project's call); a dolly-right retake gated by motion_check is in the
  queue notes. The dolly-left/right LoRAs are not on the Spark, so both are prompt-only.
- **Dolly left reads `zoom_in` at 0.05 (uncertain).** The lateral parallax is in the right direction (camera left) but
  about the same size as a slight push-in (zoom 0.14 vs lateral 0.13). By eye it is mostly Demo A leaning in, with very
  little lateral travel. Treated as uncertain, so no re-seed.
- **Dolly zoom** looks like a push-in in flow (and by eye the face grows a lot), which a single global model cannot tell
  apart from a vertigo shot; it is `any` (unchecked) rather than pretending.
- **Outfit switch** has a hard cut and a zoom-out after it; `any`.

## Classes that can and cannot be separated

- Zoom in vs out: clean (divergence sign; zoom consistency 0.7-1.0 across frame pairs on every zoom take).
- Static vs moving: clean (static, day-to-night, orbit pt1, orbit-freeze pt1 all < 0.16 summed motion; moving takes > 0.32).
  Day-to-night's lighting change did not produce false flow.
- Crane up vs down: separated by *parallax* (background vs subject), not raw vertical flow, because the jib presets tilt to
  keep the subject framed: in the good jib-up take the background moves UP (tilt down dominates) while the raw
  "image moves down when the camera rises" rule would call it a crane down. A push-in also gives the top band a
  downward residual, so vertical travel only counts when the top band and the side bands agree; without that rule the
  push-in jib-down and dolly-out-pt1 takes came within 0.01-0.08 of reading `crane_down`. Only one real crane take exists
  (jib up, 0.91) plus its reverse (crane down, 0.91) and synthetic clips, so this class is thinly validated.
- Orbit vs truck: separated only on synthetic clips (subject held + large background sweep = orbit). There is **no real
  orbit take** to validate on; both orbit renders barely move. Expect thresholds to need a retune on the first real orbit.
- Pan vs truck: synthetic only (parallax vs uniform translation).

## Thresholds

`static_motion` 0.20, `min_component` 0.12, `orbit_sweep` 0.60, `subject_hold` 0.5, `min_confidence` 0.2. Only
`min_confidence` was chosen with these takes in view (the gap is 0.05 dolly left vs 0.35 lowest BAD); the rest were set
from the synthetic clips and left alone. The structural fixes (parallax-based vertical, translation counted as pan only
where parallax does not explain it) came from failures on synthetic truck clips and the jib-up sign, not from forcing a label.

## Reverse trick

- `pt1_effect_earth_zoom_out` reversed: `zoom_out` 0.59 (also `pt1b` reversed: `zoom_out` 0.58). By eye a clean pull-back
  from a close-up of his face to a wide shot at the fence in the field. It does **not** reach rooftops/clouds/space.
- `pt1_camera_jib_up` reversed: `crane_down` 0.91. By eye a real downward crane: starts high looking down at his boots,
  descends while tilting up, the horizon and sunset sky rise into view, lands at eye level on the start still.

## Raw numbers (summed over 48 frame pairs, units of half the short side)

| take | motion | zoom | pan_x | pan_y | par_x | par_y (top) | par_y_side | par_y_agreed | sub_x |
|---|---|---|---|---|---|---|---|---|---|
| pt1_camera_crash_zoom | 1.96 | +1.09 | +0.71 | +0.64 | -0.23 | -0.04 | -0.13 | -0.04 | +0.92 |
| pt1_effect_day_to_night | 0.11 | -0.00 | +0.03 | +0.00 | -0.00 | -0.00 | +0.00 | +0.00 | +0.01 |
| pt1_camera_dolly_in | 1.56 | +1.17 | +0.62 | +0.76 | -0.03 | +0.12 | -0.18 | +0.00 | +0.71 |
| pt1_camera_dolly_left | 0.33 | +0.14 | +0.00 | +0.16 | -0.13 | +0.05 | -0.04 | +0.00 | +0.08 |
| pt1_camera_dolly_right | 0.68 | +0.22 | +0.51 | +0.26 | -0.54 | +0.07 | -0.13 | +0.00 | +0.86 |
| pt1_camera_dolly_zoom | 1.77 | +1.08 | +0.69 | +0.73 | -0.15 | +0.19 | -0.11 | +0.00 | +0.87 |
| pt1_camera_fpv | 0.88 | +0.45 | +0.33 | +0.44 | -0.41 | +0.19 | -0.15 | +0.00 | +0.58 |
| pt1_camera_jib_up | 1.09 | +0.10 | +0.00 | -1.01 | -0.04 | -1.05 | -1.04 | -1.04 | +0.02 |
| pt1_camera_static | 0.08 | -0.00 | +0.01 | -0.00 | +0.00 | -0.01 | -0.01 | +0.00 | +0.00 |
| pt1_effect_outfit_switch | 1.40 | -0.85 | +0.03 | +0.04 | +0.01 | -0.50 | +0.00 | +0.00 | +0.07 |
| pt1b_camera_dolly_out | 0.53 | -0.41 | +0.03 | -0.30 | -0.13 | -0.17 | +0.13 | +0.00 | +0.09 |
| pt1b_effect_earth_zoom_out | 1.28 | +0.86 | +0.52 | +0.73 | -0.00 | +0.33 | -0.12 | +0.00 | +0.60 |
| pt1b_camera_jib_down | 0.63 | +0.51 | -0.02 | +0.46 | +0.04 | +0.43 | -0.12 | +0.00 | -0.04 |
| pt1b_camera_orbit | 0.35 | +0.22 | +0.06 | +0.21 | -0.02 | +0.16 | -0.02 | +0.00 | +0.06 |
| pt1b_effect_orbit_freeze | 1.12 | +0.74 | +0.46 | +0.71 | +0.01 | +0.33 | -0.11 | +0.00 | +0.51 |
| pt1_camera_dolly_out | 0.73 | +0.59 | +0.02 | +0.46 | +0.05 | +0.58 | -0.02 | +0.00 | +0.00 |
| pt1_effect_earth_zoom_out | 0.86 | +0.68 | -0.01 | +0.58 | +0.01 | +0.61 | -0.13 | +0.00 | -0.02 |
| pt1_camera_jib_down | 0.83 | +0.32 | +0.44 | +0.38 | -0.48 | +0.12 | -0.14 | +0.00 | +0.66 |
| pt1_camera_orbit | 0.09 | +0.01 | +0.02 | +0.02 | -0.05 | +0.00 | -0.00 | +0.00 | +0.04 |
| pt1_effect_orbit_freeze | 0.15 | +0.00 | +0.00 | +0.03 | -0.01 | -0.03 | -0.02 | +0.00 | +0.01 |

Sheets: `production/motion_check/contact_sheet_all_takes.jpg`, `contact_sheet_reverse_fix.jpg` (box only).
