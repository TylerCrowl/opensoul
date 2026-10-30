# Lumi – Night Shift v8: progress (Oct 18, 4:35 PM EDT)

Done
- SHOT01_doodling_v8.mp4 (7.5 s, real speed, 0 % repeated frames): g5a take s41 (s42 slumps and hides her face), first 4.5 s,
  background locked to the clip's own first frame; then the book insert (still + slow push until the i01 clip lands).
- CONTINUITY_after_v8.jpg: master plate + 11 start frames, all on the same plate (v8b).
- Lumi talking takes, LTX a2v -> LatentSync 50 steps, SyncNet confidence (raw -> ls1.5 -> ls2.0):
  l04_verdict s71 0.49 -> 0.89 -> 1.10 (weak, mouth nearly still; small face), l07_real s75 4.83 -> 6.78 -> 7.12,
  l08_bye s77 0.75 -> 6.19 -> 6.70. Pick g2.0. l05_three s73/s74 rejected (cut to a new angle mid-clip) -> retake in g5d.
- LatentSync is ~10-20 min per take on the Spark; run it on picked takes only.
- Cut tools: production/v8/cut/{gen_edl.py,build.py,picks.json}; placeholder full cut builds at 93.6 s.

Queued on the Spark: f9 (daydream panels) -> g5c (couple a2v + silent shots) -> g5d (l05 retake + LS) -> g5e (LS on couple takes).

## Update 4:50 PM EDT
- Start frames rebuilt (production/v8/plates/up9, Spark v8/locked9): ear tips hidden by script (earhide.py:
  skin-coloured pixels right of the face replaced by the empty stage plate), can pasted at real size (0.105 H, about
  hand height; was 0.2 H), couple scaled 0.9–1.15 and anchored on the counter line so they stand at the counter
  (compose.py: couple matte opened + small blobs dropped to stop background slabs). Lumi's lines now start from a
  medium close-up crop of the verdict frame (the oversized can is out of frame); the pour is a close-up crop without the can.
- Book insert page redrawn (f11 i02_page s361): warm colored-pencil adventure of the three, matching the f9 panels.
  Daydream picks: d1_bridge s332, d2_camp s334, d3_dragon s335. Known: Mio's hair reads grey under her hood in the panels.
- First retake on the new frames: l04_verdict s171 MCU, background drift 3.6 (was 21), ghost 0.67 (was 1.64).
- Queue: g6a (18 LTX a2v takes ~5:35 PM, then LatentSync g2.0 + SyncNet on 14 talks, ~12 min each).
