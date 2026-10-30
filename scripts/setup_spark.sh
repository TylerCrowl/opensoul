#!/usr/bin/env bash
# OpenSoul bootstrap for NVIDIA DGX Spark (Grace+Blackwell, ARM64, CUDA 13).
#
# Safety contract:
#   - Run as non-root user `opensoul` (or any non-root account)
#   - No sudo, no firewall/network interface changes, no systemd installs
#   - Downloads only from allowlisted official repos (GitHub ComfyUI, PyTorch,
#     Hugging Face model hosts listed below) — safetensors weights only
#   - Writes only under $HOME/OpenSoul (override with OPENSOUL_HOME)
#
# Run ON the Spark after SSH access exists — not on the CPU-only agent box.
set -euo pipefail

if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  echo "ERROR: refuse to run as root. Use the non-root 'opensoul' user (no sudo)." >&2
  exit 1
fi

if [[ "$(id -un)" != "opensoul" ]]; then
  echo "WARNING: expected user 'opensoul', got '$(id -un)'. Continuing in $HOME (still no sudo)." >&2
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OPENSOUL_HOME="${OPENSOUL_HOME:-$HOME/OpenSoul}"
COMFY_DIR="${COMFY_DIR:-$OPENSOUL_HOME/ComfyUI}"
VENV="${VENV:-$OPENSOUL_HOME/comfyui-env}"
MODELS_DIR="${MODELS_DIR:-$COMFY_DIR/models}"
COMFY_REF="${COMFY_REF:-v0.41.2}"
# Qwen-Image-Edit-2511 variant: fp8mixed (~19.6 GB, default; fits beside other GPU tenants) or bf16 (~39 GB)
QWEN_VARIANT="${QWEN_VARIANT:-fp8mixed}"
DOWNLOAD_MODELS="${DOWNLOAD_MODELS:-0}"  # set 1 to fetch allowlisted safetensors

# Allowlisted clone / pip / weight hosts only
readonly ALLOW_GIT_COMFY="https://github.com/comfyanonymous/ComfyUI.git"
readonly ALLOW_PIP_TORCH="https://download.pytorch.org/whl/cu130"
readonly ALLOW_HF="https://huggingface.co"

log() { printf '==> %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "missing command: $1"
}

download_safetensors() {
  # download_safetensors <url> <dest>
  local url="$1" dest="$2"
  case "$url" in
    https://huggingface.co/*) ;;
    *) die "refusing non-allowlisted URL: $url" ;;
  esac
  case "$dest" in
    *.safetensors) ;;
    *) die "refusing non-safetensors destination: $dest" ;;
  esac
  mkdir -p "$(dirname "$dest")"
  if [[ -f "$dest" ]]; then
    log "exists, skip: $dest"
    return 0
  fi
  log "download $(basename "$dest")"
  # Resumable download to a .part file, renamed only on success
  curl -fL --retry 5 --retry-delay 5 -C - -o "$dest.part" "$url" || { log "download failed: $url"; return 1; }
  mv "$dest.part" "$dest"
  # Basic magic check: safetensors files are not HTML error pages
  if head -c 16 "$dest" | grep -qi '<!DOCTYPE\|<html'; then
    rm -f "$dest"
    die "download looks like HTML, not safetensors: $url"
  fi
}

log "OpenSoul Spark setup (non-root, no sudo)"
log "user=$(id -un) uid=$(id -u) home=$HOME"
log "root=$ROOT"
log "opensoul_home=$OPENSOUL_HOME"
log "comfy=$COMFY_DIR ref=$COMFY_REF"

require_cmd python3
require_cmd git
require_cmd curl
require_cmd uname

ARCH="$(uname -m)"
log "arch=$ARCH"
if [[ "$ARCH" != "aarch64" && "$ARCH" != "arm64" ]]; then
  log "WARNING: expected aarch64/arm64 on DGX Spark; got $ARCH"
fi

if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi -L || true
else
  log "WARNING: nvidia-smi not found — drivers may be missing"
fi

python3 --version

mkdir -p "$OPENSOUL_HOME"
if [[ ! -d "$VENV" ]]; then
  python3 -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"
python -m pip install -U pip wheel

log "PyTorch CUDA 13.0 wheels (allowlist: download.pytorch.org)"
python -m pip install torch torchvision --index-url "$ALLOW_PIP_TORCH"

if [[ ! -d "$COMFY_DIR/.git" ]]; then
  log "clone ComfyUI $COMFY_REF"
  git clone --branch "$COMFY_REF" --depth 1 "$ALLOW_GIT_COMFY" "$COMFY_DIR"
else
  log "ComfyUI already present"
fi

python -m pip install -r "$COMFY_DIR/requirements.txt"
python -m pip install "comfy-sdk>=0.5" "comfy-api-proxy>=0.1.6"
if command -v ffmpeg >/dev/null; then
  python -m pip install -e "$ROOT[dev]"
else
  # A stock DGX Spark has no system ffmpeg; without it every live take fails at the Era step and Export can't
  # stitch (seen Oct 18 on the first Lumi draft batch). Bundle the static aarch64 build into this venv.
  log "no system ffmpeg; installing the static imageio-ffmpeg build into the venv"
  python -m pip install -e "$ROOT[dev,ffmpeg]"
fi

# InfiniteTalk (lip-sync backup) shells out to bare `ffmpeg` and `ffprobe` (wan/multitalk.py get_video_codec).
# With only the bundled imageio-ffmpeg build, expose it on the venv PATH and add a tiny ffprobe shim that
# prints the first video stream's codec, the one thing InfiniteTalk asks ffprobe for (seen Oct 18, Lumi A/B).
if ! command -v ffmpeg >/dev/null; then
  FF_BIN="$(python -c 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())' 2>/dev/null || true)"
  [[ -n "$FF_BIN" ]] && ln -sf "$FF_BIN" "$VENV/bin/ffmpeg" && log "linked bundled ffmpeg into $VENV/bin"
fi
if ! command -v ffprobe >/dev/null && [[ -x "$VENV/bin/ffmpeg" ]]; then
  cat > "$VENV/bin/ffprobe" <<'SHIM'
#!/bin/bash
# OpenSoul shim: minimal ffprobe for InfiniteTalk (prints the first video stream codec) via the bundled ffmpeg.
f="${@: -1}"
"$(dirname "$0")/ffmpeg" -hide_banner -i "$f" 2>&1 | sed -n "s/.*Stream #0:[0-9]*.*: Video: \([a-z0-9_]*\).*/\1/p" | head -1
exit 0
SHIM
  chmod +x "$VENV/bin/ffprobe"
  log "installed minimal ffprobe shim into $VENV/bin"
fi

# torch.compile / Triton (used by InfiniteTalk) builds a small CUDA helper that needs Python.h. A stock Spark has
# no python3-dev and installing it needs sudo, so fetch the -dev .deb without root and unpack it under $PYHDR.
# Export the printed CPATH before running InfiniteTalk. ComfyUI itself keeps --disable-triton-backend.
PYHDR="${PYHDR:-$HOME/OpenSoul/pyhdr}"
PYV="$(python -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
if [[ ! -f "/usr/include/python$PYV/Python.h" && ! -f "$PYHDR/root/usr/include/python$PYV/Python.h" ]]; then
  log "no Python.h; fetching libpython$PYV-dev headers into $PYHDR (no sudo)"
  mkdir -p "$PYHDR/root"
  ( cd "$PYHDR" && apt-get download "libpython$PYV-dev" >/dev/null 2>&1 \
      && dpkg-deb -x libpython"$PYV"-dev_*.deb root ) \
    || log "WARNING: could not fetch Python headers; InfiniteTalk's torch.compile step will fail (see docs/MODEL_STACK.md)"
fi
if [[ -f "$PYHDR/root/usr/include/python$PYV/Python.h" ]]; then
  H="$PYHDR/root/usr/include"
  INFINITETALK_CPATH="$H/python$PYV:$H/$(uname -m)-linux-gnu/python$PYV:$H"
fi

mkdir -p \
  "$MODELS_DIR/diffusion_models" \
  "$MODELS_DIR/text_encoders" \
  "$MODELS_DIR/vae" \
  "$MODELS_DIR/loras" \
  "$MODELS_DIR/checkpoints"

if [[ "$DOWNLOAD_MODELS" == "1" ]]; then
  log "DOWNLOAD_MODELS=1 — fetching allowlisted official safetensors (large)"
  # Qwen-Image-Edit-2511 (Comfy-Org / Qwen official packaging — verify paths on first Spark run)
  # Paths verified against the HF tree API on 2026-10-16.
  download_safetensors \
    "${ALLOW_HF}/Comfy-Org/Qwen-Image-Edit_ComfyUI/resolve/main/split_files/diffusion_models/qwen_image_edit_2511_${QWEN_VARIANT}.safetensors" \
    "$MODELS_DIR/diffusion_models/qwen_image_edit_2511_${QWEN_VARIANT}.safetensors" \
    || log "WARNING: Qwen diffusion download failed — install manually (see docs/MODEL_STACK.md)"
  download_safetensors \
    "${ALLOW_HF}/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors" \
    "$MODELS_DIR/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors" \
    || log "WARNING: Qwen text encoder download failed"
  download_safetensors \
    "${ALLOW_HF}/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/vae/qwen_image_vae.safetensors" \
    "$MODELS_DIR/vae/qwen_image_vae.safetensors" \
    || log "WARNING: Qwen VAE download failed"
  # Lightning 4-step LoRA (lightx2v, official distillation for 2511)
  download_safetensors \
    "${ALLOW_HF}/lightx2v/Qwen-Image-Edit-2511-Lightning/resolve/main/Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors" \
    "$MODELS_DIR/loras/Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors" \
    || log "WARNING: Lightning LoRA download failed"
fi

if [[ "${DOWNLOAD_VIDEO:-0}" == "1" ]]; then
  log "DOWNLOAD_VIDEO=1 — LTX-2.5 (Lightricks) int8 pack + Wan2.2 TI2V-5B fallback (Comfy-Org repack)"
  L="${ALLOW_HF}/Lightricks/LTX-2.5/resolve/main"
  download_safetensors "$L/diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors" \
    "$MODELS_DIR/diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors" || log "WARNING: LTX transformer failed"
  download_safetensors "$L/text_encoders/gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors" \
    "$MODELS_DIR/text_encoders/gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors" || log "WARNING: LTX text encoder failed"
  download_safetensors "$L/vae/ltx-2.5-video-vae-bf16.safetensors" "$MODELS_DIR/vae/ltx-2.5-video-vae-bf16.safetensors" || log "WARNING: LTX video VAE failed"
  download_safetensors "$L/vae/ltx-2.5-audio-vae-bf16.safetensors" "$MODELS_DIR/vae/ltx-2.5-audio-vae-bf16.safetensors" || log "WARNING: LTX audio VAE failed"
  W="${ALLOW_HF}/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files"
  download_safetensors "$W/diffusion_models/wan2.2_ti2v_5B_fp16.safetensors" "$MODELS_DIR/diffusion_models/wan2.2_ti2v_5B_fp16.safetensors" || log "WARNING: Wan 5B failed"
  download_safetensors "$W/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors" "$MODELS_DIR/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors" || log "WARNING: umt5 failed"
  download_safetensors "$W/vae/wan2.2_vae.safetensors" "$MODELS_DIR/vae/wan2.2_vae.safetensors" || log "WARNING: Wan VAE failed"
  # Kokoro-82M and MuseTalk official repos publish only pickle (.pth/.bin) weights;
  # not auto-fetched by this safetensors-only script. See docs/MODEL_STACK.md.
fi
if [[ "$DOWNLOAD_MODELS" != "1" ]]; then
  log "Skipping image model downloads (set DOWNLOAD_MODELS=1; DOWNLOAD_VIDEO=1 for LTX/Wan)"
  log "See docs/MODEL_STACK.md for official HF paths"
fi

# Bind localhost only in the printed launch hints (no firewall changes)
cat <<LAUNCH

--------------------------------------------------------------------
Setup finished (no sudo, no firewall changes).

Launch in three terminals as user $(id -un):

  source $VENV/bin/activate
  cd $COMFY_DIR && TORCH_DISABLE_NATIVE_JIT=1 python main.py --listen 127.0.0.1 --port 8188 \\
      --cache-none --disable-triton-backend --disable-comfy-compiler --disable-api-nodes
  # TORCH_DISABLE_NATIVE_JIT / --disable-triton-backend: Triton JIT needs Python.h (python3-dev),
  # which may be absent on a stock Spark and needs sudo to install.

  source $VENV/bin/activate && comfy-api-proxy
  # default API v2 on 127.0.0.1:8189

  # Voices (default engine Orpheus, own venv, once):  $ROOT/scripts/setup_tts_orpheus.sh

  export COMFY_BASE_URL=http://127.0.0.1:8189
  unset OPENSOUL_DRY_RUN
  cd $ROOT && python -m app.ui
${INFINITETALK_CPATH:+
  # InfiniteTalk (lip-sync backup) only: Triton needs Python headers
  export CPATH=$INFINITETALK_CPATH
}
--------------------------------------------------------------------
LAUNCH
