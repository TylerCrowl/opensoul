#!/usr/bin/env bash
# OpenSoul model downloader: fetches every open-weight model the GPU path needs into ComfyUI's models/ tree
# (plus $OPENSOUL_HOME for the node-pack models). Official Hugging Face repos only; sha256-checked where pinned.
#
#   ./scripts/download_models.sh [--dry-run] [groups...]
#   groups: stills  sheet  master  video  tts  orpheus  lipsync  arcface  motion  pose  music   (default: stills sheet master video tts orpheus lipsync)
#   master = Z-Image-Turbo (Tongyi-MAI, Apache-2.0; ~12 GB + 8 GB TE + VAE) for the text-only master (workflows/07z)
#   motion (optional): LTX Union Control IC-LoRA for the experimental re-perform / motion-transfer path (docs/GENJUTSU_EVAL.md)
#   music (optional): ACE-Step 1.5 XL Turbo (MIT; ~30 GB) for the Music tab song step (workflows/08m);
#         ACE_XL_BASE=1 also fetches the optional XL base (MIT; ~20 GB) for vocal separation (off by default)
#   pose (optional): DWPose wholebody + YOLOX-L ONNX (Apache-2.0) for scripts/make_pose_guide.py (guide video made outside Comfy)
#   sheet = Qwen-Image-Edit-2511 bf16 (~41 GB) for the one-tap Character Sheet (workflows/07, 07b); skip it on small disks/GPUs
#
# Env: COMFY_DIR (default $OPENSOUL_HOME/ComfyUI), OPENSOUL_HOME (default ~/OpenSoul),
#      HF_TOKEN (needed for the gated Lightricks/LTX-2.5 repo; accept its license on huggingface.co first),
#      LTX_VARIANT=int8|bf16 (default int8, ~24 GB GPUs), ALLOW_PICKLE=1 (needed for Kokoro/.pth weights).
# Group "arcface" (InsightFace buffalo_l, NON-COMMERCIAL weights) is opt-in only and never in the default set.
set -euo pipefail

DRY=0; SEL=()
for a in "$@"; do case "$a" in --dry-run) DRY=1 ;; -h|--help) sed -n 2,12p "$0"; exit 0 ;; *) SEL+=("$a") ;; esac; done
[[ ${#SEL[@]} -eq 0 ]] && SEL=(stills sheet master video tts orpheus lipsync)

# Preflight: say up front what will fail later, instead of failing 20 GB into the run.
preflight() {
  local warn=0 g
  for g in "${SEL[@]}"; do
    case "$g" in
      video) [[ -n "${HF_TOKEN:-}" ]] || { echo "PREFLIGHT: HF_TOKEN is not set; Lightricks/LTX-2.5 is gated (accept its license on huggingface.co, then export HF_TOKEN=...)" >&2; warn=1; } ;;
      tts) [[ "${ALLOW_PICKLE:-0}" == 1 ]] || { echo "PREFLIGHT: ALLOW_PICKLE=1 is needed for the Kokoro .pth/.pt weights" >&2; warn=1; } ;;
    esac
    [[ "$g" == lipsync && ! -d "$OPENSOUL_HOME/LatentSync/.git" ]] && { echo "PREFLIGHT: clone LatentSync first (weights go into its checkpoints/): git clone https://github.com/bytedance/LatentSync \"\$OPENSOUL_HOME/LatentSync\"" >&2; warn=1; }
    case "$g" in tts|orpheus|lipsync) command -v hf >/dev/null || { echo "PREFLIGHT: the hf CLI is missing (pip install -U huggingface_hub); needed for group $g" >&2; warn=1; } ;; esac
  done
  command -v curl >/dev/null || { echo "PREFLIGHT: curl is missing" >&2; warn=1; }
  return $warn
}

OPENSOUL_HOME="${OPENSOUL_HOME:-$HOME/OpenSoul}"
COMFY_DIR="${COMFY_DIR:-$OPENSOUL_HOME/ComfyUI}"
M="$COMFY_DIR/models"
LTX_VARIANT="${LTX_VARIANT:-int8}"
HF="https://huggingface.co"
MP_MODELS="https://storage.googleapis.com/mediapipe-models"

log() { printf '==> %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# fetch <url> <dest> [sha256]
fetch() {
  local url="$1" dest="$2" sum="${3:-}"
  # Official sources only: Hugging Face, plus Google's MediaPipe model bucket (sha256 required for that one).
  if [[ "$url" == "$MP_MODELS/"* ]]; then [[ -n "$sum" ]] || die "MediaPipe model needs a pinned sha256: $url"
  elif [[ "$url" != "$HF/"* ]]; then die "refusing non-Hugging Face URL: $url"; fi
  case "$dest" in *.pth|*.pt|*.bin) [[ "${ALLOW_PICKLE:-0}" == 1 || $DRY == 1 ]] || die "pickle file $dest needs ALLOW_PICKLE=1" ;; esac
  if [[ $DRY == 1 ]]; then printf 'DRY  %s\n     -> %s\n' "$url" "$dest"; return 0; fi
  mkdir -p "$(dirname "$dest")"
  if [[ ! -f "$dest" ]]; then
    log "download $(basename "$dest")"
    local auth=(); [[ -n "${HF_TOKEN:-}" ]] && auth=(-H "Authorization: Bearer $HF_TOKEN")
    curl -fL --retry 5 --retry-delay 5 -C - "${auth[@]}" -o "$dest.part" "$url" || die "download failed: $url"
    mv "$dest.part" "$dest"
  else
    log "exists: $(basename "$dest")"
  fi
  if [[ -n "$sum" ]]; then
    echo "$sum  $dest" | sha256sum -c --status - || die "sha256 mismatch: $dest"
  fi
}

# snapshot <repo> <dest-dir>: whole official repo via the hf CLI (pip install -U huggingface_hub)
snapshot() {
  if [[ $DRY == 1 ]]; then printf 'DRY  hf download %s\n     -> %s\n' "$1" "$2"; return 0; fi
  command -v hf >/dev/null || die "need the hf CLI: pip install -U huggingface_hub"
  hf download "$1" --local-dir "$2"
}

sheet() {
  # Character Sheet (workflows/07 + 07b) uses the bf16 edit model; it shares the text encoder, VAE and Lightning LoRA with "stills".
  local Q="$HF/Comfy-Org/Qwen-Image-Edit_ComfyUI/resolve/main/split_files"
  fetch "$Q/diffusion_models/qwen_image_edit_2511_bf16.safetensors" "$M/diffusion_models/qwen_image_edit_2511_bf16.safetensors" ae42d927b5fac4f278b9a894554c727e619727a63622976f2d95625be4bce08c
}

master() {
  # Text-only master (workflows/07z, presets/text_master.json): Z-Image-Turbo, Tongyi-MAI/Z-Image-Turbo (Apache-2.0),
  # as Comfy-Org's split files (same license).
  local Z="$HF/Comfy-Org/z_image_turbo/resolve/main/split_files"
  fetch "$Z/diffusion_models/z_image_turbo_bf16.safetensors" "$M/diffusion_models/z_image_turbo_bf16.safetensors" 2407613050b809ffdff18a4ac99af83ea6b95443ecebdf80e064a79c825574a6
  fetch "$Z/text_encoders/qwen_3_4b.safetensors" "$M/text_encoders/qwen_3_4b.safetensors" 6c671498573ac2f7a5501502ccce8d2b08ea6ca2f661c458e708f36b36edfc5a
  fetch "$Z/vae/ae.safetensors" "$M/vae/ae.safetensors" afc8e28272cd15db3919bacdb6918ce9c1ed22e96cb12c4d5ed0fba823529e38
}

stills() {
  local Q="$HF/Comfy-Org/Qwen-Image-Edit_ComfyUI/resolve/main/split_files" QI="$HF/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files"
  fetch "$Q/diffusion_models/qwen_image_edit_2511_fp8mixed.safetensors" "$M/diffusion_models/qwen_image_edit_2511_fp8mixed.safetensors" c9fdc158e46d3b61ef75f21ae866ca2fe808bf4a53643120d1c1e87c19280a4e
  fetch "$QI/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors" "$M/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors" cb5636d852a0ea6a9075ab1bef496c0db7aef13c02350571e388aea959c5c0b4
  fetch "$QI/vae/qwen_image_vae.safetensors" "$M/vae/qwen_image_vae.safetensors" a70580f0213e67967ee9c95f05bb400e8fb08307e017a924bf3441223e023d1f
  fetch "$HF/lightx2v/Qwen-Image-Edit-2511-Lightning/resolve/main/Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors" \
        "$M/loras/Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors" 22226e8d05d354bb356627d428809f5afd7819399b077238a2b70a82883a904f
}

video() {
  local L="$HF/Lightricks/LTX-2.5/resolve/main"
  [[ -n "${HF_TOKEN:-}" || $DRY == 1 ]] || die "LTX-2.5 is gated: accept the LTX-2.x Community License on huggingface.co, then export HF_TOKEN"
  if [[ "$LTX_VARIANT" == bf16 ]]; then
    fetch "$L/diffusion_models/ltx-2.5-22b-distilled-transformer-bf16.safetensors" "$M/diffusion_models/ltx-2.5-22b-distilled-transformer-bf16.safetensors" 31eb3cad89b9e54e99dd3baf286f70825ac4f6c660a70d9184d895be76d7bff4
    fetch "$L/text_encoders/gemma4-12b-with-proj-ltx-2.5-bf16.safetensors" "$M/text_encoders/gemma4-12b-with-proj-ltx-2.5-bf16.safetensors" ef7243612fdae7a75cb4d5cee9433e81380675fb6c213bd98ae74a9cd16561d1
  else
    fetch "$L/diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors" "$M/diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors" c4279eeff115cbeaca494bd2183e7d768c38fe85a184dc6afbb7159157c44334
    fetch "$L/text_encoders/gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors" "$M/text_encoders/gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors" 6ce688a0aa98a5fa36a9f1e6c3f42152a498cc2b53ee8c15674c64244f91487f
  fi
  fetch "$L/vae/ltx-2.5-video-vae-bf16.safetensors" "$M/vae/ltx-2.5-video-vae-bf16.safetensors" 847e14ca7f3355debca0cea4eaa24ac0fbcdf0061da054ac89ca638a869ddba3
  fetch "$L/vae/ltx-2.5-audio-vae-bf16.safetensors" "$M/vae/ltx-2.5-audio-vae-bf16.safetensors" c52733d37f6a7fb7949c3dc0fb468c6cb2169e4d836983a73babb9f0d54837a5
  fetch "$L/latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors" "$M/latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors" eb5a71fe4068ee87ccdb1c3aa635e547ca76bd2d30ae20ae889f2c325c0677e8
}

tts() {
  local K="$HF/hexgrad/Kokoro-82M/resolve/f3ff3571791e39611d31c381e3a41a3af07b4987" D="$OPENSOUL_HOME/models/kokoro"
  fetch "$K/config.json" "$D/config.json" 5abb01e2403b072bf03d04fde160443e209d7a0dad49a423be15196b9b43c17f
  fetch "$K/kokoro-v1_0.pth" "$D/kokoro-v1_0.pth" 496dba118d1a58f5f3db2efc88dbdc216e0483fc89fe6e47ee1f2c53f18ad1e4
  # Every voice offered in the UI (presets/voices.json) plus the node default am_michael.
  local v sum
  for v in am_michael:9a443b79a4b22489a5b0ab7c651a0bcd1a30bef675c28333f06971abbd47bd37 \
           af_heart:0ab5709b8ffab19bfd849cd11d98f75b60af7733253ad0d67b12382a102cb4ff \
           am_fenrir:98e507eca1db08230ae3b6232d59c10aec9630022d19accac4f5d12fcec3c37a \
           bf_emma:d0a423deabf4a52b4f49318c51742c54e21bb89bbbe9a12141e7758ddb5da701; do
    sum=${v#*:}; v=${v%%:*}
    fetch "$K/voices/$v.pt" "$D/voices/$v.pt" "$sum"
  done
  # Chatterbox (MIT): its package pulls ResembleAI/chatterbox from the Hub on first use; pre-fetch here.
  snapshot ResembleAI/chatterbox "$OPENSOUL_HOME/models/chatterbox"
}

orpheus() {
  # Orpheus 3B 0.1 finetuned (canopylabs, Apache-2.0; Built with Llama 3.2) as a Q4_K_M GGUF for llama.cpp, plus the
  # SNAC 24 kHz decoder (MIT). Default voice engine; the venv is made by scripts/setup_tts_orpheus.sh.
  fetch "$HF/lex-au/Orpheus-3b-FT-Q4_K_M.gguf/resolve/51079fc5f7de3e137cdb453398baa1d4bc1614dc/Orpheus-3b-FT-Q4_K_M.gguf" \
        "$OPENSOUL_HOME/models/orpheus/Orpheus-3b-FT-Q4_K_M.gguf" 18284d3efd9831d0a8409f5f5877c84bff69009df7c3db818e904dccea6b6c55
  snapshot hubertsiuzdak/snac_24khz "$OPENSOUL_HOME/models/snac_24khz"
}

lipsync() {
  # LatentSync 1.6 (code Apache-2.0, weights CreativeML OpenRAIL++-M). Clone the code yourself:
  #   git clone https://github.com/bytedance/LatentSync "$OPENSOUL_HOME/LatentSync"
  snapshot ByteDance/LatentSync-1.6 "$OPENSOUL_HOME/LatentSync/checkpoints"
  # Face detector for LatentSync (runners/ls_face_detector.py). Replaces upstream's InsightFace buffalo_l, whose
  # weights are NON-COMMERCIAL: OpenSoul never downloads buffalo_l for lip-sync and blocks `import insightface`.
  # MediaPipe FaceLandmarker (BlazeFace + FaceMesh-V2), Apache-2.0, Google's official model bucket.
  fetch "$MP_MODELS/face_landmarker/face_landmarker/float16/1/face_landmarker.task" \
        "$OPENSOUL_HOME/models/mediapipe/face_landmarker.task" \
        64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff
  # Optional anime-face fallback (hysts/anime-face-detector, code + weights MIT; safetensors). Needs
  # anime-face-detector 0.1.x in latentsync-env (pip install "git+https://github.com/hysts/anime-face-detector@98a9fb4");
  # without it MediaPipe runs alone.
  # Pinned revisions, sha256-checked (the hf CLI prints the cached file's path).
  local r f rev sum path
  for r in yolov3:afdd4226a79ae8bb81f334dbcffd34f8cc000c38:23bbc708146bcbc1c910f00fe152adbc70d7658d875a0121eaf4ee61d978b2c4 \
           hrnetv2:9b3435248b26aeb82e2a8578fe9d86d5d57158af:e71271376406a743c01528a0460637fcc06e72aeeea583f85007cc72dc8b7a4a; do
    IFS=: read -r f rev sum <<<"$r"
    if [[ $DRY == 1 ]]; then printf 'DRY  hf download hysts/anime-face-detector-%s model.safetensors --revision %s (HF cache)\n' "$f" "$rev"; continue; fi
    path=$(hf download "hysts/anime-face-detector-$f" model.safetensors --revision "$rev" | tail -n 1)
    echo "$sum  $path" | sha256sum -c --status - || die "sha256 mismatch: hysts/anime-face-detector-$f"
  done
}

music() {
  # Music tab song model (workflows/08m, presets/music_models.json "ace_step"): ACE-Step 1.5 XL Turbo (ACE-Step, MIT) as
  # Comfy-Org's split files at a pinned revision (repack card says Apache-2.0; upstream MIT governs). ~30 GB. Optional,
  # not in the default set. Not yet validated on a GPU from OpenSoul.
  local A="$HF/Comfy-Org/ace_step_1.5_ComfyUI_files/resolve/6707deb277e9e0907fd9c14ce6b6f1d695c6a3fc/split_files"
  fetch "$A/diffusion_models/acestep_v1.5_xl_turbo_bf16.safetensors" "$M/diffusion_models/acestep_v1.5_xl_turbo_bf16.safetensors" 86a1afb0a1f711f0e3304ff65d874df3ae6783db683dcf982513fb9b6d14ae71
  fetch "$A/text_encoders/qwen_0.6b_ace15.safetensors" "$M/text_encoders/qwen_0.6b_ace15.safetensors" fd4590c82153b8ddb67e15a2e7aaa8afa8b83a858c8a9b82a4831063156aa7a7
  fetch "$A/text_encoders/qwen_4b_ace15.safetensors" "$M/text_encoders/qwen_4b_ace15.safetensors" ffe5ffb855086c2ab55e467e9859fb01894781020a0376484dd19de166b79873
  fetch "$A/vae/ace_1.5_vae.safetensors" "$M/vae/ace_1.5_vae.safetensors" 6de92e3a862acd287e08b024ac90f0783a8635451b728721a33ff03565bcb2bb
  # Optional, off by default: ACE-Step 1.5 XL base (MIT, ~20 GB) for vocal separation (the 'extract' task runs on base
  # models only, not on XL Turbo). For the ACE-Step Python env; the app's runner for it is a stub, untested.
  # Fetch with: ACE_XL_BASE=1 ALLOW_PICKLE=1 ./scripts/download_models.sh music   (silence_latent.pt is a pickle)
  if [[ "${ACE_XL_BASE:-0}" != 1 ]]; then log "skip ACE-Step 1.5 XL base (optional vocal separation; ACE_XL_BASE=1 to fetch)"; return 0; fi
  local xb="$OPENSOUL_HOME/models/ace_step/checkpoints/acestep-v15-xl-base" xrev=220c1166efbdd9583eafcb12eb160594bbfcb241 x f sum
  if [[ $DRY == 1 ]]; then printf 'DRY  hf download ACE-Step/acestep-v15-xl-base --revision %s\n     -> %s\n' "$xrev" "$xb"; return 0; fi
  [[ "${ALLOW_PICKLE:-0}" == 1 ]] || die "acestep-v15-xl-base includes silence_latent.pt (pickle): set ALLOW_PICKLE=1"
  command -v hf >/dev/null || die "need the hf CLI: pip install -U huggingface_hub"
  hf download ACE-Step/acestep-v15-xl-base --revision "$xrev" --local-dir "$xb" >/dev/null
  for x in model-00001-of-00004.safetensors:da654de2a66ace691fb06fedca81f14d20451eecd534c04a69d2f0207303ef23 \
           model-00002-of-00004.safetensors:ade70e18afcf9e3b656cda04e15b52d1a480f4d6a0e40141f3e614a4103a279a \
           model-00003-of-00004.safetensors:e44b5ec5fa00bb5a0da423355772bfb3688d1330d70ba65cfd5611eebb20f9d5 \
           model-00004-of-00004.safetensors:3994ec426e1fb1cc92488b3fffa8bbbf86e8daa83ab23a4dc11eeb0ad12db52b \
           silence_latent.pt:a778e9dd942f5e8b2c09c55370782d318834432b03dabbcdf70e6ed49ad6358b; do
    f=${x%%:*}; sum=${x#*:}
    echo "$sum  $xb/$f" | sha256sum -c --status - || die "sha256 mismatch: acestep-v15-xl-base/$f"
  done
}

motion() {
  # Official LTX-2.5 workflow LTX-2.5_ICLoRA_Union_Control_Distilled.json (ComfyUI-LTXVideo) loads this 2.3 IC-LoRA on the
  # 2.5 distilled transformer (needs LTX_VARIANT=bf16 video group). LTX-2 Community License. Pose/depth guides are made outside Comfy.
  fetch "$HF/Lightricks/LTX-2.3-22b-IC-LoRA-Union-Control/resolve/main/ltx-2.3-22b-ic-lora-union-control-ref0.5.safetensors" \
        "$M/loras/ltx-2.3-22b-ic-lora-union-control-ref0.5.safetensors" a1b888a87f661d27f08b394ae559e8e1050be33900bcc36a5cdf659e48f88d18
}

pose() {
  # DWPose (Apache-2.0, huggingface.co/yzd-v/DWPose). Used by scripts/make_pose_guide.py, no Comfy custom nodes needed.
  fetch "$HF/yzd-v/DWPose/resolve/main/yolox_l.onnx" "$OPENSOUL_HOME/models/dwpose/yolox_l.onnx" \
        7860ae79de6c89a3c1eb72ae9a2756c0ccfbe04b7791bb5880afabd97855a411
  fetch "$HF/yzd-v/DWPose/resolve/main/dw-ll_ucoco_384.onnx" "$OPENSOUL_HOME/models/dwpose/dw-ll_ucoco_384.onnx" \
        724f4ff2439ed61afb86fb8a1951ec39c6220682803b4a8bd4f598cd913b1843
}

arcface() {
  log "WARNING: InsightFace buffalo_l weights are licensed for NON-COMMERCIAL research only."
  log "Only needed for the optional backend=\"arcface\" identity gate (workflows/06b). insightface downloads"
  log "buffalo_l itself on first use: pip install insightface onnxruntime in the env named by OPENSOUL_IDSIM_PY."
}

if ! preflight; then
  if [[ $DRY == 1 ]]; then echo "(dry run: listing anyway; fix the PREFLIGHT items before the real run)" >&2
  else die "fix the PREFLIGHT items above and rerun"; fi
fi
for g in "${SEL[@]}"; do
  case "$g" in stills|sheet|master|video|tts|orpheus|lipsync|arcface|motion|pose|music) log "group: $g"; "$g" ;; *) die "unknown group: $g" ;; esac
done
log "done (models under $M and $OPENSOUL_HOME)"
