#!/usr/bin/env bash
# VoxCPM2 TTS (Apache-2.0, openbmb): its own venv + pinned weights. Never touches ComfyUI's env; the ComfyUI node
# OpenSoulVoxCPM2TTS calls this venv as a subprocess (runners/voxcpm2_tts.py).
#
#   scripts/setup_tts_voxcpm2.sh            # venv + weights
#   scripts/setup_tts_voxcpm2.sh --check    # report only
#
# Env: OPENSOUL_HOME (~/OpenSoul), VOXCPM2_VENV ($OPENSOUL_HOME/voxcpm2-env), PYTHON (python3),
#      TORCH_INDEX (default the CUDA 13.0 wheels; use .../whl/cpu for CPU).
# Weights: hf:openbmb/VoxCPM2@32279effe8c19989596f05d353d1447f51d9e915 (~5 GB) -> $OPENSOUL_HOME/models/voxcpm2.
# The model card forbids impersonation: clone only voices you made or have permission to use.
set -euo pipefail
OPENSOUL_HOME="${OPENSOUL_HOME:-$HOME/OpenSoul}"
VENV="${VOXCPM2_VENV:-$OPENSOUL_HOME/voxcpm2-env}"
PY="${PYTHON:-$(command -v python3)}"
INDEX="${TORCH_INDEX:-https://download.pytorch.org/whl/cu130}"
REV=32279effe8c19989596f05d353d1447f51d9e915
DIR="$OPENSOUL_HOME/models/voxcpm2"
VOXCPM_VERSION=2.0.3

if [[ "${1:-}" == "--check" ]]; then
  ok=0
  [[ -x "$VENV/bin/python" ]] && echo "venv: $VENV" || { echo "venv: MISSING ($VENV)"; ok=1; }
  [[ -f "$DIR/model.safetensors" ]] && echo "weights: $DIR" || { echo "weights: MISSING ($DIR)"; ok=1; }
  exit $ok
fi

if [[ ! -x "$VENV/bin/python" ]]; then
  echo "==> venv $VENV ($PY)"
  "$PY" -m venv "$VENV"
fi
"$VENV/bin/pip" install -q -U pip
"$VENV/bin/pip" install -q --index-url "$INDEX" torch torchaudio
"$VENV/bin/pip" install -q "voxcpm==$VOXCPM_VERSION" soundfile numpy huggingface_hub
"$VENV/bin/python" - "$DIR" "$REV" <<'PY'
import sys
from huggingface_hub import snapshot_download
snapshot_download("openbmb/VoxCPM2", revision=sys.argv[2], local_dir=sys.argv[1])
print("weights:", sys.argv[1], "@", sys.argv[2])
PY
echo "$REV" > "$DIR/REVISION"
cat <<NEXT
==> VoxCPM2 ready. The ComfyUI node OpenSoulVoxCPM2TTS finds it with:
  export OPENSOUL_VOXCPM2_PY=$VENV/bin/python OPENSOUL_VOXCPM2_DIR=$DIR
NEXT
