# OpenSoul

**Open models. Your own computer. Your characters.**

Preview mode runs on any computer. Real renders need a studio.

OpenSoul is a local film and character studio. Paste a script, and OpenSoul makes a trailer with your own consistent characters, talking shots with lip sync, picture-only shots, title cards and a song. (A studio = ComfyUI + the open models, see Setup below.)

OpenSoul is an open-source version of the Higgsfield creator workflow (Soul ID, Camera Controls, Viral Presets, Speak). It uses ComfyUI and the [Comfy Developer Platform SDK](https://docs.comfy.org/development/api-development/sdks). LTX is the core video model. Entry for [Open Source Higgsfield](https://comfy.org/open-source-higgsfield).

<!-- PUBLISH-TODO:DEMO_LOOP_IMAGE (6–8 s loop: Describe → Master → Sheet → Shot → Share, made only from logged open-model assets) -->

**Demo video:** coming with the first release (2 minutes or less). <!-- PUBLISH-TODO:DEMO_VIDEO_URL -->

**Live link:** none. OpenSoul runs on your own computer, so there is nothing to host. To try it, download it (below) or [run it from source](#setup-and-run).

> **Status legend:** ✅ works today · 🟡 **in progress** (code exists, not yet verified on GPU) · ⬜ planned

---

## Download (one click, no terminal)

**Download:** coming with the first release. <!-- PUBLISH-TODO:RELEASES_URL -->

Until then, [run OpenSoul from source](#setup-and-run): it is the same app.

| Computer | Package | Then |
|---|---|---|
| Mac, Apple chip (M1 or newer), macOS 13+ | `mac-arm64` `.dmg` (or `.zip`) | Drag OpenSoul to Applications. The first time, right-click it and pick **Open**. It opens in its own window with a Dock icon. |
| Mac, Intel | `mac-x64` `.dmg` (or `.zip`) | Same as above |
| Windows 10/11 64-bit | `windows-x64` `.zip` | Click **Extract All**. Double-click `OpenSoul.cmd`. If SmartScreen asks, click **More info**. Then click **Run anyway**. |
| Linux x64 / arm64 (DGX Spark) | `linux-x64` or `linux-arm64` `.tar.gz` | Unpack it. Run `OpenSoul/OpenSoul`. |

Each package brings its own Python and libraries: no installs, no admin password, works offline. On a Mac, OpenSoul is a
normal app in its own window. Linux and Windows open it in your browser. The first screen is a short welcome page.

**Try it now** uses Preview mode (no GPU). **Connect my studio**: type the address of a computer that runs ComfyUI.
Then click *Test connection*. On macOS 15 or newer, the first open can need **System Settings → Privacy & Security →
Open Anyway**. [docs/DESKTOP.md](docs/DESKTOP.md) has the details. It also has the one-line `scripts/install.sh` /
`install.ps1` and the build steps.

## Highlights

- **Script to trailer, with lip sync.** Click **Add from a script** and paste a screenplay. OpenSoul splits it into shots: who is in each shot, the place, the camera and the line. Lines like `TITLE CARD: …` and `END CARD: …` become title cards. Talking shots get a voice and lip sync from LTX-2.5 joint audio + video. Picture-only shots run their planned Length.
- **Consistent characters.** One photo or a description gives a six-view character sheet. Every shot uses the same look and the same voice.
- **An edit you control.** Review shows every take side by side. Export cuts each keeper to its Length from a Start point and shows the length of the cut. A shot with no keeper is black for its Length. A low room tone sits under talking shots. You can also add your own picture or clip to a shot as a take.
- **Original designs.** Each story has an **Avoid** list. It starts with well-known design traits (for example a V-shaped fin on a robot head). Add your own words. OpenSoul writes the list into the negative prompt of every start frame and take.
- **Music videos.** Write lyrics, make a song with ACE-Step, and get shots that follow the beat.
- **Shorts.** One shot, no story, as a 9:16 clip with a caption to paste.
- **Mac one-click.** A Mac app with its own window. It runs Preview mode on the Mac and connects to your studio for real renders. Packages for Windows and Linux too.

## Privacy

- OpenSoul runs on your own computer and your own studio. It has no account, no telemetry and no cloud service. Your photos, voices, scripts and videos stay in your data folder.
- It never scans your network. You type the studio address yourself.
- Model downloads come from the official Hugging Face repositories only when you run `scripts/download_models.sh`.
- The Character Sheet needs your tick on *"I own this picture or have permission"*. A voice clip needs consent too.

## What it does

One story, six tabs, left to right. Two more items sit on the right of the top bar, after a thin line. **Music videos** makes a song and shots that match it. **Shorts** makes one shot with no story. OpenSoul keeps each short in the story "Shorts".

| Tab | You do | OpenSoul does |
|---|---|---|
| **1. Characters** | Pick the demo cast, or click **New character**. Add **one photo** (or a description). Select *"I own this picture or have permission"*. Click **Make character sheet**. | Renders a **six-view character sheet** (full body + close-up × front, side, back). Then it makes a **Soul Pack** from it: six reference angles, a locked look description and a seed. Every shot shows the same person. Each character keeps one voice for every shot (**Advanced** has a per-shot change). |
| **2. Stages** | Add a place once (a picture or a description). | Makes a stage sheet: a master plate plus a few angles, so the place looks the same in every shot. |
| **3. Shots** | One card per shot: who is in it, the stage, a **camera move** tile and an optional line to **speak**. Or a **Title card** (big and small text on a color). **Add from a script** makes all the shots at once. | Turns your choices into a long, cinematographer-grade prompt and parameters (presets are prompt-driven; preset LoRAs are off by default). Moves that are not reliable yet have an *Experimental* tag. |
| **4. Render** | Click **Make a draft** (or draft every shot at once). Then click **Render final** for the ones you like. | Runs voice → LTX video → lip-sync → Era grade. Every take is new; earlier takes stay. |
| **5. Review** | Compare the takes side by side. Click **Keep this** on the best one. | The keeper is the take that goes into the story export. |
| **6. Export** | Set a Start and a Length per shot if you want. Then **Export story**, or one shot as a **Vertical clip** with **Copy caption**. | Cuts the keepers to their Length and joins them in order into one MP4 (black for a shot with no keeper, room tone under talking shots); the vertical clip is 720×1280 with a caption tagged `#OpenSourceHiggsfield`. **Credits** lists every model and tool with its license. |

The earlier three-step page (Character → Shot → Share) is still at `?ui=classic`. A later release removes it. **Shorts** in the top bar opens the new one-shot flow.

**Likeness policy:** the Character Sheet only accepts original characters or your own photos. The app asks you to confirm *"I own this picture or have permission"* before it runs. It has no feature that replaces a person in a video.

No prompts, model names or node graphs on the main path. The Advanced drawer shows the seed, length, steps and the exact prompt.

**Light and dark:** Settings → Appearance switches between System default (follows your computer), Light and Dark. This browser saves the choice and applies it before the page draws, so the page does not flash. Every colour is a token in [app/web/static/theme.css](app/web/static/theme.css), and [tests/test_theme_tokens.py](tests/test_theme_tokens.py) checks that both themes pass WCAG AA contrast (run it directly to print the table).

## Features mapped to Higgsfield

| Higgsfield | OpenSoul | How | Status |
|---|---|---|---|
| Soul ID | **Soul Pack** | Qwen-Image-Edit-2511 reference-conditioned stills + on-device consistency score that rejects off-model frames | ✅ stills on DGX Spark · ✅ scoring (CPU) |
| Soul ID / character consistency | **Character Sheet** (one click) | One photo → six gated views on light gray via Qwen-Image-Edit-2511 bf16 + Lightning (`workflows/07`, `presets/character_sheet.json`). **Auto-fix**: a local open VLM (Qwen3-VL-8B, Apache-2.0) reads the reference into an attribute checklist. It asks view-aware yes/no questions about every view (cap orientation, glasses, earbuds per ear, facial hair, outfit, profile direction, framing). It combines the answers with ArcFace/patch identity. It re-renders failed views with a corrective prompt (≤ 2 retries; it keeps the best try; flagged views get a Regenerate button). Then it makes a 3×2 grid, and the views become the Soul Pack's reference set. | ✅ UI, dry-run + tests. ✅ GPU: sheet v4 of the first demo character. Auto-fix loop, back-view-from-side-view fallback and one Regenerate; cap correct in all six views ([evidence](docs/evidence/CHARACTER_SHEET.md)). |
| Camera Controls | **11 camera tiles**: dolly in/out/left/right, jib up/down, static, crash zoom, orbit, FPV, dolly zoom | `presets/camera/*.json`: prompt recipe; optional LoRA support where the model allows it (off by default, `OPENSOUL_APPLY_LORAS=1`) | ✅ presets + UI · 🟡 LTX render on GPU |
| Viral Presets | **4 effect tiles**: Earth zoom out, orbit freeze, day-to-night, outfit switch | `presets/effects/*.json`: prompt recipe on LTX I2V; optional LoRA support where the model allows it (off by default) | ✅ presets + UI · 🟡 GPU render |
| Speak / Lipsync Studio | **Speak tab** | Stories: VoxCPM2 by default for new stories (each character's own voice clip, consent required; no clip = Orpheus, with a note). Speak tab and older stories: Orpheus (emotion tags); also Kokoro or Chatterbox TTS. Pluggable lip-sync: `ltx_av` (LTX joint audio+video, intended default) · `latentsync` (alt) · `infinitetalk`. Talking shots of rebuilt characters use L1c: a grin-gated, camera-locked a2v base (eyes open, looking at the listener; native LTXVAddGuide) → LatentSync, MediaPipe only ([docs/LIPSYNC_SCORER.md](docs/LIPSYNC_SCORER.md)). | ✅ TTS + LatentSync run as ComfyUI nodes via the SDK on DGX Spark ([evidence](docs/evidence/)) · ⬜ InfiniteTalk workflow |
| Cinema Studio "Era" | **Look toggle** | ffmpeg post: UGC = light grain, micro-shake, natural grade. 35mm = grain, gate weave, warm grade, vignette | ✅ (CPU) |
| AI Influencer "Shuffle" | **Shuffle** | Random tile + look + seed | ✅ |
| Share | **Share sheet** | Vertical MP4 export + caption | ✅ |

## Model stack (open weights only, no partner APIs)

| Stage | Model | Runs as | Status |
|---|---|---|---|
| Character stills | Qwen-Image-Edit-2511 (fp8mixed) + Lightning 4-step LoRA | core ComfyUI nodes, `workflows/02` | ✅ via comfy-sdk on DGX Spark ([evidence](docs/evidence/COMFY_SDK_PROOF.md)) |
| Character sheet | Qwen-Image-Edit-2511 (bf16) + Lightning 4-step LoRA | core nodes + `OpenSoulIdentityGate`, `workflows/07` | 🟡 see [evidence](docs/evidence/CHARACTER_SHEET.md) |
| Text-only master (Create → Describe) | **Z-Image-Turbo** (Tongyi-MAI, Apache-2.0); fallback: Qwen-Image-Edit-2511 as text-to-image (`workflows/07t`, `OPENSOUL_MASTER_BACKEND=qwen07t`) | core nodes, `workflows/07z`, `presets/text_master.json` (`./scripts/download_models.sh master`) | 🟡 fake-ComfyUI tests; first studio run logged in review notes |
| Sheet auto-fix checks | **Qwen3-VL-8B-Instruct** (bf16, ~17.5 GB, loaded on demand) | in-app (`opensoul/sheet_check.py`, transformers), next to ComfyUI | ✅ on DGX Spark, see [evidence](docs/evidence/CHARACTER_SHEET.md) |
| Video (core) | **LTX-2.5** distilled 22B | core ComfyUI LTXV nodes, `workflows/04`, `04b` | 🟡 workflows exist; not yet run through the SDK end to end |
| Camera LoRAs (optional) | LTX-2 19B camera-control LoRAs: need the LTX-2 19B model, so not used with the default LTX-2.5 pack | core `LoraLoaderModelOnly` | ⚪ off by default (`OPENSOUL_APPLY_LORAS=1`) |
| Video fallback | Wan2.2 TI2V-5B | none yet | 🟡 downloaded, not run (would forfeit the LTX bonus) |
| Voice (new stories: VoxCPM2; fallback: Orpheus) | VoxCPM2 (Apache-2.0, the character's own voice clip) for new stories. Orpheus 3B (built-in voices, `<sigh>` `<laugh>` `<chuckle>` tags) for older stories, the Speak tab and characters with no clip. Rollback: `OPENSOUL_TTS_DEFAULT=orpheus` | `OpenSoulOrpheusTTS` node, `workflows/03c` | ✅ runner tested on CPU (Lumi dialogue); ⬜ node run on Spark |
| Voice (alt) | Kokoro-82M | `OpenSoulKokoroTTS` node, `workflows/03` | ✅ via comfy-sdk |
| Voice (expressive) | Chatterbox | `OpenSoulChatterboxTTS` node, `workflows/03b` | ✅ via comfy-sdk |
| Lip-sync (default, intended) | **LTX-2.5 joint audio+video** (`ltx_av`) | `workflows/04b` | ✅ 04b ran via comfy-sdk ([evidence](docs/evidence/COMFY_SDK_PROOF.md)); switch of the app default in progress |
| Lip-sync (alt) | LatentSync 1.6 / InfiniteTalk | `OpenSoulLatentSync` node, `workflows/05` / none | see [evidence](docs/evidence/COMFY_SDK_PROOF.md) / ⬜. Our LatentSync path finds faces with the MediaPipe face landmarker (Apache-2.0). For drawn faces, it uses the hysts anime-face detector (MIT) as a fallback. It fails closed and never downloads InsightFace. |
| Identity gate (default) | patch embedding (no weights, Apache-2.0) | `OpenSoulIdentityGate` node, `backend="patch"`, `workflows/06` | ✅ CPU tests |
| Identity gate (optional) | ArcFace (insightface `buffalo_l`, **non-commercial weights**) | same node, `backend="arcface"`, `workflows/06b` | ✅ via comfy-sdk (Oct 16 evidence run) |
| App consistency score | patch embedding (default), optional CLIP ViT-B/32 | in-app (CPU) | ✅ |
| Era grade, export | ffmpeg | in-app post step (CPU, outside Comfy) | ✅ |

### Licenses (verified from source, Oct 16 2026)

| Component | What we use it for | License | Source | Notes |
|---|---|---|---|---|
| OpenSoul app + `custom_nodes/opensoul_nodes` | this repo | Apache-2.0 | [LICENSE](LICENSE) | |
| ComfyUI | workflow engine | GPL-3.0 | [repo](https://github.com/Comfy-Org/ComfyUI/blob/master/LICENSE) | runs as a separate process; it loads our node pack |
| comfy-sdk (`comfy_sdk`) | client for every GPU stage | MIT | [repo](https://github.com/Comfy-Org/comfy-python-sdk/blob/main/LICENSE) | |
| comfy-api-proxy | Comfy API v2 for local ComfyUI | MIT | [repo](https://github.com/Comfy-Org/comfy-api-proxy/blob/main/LICENSE) | |
| Qwen-Image-Edit-2511 | stills | Apache-2.0 | [HF](https://huggingface.co/Qwen/Qwen-Image-Edit-2511) | Comfy repack: [Comfy-Org/Qwen-Image-Edit_ComfyUI](https://huggingface.co/Comfy-Org/Qwen-Image-Edit_ComfyUI) (Apache-2.0) |
| Z-Image-Turbo | text-only master (`workflows/07z`) | Apache-2.0 | [HF](https://huggingface.co/Tongyi-MAI/Z-Image-Turbo) | Comfy repack: [Comfy-Org/z_image_turbo](https://huggingface.co/Comfy-Org/z_image_turbo) (diffusion model) |
| ACE-Step 1.5 XL Turbo | Music videos: the song (`workflows/08m`, optional download group `music`) | MIT | [HF](https://huggingface.co/ACE-Step/acestep-v15-xl-turbo) | Comfy repack: [Comfy-Org/ace_step_1.5_ComfyUI_files](https://huggingface.co/Comfy-Org/ace_step_1.5_ComfyUI_files) @ `6707deb2` (card says Apache-2.0; upstream MIT governs). Not yet run on a GPU from OpenSoul |
| ACE-Step 1.5 XL Base (`ACE-Step/acestep-v15-xl-base`) | vocal separation for Music videos (ACE-Step's 'extract' task) | MIT | [HF](https://huggingface.co/ACE-Step/acestep-v15-xl-base) | optional and off by default; only needed for vocal separation. Pinned to `220c1166efbd`. The download needs `ALLOW_PICKLE=1` because the repo includes `silence_latent.pt` (a pickle file): `ALLOW_PICKLE=1 ACE_XL_BASE=1 ./scripts/download_models.sh music` |
| Qwen3-4B text encoder (`qwen_3_4b`) | text-only master | Apache-2.0 | [HF](https://huggingface.co/Qwen/Qwen3-4B) | from the Comfy-Org/z_image_turbo split files |
| FLUX.1 autoencoder (ae) — Black Forest Labs (`ae.safetensors`) | text-only master (decoder) | Apache-2.0 | | from the Comfy-Org/z_image_turbo split files |
| Qwen3-VL-8B-Instruct | Character Sheet auto-fix checks | Apache-2.0 | [HF](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct) | optional; `OPENSOUL_SHEET_VLM=none` disables the checks |
| Qwen2.5-VL-7B (text encoder) + Qwen-Image VAE | stills | Apache-2.0 | [HF](https://huggingface.co/Qwen/Qwen2.5-VL-7B-Instruct) | Comfy repack (fp8 text encoder, VAE): [Comfy-Org/Qwen-Image_ComfyUI](https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI), Apache-2.0 |
| Qwen-Image-Edit-2511-Lightning LoRA | 4-step stills | Apache-2.0 | [HF](https://huggingface.co/lightx2v/Qwen-Image-Edit-2511-Lightning) | |
| LTX-2.5 (transformer, VAEs, upscalers) | video | LTX-2.x Community License | [HF](https://huggingface.co/Lightricks/LTX-2.5), [license](https://github.com/Lightricks/LTX-2/blob/main/LICENSE-2_x) | open weights, not OSI; commercial use needs a paid license at ≥ $10M annual revenue |
| Gemma-4-12B text encoder (LTX-2.5 repack, with LTX projection layers) | video prompts | upstream Gemma 4: **Apache-2.0**. The LTX-2.5 repo distributes this repack, so the LTX-2.x Community License also applies to it. | [Gemma 4 license](https://ai.google.dev/gemma/apache_2), [announcement](https://opensource.googleblog.com/2026/03/gemma-4-expanding-the-gemmaverse-with-apache-20.html), [HF](https://huggingface.co/Lightricks/LTX-2.5) | Gemma 4 is the first Gemma under OSI Apache-2.0. The older [Gemma Terms of Use](https://ai.google.dev/gemma/terms) (use restrictions, NOTICE requirement) cover only the models in that page's Appendix. The page says "For Gemma 4 terms, see the Gemma 4 license" (checked Oct 16 2026). |
| LTX-2 19B camera-control LoRAs | optional camera moves (needs the LTX-2 19B model; off by default) | LTX-2 Community License | [HF](https://huggingface.co/Lightricks/LTX-2-19b-LoRA-Camera-Control-Dolly-In), [license](https://github.com/Lightricks/LTX-2/blob/main/LICENSE-2) | |
| LTX-2.3 22B IC-LoRA Union Control (`ref0.5`) | pose-guided re-perform test (Openjutsu) | LTX-2 Community License | [HF](https://huggingface.co/Lightricks/LTX-2.3-22b-IC-LoRA-Union-Control), [license](https://github.com/Lightricks/LTX-2/blob/main/LICENSE-2) | open weights, not OSI; `download_models.sh motion` |
| DWPose (`dw-ll_ucoco_384.onnx`) + YOLOX-L (`yolox_l.onnx`) | pose guide made outside Comfy (`scripts/make_pose_guide.py`) | Apache-2.0 | [HF](https://huggingface.co/yzd-v/DWPose), [DWPose license](https://github.com/IDEA-Research/DWPose/blob/onnx/LICENSE), [YOLOX license](https://github.com/Megvii-BaseDetection/YOLOX/blob/main/LICENSE) | `download_models.sh pose` |
| Wan2.2 TI2V-5B | fallback only, unused | Apache-2.0 | [HF](https://huggingface.co/Wan-AI/Wan2.2-TI2V-5B) | |
| Orpheus 3B 0.1 finetuned (Q4_K_M GGUF) | TTS (default; emotion tags) | Apache-2.0 weights; fine-tuned from Meta Llama 3.2 3B, so the [Llama 3.2 Community License](https://www.llama.com/llama3_2/license/) applies too — **Built with Llama** | [HF](https://huggingface.co/canopylabs/orpheus-3b-0.1-ft), GGUF: [huggingface.co/lex-au/Orpheus-3b-FT-Q4_K_M.gguf](https://huggingface.co/lex-au/Orpheus-3b-FT-Q4_K_M.gguf) (Apache-2.0), [code](https://github.com/canopyai/Orpheus-TTS) | built-in voices only (no cloning); Llama terms: attribution, Acceptable Use Policy, separate license above 700M monthly active users |
| SNAC 24 kHz | Orpheus audio decoder | MIT | [HF](https://huggingface.co/hubertsiuzdak/snac_24khz) | |
| llama-cpp-python | runs the Orpheus GGUF (CPU or GPU) | MIT | [repo](https://github.com/abetlen/llama-cpp-python/blob/main/LICENSE.md) | own venv, not ComfyUI's |
| VoxCPM2 | voice for new stories (each character's own voice clip, consent required) | Apache-2.0 | [HF](https://huggingface.co/openbmb/VoxCPM2) | not gated |
| Kokoro-82M | TTS | Apache-2.0 (weights + [code](https://github.com/hexgrad/kokoro/blob/main/LICENSE)) | [HF](https://huggingface.co/hexgrad/Kokoro-82M) | |
| Chatterbox | expressive TTS | MIT (weights + [code](https://github.com/resemble-ai/chatterbox/blob/master/LICENSE)) | [HF](https://huggingface.co/ResembleAI/chatterbox) | output carries Resemble's Perth watermark |
| LatentSync 1.6 | lip-sync (alt) | code Apache-2.0, weights OpenRAIL++ (per the HF model card; the weights have no license file) | [code](https://github.com/bytedance/LatentSync/blob/main/LICENSE), [HF](https://huggingface.co/ByteDance/LatentSync-1.6) | open weights with use restrictions (no deception/impersonation etc.) |
| Whisper tiny (inside LatentSync) | audio features | MIT | [repo](https://github.com/openai/whisper/blob/main/LICENSE) | |
| InsightFace code / `buffalo_l` models | optional ArcFace identity gate (`backend="arcface"`); never a default (our LatentSync path uses MediaPipe instead) | code MIT; **models non-commercial research only** | [README](https://github.com/deepinsight/insightface#license) | the default identity gate is the Apache-2.0 patch backend. Intended: the default lip-sync (`ltx_av`) needs no InsightFace. Our LatentSync path uses the MediaPipe face landmarker (Apache-2.0) with the anime-face fallback (MIT). InsightFace is never a default. |
| MuseTalk (research comparison only, not in the app) | — | MIT code | [repo](https://github.com/TMElyralab/MuseTalk) | `scripts/spark_lipsync_musetalk.py` only |
| ffmpeg | Era grade, mux, export | LGPL-2.1+ / GPL depending on build | [ffmpeg.org/legal](https://ffmpeg.org/legal.html) | invoked as a CLI |

Details: [docs/MODEL_STACK.md](docs/MODEL_STACK.md). Newer models to watch per stage: [docs/MODEL_WATCH.md](docs/MODEL_WATCH.md). To add or swap a model per stage: [docs/SWAP_A_MODEL.md](docs/SWAP_A_MODEL.md). Platform research: [docs/COMFY_PLATFORM.md](docs/COMFY_PLATFORM.md).

## Hardware

- **What works today vs. experimental vs. planned:** [docs/STATUS.md](docs/STATUS.md). It includes the full "Hardware and models" table. We measured only the DGX Spark row; every other row is an estimate. On a Mac (Apple Silicon or Intel), the app runs Preview mode and connects to a studio; it does not render on the Mac yet.
- **Tested:** NVIDIA DGX Spark (GB10, 128 GB unified memory, ARM64, CUDA 13), ComfyUI v0.41.2. We verified stills, TTS, lip-sync, the identity gate and LTX-2.5 i2v through the SDK. Measured memory and render times: [docs/HARDWARE_MEMORY.md](docs/HARDWARE_MEMORY.md).
- **24 GB GPUs (RTX 4090/5090/3090): in progress, untested.** Use fp8/int8 checkpoints (Qwen-Image-Edit fp8mixed ≈ 20 GB, LTX int8). Load one model at a time. If you see OOM, run ComfyUI with `--lowvram`. Shorter clips (≤ 5 s) help.
- **Hardware picker (Settings → Models for this computer):** on first launch and from Settings, the app reads this computer locally (nvidia-smi, `/proc/meminfo`; no network scan). It shows one card per stage (pictures, video, lip-sync, voice, music). Each card shows the model, precision, memory, license and a tested/untested/planned badge.
- **Cards:** Lip-sync shows the real default (LTX a2v, camera-locked, then LatentSync 1.6 as Stage 2). Open weights with use restrictions (OpenRAIL++-M, Llama 3.2 Community License) get an amber “Open weights, use-restricted” badge. Voice options: VoxCPM2 (default for new stories), Chatterbox (recommended), Orpheus (older stories, the Speak tab and the no-clip fallback), and Kokoro.
- **Tiers:** 1 × Spark (the only tested one), 2 × Spark (planned: the app talks to one ComfyUI address today), 32 GB card and 24 GB card. If the hardware is too small, the app shows a plain "not enough hardware" message with no fake picks. For 8-16 GB NVIDIA cards, Apple Silicon and CPU-only computers, it adds a recommendation-only tier from `presets/model_manifest.yaml`. These are estimates, not tested; the app has no Mac render backend yet.
- **Filters and settings:** a license filter (`?commercial=allowed|open_only`) marks cards it hides. Set the number of computers with `OPENSOUL_MACHINES=2` or in Settings. You can also pick a tier by hand in Settings. Preview mode can simulate any tier (`/?settings=1&simulate=rtx5090`). API: `GET /api/hardware/detect`, `GET /api/hardware/recommend?tier=…`. Config: [presets/hardware_profiles.yaml](presets/hardware_profiles.yaml); details in [docs/HARDWARE_MEMORY.md](docs/HARDWARE_MEMORY.md#hardware-picker).
- **No GPU:** the whole app, Preview-mode renders, Era grade and export run on CPU (`OPENSOUL_DRY_RUN=1`). That's how the tests and screenshots run.

## Setup and run

Get the code first. The public repository link comes with the first release. <!-- PUBLISH-TODO:REPO_URL -->
Then, in the `opensoul` folder:

```bash
./scripts/setup_dev.sh                                  # venv + install + tests
source .venv/bin/activate && OPENSOUL_DRY_RUN=1 OPENSOUL_DEMO_CAST=1 opensoul-ui   # → http://127.0.0.1:7860
```

`OPENSOUL_DEMO_CAST=1` (the demo / judge path) lists only the example cast (Juno Pell, Lumi, Mio, Ren; Pixel the robot is on the Create page) and the characters you make in this session. Do not set it for your own studio.

Requires Python ≥ 3.10 (with `venv`; on Debian/Ubuntu `sudo apt install python3-venv`) and ffmpeg. No GPU, model weights or ComfyUI needed for this path. Deep links: `?step=1|2|3`. Change the port with `OPENSOUL_PORT=7861`.

`setup_dev.sh` runs the CPU test suite (it skips one test without torch) and the workflow node allowlist check. To re-run them by hand: `pytest -q && python scripts/check_workflows.py`.

**Fresh clone with a GPU** (Linux, NVIDIA, ≥ 24 GB VRAM or unified memory; Python ≥ 3.10, git, curl, ffmpeg):

```bash
# 1. App + tests (CPU), in the opensoul folder (see "Get the code" above)
./scripts/setup_dev.sh && source .venv/bin/activate

# 2. ComfyUI next to the app (any recent ComfyUI with LTX-2.5 support; tested v0.41.2)
export OPENSOUL_HOME=$HOME/OpenSoul COMFY_DIR=$HOME/OpenSoul/ComfyUI
git clone --branch v0.41.2 --depth 1 https://github.com/Comfy-Org/ComfyUI "$COMFY_DIR"
pip install -r "$COMFY_DIR/requirements.txt"      # install the CUDA torch build for your GPU first
ln -s "$PWD/custom_nodes/opensoul_nodes" "$COMFY_DIR/custom_nodes/"

# 3. Models (official Hugging Face repos, sha256-checked). LTX-2.5 is gated:
#    accept the LTX-2.x Community License on huggingface.co, then:
export HF_TOKEN=...                                # your own read token
pip install -U huggingface_hub                     # provides the `hf` CLI (Chatterbox, LatentSync snapshots)
git clone https://github.com/bytedance/LatentSync "$OPENSOUL_HOME/LatentSync"   # before the download: weights land in its checkpoints/
./scripts/download_models.sh --dry-run             # see what will be fetched + PREFLIGHT warnings (~60 GB with int8 LTX)
ALLOW_PICKLE=1 ./scripts/download_models.sh        # stills video tts lipsync; LTX_VARIANT=bf16 for big GPUs

# 4. Per-model venvs used by the node pack (paths in custom_nodes/opensoul_nodes/nodes.py):
#    tts-env (kokoro), chatterbox-env (chatterbox-tts), latentsync-env (LatentSync requirements.txt)

# 5. Run: ComfyUI → comfy-api-proxy → app
python "$COMFY_DIR/main.py" --listen 127.0.0.1 --port 8188 &      # add --lowvram on 24 GB cards
pip install comfy-sdk comfy-api-proxy
comfy-api-proxy --comfyui http://127.0.0.1:8188 --port 8189 &     # Comfy API v2 in front of local ComfyUI
export COMFY_BASE_URL=http://127.0.0.1:8189 OPENSOUL_DRY_RUN=0
export OPENSOUL_TTS=orpheus OPENSOUL_LIPSYNC=ltx_av              # or kokoro / chatterbox; latentsync (alt)
# Orpheus venv + weights (once): scripts/setup_tts_orpheus.sh
opensoul-ui

# one workflow by hand, through the SDK:
python scripts/sdk_run.py workflows/03_tts_api.json --set "1.text=Hello" --output-node 2 --out out/
```

The identity gate defaults to the Apache-2.0 patch backend and needs no extra weights. The optional ArcFace backend (`workflows/06b`, InsightFace `buffalo_l`, **non-commercial weights**) needs `pip install insightface onnxruntime` in the env named by `OPENSOUL_IDSIM_PY`; `./scripts/download_models.sh arcface` prints the details. DGX Spark users can use `./scripts/setup_spark.sh` instead of steps 2–3.

The node pack calls each model in its own venv; set `OPENSOUL_HOME` or the per-model paths documented in `custom_nodes/opensoul_nodes/nodes.py`.

## How it uses the Comfy Developer Platform

- Every GPU stage is a ComfyUI **API-format workflow** in `workflows/`. The stages are stills (02), TTS (03, 03b), LTX I2V/A2V (04, 04b), lip-sync (05), identity gate (06) and character sheet (07).
- `opensoul/comfy_client.py` runs all of them through the official **Comfy SDK** (`comfy-sdk`). It uploads assets with `client.assets.from_file` and sets node inputs by id (it validates them against the graph). It submits the job to **Comfy API v2** and downloads the outputs. The app's live TTS, lip-sync, stills and video paths only call this function.
- Locally, the SDK reaches ComfyUI through Comfy's own `comfy-api-proxy`, the self-hosting path documented at [docs.comfy.org](https://docs.comfy.org/development/comfyui-server/api-proxy). Pointing `COMFY_BASE_URL` (and `COMFY_API_KEY`) at a Comfy API deployment would use the same code. **We have not run it on Comfy Cloud.**
- TTS, LatentSync and the identity gate (default: Apache-2.0 patch backend; optional ArcFace backend) are our own **custom node pack** (`custom_nodes/opensoul_nodes`, Apache-2.0).
- `scripts/check_workflows.py` (run in CI and in pytest) fails if a workflow uses any node outside `workflows/node_allowlist.json` (core nodes + our pack) or any partner/API node.
- Presets are plain JSON (`presets/`), so anyone can add a camera move or effect without touching code. `opensoul/presets.py` maps a tile to workflow node inputs.
- No Router or partner-node calls (Open Weights Only). Proof run: [docs/evidence/COMFY_SDK_PROOF.md](docs/evidence/COMFY_SDK_PROOF.md).

Architecture diagram: [docs/ARCHITECTURE_DIAGRAM.md](docs/ARCHITECTURE_DIAGRAM.md).

## Project layout

```
app/          FastAPI server + static UI (six-step story timeline, Music videos, Shorts)
opensoul/     packs, consistency, presets, shot runner, speak, era, Comfy client
presets/      camera/*.json, effects/*.json, eras.json, voices.json
workflows/    ComfyUI API workflows + node_allowlist.json
custom_nodes/ opensoul_nodes: Orpheus, Kokoro, Chatterbox, LatentSync, ArcFace identity gate
tests/        pytest (CPU only)
```

## Credits and licenses

- **Code:** Apache-2.0 ([LICENSE](LICENSE)). Third-party notices: [NOTICE](NOTICE).
- **Demo characters "Lumi" and "Pixel":** Lumi is an original AI-generated character, assets **all rights reserved** ([ASSETS_LICENSE](ASSETS_LICENSE)). Her current look (and Mio's and Ren's) <!-- origin:readme_note -->comes from concept images from a closed (non-open) image generator. We are rebuilding it from text with open models. Those concept-derived files<!-- /origin:readme_note --> are not in any export (`opensoul/export_guard.py`). The open-models claim is about the tool, not these demo assets. Pixel, the neutral example character in `assets/example_character/`, is Apache-2.0, so use that one for your own builds.
- **Models and tools:** each keeps its own license (see the license table above). LTX-2.x is under the LTX Community License. InsightFace models are non-commercial: only the optional ArcFace gate uses them, and the LatentSync path until the MediaPipe switch is complete. Read them before commercial use.
- **Built with Llama.** The fallback voice, Orpheus TTS 3B, is fine-tuned from Meta Llama 3.2 3B; Llama 3.2 is licensed under the [Llama 3.2 Community License](https://www.llama.com/llama3_2/license/), Copyright © Meta Platforms, Inc. All Rights Reserved.
- **Fonts:** title cards use a bold font that your computer already has (for example Helvetica, Arial, Segoe UI, DejaVu Sans or Liberation Sans). With none of them, OpenSoul uses the Pillow default font. OpenSoul ships no font files.
- Built on [ComfyUI](https://github.com/Comfy-Org/ComfyUI), the [Comfy SDK](https://github.com/Comfy-Org/comfy-python-sdk), Qwen-Image-Edit, Z-Image-Turbo, LTX-2.5, ACE-Step, VoxCPM2, Orpheus TTS (Built with Llama), Kokoro, Chatterbox, LatentSync, InsightFace and ffmpeg. Feature research: [docs/HIGGSFIELD_TEARDOWN.md](docs/HIGGSFIELD_TEARDOWN.md).
- **AI-generated content.** Videos made with OpenSoul are AI-generated. Juno Pell, Lumi, Mio, Ren and Pixel are AI-generated characters. Every shared caption and the credits card say so (the LTX-2.x Community License asks you to label AI-generated output).
- Not affiliated with Higgsfield. We use "Higgsfield" only to describe the contest theme.
