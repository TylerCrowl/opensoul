# Model watch list

Living list of better open models to consider per pipeline stage. Seeded from
[MODEL_STACK.md](MODEL_STACK.md) and Spark findings. **Spark 128 GB UMA first**;
hardware profiles for 24/32 GB cards are deferred.

Refresh during contest self-checks (roughly each time you touch models or do a
GPU queue review). Mark status as `watching` / `trying` / `rejected` / `adopted`.

| stage | candidate | license | size / fit notes (Spark 128 GB UMA) | why / why-not | status |
|-------|-----------|---------|-------------------------------------|---------------|--------|
| sheet / stills | **Qwen-Image-Edit-2511** bf16 / fp8mixed (+ Lightning 4-step LoRA) | Apache-2.0 | bf16 ~41 GB; fp8mixed ~20 GB; Lightning LoRA light | Default path; sheet uses bf16, stills fp8mixed | **adopted** |
| stills | FLUX.1 Kontext [dev] | BFL Non-Commercial | ~12B; fits UMA | Strong edit quality, but NC license hurts Open Weights commercial story | watching (avoid as primary) |
| video | **LTX-2.5** distilled 22B (int8-convrot / bf16) | LTX-2.x Community License (<$10M) | int8 pack preferred; bf16 needs headroom | Contest LTX bonus + open weights; gated HF download | **adopted** |
| video | Wan2.2 TI2V-5B / I2V-A14B | Apache-2.0 | 5B easier; 14B MoE heavy but UMA helps | Cleaner OSS alt; downloaded on Spark, not run yet; using as core forfeits LTX bonus | watching |
| voice / tts | **Kokoro-82M** | Apache-2.0 | tiny | Default TTS; pickle weights need `ALLOW_PICKLE=1` | **adopted** |
| voice / tts | Chatterbox | MIT (watermarked) | GPU; Hub snapshot under `$OPENSOUL_HOME/models/chatterbox` | Alt via `OPENSOUL_TTS=chatterbox` | **adopted** (alt) |
| lipsync | **LTX joint audio+video (`ltx_av`, workflow 04b a2v)** | LTX-2.x Community | same as video pack | **Default** since 18 Oct (licensing decision): one pass, frozen TTS audio latent feeds both sampling passes. Sync quality still under test (PLAN in production/lipsync) | **adopted** (default) |
| lipsync | LatentSync 1.6 (optional mouth pass) | code Apache-2.0; weights OpenRAIL++-M; face detector swapped to MediaPipe (Apache-2.0) + optional anime-face-detector (MIT) | ~17 GiB GPU; checkpoints under LatentSync/ | Optional/secondary. Upstream detector (InsightFace buffalo_l, NON-COMMERCIAL weights) is blocked: `runners/latentsync_infer.py` + `ls_face_detector.py`; `--face-box` for multi-face shots; `<out>.lipsync.json` stats | **adopted** (optional) |
| lipsync | MuseTalk | MIT code | medium | Earlier research path; not the app default anymore | rejected (default) |
| lipsync | InfiniteTalk (Wan 14B / WanVideoWrapper) | Apache-2.0 (wrapper) | heavy, fits UMA | In progress in speak.py; no committed workflow yet | trying |
| identity_gate | Patch embedding (shipped) | Apache-2.0 | CPU | Default; no extra weights | **adopted** |
| identity_gate | InsightFace buffalo_l ArcFace | weights non-commercial | light | Opt-in only (`06b`); never default for Open Weights commercial path | watching (opt-in) |
| motion | LTX Union Control IC-LoRA (Openjutsu path) | LTX-2 Community | LoRA on bf16 LTX | Experimental re-perform; not an identity lever on first oj1 takes | trying |
| camera control | **Uni3C** (alibaba-damo-academy/Uni3C; ControlNet on Wan2.1-I2V-14B) | Apache-2.0: LICENSE file in the GitHub repo checked Oct 17 2026; HF card `ewrfcas/Uni3C` says apache-2.0 but has no LICENSE file | official `controlnet.pth` 4.0 GB (pickle, avoid); Comfy-ready `Kijai/WanVideo_comfy` `Wan21_Uni3C_controlnet_fp16.safetensors` 2.0 GB, plus a Wan2.1 I2V 14B base; easy fit | Explicit camera paths for orbit / orbit freeze / jib. Nodes live in ComfyUI-WanVideoWrapper (`uni3c/`, Apache-2.0), not core ComfyUI. Kijai repo card names no license (conversion, upstream Apache applies). Wan base = no LTX bonus for those presets | watching (license verified) |
| camera control | **Wan2.2-Fun-A14B-Control-Camera** (alibaba-pai) | Apache-2.0 (HF card tag; base Wan2.2-I2V-A14B Apache-2.0); no separate LICENSE file in the HF repo | official bf16: two experts x 29.6 GB + umt5 11.4 GB + VAE 0.5 GB, about 71 GB (load one expert at a time); Kijai fp8 scaled HIGH/LOW 15.5 GB each, about 31 GB | Newer and bigger than Uni3C; camera-pose conditioning built in. Heavier on the Spark beside Qwen/LTX; same LTX-bonus trade-off | watching (license verified) |
| pose | DWPose + YOLOX-L ONNX | Apache-2.0 | light CPU/GPU | Pose guides outside Comfy (`make_pose_guide.py`) | **adopted** (optional) |

## How to refresh

1. Skim HF / Comfy release notes for each stage above.
2. Check license still fits **Open Weights Only** (no partner/API critical path).
3. Note Spark fit (UMA residency, ARM64 wheels) before marking `trying`.
4. If adopted: add a `presets/models.yaml` backend + workflow, then
   `./scripts/download_models.sh <group>`.
