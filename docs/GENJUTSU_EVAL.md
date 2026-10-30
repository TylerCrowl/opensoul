# Evaluation: Higgsfield Genjutsu UGC clip (shared tweet)

Evaluated Sat Oct 17 2026, 4:50 PM ET. Source: [post by @demonugc](https://x.com/demonugc/status/2111489255100838054)
(posted 12:07 PM ET Oct 17; about 4.8K views, 91 likes, 90 bookmarks at evaluation time). The clip and image were
inspected locally for analysis only and are **not** stored in this repo (third-party content).

## What the clip actually is (verified from the frames)
- 15 s, 960x854, 24 fps, with audio. Labelled "Original" / "Higgsfield Genjutsu", and it **alternates or splits** the
  two versions of the same shot.
- The "Original" is a real handheld selfie UGC take: a woman talking to her phone camera in a car, with big head moves,
  hair grabs, pointing at the lens and hand gestures.
- The Genjutsu version **re-performs the exact same take** with a different, AI-generated character: same framing, same
  head and hand timing, same gestures and lip movement, with new face, hair (braid), outfit (navy sweater) and jewelry.
- The character comes from a **3x3 multi-view character sheet** (front, both profiles, 3/4 views, looking up and down)
  on a plain grey background, which is the second image in the post. This is the same idea as our Soul Pack / character sheet.
- The post's pitch is "$0, hundreds of free UGC videos". The "workflow" is behind a link in the comments (not followed).

## Why it matters for us
1. **It's the organizers' own example idea.** "Openjutsu (an open Genjutsu)" is listed on the contest prompt
   (see HIGGSFIELD_TEARDOWN.md). A working open version is a strong Most Innovative / Best Overall beat.
2. **It attacks our two weak spots at once.** Our i2v + LatentSync takes drift in identity while talking (ArcFace
   0.66-0.72 vs the 0.75 target) and the mouth is the weakest part by eye. A motion-transfer take copies a *real*
   human performance (natural head, hands and jaw) onto a still that already scores ~0.90, so the model only has to
   keep the look, not invent the motion.
3. **The split-screen "Original vs AI" format is the viral part.** It is self-explaining in 2 seconds, which suits
   Most Viral. Our Share sheet can offer it as a one-tap layout.

## Open-weights path (keeps the $2K LTX bonus)
- LTX docs list an official **LTX-2.5 Motion Transfer** ComfyUI workflow
  (`LTX-2.5_ICLoRA_Motion_Transfer_Distilled.json`; inputs: look still, driving video, motion caption,
  Motion Transfer IC-LoRA). Source: [LTX workflow compatibility](https://docs.ltx.io/open-source-model/reference/workflow-asset-compatibility.md).
- Fallback: [LTX-2.3 Union Control IC-LoRA](https://huggingface.co/Lightricks/LTX-2.3-22b-IC-LoRA-Union-Control)
  (pose via DWPose) plus a start image; a community test reports it runs on LTX-2.5 distilled at strength 1.0.
- IC-LoRAs need the **distilled** checkpoint. Verified on the Spark: `ltx-2.5-22b-distilled-transformer-bf16.safetensors`
  is already present. **Not** present yet: the Motion Transfer IC-LoRA, the workflow JSON, and pose/depth preprocessors
  (`comfyui_controlnet_aux`, `ComfyUI-VideoDepthAnything`).
- Audio: LTX motion-transfer paths do not keep the driver's audio as-is. Plan: the character's line in Voice 1 (`cb_low`), then
  LatentSync on the transferred take (the driver's jaw motion should already be close, which should help SyncNet).
- Unverified: quality on a 1024x1792 portrait, whether a cap/beard character holds through big head turns, VRAM peak.

## Privacy and licensing rules for the driving video
- The driver must **not** be anyone on the team or their family (the "Original" side would show their face).
- Use a CC0 / public-domain clip, or a clip we generate ourselves (e.g. an LTX take of a generic person), so the
  "Original" half is also licensable. No real-person likeness without permission (contest rule H6).

## Proposed next steps (after the v7h queue finishes, ~7 PM ET Oct 17)
1. Fetch the Motion Transfer IC-LoRA + official workflow (sha-pin in `download_models.sh`, new `openjutsu` group).
2. One test: the first demo character's still cG (ArcFace ~0.90) + a 5 s CC0 talking/gesturing driver -> score ArcFace while talking,
   SyncNet after LatentSync, and judge by eye. Success bar: id >= 0.75 held, SyncNet >= 9.
3. If it works: add an "Openjutsu / Re-perform" tile to the app (pick character, drop a video, get the side-by-side),
   and a 4-6 s split-screen beat in the demo.


## Update Oct 17, 4:55 PM ET
The Motion Transfer IC-LoRA and its workflow are not public yet (not on Hugging Face under Lightricks, not in ComfyUI-LTXVideo `example_workflows/2.5`). Switched the first test to the official public LTX-2.5 route, `LTX-2.5_ICLoRA_Union_Control_Distilled.json` (pose/depth/canny guides via the 2.3 Union Control IC-LoRA on the 2.5 distilled model, so the LTX bonus still applies). The LoRA is now on the Spark (sha256 verified) and in `download_models.sh motion`. Pose guides for it come from `scripts/make_pose_guide.py`.
