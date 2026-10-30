# Preset tile thumbnails

Looping 360x630, muted, 9:16 MP4s shown on the Camera and Effects tiles in the UI.

**Current tiles are CPU placeholders of Lumi** (Oct 18 2026), made by `scripts/make_preset_tile_placeholders.py`
with ffmpeg from committed Lumi stills (`assets/lumi/concepts/v3_*.jpg`, `assets/demo_samples/lumi_still_*.png`):
a 2-D move on one still (push, pull, slide, rise), a grade from day to night, or a wipe between two looks. No model
and no GPU. They replace the earlier tiles of the retired demo character and stay until the real LTX re-render
(job spec: `production/app_test/ltx_vfx_jobs/tiles_rerender_lumi/`) passes its checks.

`opensoul/motion_check.py` on the placeholders (`python scripts/make_preset_tile_placeholders.py --check`):

| Tile | expect_motion | detected | ok |
|---|---|---|---|
| static, day_to_night | static | static | yes |
| dolly_in, push_in_gentle, crash_zoom, fpv | zoom_in | zoom_in | yes |
| dolly_out, earth_zoom_out | zoom_out | zoom_out | yes |
| dolly_zoom, outfit_switch | any | – | yes |
| dolly_left / dolly_right | truck_left / truck_right | pan_left / pan_right | **no**: a flat still has no parallax |
| jib_up / jib_down | crane_up / crane_down | tilt_up / tilt_down | **no**: same reason |

Orbit and Orbit freeze have no file, so the UI keeps its animated placeholder: a 2-D slide would misrepresent an orbit.

License: Lumi is an original AI character (see `assets/lumi/README.md` and `/ASSETS_LICENSE`).
