# Audit AUDIT_v8_20261018_1659 -> fix tracker (executor)
| Item | Status | How |
|---|---|---|
| One locked plate | DONE | setbible/MASTER_PLATE_konbini.png = stage/master_konbini_v8b.png; cat plates in setbible/archive; SET_BIBLE.md updated (no cat, ears hidden, hands attached, eyelines); app location already = v8b (byte-identical) |
| SHOT01 floating pen hand / ear / dark grade / v8 plate | QUEUED f12 s01_draw (from v8b master: chin on LEFT hand, RIGHT forearm on counter drawing) -> g6b LTX s01_draw | then grade-match to plate in post |
| SHOT01 insert (other desk, neon tube, screen direction, pasted hand, wrong page) | QUEUED f12 i05_ots (over-shoulder, light-grey counter, arm attached, half-drawn colored-pencil page, lavender Mio) -> g6b LTX | |
| Camera creep (SHOT01, l07) | post: lock_video to own first frame + trim; a2v locked prompts | |
| Duplicate frame ~1/s in TALK | DONE (tool) | v8/cut/dedup25.py drops LatentSync's 24->25 repeat, writes true 24 fps (verified 0 near-dupes on l07) |
| Ears in talk clips | new MCU start frame ear-free (audit pass on 04 MCU) | |
| Can (fat maroon, 'arvd', scale morph) | Lumi lines framed MCU without can; c03 Ren holds a slim steel can (f12 k03, can prop ref); counter can 0.105 H everywhere | single prop can_prop_s342 |
| Black-haired frozen customer | g6b retakes 'alone in frame'; fallback striplock.py (right strip held to frame 0) | |
| Lumi into camera | f12 L_* poses re-edited, eyes to the customers | |
| Couple pasted / eyelines / hand on waist (08 sip) / 3rd forearm (07) / halo + shard (08 exit) / white blob (02) | f12 k* re-poses + L_fold re-pose; recompose with background-only grade match + feather 25 | |
| Glyphs '6' '01' kana banner | MCU decluttered; all frames rebuilt on v8b | |
| l04 mouth closed / l07 over-articulated | g6b retakes + LatentSync g2.0 and g1.5; pick by eye; l07 prompt deadpan, no grin | |
| Daydream: Mio lavender, tail, Ren design, off-brief | f12 d4_road (script beat: sunset road to glowing shop, cups raised) + d1_lav/d2_lav redraws with explicit designs, no animals; d3 whale dropped | text-only style (the style_ref image is the reference look; not passed in to avoid copying its layout) |
| stage_konbini_sheet.jpg (v1) | moved to production/takes/_superseded; v2 sheet to be re-checked | |
