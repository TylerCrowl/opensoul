# Gate scores: Demo A talking takes (v7 era + prior)

> **Demo A** in this file is the retired first demo character (replaced by Lumi and Pixel on Oct 18 2026). Its files were removed from the tree; file names below were renamed to match.

Fetched Sat Oct 17 2026, ~17:25 ET from Spark `~/OpenSoul/v4/scores.txt` (186 lines).
Bar for contest cut: **ArcFace id mean ≥ 0.75 while talking** AND **SyncNet LS confidence ≥ 9**.
Voice: **Voice 1 (`cb_low`)** unchanged (canonical Demo A voice as of Oct 17).
Source columns: LatentSync SyncNet confidence (LS), ArcFace id mean/min vs Demo A sheet.

## Summary

| Question | Answer |
|---|---|
| Talking takes scored (with LS + id) | 164 |
| B-roll (no LS) | 8 (listed separately) |
| No-face / incomplete | 10 |
| **Meet bar (id≥0.75 AND SyncNet≥9)** | **1: `v4c_21` (SN 9.35, id 0.751)** |
| v7g/v7h meet bar | **None** |
| Newest scored line | `v7h_DcloseSg_82` (SN 8.95, id 0.664); v7h queue ALLDONE 17:37 ET (188 lines) |
| Openjutsu oj1 (IC-LoRA pose guide) | 2 takes scored, ALLDONE 17:55 ET; neither meets bar (see [oj1 verdict](#oj1-verdict-openjutsu-pose-guided-ic-lora-oct-17-1805-et)) |

### Best SyncNet-with-id / best id-with-SyncNet

| Metric | Take | SyncNet | id mean | Notes |
|---|---|---|---|---|
| **Best SyncNet among id≥0.70** | `v4c_21` | 9.35 | 0.751 | Also meets the full bar |
| **Best id among SyncNet≥9** | `v4c_21` | 9.35 | 0.751 | Same take |
| Best SyncNet overall | `v7_Aclose_53` | 10.31 | 0.668 | High lipsync, id short of 0.75 |
| Best id overall (talking) | `v7_Amed_54` | 7.26 | 0.792 | High identity, SyncNet short of 9 |
| Best v7g/h SyncNet | `v7g_BcloseG_72` | 9.49 | 0.668 | id short |
| Best v7g/h id | `v7g_CcloseG_73` | 6.96 | 0.741 | SyncNet short |
| Closest v7g/h dual | `v7g_BcloseG_71` | 9.08 | 0.710 | SN clears 9; id 0.04 short |

**Near misses** (id≥0.72 and SyncNet≥8.5, or id≥0.70 and SyncNet≥9):

| Take | SyncNet | id mean | Gap |
|---|---|---|---|
| `v4c_21` | 9.35 | 0.751 | **meets** |
| `cb_A_33` (Voice 1) | 8.70 | 0.726 | SN −0.30, id −0.024 |
| `b16_D_32` | 8.87 | 0.725 | SN −0.13, id −0.025 |
| `v7f_Bmed_66` | 9.09 | 0.712 | id −0.038 |
| `v7g_BcloseG_71` | 9.08 | 0.710 | id −0.040 |
| `v7e_Bmed_63` | 9.28 | 0.701 | id −0.049 |
| `v7g_Dwork_72` | 8.52 | 0.717 | SN −0.48, id −0.033 |

No false claim: only `v4c_21` currently clears both thresholds. No v7g/v7h take does yet.

## Ranked talking takes by SyncNet LS confidence (top 25)

| # | Take | SyncNet | id mean | id min | Flag |
|---|---|---|---|---|---|
| 1 | `v7_Aclose_53` | 10.31 | 0.668 | 0.628 | |
| 2 | `v4_11_q8` | 9.77 | 0.448 | 0.364 | |
| 3 | `v2_12_q8` | 9.57 | 0.627 | 0.437 | |
| 4 | `b16_B_32` | 9.57 | 0.616 | 0.436 | |
| 5 | `v7g_BcloseG_72` | 9.49 | 0.668 | 0.578 | |
| 6 | `v7_Aclose_51` | 9.45 | 0.651 | 0.593 | |
| 7 | `v7e_Bclose_64` | 9.45 | 0.632 | 0.581 | |
| 8 | `v7g_AcloseG_71` | 9.38 | 0.676 | 0.522 | |
| 9 | `v4c_21` | 9.35 | 0.751 | 0.662 | **MEETS BAR** |
| 10 | `v7h_BworkTg_81` | 9.33 | 0.626 | 0.529 | |
| 11 | `v7g_BcloseGs_73` | 9.31 | 0.684 | 0.615 | |
| 12 | `v7e_Bmed_63` | 9.28 | 0.701 | 0.616 | near-id |
| 13 | `v7h_DcloseSg_81` | 9.26 | 0.679 | 0.488 | |
| 14 | `v7e_Dclose_63` | 9.26 | 0.648 | 0.552 | |
| 15 | `v2_11_q8` | 9.25 | 0.599 | 0.523 | |
| 16 | `b16_B_31` | 9.25 | 0.587 | 0.364 | |
| 17 | `v7e_Bclose_63` | 9.24 | 0.674 | 0.634 | |
| 18 | `v7_Dclose_54` | 9.24 | 0.647 | 0.569 | |
| 19 | `v7_Bclose_52` | 9.16 | 0.675 | 0.656 | |
| 20 | `v7e_Aclose_64` | 9.16 | 0.622 | 0.563 | |
| 21 | `v7_Bclose_53` | 9.15 | 0.611 | 0.559 | |
| 22 | `v7h_BcloseSg_81` | 9.14 | 0.647 | 0.531 | |
| 23 | `v7_Bclose_55` | 9.12 | 0.641 | 0.599 | |
| 24 | `v7f_Bmed_66` | 9.09 | 0.712 | 0.615 | near-id |
| 25 | `v7g_BcloseG_71` | 9.08 | 0.710 | 0.593 | near-id |

## Ranked talking takes by ArcFace id mean (top 25)

| # | Take | id mean | SyncNet | id min | Flag |
|---|---|---|---|---|---|
| 1 | `v7_Amed_54` | 0.792 | 7.26 | 0.702 | |
| 2 | `v1c_22` | 0.770 | 7.33 | 0.722 | |
| 3 | `cb_D_34` | 0.761 | 7.87 | 0.683 | |
| 4 | `b16_C_32` | 0.761 | 7.72 | 0.648 | |
| 5 | `v7_Amed_56` | 0.760 | 7.66 | 0.703 | |
| 6 | `v4c_21` | 0.751 | 9.35 | 0.662 | **MEETS BAR** |
| 7 | `v7_Amed_57` | 0.749 | 7.60 | 0.655 | |
| 8 | `v7g_CcloseG_73` | 0.741 | 6.96 | 0.688 | |
| 9 | `v7_Cmed_55` | 0.736 | 7.30 | 0.678 | |
| 10 | `v7_Cmed_60` | 0.729 | 7.62 | 0.622 | |
| 11 | `cb_A_33` | 0.726 | 8.70 | 0.593 | near |
| 12 | `v7g_CcloseGs_72` | 0.726 | 7.52 | 0.645 | |
| 13 | `v7_Amed_51` | 0.726 | 7.41 | 0.632 | |
| 14 | `b16_D_32` | 0.725 | 8.87 | 0.557 | near |
| 15 | `v7g_CcloseG_76` | 0.725 | 7.16 | 0.656 | |
| 16 | `v7f_Cmed_68` | 0.724 | 6.93 | 0.624 | |
| 17 | `cb_C_34` | 0.720 | 6.69 | 0.642 | |
| 18 | `v7e_Cmed_63` | 0.720 | 6.46 | 0.631 | |
| 19 | `v7g_Dwork_72` | 0.717 | 8.52 | 0.628 | |
| 20 | `v7_Cmed_51` | 0.716 | 7.09 | 0.601 | |
| 21 | `v7_Amed_60` | 0.715 | 7.43 | 0.615 | |
| 22 | `v7_Amed_53` | 0.714 | 8.33 | 0.642 | |
| 23 | `v7f_Bmed_66` | 0.712 | 9.09 | 0.615 | |
| 24 | `v7g_BcloseG_71` | 0.710 | 9.08 | 0.593 | |
| 25 | `v7h_CcloseSg_84` | 0.710 | 6.86 | 0.678 | |

## v7g / v7h only (current batch)

32 talking takes scored. None meet id≥0.75 + SyncNet≥9.

### By SyncNet

| # | Take | SyncNet | id mean | id min |
|---|---|---|---|---|
| 1 | `v7g_BcloseG_72` | 9.49 | 0.668 | 0.578 |
| 2 | `v7g_AcloseG_71` | 9.38 | 0.676 | 0.522 |
| 3 | `v7h_BworkTg_81` | 9.33 | 0.626 | 0.529 |
| 4 | `v7g_BcloseGs_73` | 9.31 | 0.684 | 0.615 |
| 5 | `v7h_DcloseSg_81` | 9.26 | 0.679 | 0.488 |
| 6 | `v7h_BcloseSg_81` | 9.14 | 0.647 | 0.531 |
| 7 | `v7g_BcloseG_71` | 9.08 | 0.710 | 0.593 |
| 8 | `v7g_Bwork_72` | 9.04 | 0.692 | 0.558 |
| 9 | `v7g_Bwork_71` | 8.97 | 0.682 | 0.555 |
| 10 | `v7g_DcloseG_71` | 8.96 | 0.668 | 0.588 |
| 11 | `v7h_AcloseSg_81` | 8.95 | 0.623 | 0.494 |
| 12 | `v7h_DworkTg_81` | 8.53 | 0.636 | 0.566 |
| 13 | `v7g_Dwork_72` | 8.52 | 0.717 | 0.628 |
| 14 | `v7g_DcloseGs_73` | 8.41 | 0.679 | 0.554 |
| 15 | `v7g_Dwork_71` | 8.13 | 0.707 | 0.633 |
| 16 | `v7g_DcloseG_72` | 8.11 | 0.699 | 0.638 |
| 17 | `v7g_Awork_71` | 7.75 | 0.683 | 0.586 |
| 18 | `v7g_CcloseH_72` | 7.61 | 0.671 | 0.540 |
| 19 | `v7g_CcloseGs_74` | 7.53 | 0.663 | 0.571 |
| 20 | `v7g_CcloseGs_72` | 7.52 | 0.726 | 0.645 |
| 21 | `v7g_Cwork_71` | 7.49 | 0.709 | 0.620 |
| 22 | `v7h_CcloseSg_82` | 7.44 | 0.631 | 0.551 |
| 23 | `v7g_AcloseG_72` | 7.32 | 0.699 | 0.652 |
| 24 | `v7g_CcloseG_71` | 7.25 | 0.709 | 0.618 |
| 25 | `v7g_CcloseG_76` | 7.16 | 0.725 | 0.656 |
| 26 | `v7h_CcloseSg_83` | 7.14 | 0.701 | 0.647 |
| 27 | `v7g_CcloseG_75` | 7.00 | 0.706 | 0.605 |
| 28 | `v7h_CcloseSg_85` | 6.99 | 0.690 | 0.626 |
| 29 | `v7g_CcloseG_73` | 6.96 | 0.741 | 0.688 |
| 30 | `v7h_CcloseSg_84` | 6.86 | 0.710 | 0.678 |
| 31 | `v7h_CcloseS_81` | 6.77 | 0.693 | 0.650 |
| 32 | `v7g_CcloseH_71` | 6.63 | 0.689 | 0.630 |

### By id mean

| # | Take | id mean | SyncNet | id min |
|---|---|---|---|---|
| 1 | `v7g_CcloseG_73` | 0.741 | 6.96 | 0.688 |
| 2 | `v7g_CcloseGs_72` | 0.726 | 7.52 | 0.645 |
| 3 | `v7g_CcloseG_76` | 0.725 | 7.16 | 0.656 |
| 4 | `v7g_Dwork_72` | 0.717 | 8.52 | 0.628 |
| 5 | `v7g_BcloseG_71` | 0.710 | 9.08 | 0.593 |
| 6 | `v7h_CcloseSg_84` | 0.710 | 6.86 | 0.678 |
| 7 | `v7g_Cwork_71` | 0.709 | 7.49 | 0.620 |
| 8 | `v7g_CcloseG_71` | 0.709 | 7.25 | 0.618 |
| 9 | `v7g_Dwork_71` | 0.707 | 8.13 | 0.633 |
| 10 | `v7g_CcloseG_75` | 0.706 | 7.00 | 0.605 |
| 11 | `v7h_CcloseSg_83` | 0.701 | 7.14 | 0.647 |
| 12 | `v7g_DcloseG_72` | 0.699 | 8.11 | 0.638 |
| 13 | `v7g_AcloseG_72` | 0.699 | 7.32 | 0.652 |
| 14 | `v7h_CcloseS_81` | 0.693 | 6.77 | 0.650 |
| 15 | `v7g_Bwork_72` | 0.692 | 9.04 | 0.558 |
| 16 | `v7h_CcloseSg_85` | 0.690 | 6.99 | 0.626 |
| 17 | `v7g_CcloseH_71` | 0.689 | 6.63 | 0.630 |
| 18 | `v7g_BcloseGs_73` | 0.684 | 9.31 | 0.615 |
| 19 | `v7g_Awork_71` | 0.683 | 7.75 | 0.586 |
| 20 | `v7g_Bwork_71` | 0.682 | 8.97 | 0.555 |
| 21 | `v7h_DcloseSg_81` | 0.679 | 9.26 | 0.488 |
| 22 | `v7g_DcloseGs_73` | 0.679 | 8.41 | 0.554 |
| 23 | `v7g_AcloseG_71` | 0.676 | 9.38 | 0.522 |
| 24 | `v7g_CcloseH_72` | 0.671 | 7.61 | 0.540 |
| 25 | `v7g_BcloseG_72` | 0.668 | 9.49 | 0.578 |
| 26 | `v7g_DcloseG_71` | 0.668 | 8.96 | 0.588 |
| 27 | `v7g_CcloseGs_74` | 0.663 | 7.53 | 0.571 |
| 28 | `v7h_BcloseSg_81` | 0.647 | 9.14 | 0.531 |
| 29 | `v7h_DworkTg_81` | 0.636 | 8.53 | 0.566 |
| 30 | `v7h_CcloseSg_82` | 0.631 | 7.44 | 0.551 |
| 31 | `v7h_BworkTg_81` | 0.626 | 9.33 | 0.529 |
| 32 | `v7h_AcloseSg_81` | 0.623 | 8.95 | 0.494 |

## B-roll (no LatentSync; listed separately)

| Take | id mean | id min |
|---|---|---|
| `v7e_BRbucket_63` | 0.786 | 0.700 |
| `v7e_BRcam_63` | 0.687 | 0.640 |
| `v7e_BRcam_64` | 0.678 | 0.596 |
| `v7e_BRbucket_64` | 0.484 | 0.077 |
| `v7e_BRwalk_63` | 0.463 | 0.315 |
| `v7e_BRwalk_64` | 0.460 | 0.130 |
| `v7g_BRwalkS_72` | 0.298 | -0.027 |
| `v7g_BRwalkS_71` | 0.291 | 0.070 |

Highest b-roll id: `v7e_BRbucket_63` (0.786) — not a talking take, so it does not count toward the SyncNet+id gate.

## Voice 1 (`cb_low`) reference

Canonical Demo A voice remains Voice 1 / `cb_low` (unchanged). Chatterbox Voice 1 scored takes:

| Take | SyncNet | id mean |
|---|---|---|
| `cb_A_33` | 8.70 | 0.726 |
| `cb_B_34` | 8.67 | 0.636 |
| `cb_B_33` | 8.37 | 0.636 |
| `cb_D_33` | 8.09 | 0.690 |
| `cb_A_34` | 8.07 | 0.701 |
| `cb_D_34` | 7.87 | 0.761 |
| `cb_C_34` | 6.69 | 0.720 |

Best Voice 1 dual: `cb_A_33` (SN 8.70, id 0.726) — near bar; user previously rated lip-sync ~5/10 despite SyncNet 8.7, so SyncNet alone is not enough for cut approval.

## Method notes

- SyncNet values are **post-LatentSync** (LS column), not raw LTX A/V.
- ArcFace id is mean cosine vs Demo A photoreal sheet across sampled frames (`n` usually 8).
- Regenerated from live `scores.txt`; re-fetch after `v7h_*_82` and oj1 finish.


## v7h verdict: serious start still + end guide frame (added Oct 17, ~17:45 ET)

All 12 v7h takes are scored (v7h queue finished 17:37 ET, no render failures). Idea under test: start from a serious-expression still (`cS`/`cT`) and add an end guide frame (`LTXVAddGuide` at frame -1, strength 0.3-0.5) to hold identity and avoid the smile-lock ending.

| Set | Talking takes | Mean SyncNet (LS) | Mean id | Best id |
|---|---|---|---|---|
| v7g (smiling-ref close-up stills cG/cH, no guide) | 22 | 8.07 | 0.696 | 0.741 |
| v7h (serious still + end guide) | 12 | 8.23 | 0.663 | 0.710 |

| Take | SyncNet LS | id min | id mean |
|---|---|---|---|
| v7h_CcloseS_81 (no guide) | 6.77 | 0.650 | 0.693 |
| v7h_CcloseSg_82 | 7.44 | 0.551 | 0.631 |
| v7h_BcloseSg_81 | 9.14 | 0.531 | 0.647 |
| v7h_DcloseSg_81 | 9.26 | 0.488 | 0.679 |
| v7h_DworkTg_81 | 8.53 | 0.566 | 0.636 |
| v7h_CcloseSg_83 (guide 0.3) | 7.14 | 0.647 | 0.701 |
| v7h_CcloseSg_84 | 6.86 | 0.678 | 0.710 |
| v7h_CcloseSg_85 | 6.99 | 0.626 | 0.690 |
| v7h_AcloseSg_81 | 8.95 | 0.494 | 0.623 |
| v7h_BworkTg_81 | 9.33 | 0.529 | 0.626 |
| v7h_BcloseSg_82 | 9.40 | 0.541 | 0.656 |
| v7h_DcloseSg_82 | 8.95 | 0.608 | 0.664 |

**Verdict: drop it.** The serious start + end guide cost about 0.03 mean identity versus v7g with no real SyncNet gain, and no v7h take clears the dual bar. Part of the drop is that serious faces score lower against the smiling `ref_00` anchor, so a serious anchor may be worth adding to the gate later, but by the current gate the v7g setup (still `cG`, no guide) stays the baseline. Next identity lever is the Openjutsu pose-guided IC-LoRA test (oj1), then by-eye review of the closest v7g takes.

## oj1 verdict: Openjutsu pose-guided IC-LoRA (Oct 17, 18:05 ET)

Two takes using the LTX-2.3 Union Control IC-LoRA with a DWPose guide made from the synthetic Demo A take `v7g_Bwork_72` (Voice 1 `cb_low`, start still cE). Scores from Spark `scores.txt` (LatentSync 2.0 + ArcFace vs `ref_00`, n=8 frames):

| Take | Guide | SyncNet (after LS) | id min | id mean |
|---|---|---|---|---|
| `oj1_BworkIC_91` | pose + face dots | 8.95 | 0.559 | 0.678 |
| `oj1_BworkICnf_92` | pose, no face dots | 8.48 | 0.524 | 0.681 |
| `v7g_Bwork_72` (driver, for comparison) | none | 9.04 | n/a | 0.692 |

**Verdict: not an identity lever.** The pose guide copies the driver's motion well (LTX render ~245 s, no custom nodes), but identity lands slightly below the unguided v7g baseline (0.678-0.681 vs 0.692-0.696) and neither take clears SyncNet 9 + id 0.75. Openjutsu stays a possible "re-perform" feature for the demo (motion transfer works), not a fix for face match. Baseline stays v7g (`cG`, no guide).

## v10s / v10t: prompt vs. identity (Oct 17, 8:20 PM ET)

All takes speak Voice 1 (`cb_low`). Scores from Spark `scores.txt` (LatentSync 2.0, then ArcFace vs `ref_00`; n = frames with a detected face). Bar: SyncNet ≥ 9 and id mean ≥ 0.75.

**v10s**: serious prompt (the v7g baseline), seed sweep on still `cG`, plus still `cE`:

| Take | Setup | SyncNet (after LS) | id min | id mean |
|---|---|---|---|---|
| `v10s_BcloseG_74` | cG, serious | 8.81 | 0.615 | 0.695 |
| `v10s_BcloseG_75` | cG, serious | 8.27 | 0.561 | 0.644 |
| `v10s_BcloseG_76` | cG, serious | 8.56 | 0.614 | 0.690 |
| `v10s_BcloseE_71` | cE, serious | **9.61** | 0.619 | 0.690 |
| `v10s_BcloseE_72` | cE, serious | 9.12 | 0.555 | 0.680 |
| `v10s_BdollyE_21` | cE, serious, dolly-in | n/a | n/a | no face (dolly ends too tight) |

**v10t**: the dry-smirk prompt from `v4c_21` (its only dual clear was on the old pre-Voice-1 audio), still `cE`, dolly-in LoRA framed to stop at head-and-shoulders:

| Take | SyncNet (after LS) | id min | id mean |
|---|---|---|---|
| `v10t_DdollyE_21` | 8.27 | 0.703 | **0.790** |
| `v10t_DdollyE_22` | 8.22 | 0.695 | **0.766** |
| `v10t_DdollyE_23` | 8.55 | 0.712 | **0.797** |
| `v10t_DdollyE_24` | 8.22 | 0.756 | **0.801** |
| `v10t_DstatE_21` (static, no LoRA) | 8.52 | 0.692 | **0.760** |
| `v10t_DstatE_22` (static, no LoRA) | 8.38 | 0.679 | **0.774** |

**Finding:** the prompt is the identity lever. Every serious-prompt take sits at id 0.64-0.70; all four dry-smirk Voice 1 takes clear 0.75 (one holds 0.756 even at its worst frame). The cost is lip-sync: LatentSync 2.0 lands at 8.2-8.55 on these, short of 9. Next: a LatentSync re-pass sweep (guidance 1.5/2.5, seeds 7/42/1247, 50 steps) on the id ≥ 0.75 takes, then a by-eye check, since SyncNet alone overrates lips (an 8.7 take was judged about 5/10). The two static, no-LoRA dry-smirk takes also clear 0.75 (0.760, 0.774), so 6/6 dry-smirk takes hold the face with or without the dolly LoRA; SyncNet stays 8.2-8.55 across all six. v10t finished 20:31 ET.

## LatentSync re-pass sweep (lsr, closed) — Oct 17 2026

Same LTX takes as v10t, LatentSync re-run at 50 steps with deepcache, only guidance and seed changed. Baseline is the v10t row (guidance 2.0, seed 1247). Scored with the same SyncNet + ArcFace scripts. All 24 variants scored (done 10:55 PM ET), plus a guidance 3.0 follow-up on the two takes with the most face-match headroom (done 11:13 PM ET).

| Take | g2.0 s1247 (baseline) SN / id | g1.5 s1247 | g2.5 s1247 | g2.0 s7 | g2.0 s42 |
|---|---|---|---|---|---|
| `v10t_DdollyE_24` | 8.22 / 0.801 | 6.88 / 0.812 | 8.52 / 0.781 | 8.31 / 0.808 | 8.39 / 0.801 |
| `v10t_DdollyE_23` | 8.55 / 0.797 | 7.60 / 0.807 | 8.45 / 0.779 | 8.48 / 0.804 | 8.33 / 0.784 |
| `v10t_DdollyE_21` | 8.27 / 0.790 | 7.05 / 0.808 | 8.52 / 0.762 | 8.33 / 0.795 | 8.19 / 0.790 |
| `v10t_DstatE_22` | 8.38 / 0.774 | 6.74 / 0.785 | **8.84** / 0.757 | 8.19 / 0.779 | 8.27 / 0.779 |
| `v10t_DdollyE_22` | 8.22 / 0.766 | 7.25 / 0.775 | 8.46 / 0.749 | 8.44 / 0.775 | 8.24 / 0.767 |
| `v10t_DstatE_21` | 8.52 / 0.760 | 6.94 / 0.772 | 8.87 / 0.745 | 8.41 / 0.767 | 8.32 / 0.763 |

**Finding:** guidance is the lip-sync lever and seed is noise. Guidance 1.5 costs about 1.3 SyncNet points; guidance 2.5 adds about +0.2 on average (−0.10 to +0.46) but lowers face match by about 0.02. Changing only the seed at guidance 2.0 moves SyncNet by about ±0.15. `DdollyE_22` fits the same pattern (g2.5 +0.24 SyncNet, but its face match drops to 0.749, just under the bar). No variant clears both bars yet (SyncNet 9+ and id 0.75+); the closest is `DstatE_22` g2.5 at 8.84 / 0.757, which barely holds the face. Next, if the remaining rows don't clear: guidance 3.0 on the takes with the most face-match headroom (`DdollyE_24`, `DdollyE_23`, id ≈ 0.80), then a by-eye check of anything that clears.

Guidance 3.0 follow-up (50 steps, SN / id mean):

| Take | g3.0 s1247 | g3.0 s7 |
|---|---|---|
| `v10t_DdollyE_24` | 8.54 / 0.763 | 8.47 / 0.767 |
| `v10t_DdollyE_23` | 8.15 / 0.759 | 8.14 / 0.773 |

Guidance 3.0 buys nothing over 2.5 (SyncNet flat or lower) and costs another ~0.02-0.04 face match. `DstatE_21` g2.5 hits the sweep's top SyncNet (8.87) but drops to 0.745 id. **Result: no variant of 32 clears SyncNet 9 + id 0.75.** By eye we rated these LatentSync re-pass takes about 3/10 for lip-sync (face match acceptable) on Oct 17 at 11 PM ET, so SyncNet 8.4-8.9 does not mean good lips for us. LatentSync tuning is closed; Demo A tuning is capped under the approved plan, and the next lip-sync path is LTX joint audio+video (a2v) or InfiniteTalk, judged by eye.
