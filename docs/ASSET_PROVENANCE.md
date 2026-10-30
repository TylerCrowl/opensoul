# Asset provenance

Contest rule: submissions must not contain unlicensed IP or real people’s likenesses.
Every image currently in this repository is listed below with origin and license.

**Closed-generator lineage (corrected Oct 18 2026).** The `assets/lumi/concepts/` images were made with a closed
(non-open) image generator, and so were the Mio and Ren couple concepts. Lumi's v3 sheet and references, the stills and
pack refs cropped from them, the konbini stage plate and the demo film's start frames descend from those concepts. <!-- origin:provenance_note -->The current demo looks are being rebuilt from text with open models.<!-- /origin:provenance_note -->
Concept files and every file the release check's hash
gate matches are left out of every export and release archive (`opensoul/export_guard.py`, `.gitattributes`). The
"open weights" claims in this repo are about the tool, not these demo assets.

| Path | Origin | Likeness / IP | License / rights |
|------|--------|---------------|------------------|
| `assets/demo_samples/lumi_pack/refs/ref_*.png`, `lumi_still_0[1-3]_*.png`, `lumi_sheet_preview.jpg` | Crops / letterbox of `assets/lumi/lumi_character_sheet_v3_trimmed.jpg` (`scripts/make_demo_samples.py`) | Lumi, original AI character (see `assets/lumi/README.md`) | **All rights reserved** (`ASSETS_LICENSE`) · **not in release archives**: live app only, until the open-model rebuild replaces it (`opensoul/export_guard.py`) |
| `assets/demo_samples/lumi_still_reject_demo.png` | Close-up crop of Lumi's retired v1 sheet (`assets/lumi/lumi_character_sheet_v1.jpg`), off-model on purpose | Lumi | Same as source sheet · **not in release archives**: live app only, until the open-model rebuild replaces it (`opensoul/export_guard.py`) |
| `assets/demo_samples/lumi_video_poster.png` | 9:16 crop of `assets/lumi/concepts/v3_cold_open.jpg` | Lumi | Same as source · **not in release archives**: live app only, until the open-model rebuild replaces it (`opensoul/export_guard.py`) |
| `assets/demo_samples/pixel_pack/refs/ref_00.png` | Copy of `assets/example_character/pixel_reference.png` with its caption box and footnote painted out (`scripts/make_demo_samples.py`) | No real person | **Apache-2.0** with the repo |
| `assets/preset_thumbs/**/*.mp4` | CPU placeholders made with ffmpeg from `concepts/v3_real_coffee.jpg`, `concepts/v3_cold_open.jpg` and the v3 Lumi stills (`scripts/make_preset_tile_placeholders.py`); closed-generator lineage | Lumi | Same as the Lumi stills · **not in release archives**: live app only, until the open-model rebuild replaces it (`opensoul/export_guard.py`) |
| `docs/media/opensoul_demo.gif` | First 5 s of the Lumi shot "Real coffee" v7 (LTX-2.5 i2v on the Spark), cropped, 400 px / 8 fps | Lumi | Same as the Lumi assets · **not in release archives**: live app only, until the open-model rebuild replaces it (`opensoul/export_guard.py`) |
| `app/web/static/opensoul-icon.svg`, `packaging/icon/OpenSoul-1024.png` | OpenSoul app icon, original vector artwork written for this repo (a friendly soul on the OpenSoul blue); the PNG is rendered from the SVG (`packaging/make_icon.py`) and becomes the .icns/.ico/.png in the packages | No real person, no third-party or Apple artwork | **Apache-2.0** with the repo |
| `assets/example_character/pixel_reference.png` | Original geometric placeholder drawn with Pillow for CI/docs | No real person | **Apache-2.0** with the repo |
| `assets/music_candidates/long_trail_kevin_macleod.ogg` (not committed; `scripts/fetch_demo_music.sh`) | Demo soundtrack *Long Trail* by Kevin MacLeod (FreePD) | Instrumental, no likeness | **Public domain** per https://commons.wikimedia.org/wiki/File:Kevin_MacLeod_-_Long_Trail.ogg (CC0 alternates by Monplaisir listed in `assets/music_candidates/README.md`) |

## Removed / not shipped

| Former asset | Why removed |
|--------------|-------------|
| Unsplash portrait used briefly as the "Needs a redo" demo still of the first demo character (Michael Dam / `photo-1494790108377-be9c29b29330`) | Real-person likeness; contest forbids unlicensed likenesses. Deleted from the tree on Oct 15 2026 and replaced with an AI-generated crop; that character was retired later (next row). |
| The first demo character (all sheets, demo crops, preset tiles, scripts, evidence stills and voice samples) | Retired on Oct 18 2026 (brand tie); replaced by Lumi and Pixel. Not in the tree any more; the public repo is published as a fresh history. |

## Notes

- Model checkpoints are **not** stored in this repo; see `docs/MODEL_STACK.md`.
- Screenshots under `ui_shots/` are local capture artifacts of the UI, not product assets for redistribution.

## Model weights used on the Spark (not stored in this repo)

Downloaded 2026-10-16 directly from huggingface.co (no mirrors) or download.pytorch.org. Repo owner verified via the HF API `author` field. Pickle-format files (`.pth`/`.pt`/`.bin`) are used only from these official repos, with the owner's approval, and are loaded with `torch.load(weights_only=True)` where we control the loader.

### Image / video (safetensors only; fetched from `main`)

| File | Source (owner verified) | sha256 |
|---|---|---|
| `ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors` | https://huggingface.co/Lightricks/LTX-2.5/resolve/main/diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors | `c4279eeff115cbeaca494bd2183e7d768c38fe85a184dc6afbb7159157c44334` |
| `gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors` | https://huggingface.co/Lightricks/LTX-2.5/resolve/main/text_encoders/gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors | `6ce688a0aa98a5fa36a9f1e6c3f42152a498cc2b53ee8c15674c64244f91487f` |
| `ltx-2.5-video-vae-bf16.safetensors` | https://huggingface.co/Lightricks/LTX-2.5/resolve/main/vae/ltx-2.5-video-vae-bf16.safetensors | `847e14ca7f3355debca0cea4eaa24ac0fbcdf0061da054ac89ca638a869ddba3` |
| `ltx-2.5-audio-vae-bf16.safetensors` | https://huggingface.co/Lightricks/LTX-2.5/resolve/main/vae/ltx-2.5-audio-vae-bf16.safetensors | `c52733d37f6a7fb7949c3dc0fb468c6cb2169e4d836983a73babb9f0d54837a5` |
| `ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors` | https://huggingface.co/Lightricks/LTX-2.5/resolve/main/latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors | `eb5a71fe4068ee87ccdb1c3aa635e547ca76bd2d30ae20ae889f2c325c0677e8` |
| `ltx-2.5-22b-distilled-transformer-bf16.safetensors` | https://huggingface.co/Lightricks/LTX-2.5/resolve/main/diffusion_models/ltx-2.5-22b-distilled-transformer-bf16.safetensors | `31eb3cad89b9e54e99dd3baf286f70825ac4f6c660a70d9184d895be76d7bff4` |
| `gemma4-12b-with-proj-ltx-2.5-bf16.safetensors` | https://huggingface.co/Lightricks/LTX-2.5/resolve/main/text_encoders/gemma4-12b-with-proj-ltx-2.5-bf16.safetensors | `ef7243612fdae7a75cb4d5cee9433e81380675fb6c213bd98ae74a9cd16561d1` |
| `qwen_image_edit_2511_fp8mixed.safetensors` | https://huggingface.co/Comfy-Org/Qwen-Image-Edit_ComfyUI/resolve/main/split_files/diffusion_models/qwen_image_edit_2511_fp8mixed.safetensors | `c9fdc158e46d3b61ef75f21ae866ca2fe808bf4a53643120d1c1e87c19280a4e` |
| `qwen_2.5_vl_7b_fp8_scaled.safetensors` | https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors | `cb5636d852a0ea6a9075ab1bef496c0db7aef13c02350571e388aea959c5c0b4` |
| `qwen_image_vae.safetensors` | https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/vae/qwen_image_vae.safetensors | `a70580f0213e67967ee9c95f05bb400e8fb08307e017a924bf3441223e023d1f` |
| `Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors` | https://huggingface.co/lightx2v/Qwen-Image-Edit-2511-Lightning/resolve/main/Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors | `22226e8d05d354bb356627d428809f5afd7819399b077238a2b70a82883a904f` |
| `wan2.2_ti2v_5B_fp16.safetensors` | https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/diffusion_models/wan2.2_ti2v_5B_fp16.safetensors | `456f901338bd9eadbded3828b819109a9b68e8a525ca5cf8d0049a69fcfeca1e` |
| `umt5_xxl_fp8_e4m3fn_scaled.safetensors` | https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors | `c3355d30191f1f066b26d93fba017ae9809dce6c627dda5f6a66eaa651204f68` |
| `wan2.2_vae.safetensors` | https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/vae/wan2.2_vae.safetensors | `e40321bd36b9709991dae2530eb4ac303dd168276980d3e9bc4b6e2b75fed156` |

Licenses: LTX-2.5 is the LTX-2.x Community License (gated; we accepted it on our HF account). Qwen-Image / Qwen-Image-Edit Comfy packs, the lightx2v Lightning LoRA and the Wan2.2 repack are Apache-2.0.

### TTS / lip-sync (pinned commit URLs; pickle files flagged)

| File | Source | Format | Bytes | sha256 |
|---|---|---|---|---|
| `kokoro-v1_0.pth` | https://huggingface.co/hexgrad/Kokoro-82M/resolve/f3ff3571791e39611d31c381e3a41a3af07b4987/kokoro-v1_0.pth | pickle | 327212226 | `496dba118d1a58f5f3db2efc88dbdc216e0483fc89fe6e47ee1f2c53f18ad1e4` |
| `config.json` | https://huggingface.co/hexgrad/Kokoro-82M/resolve/f3ff3571791e39611d31c381e3a41a3af07b4987/config.json | json | 2351 | `5abb01e2403b072bf03d04fde160443e209d7a0dad49a423be15196b9b43c17f` |
| `am_michael.pt` | https://huggingface.co/hexgrad/Kokoro-82M/resolve/f3ff3571791e39611d31c381e3a41a3af07b4987/voices/am_michael.pt | pickle | 523435 | `9a443b79a4b22489a5b0ab7c651a0bcd1a30bef675c28333f06971abbd47bd37` |
| `am_adam.pt` | https://huggingface.co/hexgrad/Kokoro-82M/resolve/f3ff3571791e39611d31c381e3a41a3af07b4987/voices/am_adam.pt | pickle | 523420 | `ced7e284aba12472891be1da3ab34db84cc05cc02b5889535796dbf2d8b0cb34` |
| `am_eric.pt` | https://huggingface.co/hexgrad/Kokoro-82M/resolve/f3ff3571791e39611d31c381e3a41a3af07b4987/voices/am_eric.pt | pickle | 523420 | `ada66f0eefff34ec921b1d7474d7ac8bec00cd863c170f1c534916e9b8212aae` |
| `am_liam.pt` | https://huggingface.co/hexgrad/Kokoro-82M/resolve/f3ff3571791e39611d31c381e3a41a3af07b4987/voices/am_liam.pt | pickle | 523420 | `c82550757ddb31308b97f30040dda8c2d609a9e2de6135848d0a948368138518` |
| `musetalk.json` | https://huggingface.co/TMElyralab/MuseTalk/resolve/2bcb936e2fddb4d86db4c62fd45b387d0c061571/musetalkV15/musetalk.json | json | 748 | `5b6923aee04d71692e0e9846c471e0a4ea07a4f686d39545e472bd4ba17e1b47` |
| `unet.pth` | https://huggingface.co/TMElyralab/MuseTalk/resolve/2bcb936e2fddb4d86db4c62fd45b387d0c061571/musetalkV15/unet.pth | pickle | 3400074924 | `7ebf6c98c181e20838e4c0054e96e944ac60d5d692cc01db42839fe11b787007` |
| `config.json` | https://huggingface.co/stabilityai/sd-vae-ft-mse/resolve/31f26fdeee1355a5c34592e401dd41e45d25a493/config.json | json | 547 | `92d3dfb746fca211a2c9e019e285f8597412211728dce3c5bcf4eda0f2d62e7e` |
| `diffusion_pytorch_model.safetensors` | https://huggingface.co/stabilityai/sd-vae-ft-mse/resolve/31f26fdeee1355a5c34592e401dd41e45d25a493/diffusion_pytorch_model.safetensors | safetensors | 334643276 | `a1d993488569e928462932c8c38a0760b874d166399b14414135bd9c42df5815` |
| `config.json` | https://huggingface.co/openai/whisper-tiny/resolve/169d4a4341b33bc18d8881c4b69c2e104e1cc0af/config.json | json | 1983 | `ffdccec4f3211f4c63310f2b7098f309fe70f3952cedc5e4d11e43f5b2379b98` |
| `model.safetensors` | https://huggingface.co/openai/whisper-tiny/resolve/169d4a4341b33bc18d8881c4b69c2e104e1cc0af/model.safetensors | safetensors | 151061672 | `7ebd0e69e78190ffe1438491fa05cc1f5c1aa3a4c4db3bc1723adbb551ea2395` |
| `preprocessor_config.json` | https://huggingface.co/openai/whisper-tiny/resolve/169d4a4341b33bc18d8881c4b69c2e104e1cc0af/preprocessor_config.json | json | 184990 | `9b5cd03a36fbb8a627c64d98a5b5b126ead95a77720723944487311f0110b666` |
| `dw-ll_ucoco_384.pth` | https://huggingface.co/yzd-v/DWPose/resolve/1a7144101628d69ee7a3768d1ee3a094070dc388/dw-ll_ucoco_384.pth | pickle | 406878486 | `0d9408b13cd863c4e95a149dd31232f88f2a12aa6cf8964ed74d7d97748c7a07` |
| `resnet18-5c106cde.pth` | https://download.pytorch.org/models/resnet18-5c106cde.pth | pickle | 46827520 | `5c106cde386e87d4033832f2996f5493238eda96ccf559d1d62760c4de0613f8` |

Owners: `hexgrad/Kokoro-82M` (author hexgrad, Apache-2.0), `TMElyralab/MuseTalk` (author TMElyralab, MIT), `stabilityai/sd-vae-ft-mse` (MIT), `openai/whisper-tiny` (Apache-2.0; safetensors used), `yzd-v/DWPose` (Apache-2.0), and PyTorch's official torchvision ResNet-18 (BSD). Code: MuseTalk git `0a89dec45a0192b824e3cf4daf96c239440c5ed8`; ComfyUI `v0.41.2` (`b53f77a74e21091cbdebfdf7b85fc80326932646`).

Runtime extras pulled by pip: `espeakng-loader` (bundled espeak-ng data, so no system espeak-ng or sudo is needed) and spaCy `en_core_web_sm` 3.8.0, which misaki auto-installs from the official explosion/spacy-models release.

**Not downloaded:** MuseTalk's BiSeNet face-parsing weights (`79999_iter.pth`). The upstream script fetches them from a Google Drive ID, not an official model repo. `scripts/spark_lipsync_musetalk.py` uses a feathered jaw ellipse mask instead. The DWPose checkpoint was downloaded, but it isn't used yet: running it needs mmpose/mmcv, which have to be compiled on ARM64 against Python headers we don't have. Face boxes come from OpenCV's bundled Haar cascades instead.
