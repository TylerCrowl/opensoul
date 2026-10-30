# Lip-sync scorer (optional, external)

`opensoul/lipsync_scorer.py` can run an **external** lip-sync scoring CLI (fair SyncNet LSE-C / LSE-D) as a
subprocess. That CLI is **not part of this repository**, OpenSoul never downloads or installs it, and the shipped
`presets/lipsync_scorer.json` leaves `cli` empty, so the scorer is **off**.

- **Who uses it:**
  - `opensoul.lipsync.run_rebuilt_method` (the rebuilt-character method: articulated LTX a2v take, LatentSync 1.6
    fallback when LSE-C < 4.5, then the inner-mouth pass). Nothing in the app, the ComfyUI nodes or the scripts calls
    it, and the default backend stays `ltx_av` (`tests/test_rebuilt_method_off_default.py`).
  - **L1c** (the default recipe, below) and its best-of-3 base seeds (`opensoul.lipsync.best_of_seeds`, run by
    `opensoul.shot.run_shot`) for Final talking shots on the `ltx_av` engine of **rebuilt characters**. With the
    shipped (empty) config the scorer is off, so these shots render seed 1 only, flagged `scorer_failed`.
- **Turning it on (optional):** set `cli` (and `python`, the tool's own interpreter) in
  `presets/lipsync_scorer.json`, or `OPENSOUL_LIPSYNC_SCORER` / `OPENSOUL_LIPSYNC_SCORER_PYTHON` /
  `OPENSOUL_LIPSYNC_SCORER_TIMEOUT`. Contract: `<python> <cli> --score-only VIDEO [--ref RAW] --json` prints one JSON
  object with a numeric `lse_c` (and `lse_d`, `method`). `lse_c: null` (SyncNet found no face) is a scorer failure
  (`no_face`): the method keeps the a2v take and flags it (`scorer_failed`, `flag`), with no automatic LatentSync
  fallback. Never put a home path in the preset.
- **Licensing, if a scorer is ever shipped or documented for download:** the SyncNet model and code (`syncnet_v2`)
  are MIT. The S3FD face-detector weights it uses (`sfd_face.pth`) have **no upstream licence**: they must **never be
  redistributed** with OpenSoul and **never downloaded by default** (no `download_models.sh` group, no auto-fetch).

## L1c: the default lip-sync recipe for talking shots (rebuilt characters)

**Grin-gated + camera-locked a2v base (eyes open, looking at the listener) → LatentSync, MediaPipe only.** In plain
words: render a few LTX audio+video takes with the camera locked (native ComfyUI `LTXVAddGuide` pins the last frame
to the start frame), throw away the ones that grin, keep the lips shut, or let the camera creep, keep the one with
the most open eyes, then let LatentSync redo the mouth. All numbers are in `presets/lipsync_best_of.json` (`recipe`
and the `l1c` block). **METHOD ONLY** wording below describes the method; method-test clips stay out of a story.

**Camera lock on the a2v graph (default).** After stage-1 `LTXVImgToVideoInplace` (strength stays **0.85**), native
`LTXVAddGuide` (NOT KJNodes) takes the **same** start-frame preprocess as frame 0, `frame_idx=-1`, `strength=1.0`,
then ConcatAV; DualCFG gets the guide conds. After SeparateAV, `LTXVCropGuides` runs **before** the upsampler;
stage-2 DualCFG runs on the cropped conds. Cfg stays **video/audio 1.0/1.0**. Do not count on the prompt or negative
for the lock (nothing is removed from them). Env `OPENSOUL_A2V_CAMLOCK=off` restores the old graph (no AddGuide /
CropGuides) and skips the cam gate. Wiring mirrors `notes/v7g/batch3.py` and the last-guide a2v workflow.

1. **Base (stage 1).** The best-of-3 seeds below are judged on **look and camera, not sync**: a seed is rejected for a
   grin (`grin_win_max > 0.15` or `grin_frac > 0.3`), closed lips (`open_frac == 0`), or **camera drift** (scale >
   **0.5%** or centre translation > **1 px** over the take). Offset and LSE-C never
   reject a base. `open_frac` is never a hard reject on its own beyond the closed-lips rule; it stays descriptive
   otherwise. Among the passing bases the one with the highest `eyes_open_frac` wins, then the higher LSE-C (a base
   with `eyes_shut_flag` ranks after unflagged ones; the flag stays a review flag). A cam fail **re-seeds** (the next
   best-of-N base) and **never** runs LatentSync on that take. Every base rejected -> the best-ranked one is kept,
   needs review, and the mouth pass is not run (LatentSync can't remove a grin or fix a drifting camera). The record
   says which seed was picked and why (`pick_why`, `order_seeds`) and stores each seed's `cam`.
2. **Mouth (stage 2).** LatentSync 1.6 through our wrapper with the **MediaPipe face detector only** (never
   InsightFace; `face_style: real`), guidance **2.0**, **50** steps, seed **1247**. The base is **trimmed** to the
   voice length first (the first frames; never looped). A base shorter than the voice is flagged `base_short` for
   review and not re-mouthed. The **output** is scored with every check (`|offset| >= 3`, `open_frac == 0`, the grin
   rules) and the **camera is re-checked** with the same ≤ 0.5% / ≤ 1 px limits. A grin **or** a post-LatentSync cam
   fail means the base was wrong: the next passing base is used (flagged in the take notes). LatentSync is never
   re-run with other settings. Another failing check keeps the output and marks it needs review. The camera lock does
   **not** replace LatentSync: stage 2 stays on when the base passes cam and grin (same voice / rebuilt defaults).
   - **Camera-locked takes (the default a2v graph, LTXVAddGuide): OFF by default.** Review ruling: LatentSync
     pales the lips on AddGuide bases, so the rules below apply only with camera lock off (`OPENSOUL_A2V_CAMLOCK=off`).
     Opt in per shot with **Mouth refine (LatentSync), may pale lips** (Storyboard, Advanced; shot field
     `mouth_refine`), or for every shot with `OPENSOUL_MOUTH_REFINE=on`. The take note says why it didn't run.
   - **When it runs:** on by default for every **rebuilt** character's talk take, whatever the voice id
     (`l1c.stage2.default_on_rebuilt: true`; rebuilt is the same test the best-of scope uses: the pack says
     `"rebuilt": true`, or it was made from text in Create, `meta.origin.kind == "text"`). For a character that isn't
     rebuilt it is on by default for voice **F** (`l1c.stage2.default_on_voices: ["F"]`, matched against the shot's
     voice id, case-insensitive); other voices skip it when the base already passes every check. The take note says
     why it ran: "on by default for rebuilt characters", "on by default for voice F (clip_F)", "on by setting" or
     "stage 1 didn't pass every check (...)"; the plan records `rebuilt`, `stage2_default_on` and
     `stage2_default_why`. A dry run, or no base passing the look checks, still skips it. Settings:
     `OPENSOUL_L1C_STAGE2` = `auto` (default) | `on` | `off`, `OPENSOUL_L1C_STAGE2_REBUILT` = `on` (default) | `off`
     (the rebuilt default), `OPENSOUL_L1C_STAGE2_VOICES` (comma list of voice ids). The shipped Orpheus voices have no id `F`: voice F is a voice made outside the shipped set, so a shot
     only gets the default when its voice id is `F` or one of its aliases (or the list is changed).
   - **Voice F aliases:** `clip_F`, `revoice_F` and `qwen3_F` (any case) count as voice `F`
     (`l1c.stage2.voice_aliases`). `F` stays the canonical id: the plan records the voice id as given plus
     `voice_canonical`, and the take note says "on by default for voice F (clip_F)". `OPENSOUL_L1C_STAGE2_VOICES`
     changes the list; the aliases of a listed canonical id still apply.
   - **Pack voice label (metadata only).** A character pack may carry `"voice_label": "F"` (top level, or in `meta`)
     and a notes block next to it (`voice_label_notes`, or `voice_notes`). The lip-sync side reads it through the
     voice aliases: the plan and the take record show `voice_label` and `voice_canonical` (and the notes), the take
     notes say "Lip-sync voice label: F (metadata; the voice is made with tara)", and the stage-2 reason can name it
     ("voice F (voice_label F)"). The TTS never reads it: the voice that speaks the line is still the character's
     voice from the Characters picker. The cast shows the label read only next to the voice picker.
   - **Inner-mouth pass: optional, experimental, off by default.** `OPENSOUL_L1C_INNER_MOUTH=on` runs
     `ls_inner_mouth.py` after LatentSync with its own defaults (the L1c2 settings: lip colour fix on in blend mode,
     mask erode 1, open threshold 0.06, dilate 1). It can leave black voids in the mouth and hold the mouth open into
     a pause, so it is not a finishing step.
   - Needs LatentSync installed and a face the check allows (one face, or the speaker's face box); otherwise the base
     take is kept and the plan says so.
3. **Framing (warning only).** A talk shot whose start frame has the face taller than 35% of the frame height, or
   `|yaw| > 0.15`, gets a note: use a medium start frame (face about 25-30% of the frame height) and crop in during
   the edit. It runs when the data is there (the shot's face box, or the scorer's `start_face_h_frac` / `start_yaw`)
   and is silent otherwise.
4. **Eyeline at the end (warning only, provisional).** The talk prompt puts the eyes on the listener; a take whose
   eyes drift back to the lens by the end gets the warning **"eyeline drifts to lens at end"**. The look score is how
   much the eyes look at the listener (1) rather than at the lens (0). It comes from the scorer's
   `start_eye_look_listener` / `end_eye_look_listener`, else from its per-frame `eye_look_listener_frames`: the mean
   over the first and last `eyeline.window_s` (0.25 s, with `fps`; one frame without it; frames without a face left
   out). The warning fires when the end is below `eyeline.end_warn` (0.3) or falls by `eyeline.drop_warn` (0.3) or
   more from the start (for example 0.68 -> 0.19). Both numbers are provisional. When the scorer sends its own
   `eyeline_drift_warn` (true / false), that decides the warning (the scorer wins) and the numbers are only recorded;
   its per-frame values may be 1 / 0 (look >= 0.3 or not) with `null` for a frame without a face, and the whole
   eyeline group is left out when the shot has no listener. It never rejects a base or an
   output, never adds a review reason, never re-picks and never triggers a fallback. No look data -> no check and no
   note. Each seed and each mouth-pass attempt records `eyeline` (`start`, `end`, `drop`, `from`, `warn`, `why`).
5. **Cost hint.** LatentSync works in 16-frame chunks at about 35.3 s each (measured on a DGX Spark):
   `ceil(frames / 16) * 35.3` s. The plan note and the take details (Storyboard) show it.
6. **Record.** `<take>.best_of.json` next to the final file has `recipe: "L1c"`, `stage1` (seed, file, why, eyeline, cam),
   `stage2` (params, the base kept, re-picks, output scores, eyeline, cam, review reasons), `warnings` (the eyeline
   warning of the file that ships) and the full best-of record;
   `out_sha256` / `out_frames` are computed from the final file and the file is written atomically. Every seed stays
   under `<take>/seeds/s<seed>/`; the mouth-pass files are in `<take>/seeds/s<seed>/l1c/`.
7. **The older pick** (highest LSE-C, LatentSync only when every seed is rejected) is still there, but only by
   setting: `"recipe": "best_of_fallback"` in the preset or `OPENSOUL_LIPSYNC_RECIPE=best_of_fallback`. The rules
   below describe that pick; the seed rendering, scorer, eyes and line-id rules are shared with L1c.

**Method tests are METHOD ONLY.** Clips made to test a method (for example a LatentSync run over a test start frame)
are not shippable takes, even when they score well. Keep them out of a story and out of a release; where a test has a
manifest or metadata, mark it `"method_only": true`.

## Best-of-3 seeds (`ltx_a2v_artic`, rebuilt characters)

The seed decides sync far more than the wording (LSE-C swings up to 5.8 between seeds on the same line), so a Final
talking shot of a rebuilt character renders **3 seeds** by default (s, s+1, s+2), scores each with the scorer above and keeps one.

- **Which characters:** the setting `OPENSOUL_LIPSYNC_BEST_OF` is `auto` by default: on only for **rebuilt**
  characters. A character is rebuilt when its pack (`pack.json`, top level or `meta`) says `"rebuilt": true`; without
  that field, a pack made from text in Create (`meta.origin.kind == "text"`, open models only) counts as rebuilt, and
  `"rebuilt": false` opts out. `on` = every speaker, `off` = nobody. The shipped demo packs carry no field (not rebuilt).
- **Only the `ltx_av` engine, Final quality.** Draft and the LatentSync engine are unchanged.
- **Config, not code:** `presets/lipsync_best_of.json` holds the seed count, the seed step, every threshold and the
  scorer's field names. Keys: `seeds` (3), `seed_step` (1),
  `fields.{lse_c, lse_d, offset, open_frac, grin_frac, grin_win_max, grin_def, eyes_open_frac, eyes_shut_flag,
  eyes_shut_max_s, start_eye_blink, eye_blink_frames, eye_look_down_frames, fps, start_eye_look_listener,
  end_eye_look_listener, eye_look_listener_frames}` (the three eyeline keys are optional) (metric -> key in the scorer's JSON), `reject.abs_offset_min` (3), `reject.open_frac_max` (0.0),
  `reject.grin_frac_max` (0.3), `reject.grin_win_max` (0.15), `tiebreak.eyes_open_frac_lse_c_window` (0.3),
  `eyes_rules_apply_to` (`["ltx_av"]`), `eyes_shut.{eye_blink_min 0.6, look_down_max 0.3, min_duration_s 1.0}`
  (provisional, see below), `start_frame.eye_blink_warn` (0.5), `grin_review_only`
  (`["l07"]`), `info.grin_def` (`v2_blendshape_smile`) and `report_fields` (recorded, never gate:
  `eyes_open_frac`, `eyes_closed_max_s`, `eyes_shut_flag`, `eyes_shut_max_s`, `start_eye_blink`, `grin_smile_p90`, `grin_base_smile`, `grin_def`,
  `grin_geom_frac`, `grin_geom_win_max`). Env overrides: `OPENSOUL_BEST_OF_SEEDS`, `OPENSOUL_BEST_OF_SEED_STEP`,
  `OPENSOUL_BEST_OF_ABS_OFFSET`, `OPENSOUL_BEST_OF_OPEN_FRAC_MAX`, `OPENSOUL_BEST_OF_GRIN_FRAC_MAX`,
  `OPENSOUL_BEST_OF_GRIN_WIN_MAX`, `OPENSOUL_BEST_OF_EYES_TIEBREAK_WINDOW`, `OPENSOUL_BEST_OF_GRIN_REVIEW_ONLY`
  (comma list; empty = none), `OPENSOUL_BEST_OF_FIELD_<METRIC>` (e.g. `OPENSOUL_BEST_OF_FIELD_GRIN_WIN_MAX`), and
  `OPENSOUL_BEST_OF_CONFIG` for another file.
- **Reject a seed** when `|offset| >= abs_offset_min` frames, `open_frac <= open_frac_max` (lips closed through the
  speech), or grin v2: `grin_frac > grin_frac_max` or `grin_win_max > grin_win_max` (MediaPipe smile blendshape,
  highest mean over any 0.5 s window). If the scorer reports a `grin_def` other than `info.grin_def` (the old
  geometry), the grin rules are not applied and the seed carries `scorer_failed:grin_def`; no `grin_def` = trusted.
  Among the survivors the **highest LSE-C** wins.
- **Eyes never reject.** `eyes_open_frac` is only a tiebreak: among passing `ltx_av` seeds within 0.3 LSE-C of the
  best, a seed with `eyes_shut_flag` loses to an unflagged one, then the higher `eyes_open_frac` wins, then LSE-C (a
  seed without `eyes_open_frac` ranks last in the tiebreak; it is not `scorer_failed`). The record has
  `tiebreak: {by, decided, window, candidates, highest_lse_c_seed}` and `tiebreak_decided: true` when the tiebreak
  (not the highest LSE-C) picked the seed; `by` is `eyes_shut_flag` or `eyes_open_frac`.
- **`eyes_shut_flag` is a needs_review reason, never a reject and never the LatentSync fallback** (only every seed
  rejected allows that). Provisional numbers (eye ruling, 19 Oct): a face frame is shut when mean
  eyeBlink (L/R) >= `eyes_shut.eye_blink_min` 0.6 **and** mean eyeLookDown (L/R) < `eyes_shut.look_down_max` 0.3;
  `eyes_shut_max_s` = the longest continuous run of shut face frames (a frame without a face breaks it);
  `eyes_shut_flag` = that run is more than `eyes_shut.min_duration_s` 1.0 s. Lids lowered toward a counter score a
  high blink together with a high look-down, so they don't flag. The scorer's `eyes_shut_flag` and `eyes_shut_max_s`
  are used when present (`eyes_shut_from: scorer`; only `eyes_shut_max_s` -> flag = run > 1.0 s, `scorer_max_s`).
  Without them the app applies the same rule to the scorer's per-frame series `eye_blink_frames` /
  `eye_look_down_frames` with `fps` (`frames`); with neither, there is no flag. Each seed records `eyes_shut_flag`,
  `eyes_shut_max_s` and `eyes_shut_from`. If the kept seed is flagged, the take gets `needs_review`, the reason goes
  into `needs_review_reasons` (e.g. "eyes shut 1.40 s (eyes_shut_flag)") and the note says "Needs review: ...".
- **Start frame (warning only):** when the scorer reports the start frame's mean eyeBlink (`start_eye_blink`) and it
  is >= `start_frame.eye_blink_warn` 0.5, the record's `warnings` and the take note say "Eyes look closed in the start
  frame." It never rejects and never sets needs_review. No data -> no warning.
- **Per-line grin exemption (`grin_review_only`, `["l07"]`).** A listed line's grin becomes a review flag instead of
  a reject (the take gets `needs_review`; offset and open_frac still reject). The line id is found in the tools'
  order (`opensoul.lipsync.resolve_line_id`): (1) an explicit line field: the shot's `line_id` (Storyboard JSON,
  e.g. `"line_id": "l07"`; `7` / `L7` count as `l07`); (2) `lNN` in the take / shot name: the shot's beat name, then
  its id (`l` must start a token: `l04mcu` -> l04, `bowl07` -> nothing); (3) `lNN` in the wav name, checked at render
  time on the a2v stage's voice file. The app adds a last fallback the tools don't have: (4) the shot's 1-based
  position in the story (`l07` = the 7th shot). The app names its wav `voice_padded.wav`, so (3) only matters for
  callers that pass their own named wav. The plan's a2v stage and the record carry `line_id`, `line_id_from`
  (`line` | `name` | `wav` | `position`) and `grin_review_only`.
- **All 3 rejected:** keep the least bad (highest LSE-C), flag `needs_review`, and only then run the LatentSync
  fallback (the plan's LatentSync stage carries `only_if: best_of_all_rejected`; it is added only when LatentSync is
  installed and the face check allows it). If it runs, the take is LatentSync's output.
- **Scorer missing or failing:** no scorer configured -> only seed 1 is rendered (no extra GPU time), kept as before
  and flagged `scorer_failed`. A seed whose result has `lse_c: null` (or no numeric `lse_c`, or a scorer error) is
  `scorer_failed` and can't win; if no seed scores, seed 1 is kept, `scorer_failed`. A **missing field** makes that one
  rule `scorer_failed:<field>`: the seed isn't rejected by it but ranks after fully checked survivors, and the take
  keeps the flag.
- **Recorded:** every seed's metrics, reject reasons and undecided rules, the chosen seed and the flags go into the
  take's settings (`lipsync_best_of`, plus the `best_of` step) and into `<take>.best_of.json`, which carries
  `out_sha256` / `out_frames` of the kept file and is re-hashed (`opensoul.speak.restamp_take`) after any later rewrite
  (mux, era, LatentSync fallback).
- **Losing seeds are kept, not deleted:** each seed renders into `<take folder>/seeds/s<seed>/`; the chosen file is
  used in place and the others stay there for review.
- **Status line:** the take note says e.g. "Best of 3 takes: kept seed 79 (LSE-C 4.60)." or "... none passed the
  checks; kept the closest (...). Needs review." or "Best of 3 takes skipped: the lip-sync scorer isn't available".
- **Dry-run (Preview mode):** one stand-in render, no extra seeds and no scorer call; the note says best of 3 runs in
  Studio mode.

## Default articulation sentence (soft wording)

Talking shots get one sentence in the speaker's pronoun (pack `pronoun`, default *they*): "She speaks clearly, eyes
open: her lips open and close on every syllable, teeth visible on open vowels, calm neutral expression." (*He speaks ... his*,
*They speak ... their*). Same LSE-C as the older wording with fewer teeth and slightly less grin; it is not a grin
fix (the seed is). L1c adds one more sentence: "Head still, no tilt, eyes on Ren." The eyes go off-lens, onto the
listener in the scene (the one other character, or "Ren and Ivy" for several); "eyes on the camera" only when nobody
else is in the shot.

## Eyes in generated prompts

App-generated prompts (the shot plan, camera/action presets, the speaker sentence) never carry "a slow blink",
"blinks slowly" or "glances down": in the checked takes those gave shut eyes. `opensoul.lipsync.eyes_safe` drops
the phrase and adds one sentence from `eyes_sentence`: with the shot's object and listener, "Eyes open, a brief glance
down at the counter, then holds on the customer."; with a listener only, "Eyes open, holding on Ren."; otherwise
"Eyes open, holding on the camera." **Talk shots never get the glance:** they have no blink or glance-down beat, so
the object is ignored there and the eyes hold on the listener. The listener is the other character (or characters)
in the shot (Storyboard); with nobody else -> the camera. Shots have no object field yet, so `look_at` is only set by callers that pass it.
Story text that is held (the script's K/D lines, the daydream presets, the elf/ear text) is not edited; no shipped
pack template or preset carries the old phrases. No anti-grin wording yet.
