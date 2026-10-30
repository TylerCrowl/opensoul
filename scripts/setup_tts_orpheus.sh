#!/usr/bin/env bash
# Orpheus TTS (default OpenSoul voice engine): own venv + weights. CPU works (~5x slower than real time on
# 8 cores); a CUDA llama.cpp build makes it faster. Never touches ComfyUI's env.
#
#   scripts/setup_tts_orpheus.sh            # venv + weights
#   scripts/setup_tts_orpheus.sh --check    # report only
#
# Env: OPENSOUL_HOME (~/OpenSoul), ORPHEUS_VENV ($OPENSOUL_HOME/tts-envs/orpheus), PYTHON (python3.11 or python3),
#      LLAMA_CPP_INDEX (prebuilt llama-cpp-python wheels; default the CPU index; use .../whl/cu124 for CUDA).
# Licenses: Orpheus weights Apache-2.0, fine-tuned from Meta Llama 3.2 3B ("Built with Llama", Llama 3.2
# Community License); SNAC MIT; llama-cpp-python MIT. See docs/MODEL_STACK.md.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OPENSOUL_HOME="${OPENSOUL_HOME:-$HOME/OpenSoul}"
VENV="${ORPHEUS_VENV:-$OPENSOUL_HOME/tts-envs/orpheus}"
PY="${PYTHON:-$(command -v python3.11 || command -v python3)}"
INDEX="${LLAMA_CPP_INDEX:-https://abetlen.github.io/llama-cpp-python/whl/cpu}"
GGUF="$OPENSOUL_HOME/models/orpheus/Orpheus-3b-FT-Q4_K_M.gguf"
SNAC="$OPENSOUL_HOME/models/snac_24khz"

if [[ "${1:-}" == "--check" ]]; then
  ok=0
  [[ -x "$VENV/bin/python" ]] && echo "venv: $VENV" || { echo "venv: MISSING ($VENV)"; ok=1; }
  [[ -f "$GGUF" ]] && echo "gguf: $GGUF" || { echo "gguf: MISSING ($GGUF)"; ok=1; }
  [[ -f "$SNAC/config.json" ]] && echo "snac: $SNAC" || { echo "snac: MISSING ($SNAC)"; ok=1; }
  exit $ok
fi

if [[ ! -x "$VENV/bin/python" ]]; then
  echo "==> venv $VENV ($PY)"
  mkdir -p "$(dirname "$VENV")"
  "$PY" -m venv "$VENV"
fi
"$VENV/bin/pip" install -q -U pip
"$VENV/bin/pip" install -q --extra-index-url https://download.pytorch.org/whl/cpu torch snac soundfile numpy huggingface_hub
"$VENV/bin/pip" install -q --only-binary llama-cpp-python --extra-index-url "$INDEX" llama-cpp-python
# Weights (pinned, sha256-checked) through the same download script as every other model.
PATH="$VENV/bin:$PATH" OPENSOUL_HOME="$OPENSOUL_HOME" "$ROOT/scripts/download_models.sh" orpheus
cat <<NEXT
==> Orpheus ready. ComfyUI node OpenSoulOrpheusTTS finds it with:
  export OPENSOUL_ORPHEUS_PY=$VENV/bin/python OPENSOUL_ORPHEUS_GGUF=$GGUF
Quick test:
  $VENV/bin/python $ROOT/custom_nodes/opensoul_nodes/runners/orpheus_tts.py --voice tara \\
      --text "<sigh> No. Anything hotter is an apology." --out /tmp/orpheus_test.wav
NEXT
