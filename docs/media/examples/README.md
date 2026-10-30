# Example outputs (real GPU renders)

Clips rendered on a local DGX Spark with the OpenSoul stack (Qwen-Image-Edit stills, LTX-2.5 video through ComfyUI,
Orpheus / Chatterbox TTS, LatentSync lip-sync), re-encoded at 540 px wide (H.264 CRF 28) to keep the repo small.

| File | What it shows | Measured scores |
|---|---|---|
| `kevin_raccoon_ir_trailcam.mp4` | IR trail-cam style shot (effect) | no speech |

The earlier example clips starred the retired first demo character and were removed on Oct 18 2026 (copies are kept
outside the repo). Lumi examples from *Lumi – Night Shift* will be added here once we pick the takes.

The earlier interim README loop (`../opensoul_demo.gif`, from the pre-rebuild Lumi) is live-only and left out of release
archives (`opensoul/export_guard.py` PRE_REBUILD). A new Describe → Master → Sheet → Shot → Share loop, made only from
logged open-model assets, will replace it.

SyncNet is the LatentSync confidence score (higher is better, about 7+ is usable). ArcFace mean is the identity
similarity to the canonical reference over 8 sampled frames. By-eye review still decides the final pick, because
SyncNet alone overrates lip-sync.
