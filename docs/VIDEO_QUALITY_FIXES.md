# Video quality fixes, problem by problem (what changed the app defaults)

These come from our review of the Lumi rough cut (18 Oct). Each entry lists the symptom, the cause I
found by eye plus frame metrics, the fix, and whether it is now an app default. The goal is footage that feels
filmed by a person.

## 1. Background ghosting or smearing when the subject moves her head
- **Where:** Real coffee showed it most. A grey, semi-transparent haze (the "steam rising" from the prompt) drifted
  behind her head over the dark window and moved with her, which reads as a ghost. In the Cold open, the
  "static" camera still pushed in about 14% and refocused, so the whole background pumped and smeared. The
  Ending had only small smearing at the hair edge.
- **Not the cause:** the outpainted border (Real coffee and Ending were never outpainted, and the Cold open
  border area stayed clean) and step count (finals already use 8+3 steps).
- **Cause:** (a) wording that invites volumetric effects ("steam rising") or framing ("medium close-up" inside
  the Static preset, which LTX-2.5 reads as a push-in from a wider frame); (b) weak first-frame conditioning
  (stage-1 strength 0.85, img_compression 18), so LTX blends background pixels over time.
- **Fix (A/B on the same seeds, g7):** G1, prompt only, cut the Cold open zoom from 0.144 to 0.063. G2, prompt
  plus the defaults below, cut it to 0.022 and reduced background drift from 25.6 to 11.0, and the haze was
  gone. G2 is the default:
  - Static preset prompt names no framing: "framing, zoom and focus stay exactly as in the first frame…
    background stays still and sharp".
  - Every silent shot (workflow 04): the negative prompt adds `ghosting, smearing, double exposure, motion trails, fog, haze,
    smoke cloud, background warping, melting objects, flicker, refocus, frozen animal`.
    Talking shots (workflow 04b, guidance pinned at video_cfg = audio_cfg = 1.0) never evaluate a negative
    prompt: at cfg 1 ComfyUI skips the unconditional pass, so a negative is not a control there (adding one gave
    framemd5-identical output). The mouth and the grin are steered by the positive articulation sentence only.
  - Static shots only: stage-1 image strength 1.0 and img_compression 10 (moving cameras keep 0.85/18 so they
    still move).
  - Scene prompts: keep steam to "a thin, faint wisp just above the cup", and add "nothing drifting behind her
    head".
- **Check:** temporal-std heat map plus 1:1 crops around the head (`production/ghost/`,
  `production/g7/cmp_*.jpg`).

- **Follow-up (Real coffee):** prompt changes alone did NOT remove the haze. The start frame itself had a
  steam plume (beside the cat, in front of the window), and LTX spread it behind her head. Fix: a Qwen-Edit
  pass on the start frame ("remove the white cloud of steam… show the clear dark window"), then the final.
  The haze was gone in both seeds (r6 v23/v24). **Rule: clean volumetrics (steam, smoke, fog) out of the
  start frame first; the video model makes them bigger.**
- **Result (r6 finals):** in the Cold open, background std at the frame edges dropped from 12 to 5–6, and the
  push-in is gone (zoom 0.144 → 0.027). Real coffee has no haze behind her head. The Ending was already
  clean. Proof crops: `production/takes/GHOSTING_before_after_crops.jpg`.

## 2. Animals frozen
- Prompt one small, specific sign of life per shot: "breathes slowly, its side gently rising and falling, one
  ear flicks once", "tail tip twitches once", "blinks slowly". The negative prompt includes "frozen animal".
  Check by measuring pixel change inside the cat's box (it changed in all g7 takes) and by eye.

## 3. Readable text
- Name tags and shelf signs: a Qwen-Edit cleanup pass on the start frame (blank tag, blank colour panels).
  Small product cartons can still grow text (the Real coffee milk carton shows a short word), so check props
  too.

## 5. Lip-sync: natural-looking but not in sync (18 Oct, Lumi A/B)
- **Measured:** SyncNet confidence (LatentSync eval, higher = better, ~>6 is clearly synced). LTX-2.5 joint a2v
  takes score 0.1–1.6 on every setting tried (prompt articulation cues, 12+4 steps, video CFG 2.0, strength 1.0,
  clean/lead-in audio). The mouth barely moves, which is why it "looks natural". InfiniteTalk (audio guidance 4,
  40 steps) scores 9.5 but over-animates the mouth.
- **Close-up start frames make LTX push in.** From a medium close-up start frame, LTX a2v zoomed in (zoom 0.10–0.23)
  despite "no zoom" in the prompt; video CFG 2.0 was the only setting that held (0.035). More steps made it worse.
  The wider d2 frame stayed locked (zoom < 0.005). **Rule: for a2v, start from a medium shot, not a close-up.**
- **What to try instead:** LTX take for the body + a mouth-only LatentSync 1.6 pass at guidance 1.5 (Apache-2.0 code; face detector swapped to MediaPipe, see runners/ls_face_detector.py); InfiniteTalk with
  lower audio guidance (2.5) and fewer steps on short lines. Results in the next update.

## 6. The same place looks different from shot to shot (18 Oct, Lumi konbini)
- **Symptom:** each interior start frame drew its own konbini: different lamps, shelves, window neon, counter, and
  the cat in a different spot (Real coffee and Ending had no globe pendants and another neon sign).
- **Cause:** every start frame was composed from scratch from a text description, so the model invents the set again.
- **Fix: a set bible.** Pick one clean interior frame as the **master plate**, write one fixed **set-description
  block**, and build every interior start frame by **editing from the plate** (Qwen-Edit, plate = picture 1),
  never from scratch. Keep the camera side the same where you can; move people and props, not the room.
- **App feature (implemented):** *Locations*, like a character reference but for a set. A story has
  `locations` (name, master-plate picture, set description); a shot can be set at one (`shot.location`).
  "New start frame" on a located shot sends the plate as picture 1, the cast as pictures 2–3, and prepends
  "Picture 1 is the master plate of the location … keep its camera position, set, layout, props, window view,
  lighting and colors exactly the same" + the set block. API: `PUT/DELETE /api/storyboard/projects/{pid}/locations/{name}`
  (`image` path or `from_version: "<shot>/<take>"` to promote a take's still to the plate), `PATCH …/shots/{sid}`
  with `location`. UI controls are still to come (a "Location" picker on the shot card).
- **Limit:** a plate takes one of the three picture slots, so a located shot fits two cast pictures; with three
  characters, describe the third in words or composite in two passes.

## 7. Ghosting, judder and the set "breathing" (18 Oct, Lumi v7 review)

**Symptom.** Review found: ghosting still visible; people and set smear; the shop changes from shot to shot.

**Diagnosis (frame diffs, `production/v8/ghost/`).** Three separate causes, not one:
1. *Judder from slow-motion.* The v7 cut slowed 3.5 s drafts to 0.45–0.5x with `setpts`, which just repeats frames:
   47–52 % of the frames in SHOT02/03 are exact repeats of the previous frame. Repeated frames plus the model's own smear
   read as ghosting. → Render each clip at its real length; never slow LTX output below ~0.85x by frame repeats.
   `opensoul.plate_lock.repeated_frame_share(video)` measures it (should be ~0 % for generated clips).
2. *Set drift.* The difference between the first and last frame is bright on every edge of the static set (shelves, lights,
   window frame), i.e. the "locked" camera creeps and the set re-renders a little every frame.
3. *Morphing props in motion* (the half-folded umbrella, hands, cups): the motion heat map concentrates there.
   → fewer moving props per shot, shorter clips (≤ 5 s), one action per shot.

**Fix (app default when a shot has a stage).** `opensoul/plate_lock.py`:
- `lock_frame(frame, plate)`: start frames edited from the stage plate are aligned to it (guarded ECC affine) and the plate
  is copied back everywhere except where the frame really differs (actors, props). `make_frame` does this automatically
  for shots with a stage and keeps the unlocked render as `frame_raw.png`.
- `lock_video(src, dst, plate)`: actor-over-plate matte compositing for locked-camera shots. The matte for frame *t* is the
  union of the masks in *t±4*, feathered, so fast hands aren't clipped and the edge doesn't flicker; `live_boxes` keep
  e.g. a rainy window moving. The set can no longer breathe or smear.

## 8. Stage sheets: continuity for places (18 Oct)

Character sheets keep a face the same; **stage sheets** keep a place the same. A stage sheet (a `Location`) holds:
the locked master plate (wide), up to six angles of the SAME room (default presets: behind the counter, customer side,
window side, medium at register), an empty plate (master angle, nobody in it, for compositing), the fixed set
description and a continuity checklist, plus the rendered sheet image.

- Angles are generated by editing the empty/master plate with a camera-move-only prompt (`stage_sheet.angle_prompt`),
  then checked by eye on the sheet (`POST /locations/{name}/sheet`). Reject an angle whose counter, register side,
  shelves, lamps or window don't match the master.
- Each shot picks a stage **and an angle** (`Shot.location`, `Shot.stage_angle`; UI: Stage picker with angle thumbnails
  in the shot sheet). Start frames are edited from that angle's plate (picture 1) and then plate-locked against it.
- API: `PUT/DELETE /projects/{pid}/locations/{name}` (image, empty, description, checklist),
  `PUT/DELETE /projects/{pid}/locations/{name}/angles/{angle}` (image, from_version, note, or `generate: true`),
  `POST /projects/{pid}/locations/{name}/sheet`.

**What actually makes stage angles (tested on the Lumi konbini, 18 Oct):**
- Qwen-Image-Edit 2511 does **not** move the camera: 8 of 8 "same room from another viewpoint" edits returned the
  master view unchanged (some added random people). Don't use it for angles.
- An LTX camera move from the empty plate does: the **early** frames of an orbit (~frame 30 of 97) and the end of a short
  truck are the same room from a new position. Later in an orbit LTX invents a bigger store — take the frame before
  the room starts changing.
- Tighter-lens crops of the empty plate are the cheapest perfectly-consistent angles (soft when upscaled).
- Paint plate fixes (ear tips, sign glyphs) into the master/empty plate once: with plate lock every start frame inherits them.

**v8 measurements (LTX-2.5 final, 169 frames, "static" preset):** even locked-off, the actor slowly grows ~20 %
over 7 s and the whole frame goes soft after ~4.5 s (frame 0 vs 168 on SHOT01). That late softening is what reads as
"ghosting". Rules now: use only the first ~4.5 s of a generated clip (cut more, shorter shots instead of long takes);
lock the background to the clip's **own first frame** (`lock_video(src, dst, first_frame, match_color=False)`;
ghost score 1.64 → 0.93, background drift 21 → 12) rather than to the raw stage plate, because the video model
re-grades and re-blurs the whole frame and a raw-plate matte ends up covering ~95 % of it. `match_colors` helps
when a stage plate must be used.
