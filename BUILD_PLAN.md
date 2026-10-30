# OpenSoul 15-day build plan → Fri Oct 30, 2026 9:00 AM PT (12:00 PM ET)

Today: **Thu Oct 15, 2026**. Working days ≈ Oct 15–29; buffer Oct 29 evening; hard stop submission morning Oct 30 PT.

| Day | Date | Milestone | Exit criteria |
|-----|------|-----------|---------------|
| 0 | Oct 15 | Scaffold + research | Repo scaffolded, CPU tests green, model stack doc, open questions listed |
| 1 | Oct 16 | GPU host access | GPU host reachable; `nvidia-smi` OK; ComfyUI hello-image (Z-Image or SD) |
| 2 | Oct 17 | Comfy SDK glue | `comfy-api-proxy` + Gradio still dry-run→live probe; SDK run of a tiny workflow |
| 3 | Oct 18 | Qwen Edit stills | Official Qwen-Image-Edit-2511 template works; export API JSON replaces stub `02_` |
| 4 | Oct 19 | Character builder | Turnaround/expression sheet from 1–3 refs; pack save/load in UI |
| 5 | Oct 20 | Consistency gate | CLIP optional backend calibrated; reject loop in pipeline; gallery shows only passes |
| 6 | Oct 21 | Lumi + Pixel demos | Lumi sheet → pack → 4 accepted stills; Pixel path fully OSS-clean |
| 7 | Oct 22 | TTS | Kokoro (or Piper) produces clean WAV from script; wire workflow/helper |
| 8 | Oct 23 | LTX I2V | LTX-2.5 distilled I2V 9:16 from still; confirm open weights (no partner node) |
| 9 | Oct 24 | Lip-sync + mux | MuseTalk (or LatentSync) + captions + MP4 export |
| 10 | Oct 25 | One-command polish | `setup_spark.sh` end-to-end on clean shell; README “5 commands to demo” |
| 11 | Oct 26 | Example outputs | Freeze gallery: sheet, stills, MP4; record paths for README |
| 12 | Oct 27 | Demo video ≤2 min | Capture UI walkthrough + architecture one-liner; no music copyright issues |
| 13 | Oct 28 | Repo public-ready | LICENSE/ASSETS_LICENSE, privacy scrub, GitHub remote **after sign-off** |
| 14 | Oct 29 | Submission pack | Form fields drafted; social post draft `#OpenSourceHiggsfield`; optional live link |
| 15 | Oct 30 AM | Submit | Submitted by a person before **9:00 AM PT**; agents do not submit |

## Parallel tracks

- **Most Viral**: delightful Gradio UX, one-click Lumi demo, shareable vertical clip.
- **Best Overall**: reliability + docs + SDK clarity.
- **Open Weights Only**: keep Router/Partner Nodes out of critical path (lint checklist in PR).
- **LTX bonus**: LTX remains core I2V; document in demo video.

## Risk buffer

If LTX fails on Spark ARM64: fall back to **Wan2.2 TI2V-5B** for Open Weights / Overall / Viral; keep an LTX attempt branch for bonus if time remains.
