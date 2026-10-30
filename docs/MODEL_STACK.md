# OpenSoul model stack (Open Weights Only + LTX bonus)

Pinned for NVIDIA **DGX Spark** (Grace + Blackwell GB10, 128 GB unified memory, ARM64 + CUDA 13).  
ComfyUI is officially supported on Spark via [NVIDIA playbooks](https://build.nvidia.com/spark/comfyui/image-gen-quick-start) (`torch` cu130 ARM64 wheels).

**Legend:** ✅ verified from primary sources this session · ⚠️ partially verified / check on device · ❌ not verified on Spark yet

## Critical path (contest: Open Weights Only)

No Comfy Router / Partner Node / hosted API on the critical path. Local weights only.

| Stage | Model | Open weights? | License | ComfyUI | Spark fit | Status |
|-------|-------|---------------|---------|---------|-----------|--------|
| Identity / stills / turnaround | **Qwen-Image-Edit-2511** (~20B) | Yes (HF) | **Apache-2.0** | Native templates | ⚠️ Should fit 128GB UMA; prefer bf16 or fp8 TE | ✅ license + Comfy docs |
| Text-only master (Describe your character) | **Z-Image-Turbo** (6B, Tongyi-MAI; Comfy-Org/z_image_turbo split files `z_image_turbo_bf16` + `qwen_3_4b` text encoder + `ae` VAE) | Yes (HF) | **Apache-2.0** (Z-Image-Turbo; `qwen_3_4b` text encoder Apache-2.0; `ae` VAE: FLUX.1 autoencoder (ae) — Black Forest Labs, Apache-2.0) | Core nodes (`workflows/07z`): UNETLoader, CLIPLoader type lumina2, ModelSamplingAuraFlow shift 3, KSampler 9 steps cfg 1 res_multistep/simple | ✅ ~12 s per 1024×1536 image on Spark (rebuild lane, Oct 19) | ✅ license; fallback `07t` (Qwen-Image-Edit as text-to-image, no extra download) |
| Optional identity alt | FLUX.1 Kontext [dev] (12B) | Yes | **BFL Non-Commercial** (outputs rules nuanced; model itself NC for production hosting) | Native | ⚠️ | ✅ open weights; ⚠️ avoid as *primary* if you need clean commercial OSS story |
| Video (LTX bonus) | **LTX-2.5** distilled 22B (Comfy int8-convrot) | Yes | **LTX-2.x Community License** — free commercial/production use for entities under **$10M** annual revenue (affiliates included); ≥$10M needs paid CUA | Native templates (ComfyUI ≥0.32) | ⚠️ int8 pack recommended; UMA flush if pressure | ✅ open weights + Comfy; ⚠️ confirm Spark runtime |
| Video alt (cleaner OSS) | **Wan2.2** I2V-A14B or TI2V-5B | Yes | **Apache-2.0** | Native | ⚠️ 5B easier; 14B MoE heavy but UMA helps | ✅ |
| TTS (Speak tab, older stories, no-clip fallback; new stories use VoxCPM2) | **Orpheus 3B 0.1-ft** (Q4_K_M GGUF on llama.cpp + SNAC) | Yes | **Apache-2.0** weights; **Built with Llama** (Llama 3.2 Community License applies to this Llama 3.2 3B fine-tune) | `OpenSoulOrpheusTTS` (own venv), `workflows/03c` | ✅ CPU ~5x slower than real time on 8 cores; GPU faster | ✅ license (HF card, Oct 18 2026); our pick Oct 18 |
| TTS alt | **Kokoro-82M** | Yes | **Apache-2.0** | `OpenSoulKokoroTTS`, `workflows/03` | ✅ CPU/GPU light | ✅ license |
| TTS alt | Chatterbox | Yes | MIT (watermarked) | Community | ⚠️ GPU | ✅ |
| Lip-sync | **MuseTalk** | Yes | Code **MIT**; upstream states weights usable commercially (verify HF card) | Community wrappers | ⚠️ | ✅ code; ⚠️ wrapper stability |
| Lip-sync alt | LatentSync **1.6** (on-Spark `latentsync_unet.pt` / `stable_syncnet.pt` sha256 match ByteDance/LatentSync-1.6; runner uses `configs/unet/stage2_512.yaml`) | Yes | Code Apache-2.0; **weights OpenRAIL++** | Community wrappers | ⚠️ ~VRAM heavy | ✅ dual license note |
| Consistency score | **Patch embedding** (shipped) + optional **OpenAI CLIP ViT-B/32** via `transformers` | N/A / Yes | MIT-style / OpenAI CLIP terms | App-side (CPU) | ✅ | ✅ patch tested CPU |
| Consistency alt (NOT default) | InsightFace buffalo_* | Yes | Code MIT; **pretrained packs non-commercial** | N/A | ✅ | ✅ — do **not** ship as default for Open Weights commercial path |

**Union Control IC-LoRA version note (checked 18 Oct 2026).** The motion / re-perform path (`presets/models.yaml` `union_control_iclora`) loads `ltx-2.3-22b-ic-lora-union-control-ref0.5.safetensors` on the LTX-2.5 transformer. No LTX-2.5 Union Control IC-LoRA has been published. Hugging Face has only `Lightricks/LTX-2-19b-IC-LoRA-Union-Control` and `Lightricks/LTX-2.3-22b-IC-LoRA-Union-Control`. Lightricks' own LTX-2.5 workflow `example_workflows/2.5/LTX-2.5_ICLoRA_Union_Control_Distilled.json` (ComfyUI-LTXVideo) also loads the 2.3 `ref0.5` file, so this cross-version pairing is the official recipe, not a mistake. Fix: no file change. Keep the 2.3 file, label it "LTX-2.3 IC-LoRA (official recipe on 2.5)" in credits, and swap it for an `LTX-2.5-22b-IC-LoRA-Union-Control` file if one appears (pin revision + sha256 as in `scripts/download_models.sh`).

## Voice: Orpheus TTS (fallback) — Built with Llama

**Built with Llama.** New stories speak with VoxCPM2 (Apache-2.0) in each character's own voice clip; OpenSoul's fallback voice engine (older stories, the Speak tab, a character with no clip; rollback `OPENSOUL_TTS_DEFAULT=orpheus`) is [Orpheus 3B 0.1 finetuned](https://huggingface.co/canopylabs/orpheus-3b-0.1-ft)
by Canopy Labs, a fine-tune of Meta Llama 3.2 3B. Llama 3.2 is licensed under the Llama 3.2 Community License,
Copyright © Meta Platforms, Inc. All Rights Reserved.

| Piece | License | Link | What it means for us |
|---|---|---|---|
| Orpheus 3B 0.1-ft weights | Apache-2.0 (HF model card tag) | [HF](https://huggingface.co/canopylabs/orpheus-3b-0.1-ft), [code](https://github.com/canopyai/Orpheus-TTS) (Apache-2.0) | commercial use OK |
| Base model Llama 3.2 3B | Llama 3.2 Community License | [license](https://www.llama.com/llama3_2/license/), [AUP](https://www.llama.com/llama3_2/use-policy/) | show "Built with Llama" (README, credits card, this page); keep the notice above; follow the Acceptable Use Policy; a separate Meta license is needed above 700M monthly active users |
| Q4_K_M GGUF we download | Apache-2.0 (repack of the above) | [HF](https://huggingface.co/lex-au/Orpheus-3b-FT-Q4_K_M.gguf), pinned rev `51079fc`, sha256 `18284d3e…6c55` | ungated mirror; same terms as the original |
| SNAC 24 kHz decoder | MIT | [HF](https://huggingface.co/hubertsiuzdak/snac_24khz) | |
| llama-cpp-python | MIT | [repo](https://github.com/abetlen/llama-cpp-python) | prebuilt CPU/CUDA wheels |

- Voices: the 8 built-in speakers only (tara, leah, jess, mia, zoe, zac, leo, dan). No voice cloning, no reference audio.
  Lumi = tara, Mio = leah, Ren = zac (our pick, Oct 18 2026; saved per character in `data/character_voices.json`).
- Emotion tags inline in the line: `<laugh> <chuckle> <sigh> <gasp> <cough> <sniffle> <groan> <yawn>`. The editor also accepts
  `[laugh]`, `(sighs)`, `*gasp*` (`opensoul/orpheus.py: normalize_tags`). Unknown `<tags>` are refused, so a typo is never read out.
  Kokoro/Chatterbox and the LTX speech prompt get the line without tags.
- Setup: `scripts/setup_tts_orpheus.sh` (venv `$OPENSOUL_HOME/tts-envs/orpheus`, then `download_models.sh orpheus`).
- Speed measured on the agent box (8 vCPU, no GPU): about 4.5–6 s of compute per second of speech.
- Evaluated and not chosen (Oct 18 voice bake-off, `production/voice2/README.md`): Dia 1.6B (Apache-2.0), Zonos v0.1
  (Apache-2.0), Chatterbox-Turbo (MIT). Rejected on license: F5-TTS (CC-BY-NC), Fish Speech (CC-BY-NC), IndexTTS2 (bilibili license),
  Higgs Audio v2 (Boson community license), VibeVoice (research only).

## Explicitly avoided on Open Weights critical path

| Thing | Why |
|-------|-----|
| Comfy Router partner models (Flux API, Kling, Veo, MiniMax H3 API, LTX Partner Nodes, …) | Disqualifies **Open Weights Only** |
| MiniMax H3 open weights | H3 **does** publish open weights, but its Community License excludes users in the US, EU, UK and South Korea. We are US-based (and so is ComfyUI), so H3 is **benchmark-only**: we compare our lip-sync against an H3 demo clip by eye, but never download, run or ship H3. Lip-sync path: LTX joint audio+video first, InfiniteTalk (Apache-2.0) as backup. |
| FLUX3 / MiniMax H3 bonuses | Those bonuses are API-credit tracks; conflict with Open Weights Only if used as core |
| InsightFace buffalo as required dep | Non-commercial model pack |

## LTX $2k bonus compatibility

Contest rule: **“LTX must be the core video model in the workflow.”**  
Using **LTX-2.5 open weights** (not Partner Nodes) as the I2V core should satisfy both:

1. **VFX Workflow Built with LTX** ($2k), and  
2. **Open Weights Only** (RTX 5090),

provided no partner API remains on the critical path. **⚠️ Unverified with organizers** — confirm in submission FAQ/Discord if dual-eligibility is OK when LTX is local weights.

OpenSoul's non-commercial contest use is almost certainly under the $10M Community License threshold; still read `LICENSE` on [Lightricks/LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5).

## Recommended Spark downloads (names from Comfy docs / HF)

**Qwen-Image-Edit-2511**

- `models/diffusion_models/qwen_image_edit_2511_bf16.safetensors`
- `models/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors`
- `models/vae/qwen_image_vae.safetensors`
- optional: Lightning 4-step LoRA for speed

**LTX-2.5 (Comfy pack)**

- `diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors` (or bf16 if preferred)
- matching Gemma text encoder + VAE from the LTX-2.5 Comfy-aligned pack

**Wan2.2 fallback**

- `wan2.2_ti2v_5B_fp16.safetensors` (+ umt5 + wan VAE) from Comfy-Org repack

## Comfy SDK (required for clear contest credit)

```bash
pip install "comfy-sdk>=0.5"
pip install comfy-api-proxy   # on the ComfyUI host
comfy-api-proxy               # serves API v2 on :8189 (ComfyUI on :8188)
export COMFY_BASE_URL=http://127.0.0.1:8189
# no API key for local proxy
```

Docs: https://docs.comfy.org/development/api-development/sdks  

Gradio app imports `comfy_sdk.Comfy` via `opensoul.comfy_client` — explicit SDK usage for judges.

## Unverified on this box (no GPU / no Spark access yet)

- Actual VRAM/UMA residency for Qwen-Edit-2511 + LTX-2.5 distilled on GB10
- ARM64 wheels for MuseTalk / Kokoro custom nodes
- Exact node `class_type` names after ComfyUI upgrade (workflow JSON stubs must be re-exported)
- Dual prize eligibility (Open Weights + LTX bonus) confirmation from organizers

## Spark findings (2026-10-16)

- ✅ **Qwen-Image-Edit-2511 fp8mixed + Lightning 4-step LoRA** runs on GB10 with ComfyUI v0.41.2: one 768×1344 still from the character sheet in ~44 s (first run, includes model load). Workflow: `workflows/02_consistent_stills_api.json`; runner: `scripts/spark_smoke_still.py`.
- Launch flags: `TORCH_DISABLE_NATIVE_JIT=1 --disable-triton-backend --disable-comfy-compiler` (Triton JIT needs Python headers; not installed without sudo).
- Default to **fp8mixed** (~19.6 GB) rather than bf16 (~39 GB) when the Spark is shared with another resident model.
- ✅ Wan2.2 TI2V-5B fp16 + umt5 fp8 + Wan VAE downloaded (Comfy-Org repack). Not run yet.
- ❌ **Lightricks/LTX-2.5 is gated** on Hugging Face (auto-approve): needs an HF account that has accepted the license plus `HF_TOKEN` to download.
- ⚠️ **Kokoro-82M** (`hexgrad/Kokoro-82M`) and **MuseTalk** (`TMElyralab/MuseTalk`) official repos only publish pickle weights (`.pth` / `.bin`). The setup script is safetensors-only, so it doesn't fetch them; that needs an explicit project decision.
