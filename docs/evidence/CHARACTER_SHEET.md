# Character Sheet: real runs (Demo A, Sat Oct 17 2026)

> **Demo A** in this file is the retired first demo character (replaced by Lumi and Pixel on Oct 18 2026). Its files were removed from the tree; file names below were renamed to match.

**Result:** sheet v1 of Demo A (image removed from the tree on Oct 18 2026; kept outside the repo) (2576×2668, 3×2 grid on #D8D8D8).

- **Input:** one photo, `production/demoa_photoreal_ref/ref_00` (the canonical Demo A anchor, an AI-generated original character).
- **Path:** `scripts/sheet_run.py` → `opensoul.character_sheet.make_character_sheet` → `opensoul.comfy_client.run_workflow_file` (comfy-sdk 0.5.0) → comfy-api-proxy :8189 → ComfyUI :8188 on the DGX Spark. Workflow `workflows/07_character_sheet_api.json`: Qwen-Image-Edit-2511 **bf16** + Lightning 4-step LoRA, 4 steps, CFG 1, 832×1248 for full-body views and 1024×1024 for close-ups. The jobs queued behind the running Demo A LTX renders; nothing was cancelled or reordered.
- **Time:** about 50 s of GPU time per view once a job reached the head of the queue (first view about 7 min including the model swap). Min MemAvailable seen during the sheet jobs: about 44 GB.
- **Identity gate:** patch backend, threshold 0.70, one retry. The live :8188 ComfyUI does not load the OpenSoul node pack, and restarting it would interrupt the Demo A renders, so this run used `OPENSOUL_SHEET_GATE=local`. That mode removes node 20 and runs the node's own code (`patch_embedding_array` + `gate_report` from `custom_nodes/opensoul_nodes/nodes.py`) in-app, giving the same score. The default `graph` mode (gate node in the workflow) is covered by the CPU tests only.
- **Assembly:** final grid and Soul Pack built with `sheet_run.py --reuse-from` (same code path, no GPU), from these renders: full-body views from run v2, close-ups from run v3.

## Runs

| Run | What changed | Outcome |
|---|---|---|
| v1 | first prompts, 832×1248 for every view | Full-body views good. **The close-ups came out full-body**, yet the patch gate passed them (0.73 to 0.74). Discarded; my own two queued retries were removed from the queue. |
| v2 | close-up prompts reworded | Full-body views good. Close-ups still broken (oversized head on a small body, legs in the back view); patch gate 0.75 to 0.82. Kept the full-body views. full_front retried once (0.693 → 0.697, both below 0.70; best kept). |
| v3 | close-ups: **1024×1024 latent**, lower-body terms dropped from the look description (`close_drop_terms`), crop instruction repeated at the end | All three close-ups correctly framed. |

## Scores per view

ArcFace = `scripts/idsim.py` (insightface buffalo_l, cosine of the largest face). For reference, Demo A's own reference set scores 0.69–0.75 against ref_00 (docs/SOUL_ID.md). Patch = the OpenSoul gate score against ref_00.

| View | Patch gate (thr 0.70) | Tries | ArcFace vs ref_00 | ref_01 | ref_02 | ref_03 | ref_04 | mean of 5 |
|---|---|---|---|---|---|---|---|---|
| Full body · front | 0.697 (below thr, best of 2 kept) | 2 | 0.653 | 0.530 | 0.468 | 0.455 | 0.290 | 0.479 |
| Full body · side | 0.767 ✓ | 1 | 0.450 | 0.398 | 0.392 | 0.498 | 0.311 | 0.410 |
| Full body · back | 0.780 ✓ | 1 | no face (expected) | – | – | – | – | – |
| Close-up · front | 0.846 ✓ | 1 | **0.697** | 0.627 | 0.533 | 0.473 | 0.533 | 0.573 |
| Close-up · side | 0.773 ✓ | 1 | 0.609 | 0.541 | 0.660 | 0.539 | 0.523 | 0.574 |
| Close-up · back | 0.830 ✓ | 1 | no face (expected) | – | – | – | – | – |

Close-up front against the anchor (0.697) is inside the range of the hand-made reference set. Full-body faces are small, about 100 px, so ArcFace scores lower on them.

## Caveats (seen by eye)

- **Back views:** Demo A wears the cap backwards. The close-up back shows the cap's rear strap instead of the brim, and the full-body back shows a plain crown, so cap orientation is not consistent from behind. The side views get it right (brim at the back).
- Both close-ups show an earbud in both ears; the reference has one.
- The full-body side faces right and the close-up side faces left. Both are true profiles.
- **The patch gate overrates.** It is dominated by background and layout: a flat gray image scores 0.68 against ref_00. It passed the wrong-framing close-ups in v1 and v2, and it failed a good full_front (ArcFace 0.653). Treat it as a coarse catch for catastrophic failures. Use ArcFace (`06b`, non-commercial weights) or by-eye review for real identity checks.

# Auto-fix run: Demo A sheet v2 (Sat Oct 17 2026, 12:32–12:54 EDT)

**Result:** sheet v2 of Demo A (image removed from the tree on Oct 18 2026; kept outside the repo). Produced in one pass by the auto-fix loop (`scripts/sheet_run.py … --gate local`, defaults otherwise: VLM checks on, up to 2 corrective retries per view). No hand-picking and no `--reuse-from`.

## What the auto-fix step does

1. **Read the reference once.** Qwen3-VL-8B-Instruct (Apache-2.0, open weights, local) extracts a JSON attribute checklist from the reference photo: headwear and its orientation, glasses, sunglasses on the cap, earbuds/earrings per ear, facial hair, hair, clothing layers and colours, bottoms, footwear.
2. **Check every view.** View-aware yes/no questions (`opensoul/sheet_check.py: checks_for_view`). Examples: a backward cap should show its brim from behind and not from the front; inner layers are only checked from the front; ears are not counted in profile; full-body views need shoes in frame; close-ups must not show legs; side views must face the LEFT edge; back views must not show a face. Identity is checked alongside: ArcFace where a face is visible (thresholds close 0.50 / full 0.40), the patch gate otherwise.
3. **Fix.** Each failed check carries a correction sentence. Failed views are re-rendered with `CORRECTIONS (the previous attempt got these wrong): …` appended to the prompt and a new seed, up to 2 retries. The best try is kept: fewest failed checks first, then identity score.
4. **Flag.** A view that still fails keeps its best try and gets a note such as "Full body · back: cap orientation, sunglasses on cap may be wrong. Tap Regenerate to try again." The UI shows ✓/✗ per check, the face score, "fixed in N tries", and a per-view **Regenerate** button (`POST /api/sheet/{job}/regenerate/{view}`). Regenerate reuses the stored corrections and never replaces a view with a worse try.

**Memory:** the VLM is ~17.5 GB in bf16 and loads on demand. It waits until MemAvailable − 17.5 GB ≥ 12 GB (`OPENSOUL_MIN_FREE_GB`) and is freed after the checklist and after every check round, so it never sits beside the Qwen-Image-Edit renders. Load takes ~2 min (134.5 s and 120.8 s in this run); checks take ~6 s per view. `OPENSOUL_VLM_KEEP=auto|always` keeps it resident when there is ≥ 50 GB headroom. That option was added after this run, so this run reloaded each round. Min MemAvailable seen: ~29 GB, while the VLM was loading next to a Demo A job; memguard never fired.

## This run

| Round | Views | Result |
|---|---|---|
| 0 (6 renders) | all | 4 of 6 pass. full_front ✗ earbuds in both ears; full_back ✗ cap orientation, sunglasses; close_back ✗ cap orientation |
| 1 (3 fixes) | full_front, full_back, close_back | **full_front fixed** (one earbud, 10/10). Both back views still ✗ |
| 2 (2 fixes) | full_back, close_back | still ✗; flagged for Regenerate |

| View | Checks | Tries | Patch | ArcFace ref_00 | ref_01 | ref_02 | ref_03 | ref_04 | mean of 5 |
|---|---|---|---|---|---|---|---|---|---|
| Full body · front | 10/10 ✓ (auto-fixed) | 2 | 0.709 | 0.648 | 0.543 | 0.469 | 0.447 | 0.315 | 0.484 |
| Full body · side | 9/9 ✓ | 1 | 0.762 | 0.461 | 0.388 | 0.419 | 0.499 | 0.320 | 0.417 |
| Full body · back | 5/7 ⚑ cap orientation, sunglasses | 3 | 0.782 | no face | – | – | – | – | – |
| Close-up · front | 10/10 ✓ | 1 | 0.845 | 0.688 | 0.638 | 0.548 | 0.480 | 0.515 | 0.574 |
| Close-up · side | 9/9 ✓ | 1 | 0.774 | 0.578 | 0.513 | 0.638 | 0.532 | 0.518 | 0.556 |
| Close-up · back | 6/7 ⚑ cap orientation | 3 | 0.834 | no face | – | – | – | – | – |

**Checked by eye:** every pass and every flag is correct. Compared with v1:
- The earbud count is now right (one, on the same side as the reference).
- Both side views face left, and the cap brim points back in both.
- The close-ups are real chest-up crops.

The back views still show the cap's rear strap where the backward cap's brim should be. The VLM caught this on all 3 tries, and the corrective prompt did not move Qwen-Image-Edit, so the sheet flags those two views instead of passing them silently. The remaining gap is a model limitation, not a gap in the checker.

**Caveats:** "left/right ear" from a selfie is ambiguous. The checklist uses image sides, and the "both ears?" check is the robust one. ArcFace (buffalo_l) weights are non-commercial; without them identity falls back to the patch gate, which overrates (see above).

# Back-view fix: Demo A sheet v3 (Sat Oct 17 2026, 13:15–13:58 EDT)

**Result:** sheet v3 of Demo A (image removed from the tree on Oct 18 2026; kept outside the repo) (full size: `production/demoa_sheet_v3.jpg`, 2576×2668). It keeps the four v2 views that passed and swaps in two new back views; in both, the cap's visor now points at the camera over the back of the neck.

In v2, corrective prompt lines ("the cap is worn BACKWARDS…") never changed the back views, so this run tried two other strategies through `scripts/sheet_run.py --regenerate full_back,close_back --strategy side|wording --tries 3` (comfy-sdk → :8189, queued behind the Demo A jobs, nothing cancelled):

- **side**: workflow `07b_character_sheet_back_from_side_api.json`. Picture 1 is the sheet's already-correct side view (close_side for close_back, full_side for full_back) and picture 2 is the reference. The prompt is "rotate the camera 90 degrees to directly behind them…".
- **wording**: workflow 07 with a prompt that avoids "backwards cap": "the cap's visor points toward the viewer, the cap sitting on the back of the head: the visor (bill) covers the back of the neck and points at the camera. The visor is visible; no strap or closure is visible."

| Try | Strategy | By eye | Qwen3-VL "strap visible?" |
|---|---|---|---|
| close_back try70 | side | ✅ visor at the back, no strap (**kept**) | no ✓ |
| close_back try71 | side | ✅ visor at the back | no ✓ |
| close_back try72 | side | ✗ strap | yes ✓ |
| close_back try140 | wording | ✗ strap above a visor | yes ✓ |
| full_back try70–72 | side | ✗ strap/opening on all 3 | yes, no, yes |
| full_back try140 | wording | ✅ visor covers the neck, sunglasses on top (**kept**) | no ✓ |
| full_back try141–142 | wording | ✗ strap | yes ✓ |
| v2 back tries (6) | corrective prompt | ✗ strap | yes on all 6 ✓ |

**Strategy findings:**
- Rotating from the side view fixed the close-up (2 of 3 tries) but not the full body (0 of 3).
- The visor wording fixed the full body (1 of 3) but not the close-up.

**What changed in the auto-fix:**
- **Back-view fallback.** It is now part of auto-fix (preset `back_fallback`, `_Ctx.fallback`). When a back view fails its checks twice, the next try uses the per-framing strategy order: close-up = side, side, wording; full body = wording, wording, side. If the side view itself did not pass, it falls back to the wording. Fixes for non-headwear checks (e.g. "only ONE earbud") are carried into the fallback prompt. The Regenerate button and `--regenerate` use the same path.
- **Back-view cap check.** The old question, "does the brim point toward the camera?", was unreliable from behind: it said no to correct visors (full_back try140, close_back try71) and yes to a strap drawn above a visor (close_back try140). It is replaced by `cap_strap` ("Is the cap's adjustable strap or the strap opening visible?"). On every back try reviewed by eye in this run, the strap answer agreed with that review. `scripts/sheet_recheck.py` re-ran the checks on all 16 back tries with a single VLM load.
- **Best-try ranking.** Ranking now weights failures (`CHECK_WEIGHTS`): a wrong cap counts 2 and missed sunglasses in a full-body view count 0.5. Under plain failure counts the run's own picks were full_back try141 and close_back try140, both wrong by eye. With the weights, the ranking prefers full_back try140 over try141. The v3 back views were chosen by eye.
- **VLM memory.** The VLM is freed after every round by default (`OPENSOUL_VLM_KEEP=never`). With it kept resident during this run, an LTX job dropped MemAvailable to ~27 GB (still ≥ 12 GB, and memguard never fired).

**v3 status per view:**
- Full body front, full body side, close-up front and close-up side: unchanged from v2; all checks pass, face 0.65 / 0.46 / 0.69 / 0.58 vs ref_00.
- Full body · back: cap correct by eye. Qwen3-VL still answers no to "sunglasses on the cap" (they are a few pixels at this size and visible by eye).
- Close-up · back: cap correct. **Still flagged: an earbud in both ears** (the reference has one). That was the try's only failed check; it was not re-rendered, because the per-view try budget was used up.

## v4: one Regenerate on the close-up back (Sat Oct 17 2026, 14:07–14:19 EDT)

`scripts/sheet_run.py --out out_bk1 --regenerate close_back --strategy side --tries 2`. This is the app's own Regenerate path: it rotates from the close-up side view, and the "only ONE earbud" fix is carried in from earlier failed tries.

| Try | Qwen3-VL | By eye |
|---|---|---|
| close_back try160 | 6/7 (sunglasses not seen) | visor right, no strap, one earbud |
| close_back try161 | **7/7, passed** (kept by the app) | visor right, no strap, sunglasses on top, no second earbud |

**Result:** sheet v4 of Demo A (image removed from the tree on Oct 18 2026; kept outside the repo) (full size: `production/demoa_sheet_v4.jpg`). Same as v3 except the close-up back is try161. All six views now show the cap the right way round, and no view shows a second earbud.

**Remaining nits:**
- try161 shows no earbud at all from behind.
- For full_back try140, the VLM still answers no to "sunglasses on the cap" (they are visible by eye).
- Earbud side is ambiguous on a selfie reference.

# Lumi: a new character from text only (Sat Oct 17 2026, 20:29–21:24 EDT)

**Result:** [assets/lumi/lumi_character_sheet_v1.jpg](../../assets/lumi/lumi_character_sheet_v1.jpg). Lumi is an original elf barista (see `assets/lumi/`). No photo was used at any stage. *(Note, Oct 18 2026: this is the v1 sheet. The current v3 look does not come from this run; it descends from a concept image made with a closed (non-open) image generator, see `assets/lumi/README.md`.)*

**Text-only start (new):** `sheet_run.py --from-text --ref-only --ref-seeds 7,8,9,10 --subject "<description>"` uses workflow `07t_character_from_text_api.json`, which is the sheet's own Qwen-Image-Edit-2511 bf16 + Lightning with no input image, so no extra model is needed. It took 15–60 s per candidate. Seed 8 was picked by eye. The sheet was then run from that image the normal way.

| Run | What happened |
|---|---|
| out_v1 | 6 renders at ~30 s each, after a 95 s VLM load. **Every view passed every check on the first try**, including the new pointed-ears and hair-colour checks. ArcFace: full_front 0.92, full_side 0.49, close_front 0.85, close_side 0.58. **By eye:** all three close-ups were waist-up, and the checklist had no apron. |
| out_v2 | `--reuse-from out_v1 --only close_*`, with the new checks (apron in the checklist, close-up "waist visible?"). The full-body views were re-checked and passed (11/11, 9/9, 8/8). The waist check failed all 3 close-ups on every try: 0/1/2 with the corrective prompt, then 70/71 via `--regenerate --tries 2` starting from a head crop of the reference. **No corrective prompt or reference crop changed the framing.** |
| chest crop | `--regenerate close_front,close_side,close_back --tries 0` runs the new last auto-fix step only. It cuts the best try to chest-up (`close_post_crop`) and checks again. close_front 10/10 (face 0.94), close_side 8/8 (0.62). close_back failed only "apron visible", which is correct from behind at chest-up, so that check was removed for close-up backs. |

**App fixes from this run (all with tests):**
- The checklist now lists every upper-body layer, outermost first and including aprons; before, it skipped Lumi's apron.
- New checks: pointed ears (weight 2), hair colour, and "close-up: waist visible?".
- Chest-crop is the last step for close-ups that fail only on framing.
- Reused views are checked in one VLM round. Before, there was one VLM load per reused view, which cost ~6.5 min here.
- Aprons and overalls are not expected in close-up back views.

**Memory:** MemAvailable minimum 48.5 GB during the reference renders and 66.8 GB during out_v1, with the GPU otherwise idle. During out_v2 it fell to **23.2 GB**: the pt1b hold had been released early, and pt1b's LTX jobs ran between the sheet's jobs while the VLM (17.5 GB) loaded beside them. That is below the 30 GB runner rule, though memguard (4 GB) never fired. The regenerate step's minimum was 44.2 GB.
